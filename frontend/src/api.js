export const API = import.meta.env.VITE_API_URL || "http://localhost:7860";

async function get(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`${path} ${res.status}`);
  return res.json();
}

export async function fetchAll() {
  const [doctors, slots, appointments] = await Promise.all([
    get("/doctors"),
    get("/slots"),
    get("/appointments"),
  ]);
  return { doctors, slots, appointments };
}