// API helpers + shared helpers + constants

const POLL_MS = 700;

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  const d = await r.json();
  if (!r.ok) throw new Error(d.reason || d.last_error || r.statusText);
  return d;
}

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body == null ? {} : body),
  });
  const d = await r.json().catch(() => ({ ok: false, reason: r.statusText }));
  if (!r.ok && d.ok !== false) throw new Error(d.reason || d.last_error || r.statusText);
  return d;
}

async function delJSON(url) {
  const r = await fetch(url, { method: "DELETE" });
  const d = await r.json().catch(() => ({ ok: false, reason: r.statusText }));
  if (!r.ok && d.ok !== false) throw new Error(d.reason || d.last_error || r.statusText);
  return d;
}

// dotted path read on a config snapshot
function getPath(obj, path) {
  return path.split(".").reduce((c, k) => (c && typeof c === "object" ? c[k] : undefined), obj);
}

function fmtBytes(n) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  let v = Number(n);
  let i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
  return v.toFixed(i ? 1 : 0) + " " + u[i];
}

function fmtDuration(seconds) {
  const v = Number(seconds || 0);
  if (!isFinite(v) || v <= 0) return "0:00";
  const mins = Math.floor(v / 60);
  const rest = Math.round(v % 60).toString().padStart(2, "0");
  return mins + ":" + rest;
}

function fmtClock(ts) {
  if (!ts) return "";
  return new Date(Number(ts) * 1000).toLocaleTimeString("en-GB", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
}

function fmtMs(ms) {
  const v = Number(ms || 0);
  if (!isFinite(v) || v <= 0) return "";
  return Math.round(v) + " ms";
}

function fmtUptime(secs) {
  const s = Math.max(0, Number(secs || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = Math.floor(s % 60);
  return h + "h " + String(m).padStart(2, "0") + "m " + String(ss).padStart(2, "0") + "s";
}

// state -> pill kind / label
function statePill(state, online) {
  if (!online) return { cls: "offline", label: "Disconnected" };
  switch (state) {
    case "RECORDING":
    case "STARTING":
      return { cls: "rec", label: "Recording" };
    case "TRANSCRIBING":
    case "TRANSCRIBING_NO_PASTE":
      return { cls: "busy", label: "Transcribing" };
    case "PASTING":
      return { cls: "busy", label: "Pasting" };
    case "STOPPING":
    case "STOPPING_NO_PASTE":
      return { cls: "busy", label: "Stopping" };
    case "OFFLINE":
      return { cls: "offline", label: "Offline" };
    default:
      return { cls: "idle", label: "Idle" };
  }
}

window.API = { getJSON, postJSON, delJSON };
window.fmt = { bytes: fmtBytes, dur: fmtDuration, clock: fmtClock, ms: fmtMs, uptime: fmtUptime };
window.getPath = getPath;
window.statePill = statePill;
window.POLL_MS = POLL_MS;
