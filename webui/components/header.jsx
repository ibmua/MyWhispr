// Header, status pills, shared Toggle, Stepper
const { useState, useEffect, useRef, useCallback, useMemo } = React;

function Toggle({ on, onChange, accent = false, disabled = false }) {
  return (
    <button
      type="button"
      className={`toggle ${on ? "on" : ""} ${accent ? "accent" : ""}`}
      onClick={() => !disabled && onChange(!on)}
      disabled={disabled}
      aria-pressed={on}
    />
  );
}

function Header({ state, model, online, onRefresh, modelLoaded, queuePending = 0 }) {
  const pill = statePill(state, online);
  const showGpuPill = !!modelLoaded && online;
  // Recordings still being transcribed/inserted behind the live one.
  const backlog = online ? Math.max(0, queuePending - (state === "TRANSCRIBING" || state === "PASTING" ? 1 : 0)) : 0;
  return (
    <header className="app-header">
      <div className="brand">
        <div className="brand-mark"><Icon.Logo style={{ color: "#22c55e" }} /></div>
        <div className="brand-title">
          <div className="brand-name">MyWhispr</div>
          <div className="brand-sub">Local dictation daemon</div>
        </div>
      </div>
      <div className="header-status">
        {showGpuPill
          ? <span className="pill ok"><span className="dot"></span>Model on GPU</span>
          : online
            ? <span className="pill"><span className="dot"></span>{model ? "Model idle" : "No model"}</span>
            : <span className="pill offline"><span className="dot"></span>Disconnected</span>}
        <span className="pill model-pill"><span className="label-muted">model:</span> <b>{model || "—"}</b></span>
        <span className={`pill ${pill.cls}`}>
          {pill.cls === "rec" ? <span className="dot"></span> : null}
          {pill.label}
        </span>
        {backlog > 0 && (
          <span className="pill busy" title="Earlier recordings still being transcribed and inserted">
            {backlog} queued
          </span>
        )}
      </div>
      <div className="header-actions">
        <button className="btn" onClick={onRefresh}><Icon.Refresh /> Refresh</button>
      </div>
    </header>
  );
}

function Stepper({ value, onChange, min = 0, max = 9999, step = 1 }) {
  return (
    <div className="stepper">
      <button onClick={() => onChange(Math.max(min, value - step))} aria-label="decrement"><Icon.Minus /></button>
      <input
        type="text"
        value={value}
        onChange={(e) => {
          const v = parseInt(e.target.value, 10);
          if (!isNaN(v)) onChange(Math.max(min, Math.min(max, v)));
        }}
      />
      <button onClick={() => onChange(Math.min(max, value + step))} aria-label="increment"><Icon.Plus /></button>
    </div>
  );
}

window.Toggle = Toggle;
window.Header = Header;
window.Stepper = Stepper;
