export const fmtDay = (d) =>
  new Date(`${d}T00:00`).toLocaleDateString("en-IN", {
    weekday: "short", day: "numeric", month: "short",
  });

export const fmtWeekday = (d) =>
  new Date(`${d}T00:00`).toLocaleDateString("en-IN", { weekday: "short" });

export const fmtDayNum = (d) => new Date(`${d}T00:00`).getDate();

export const fmtMonth = (d) =>
  new Date(`${d}T00:00`).toLocaleDateString("en-IN", { month: "short" });

export const fmtTime = (t) =>
  new Date(t.replace(" ", "T")).toLocaleTimeString("en-US", {
    hour: "numeric", minute: "2-digit",
  });

export const fmtWhen = (t) => `${fmtDay(t.slice(0, 10))}, ${fmtTime(t)}`;

export const fmtPhone = (p) => (p && p.length === 10 ? `${p.slice(0, 5)} ${p.slice(5)}` : p);

export const mmss = (s) =>
  `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

export const todayStr = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export const initials = (name = "") =>
  name.replace(/^dr\.?\s+/i, "").split(/\s+/).filter(Boolean).slice(0, 2)
    .map((w) => w[0].toUpperCase()).join("");

export const hueOf = (s = "") =>
  ([...s].reduce((a, c) => a + c.charCodeAt(0), 0) * 7) % 360;