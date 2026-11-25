import { useEffect, useRef, useState } from "react";
import { audioCtx } from "./sounds";
import { fmtWhen, mmss } from "./format";

const CALL = "M6.6 10.8a15.1 15.1 0 006.6 6.6l2.2-2.2a1 1 0 011-.25c1.1.37 2.3.57 3.6.57a1 1 0 011 1V20a1 1 0 01-1 1C10.6 21 3 13.4 3 4a1 1 0 011-1h3.5a1 1 0 011 1c0 1.25.2 2.5.57 3.6a1 1 0 01-.25 1l-2.2 2.2z";
const MIC = "M12 14a3 3 0 003-3V5a3 3 0 10-6 0v6a3 3 0 003 3zm5-3a5 5 0 01-10 0H5a7 7 0 006 6.92V21h2v-3.08A7 7 0 0019 11h-2z";

const clock = () => new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

const Icon = ({ d, className, size = 26 }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="currentColor" className={className} aria-hidden="true">
    <path d={d} />
  </svg>
);

function StatusBar() {
  const [t, setT] = useState(clock);
  useEffect(() => {
    const id = setInterval(() => setT(clock()), 15000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="sbar">
      <span className="num">{t}</span>
      <span className="island" />
      <span className="sicons">
        <svg viewBox="0 0 18 12" width="18" height="12" fill="currentColor">
          <rect x="0" y="8" width="3" height="4" rx="1" /><rect x="5" y="5" width="3" height="7" rx="1" />
          <rect x="10" y="2" width="3" height="10" rx="1" /><rect x="15" y="0" width="3" height="12" rx="1" opacity=".35" />
        </svg>
        <svg viewBox="0 0 26 12" width="26" height="12" fill="currentColor">
          <rect x=".5" y=".5" width="21" height="11" rx="3.5" fill="none" stroke="currentColor" opacity=".5" />
          <rect x="2" y="2" width="15" height="8" rx="2" /><rect x="23" y="4" width="2" height="4" rx="1" opacity=".5" />
        </svg>
      </span>
    </div>
  );
}

function Waveform({ stream }) {
  const bars = useRef([]);
  useEffect(() => {
    if (!stream) return;
    const ctx = audioCtx();
    const src = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 64;
    src.connect(analyser); // not connected to speakers, so no double playback
    const data = new Uint8Array(analyser.frequencyBinCount);
    let raf;
    const loop = () => {
      analyser.getByteFrequencyData(data);
      bars.current.forEach((el, i) => {
        if (el) el.style.transform = `scaleY(${Math.max(0.1, data[(i % 28) + 1] / 255)})`;
      });
      raf = requestAnimationFrame(loop);
    };
    loop();
    return () => { cancelAnimationFrame(raf); src.disconnect(); };
  }, [stream]);

  return (
    <div className={`wave ${stream ? "" : "idle"}`} aria-hidden="true">
      {Array.from({ length: 28 }).map((_, i) => (
        <span key={i} style={{ "--i": i }} ref={(el) => (bars.current[i] = el)} />
      ))}
    </div>
  );
}

function ConfirmCard({ toast }) {
  const { kind, appt } = toast;
  return (
    <div className={`card ${kind}`} key={toast.key}>
      <span className="card-ic">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
             strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
          {kind === "booked" ? <path d="M5 12.5l4.5 4.5L19 7.5" /> : <path d="M6 6l12 12M18 6L6 18" />}
        </svg>
      </span>
      <div className="card-body">
        <div className="card-kind">{kind === "booked" ? "Booked" : "Cancelled"}</div>
        <div className="card-doc">{appt.doctor}</div>
        <div className="card-when num">{fmtWhen(appt.start_time)}</div>
        <div className="card-who">{appt.patient_name}</div>
      </div>
    </div>
  );
}

export default function Phone({ call, toast }) {
  const { phase, muted, messages, seconds, error, botStream, start, hangUp, toggleMute } = call;
  const scroller = useRef(null);

  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [messages]);

  return (
    <div className={`stage ${phase}`}>
      <div className={`phone ${phase}`}>
        <div className="screen">
          <StatusBar />

          {phase === "idle" && (
            <div className="view center">
              <div className="avatar">CC</div>
              <div className="pname">City Care</div>
              <div className="psub">Appointment line</div>
              <div className="spacer" />
              <p className="try">“Book me an appointment for tomorrow”</p>
              <button className="btn call" onClick={start} aria-label="Try call"><Icon d={CALL} /></button>
              <div className="hint">Try call</div>
            </div>
          )}

          {phase === "ringing" && (
            <div className="view center">
              <div className="ava-wrap">
                <span className="ripple" /><span className="ripple r2" /><span className="ripple r3" />
                <div className="avatar">CC</div>
              </div>
              <div className="pname">City Care</div>
              <div className="psub dots">Calling</div>
              <div className="spacer" />
              <button className="btn end" onClick={hangUp} aria-label="Cancel call">
                <Icon d={CALL} className="rot" />
              </button>
              <div className="hint">Cancel</div>
            </div>
          )}

          {phase === "live" && (
            <div className="view live-view">
              <div className="live-head">
                <span className="live-pill"><i />Live</span>
                <div className="pname sm">City Care</div>
                <div className="timer num">{mmss(seconds)}</div>
              </div>
              <Waveform stream={botStream} />
              <div className="transcript" ref={scroller}>
                {messages.map((m) => (
                  <div key={m.id} className={`b ${m.role}`}>{m.text}</div>
                ))}
              </div>
              {toast && <ConfirmCard toast={toast} />}
              <div className="controls">
                <div className="ctl">
                  <button className={`btn round ${muted ? "on" : ""}`} onClick={toggleMute}
                          aria-label={muted ? "Unmute" : "Mute"}>
                    <Icon d={MIC} />
                    {muted && <i className="slash" />}
                  </button>
                  <span>{muted ? "Unmute" : "Mute"}</span>
                </div>
                <div className="ctl">
                  <button className="btn end" onClick={hangUp} aria-label="End call">
                    <Icon d={CALL} className="rot" />
                  </button>
                  <span>End</span>
                </div>
              </div>
            </div>
          )}

          {phase === "ended" && (
            <div className="view center">
              <div className="avatar dim">CC</div>
              <div className="pname">Call ended</div>
              <div className="psub num">{error || mmss(seconds)}</div>
              {toast && <ConfirmCard toast={toast} />}
              <div className="spacer" />
              <button className="btn call" onClick={start} aria-label="Call again"><Icon d={CALL} /></button>
              <div className="hint">Call again</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}