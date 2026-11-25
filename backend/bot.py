"""Pipecat voice agent: ElevenLabs STT -> Gemini -> ElevenLabs TTS, with tools."""

import sys

# Windows consoles default to cp1252 and choke on Pipecat's log characters.
# This must run before Pipecat is imported, because its banner prints on import.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import os
from datetime import date

import aiohttp
from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments, SmallWebRTCRunnerArguments
from pipecat.services.elevenlabs.stt import ElevenLabsSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

import db
import tools

load_dotenv(override=True)
db.init_db()

SYSTEM_PROMPT = """You are the voice receptionist for City Care Clinic. You help callers \
check doctor availability, book an appointment, and cancel an appointment.
Today is {today}.

Speaking style:
- This is a phone call. Keep every reply to one or two short sentences.
- Never use lists, markdown, or emojis. Offer at most three options at a time.
- Say dates and times naturally, like "Wednesday at ten thirty AM".

Rules:
1. Never invent doctors or times. Always call check_doctor_availability before \
offering any slot. If the caller gives a date, convert it to YYYY-MM-DD yourself \
using today's date.
2. The caller is identified ONLY by the phone number they say out loud.
3. Before booking or cancelling, get the phone number, then read it back digit by \
digit, like "nine, eight, seven, six, five, four, three, two, one, zero", and ask \
"Is that correct?". Only after the caller says yes may you set \
number_confirmed_by_caller to true. If they correct any digit, read the new number \
back and ask again.
4. To book: confirm the doctor, the day and time, and the caller's name. Then call \
book_appointment with the slot_id from the availability results.
5. To cancel: get and confirm the phone number, then call cancel_appointment. Tell \
the caller which appointment was cancelled.
6. If a tool returns success false, explain it simply and offer the next step. \
For example, if the slot was taken, offer other times. If the number is not \
confirmed, read it back again.
7. After finishing a task, ask if there is anything else.

Start by greeting the caller briefly and asking how you can help."""


async def run_bot(transport: SmallWebRTCTransport) -> None:
    session = aiohttp.ClientSession()

    stt = ElevenLabsSTTService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        aiohttp_session=session,
    )

    llm = GoogleLLMService(
        api_key=os.environ["GOOGLE_API_KEY"],
        settings=GoogleLLMService.Settings(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        ),
    )
    tools.register_tools(llm)

    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsTTSService.Settings(
            voice=os.environ["ELEVENLABS_VOICE_ID"],
            model="eleven_flash_v2_5",
        ),
    )

    context = LLMContext(
        messages=[{
            "role": "system",
            "content": SYSTEM_PROMPT.format(today=date.today().strftime("%A, %d %B %Y")),
        }],
        tools=tools.build_tools_schema(),
    )
    user_agg, assistant_agg = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline([
        transport.input(),   # caller audio in
        stt,                 # audio -> text
        user_agg,            # collects the user's turn into the context
        llm,                 # Gemini, calls tools when needed
        tts,                 # text -> audio
        transport.output(),  # bot audio out
        assistant_agg,       # saves bot replies and tool results to the context
    ])

    task = PipelineTask(pipeline, params=PipelineParams(enable_metrics=True))

    @transport.event_handler("on_client_connected")
    async def on_connected(transport, client):
        logger.info("Caller connected, queueing greeting")
        await task.queue_frames([LLMRunFrame()])  # makes the bot greet first

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(transport, client):
        logger.info("Caller disconnected")
        await task.cancel()

    try:
        await PipelineRunner(handle_sigint=False).run(task)
    finally:
        await session.close()


async def bot(runner_args: RunnerArguments):
    """Entry point called by Pipecat's development runner for each session."""
    if not isinstance(runner_args, SmallWebRTCRunnerArguments):
        raise RuntimeError("This bot only supports the SmallWebRTC transport.")

    transport = SmallWebRTCTransport(
        webrtc_connection=runner_args.webrtc_connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )
    await run_bot(transport)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()