import { useCallback, useEffect, useRef, useState } from "react";
import { PipecatClient } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import { API } from "./api";
import { audioCtx, ringOnce, connectedTone, endTone } from "./sounds";

/** Call lifecycle: idle -> ringing -> live -> ended */
export function useCall() {
  const [phase, setPhase] = useState("idle");
  const [muted, setMuted] = useState(false);
  const [messages, setMessages] = useState([]);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");
  const [botStream, setBotStream] = useState(null);

  const phaseRef = useRef("idle");
  const mutedRef = useRef(false);
  const clientRef = useRef(null);
  const audioRef = useRef(null);
  const ringRef = useRef(null);
  const timerRef = useRef(null);

  const go = useCallback((p) => { phaseRef.current = p; setPhase(p); }, []);

  const clearTimers = () => {
    clearInterval(ringRef.current);
    clearInterval(timerRef.current);
  };

  const finish = useCallback(() => {
    if (phaseRef.current === "idle" || phaseRef.current === "ended") return;
    clearTimers();
    endTone();
    if (audioRef.current) audioRef.current.srcObject = null;
    setBotStream(null);
    go("ended");
  }, [go]);

  // Merge consecutive messages from the same speaker into one bubble.
  const addMessage = useCallback((role, text) => {
    const t = (text || "").trim();
    if (!t) return;
    setMessages((m) => {
      const last = m[m.length - 1];
      if (last && last.role === role) {
        return [...m.slice(0, -1), { ...last, text: `${last.text} ${t}` }];
      }
      return [...m, { id: `${Date.now()}-${m.length}`, role, text: t }];
    });
  }, []);

  // Route the bot's audio track to the speakers (and to the waveform).
  const attachBotAudio = useCallback((track) => {
    if (!audioRef.current) return;
    const stream = new MediaStream([track]);
    audioRef.current.srcObject = stream;
    audioRef.current.muted = false;
    audioRef.current.volume = 1;
    audioRef.current.play().catch((e) => console.warn("Audio play blocked:", e));
    setBotStream(stream);
  }, []);

  const start = useCallback(async () => {
    if (phaseRef.current === "ringing" || phaseRef.current === "live") return;
    setError("");
    setMessages([]);
    setSeconds(0);
    setMuted(false);
    mutedRef.current = false;
    go("ringing");

    audioCtx(); // unlock audio on this click
    ringOnce();
    ringRef.current = setInterval(ringOnce, 2200);

    if (!audioRef.current) {
      audioRef.current = new Audio();
      audioRef.current.autoplay = true;
    }
    audioRef.current.srcObject = null;

    const client = new PipecatClient({
      transport: new SmallWebRTCTransport(),
      enableMic: true,
      enableCam: false,
      callbacks: {
        onBotReady: () => {
          // Second route to the bot audio, in case onTrackStarted missed it.
          try {
            const botTrack = clientRef.current?.tracks?.()?.bot?.audio;
            if (botTrack && !audioRef.current?.srcObject) attachBotAudio(botTrack);
          } catch (e) {
            console.warn("tracks() lookup failed:", e);
          }
          if (phaseRef.current !== "ringing") return;
          clearInterval(ringRef.current);
          connectedTone();
          go("live");
          timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
        },
        onDisconnected: () => finish(),
        onUserTranscript: (d) => { if (d.final !== false) addMessage("user", d.text); },
        onBotTranscript: (d) => addMessage("bot", d.text),
        onTrackStarted: (track, participant) => {
          console.log("track started:", track.kind, participant);
          // Accept every remote audio track. Only skip our own microphone.
          if (track.kind === "audio" && !participant?.local) attachBotAudio(track);
        },
                onError: (msg) =>
          console.error("Pipecat error:", JSON.stringify(msg?.data ?? msg, null, 2)),
      },
    });
    clientRef.current = client;

    try {
      await client.startBotAndConnect({
        endpoint: `${API}/start`,
        requestData: { createDailyRoom: false, enableDefaultIceServers: true, transport: "webrtc" },
      });
    } catch (e) {
      console.error(e);
      setError("Could not reach the agent. Is the server running?");
      finish();
    }
  }, [addMessage, attachBotAudio, finish, go]);

  const hangUp = useCallback(async () => {
    try { await clientRef.current?.disconnect(); } catch { /* already closed */ }
    finish();
  }, [finish]);

  const toggleMute = useCallback(() => {
    const next = !mutedRef.current;
    mutedRef.current = next;
    setMuted(next);
    clientRef.current?.enableMic(!next);
  }, []);

  useEffect(() => () => {
    clearTimers();
    try { clientRef.current?.disconnect(); } catch { /* ignore */ }
  }, []);

  return { phase, muted, messages, seconds, error, botStream, start, hangUp, toggleMute };
}