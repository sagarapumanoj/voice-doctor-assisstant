let ctx;

export function audioCtx() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === "suspended") ctx.resume();
  return ctx;
}

function tone(freqs, start, dur, vol = 0.05) {
  const c = audioCtx();
  const t0 = c.currentTime + start;
  const gain = c.createGain();
  gain.gain.setValueAtTime(0, t0);
  gain.gain.linearRampToValueAtTime(vol, t0 + 0.02);
  gain.gain.setValueAtTime(vol, t0 + dur - 0.04);
  gain.gain.linearRampToValueAtTime(0, t0 + dur);
  gain.connect(c.destination);
  freqs.forEach((f) => {
    const osc = c.createOscillator();
    osc.frequency.value = f;
    osc.connect(gain);
    osc.start(t0);
    osc.stop(t0 + dur);
  });
}

export const ringOnce = () => tone([440, 480], 0, 0.9);
export const connectedTone = () => { tone([660], 0, 0.1); tone([880], 0.12, 0.14); };
export const endTone = () => { tone([480], 0, 0.12); tone([380], 0.18, 0.22); };