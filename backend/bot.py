"""Pipecat voice agent:
ElevenLabs STT -> Groq LLM -> ElevenLabs TTS, with appointment tools.
"""

import sys

# Configure Windows console encoding before importing Pipecat.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp
from dotenv import load_dotenv
from loguru import logger

# Load environment variables before importing project modules.
load_dotenv(override=True)

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame, TranscriptionFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.runner.types import RunnerArguments, SmallWebRTCRunnerArguments
from pipecat.services.elevenlabs.stt import ElevenLabsSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

import db
import tools


# --------------------------------------------------
# 1. Environment configuration
# --------------------------------------------------

def validate_environment():
    required = [
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
    ]

    provider = os.getenv("LLM_PROVIDER", "groq").lower()

    if provider == "groq":
        required.append("GROQ_API_KEY")
        os.environ.setdefault("GROQ_MODEL", "qwen/qwen3.8-27b")

    elif provider == "gemini":
        required.append("GOOGLE_API_KEY")

    else:
        raise ValueError(
            f"Unsupported LLM_PROVIDER: {provider}. "
            "Use groq or gemini."
        )

    missing = [key for key in required if not os.getenv(key)]

    if missing:
        raise RuntimeError(
            "Missing environment variables: " + ", ".join(missing)
        )


validate_environment()

db.init_db()


# --------------------------------------------------
# 2. System prompt
# --------------------------------------------------

SYSTEM_PROMPT = """You are the voice receptionist for City Care Clinic.
You help callers check doctor availability, book appointments,
and cancel appointments.

Today is {today}.

HOW YOU SPEAK:

- This is a natural telephone conversation.
- Maximum two short sentences per reply.
- Keep replies under 30 words.
- Ask only ONE question per reply.
- After asking a question, stop and wait for the caller.
- Never use markdown, lists, or emojis.
- Never say that you are waiting.
- Never predict what the caller will say next.
- Never repeat information unnecessarily.
- Speak naturally and clearly.
- Say times naturally, for example, Wednesday at ten thirty AM.

PHONE NUMBER VERIFICATION:

1. Ask: "What's your ten digit phone number?"
2. Wait for the caller.
3. Collect all ten digits.
4. If fewer than ten digits are received, retain the digits
   and ask for the remaining digits.
5. Once ten digits are collected, read them back one by one.
6. Ask: "Is that correct?"
7. Only after an explicit YES, mark the number as confirmed.
8. If the caller corrects a digit, read the corrected number
   back and ask for confirmation again.

APPOINTMENT RULES:

1. Never invent doctors, dates, or appointment times.
2. ALWAYS call check_doctor_availability before offering a slot.
3. Convert spoken dates into YYYY-MM-DD format.
4. Identify callers only using their confirmed phone number.
5. Before booking, confirm:
   - Doctor
   - Appointment date
   - Appointment time
   - Caller name
6. Use the actual slot_id returned by the availability tool.
7. Call book_appointment only after all required details
   are confirmed.
8. Never call book_appointment before phone verification.
9. Before cancellation, collect and confirm the phone number.
10. Call cancel_appointment only after phone verification.
11. Never invent a successful booking or cancellation.
12. If a tool returns success=false, explain the issue
    briefly and offer the next step.
13. If a tool returns number_not_confirmed, ask:
    "Could you confirm that number?"
14. After completing a task, ask whether the caller needs
    anything else.

IMPORTANT:

Never claim that an appointment has been booked or cancelled
unless the corresponding tool confirms success.

START:

Greet the caller in one short sentence and ask how you can help.
Then wait for the caller's response.
"""


# --------------------------------------------------
# 3. Remove STT sound tags
# --------------------------------------------------

class NoiseTagFilter(FrameProcessor):
    """Remove common non-speech tags from transcriptions."""

    SOUND_TAG_PATTERN = re.compile(
        r"\[(?:background noise|music|silence|noise|"
        r"laughter|laughing|coughing|clears throat)[^\]]*\]"
        r"|\((?:laughing|laughter|coughing|clears throat|"
        r"sighing|sobbing)\)",
        re.IGNORECASE,
    )

    async def process_frame(
        self,
        frame,
        direction: FrameDirection,
    ):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            cleaned = self.SOUND_TAG_PATTERN.sub("", frame.text).strip()

            if not cleaned:
                return

            frame.text = cleaned

        await self.push_frame(frame, direction)


# --------------------------------------------------
# 4. Build LLM
# --------------------------------------------------

def build_llm():
    """Build Groq by default, or Gemini when configured."""

    provider = os.getenv("LLM_PROVIDER", "groq").lower()

    if provider == "groq":
        from pipecat.services.openai.llm import OpenAILLMService

        model = os.getenv(
            "GROQ_MODEL",
            "qwen/qwen3.8-27b",
        )

        logger.info(f"Using Groq model: {model}")

        return OpenAILLMService(
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1",
            settings=OpenAILLMService.Settings(
                model=model,
            ),
        )

    logger.info("Using Google Gemini")

    return GoogleLLMService(
        api_key=os.environ["GOOGLE_API_KEY"],
        settings=GoogleLLMService.Settings(
            model=os.getenv(
                "GEMINI_MODEL",
                "gemini-2.5-flash",  # FIX: known-good fallback name
            ),
        ),
    )


# --------------------------------------------------
# 5. Main voice pipeline
# --------------------------------------------------

async def run_bot(transport: SmallWebRTCTransport):

    session = aiohttp.ClientSession()

    try:
        # ElevenLabs Speech-to-Text
        stt = ElevenLabsSTTService(
            api_key=os.environ["ELEVENLABS_API_KEY"],
            aiohttp_session=session,
        )

        noise_filter = NoiseTagFilter()

        # LLM
        llm = build_llm()

        # Register appointment tools
        tools.register_tools(llm)

        # ElevenLabs Text-to-Speech
        tts = ElevenLabsHttpTTSService(
            api_key=os.environ["ELEVENLABS_API_KEY"],
            aiohttp_session=session,
            settings=ElevenLabsHttpTTSService.Settings(
                voice=os.environ["ELEVENLABS_VOICE_ID"],
                model="eleven_flash_v2_5",
            ),
        )

        # Current Indian date
        today = datetime.now(
            ZoneInfo("Asia/Kolkata")
        ).strftime("%A, %d %B %Y")

        # Conversation context
        # FIX: Groq's Qwen template rejects requests with no user message,
        # so the greeting trigger needs one.
        context = LLMContext(
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT.format(today=today),
                },
                {
                    "role": "user",
                    "content": "The caller has just connected. "
                               "Greet them in one short sentence.",
                },
            ],
            tools=tools.build_tools_schema(),
        )

        # User and assistant conversation aggregators
        user_agg, assistant_agg = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(
                    params=VADParams(
                        confidence=0.85,
                        start_secs=0.4,
                        stop_secs=0.8,  # FIX: wait longer between phone digits
                        min_volume=0.6,
                    )
                ),
            ),
        )

        # Pipeline
        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                noise_filter,
                user_agg,
                llm,
                tts,
                transport.output(),
                assistant_agg,
            ]
        )

        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
            ),
        )

        # Caller connects
        @transport.event_handler("on_client_connected")
        async def on_connected(transport, client):
            logger.info("Caller connected. Sending greeting.")

            await task.queue_frames(
                [LLMRunFrame()]
            )

        # Caller disconnects
        @transport.event_handler("on_client_disconnected")
        async def on_disconnected(transport, client):
            logger.info("Caller disconnected.")

            await task.cancel()

        logger.info("City Care Clinic voice agent started.")

        await PipelineRunner(
            handle_sigint=False
        ).run(task)

    finally:
        await session.close()
        logger.info("Voice agent session closed.")


# --------------------------------------------------
# 6. Pipecat development runner
# --------------------------------------------------

async def bot(runner_args: RunnerArguments):

    if not isinstance(
        runner_args,
        SmallWebRTCRunnerArguments,
    ):
        raise RuntimeError(
            "This bot only supports SmallWebRTC transport."
        )

    transport = SmallWebRTCTransport(
        webrtc_connection=runner_args.webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    )

    await run_bot(transport)


# --------------------------------------------------
# 7. Application entry point
# --------------------------------------------------

if __name__ == "__main__":

    from pipecat.runner.run import app, main

    import server

    app.include_router(server.router)

    main()