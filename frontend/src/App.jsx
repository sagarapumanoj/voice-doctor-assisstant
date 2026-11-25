import { useEffect, useMemo, useRef, useState } from "react";
import "./index.css";
import { fetchAll } from "./api";
import {
  fmtTime, fmtWhen, fmtPhone, fmtWeekday, fmtDayNum, fmtMonth,
  initials, hueOf, todayStr, mmss,
} from "./format";
import { useCall } from "./useCall";
import Phone from "./Phone";

const Avatar = ({ name, size = 40 }) => (
  <span className="av" style={{ "--h": hueOf(name), width: size, height: size, fontSize: size * 0.38 }}>
    {initials(name)}
  </span>
);

const SlotGroup = ({ label, slots }) =>
  slots.length ? (
    <div className="sg">
      <div className="sg-label">{label}</div>
      <div className="chips">
        {slots.map((s) => (
          <span key={s.slot_id} className={`chip num ${s.is_booked ? "booked" : ""}`}>
            {fmtTime(s.start_time)}
          </span>
        ))}
      </div>
    </div>
  ) : null;

export default function App() {
  const call = useCall();
  const [data, setData] = useState({ doctors: [], slots: [], appointments: [] });
  const [online, setOnline] = useState(true);
  const [doctorId, setDoctorId] = useState(null);
  const [day, setDay] = useState(null);
  const [filter, setFilter] = useState("all");
  const [flash, setFlash] = useState({});
  const [toast, setToast] = useState(null);
  const prev = useRef(null);

  // Poll the REST routes every 2 seconds; detect new or changed appointments.
  useEffect(() => {
    let stopped = false;
    const tick = async () => {
      try {
        const d = await fetchAll();
        if (stopped) return;
        setOnline(true);
        if (prev.current) {
          const changed = d.appointments.filter((a) => prev.current.get(a.id) !== a.status);
          if (changed.length) {
            setFlash(Object.fromEntries(changed.map((a) => [a.id, true])));
            setTimeout(() => setFlash({}), 2600);
            const a = changed[0];
            setToast({ kind: a.status === "cancelled" ? "cancelled" : "booked", appt: a, key: Date.now() });
          }
        }
        prev.current = new Map(d.appointments.map((a) => [a.id, a.status]));
        setData(d);
        setDoctorId((id) => id ?? d.doctors[0]?.id ?? null);
      } catch {
        if (!stopped) setOnline(false);
      }
    };
    tick();
    const timer = setInterval(tick, 2000);
    return () => { stopped = true; clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 9000);
    return () => clearTimeout(t);
  }, [toast]);

  const doctor = data.doctors.find((d) => d.id === doctorId);
  const maxOpen = Math.max(1, ...data.doctors.map((d) => d.open_slots));
  const openTotal = data.doctors.reduce((n, d) => n + d.open_slots, 0);
  const bookedCount = data.appointments.filter((a) => a.status === "booked").length;
  const cancelledCount = data.appointments.length - bookedCount;

  const days = useMemo(() => {
    const byDay = {};
    data.slots
      .filter((s) => s.doctor_id === doctorId)
      .forEach((s) => (byDay[s.start_time.slice(0, 10)] ||= []).push(s));
    return Object.entries(byDay);
  }, [data.slots, doctorId]);

  const activeDay = days.some(([d]) => d === day) ? day : days[0]?.[0];
  const daySlots = days.find(([d]) => d === activeDay)?.[1] ?? [];
  const morning = daySlots.filter((s) => +s.start_time.slice(11, 13) < 12);
  const afternoon = daySlots.filter((s) => +s.start_time.slice(11, 13) >= 12);

  const shown = filter === "all"
    ? data.appointments
    : data.appointments.filter((a) => a.status === filter);

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
            <rect width="32" height="32" rx="9" fill="var(--accent)" />
            <path d="M16 8v16M8 16h16" stroke="#fff" strokeWidth="3.2" strokeLinecap="round" />
          </svg>
          <span>City Care</span>
        </div>
        <div className="top-right">
          {call.phase === "live" && (
            <span className="oncall"><i />On call · <span className="num">{mmss(call.seconds)}</span></span>
          )}
          <span className="conn">
            <span className={`dot ${online ? "" : "off"}`} />
            {online ? "Live" : "Server offline"}
          </span>
        </div>
      </header>

      <div className="grid">
        <aside className="side">
          <Phone call={call} toast={toast} />
        </aside>

        <main className="main">
          <section className="stats">
            <div className="stat"><small>Open slots</small><b key={openTotal} className="tick num">{openTotal}</b></div>
            <div className="stat"><small>Booked</small><b key={bookedCount} className="tick num">{bookedCount}</b></div>
            <div className="stat"><small>Cancelled</small><b key={cancelledCount} className="tick num">{cancelledCount}</b></div>
          </section>

          <section className="panel">
            <div className="ph"><h2>Doctors</h2></div>
            <div className="docs">
              {data.doctors.map((d) => (
                <button
                  key={d.id}
                  className={`doc ${d.id === doctorId ? "active" : ""}`}
                  onClick={() => setDoctorId(d.id)}
                >
                  <div className="doc-top">
                    <Avatar name={d.name} size={42} />
                    <div>
                      <div className="doc-name">{d.name}</div>
                      <div className="doc-spec">{d.specialty}</div>
                    </div>
                  </div>
                  <div className="bar"><i style={{ width: `${(d.open_slots / maxOpen) * 100}%` }} /></div>
                  <div className="doc-open num">{d.open_slots} open</div>
                </button>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="ph">
              <h2>Slots{doctor && <span className="sub"> · {doctor.name}</span>}</h2>
              <div className="legend"><span><i className="lg open" />Open</span><span><i className="lg" />Booked</span></div>
            </div>
            <div className="dtabs">
              {days.map(([d, slots]) => (
                <button key={d} className={`dtab ${d === activeDay ? "on" : ""}`} onClick={() => setDay(d)}>
                  <small>{d === todayStr() ? "Today" : fmtWeekday(d)}</small>
                  <b className="num">{fmtDayNum(d)}</b>
                  <span className="dn num">{slots.filter((s) => !s.is_booked).length} open · {fmtMonth(d)}</span>
                </button>
              ))}
            </div>
            <SlotGroup label="Morning" slots={morning} />
            <SlotGroup label="Afternoon" slots={afternoon} />
            {!daySlots.length && <div className="empty">No upcoming slots</div>}
          </section>

          <section className="panel">
            <div className="ph">
              <h2>Appointments<span className="sub"> · {data.appointments.length}</span></h2>
              <div className="seg">
                {["all", "booked", "cancelled"].map((f) => (
                  <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
                    {f[0].toUpperCase() + f.slice(1)}
                  </button>
                ))}
              </div>
            </div>
            <ul className="list">
              {shown.map((a) => (
                <li key={a.id} className={`row ${flash[a.id] ? "flash" : ""}`}>
                  <Avatar name={a.patient_name} />
                  <div className="r-main">
                    <div className="r-name">{a.patient_name}</div>
                    <div className="r-sub num">{fmtPhone(a.phone)}</div>
                  </div>
                  <div className="r-doc">
                    <div>{a.doctor}</div>
                    <div className="r-sub num">{fmtWhen(a.start_time)}</div>
                  </div>
                  <span className={`pill ${a.status}`}>{a.status}</span>
                </li>
              ))}
            </ul>
            {!shown.length && <div className="empty">No appointments yet</div>}
          </section>
        </main>
      </div>
    </div>
  );
}