// Settings card — wired to backend config; input device row + mic meter at top

function SettingToggleRow({ label, on, setOn }) {
  return (
    <div className="field-row">
      <span className="field-label">{label}</span>
      <span className="field-input"><Toggle on={on} onChange={setOn} /></span>
    </div>
  );
}

// VU-style meter — pulses while recording, idles otherwise
function MicMeter({ transcribing }) {
  const [bars, setBars] = useState([0.15, 0.25, 0.18, 0.3, 0.2]);
  useEffect(() => {
    let timer;
    const tick = () => {
      setBars((prev) =>
        prev.map((v) => {
          if (transcribing) {
            const target = 0.25 + Math.random() * 0.75;
            return v * 0.55 + target * 0.45;
          }
          const target = 0.08 + Math.random() * 0.12;
          return v * 0.85 + target * 0.15;
        })
      );
      timer = setTimeout(() => requestAnimationFrame(tick), transcribing ? 70 : 220);
    };
    tick();
    return () => clearTimeout(timer);
  }, [transcribing]);
  return (
    <span className="mic-meter" aria-hidden="true">
      {bars.map((v, i) => (
        <span
          key={i}
          className="mic-bar"
          style={{
            height: `${4 + v * 14}px`,
            background: transcribing && v > 0.7 ? "var(--accent)" : transcribing ? "var(--info)" : "var(--text-4)",
            opacity: transcribing ? 0.9 : 0.55,
          }}
        />
      ))}
    </span>
  );
}

function AudioInputRow({ audioSources, onReloadAudioSources, onWrite, transcribing }) {
  const items = (audioSources && audioSources.items) || [];
  const selected = (audioSources && audioSources.selected) || "";
  // Hide monitor sources (loopback) by default; show them as a fallback group only if no real input is available.
  const live = items.filter(s => !s.monitor);
  const monitors = items.filter(s => s.monitor);
  const showItems = live.length ? live : items;
  const noSources = !audioSources || !audioSources.items;
  const detected = items.length > 0;
  return (
    <div className="input-device-row">
      <div className="idr-label">
        <Icon.Mic style={{ color: "var(--text-3)" }} />
        <span>Audio input</span>
      </div>
      <div className="idr-control">
        <select
          className="device-select"
          value={selected}
          onChange={(e) => onWrite("audio_input_device", e.target.value)}
          disabled={noSources}
          title={selected ? selected : "System default audio source"}
        >
          <option value="">System default (follow PipeWire)</option>
          {showItems.map((s) => (
            <option key={s.name} value={s.name}>
              {s.nick || s.description || s.name}
            </option>
          ))}
          {live.length > 0 && monitors.length > 0 && monitors.map((s) => (
            <option key={s.name} value={s.name}>
              {(s.nick || s.description || s.name)} (monitor)
            </option>
          ))}
        </select>
        <button
          className="btn icon ghost sm"
          onClick={onReloadAudioSources}
          title="Rescan audio devices"
          style={{ marginLeft: 6 }}
        >
          <Icon.Refresh />
        </button>
        <MicMeter transcribing={transcribing} />
      </div>
      {!detected && (
        <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
          No PipeWire audio sources detected. Using system default.
        </div>
      )}
    </div>
  );
}

function SettingsCard({ config, onWrite, hallucinationPhrases, onSaveHallucinationPhrases, devices, audioSources, onReloadAudioSources, transcribing }) {
  const get = (path, fallback) => {
    const v = getPath(config, path);
    return v === undefined ? fallback : v;
  };
  const onBool = (path) => (v) => onWrite(path, !!v);
  const livePreview = get("live_preview.enabled", true);
  const streamIntoApp = get("streaming.app_output_enabled", true);
  const trailingSpace = get("append_trailing_space", true);
  const showLastTopbar = get("topbar.show_when_idle", true);
  const hallucinationOn = get("hallucination_filter.enabled", true);
  const audioCuesOn = get("audio_cues.enabled", true);
  const volumePct = Math.round(Number(get("audio_cues.volume", 0.55)) * 100);
  const maxRec = String(get("maximum_recording_seconds", 240));
  const startCooldown = String(get("start_cooldown_seconds", 0.2));
  const wordLimit = Number(get("topbar.max_words", 10));

  const [maxRecDraft, setMaxRecDraft] = useState(maxRec);
  const [coolDraft, setCoolDraft] = useState(startCooldown);
  const [volDraft, setVolDraft] = useState(volumePct);

  useEffect(() => setMaxRecDraft(maxRec), [maxRec]);
  useEffect(() => setCoolDraft(startCooldown), [startCooldown]);
  useEffect(() => setVolDraft(volumePct), [volumePct]);

  const commitMaxRec = () => {
    const v = parseInt(maxRecDraft, 10);
    if (!isNaN(v) && v > 0) onWrite("maximum_recording_seconds", v);
    else setMaxRecDraft(maxRec);
  };
  const commitCooldown = () => {
    const v = parseFloat(coolDraft);
    if (!isNaN(v) && v >= 0) onWrite("start_cooldown_seconds", v);
    else setCoolDraft(startCooldown);
  };
  const commitVolume = () => {
    const v = Math.max(0, Math.min(100, Number(volDraft) || 0));
    onWrite("audio_cues.volume", v / 100);
    if (v === 0 && audioCuesOn) onWrite("audio_cues.enabled", false);
    if (v > 0 && !audioCuesOn) onWrite("audio_cues.enabled", true);
  };

  return (
    <section className="card col-7">
      <div className="card-head">
        <div className="card-title">Settings</div>
      </div>

      <AudioInputRow
        audioSources={audioSources}
        onReloadAudioSources={onReloadAudioSources}
        onWrite={onWrite}
        transcribing={transcribing}
      />

      <div className="settings-grid">
        <div className="col">
          <SettingToggleRow label="Live preview" on={livePreview} setOn={onBool("live_preview.enabled")} />
          <SettingToggleRow label="Stream into app" on={streamIntoApp} setOn={onBool("streaming.app_output_enabled")} />
          <SettingToggleRow label="Append trailing space" on={trailingSpace} setOn={onBool("append_trailing_space")} />
          <SettingToggleRow label="Show last transcript in top bar" on={showLastTopbar} setOn={onBool("topbar.show_when_idle")} />
          <HallucinationRow
            on={hallucinationOn}
            setOn={onBool("hallucination_filter.enabled")}
            phrases={hallucinationPhrases}
            onSavePhrases={onSaveHallucinationPhrases}
          />
        </div>
        <div className="col">
          <div className="field-row">
            <span className="field-label">Max recording</span>
            <span className="field-input">
              <span className="input-wrap">
                <input className="input unit-suffix" value={maxRecDraft}
                  onChange={(e) => setMaxRecDraft(e.target.value.replace(/[^0-9]/g, ""))}
                  onBlur={commitMaxRec}
                  onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                />
                <span className="unit">s</span>
              </span>
            </span>
          </div>
          <div className="field-row">
            <span className="field-label">Start cooldown</span>
            <span className="field-input">
              <span className="input-wrap">
                <input className="input unit-suffix" value={coolDraft}
                  onChange={(e) => setCoolDraft(e.target.value.replace(/[^0-9.]/g, ""))}
                  onBlur={commitCooldown}
                  onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                />
                <span className="unit">s</span>
              </span>
            </span>
          </div>
          <div className="field-row">
            <span className="field-label">Top-bar word count</span>
            <span className="field-input">
              <Stepper
                value={wordLimit}
                onChange={(v) => onWrite("topbar.max_words", v)}
                min={1}
                max={50}
              />
            </span>
          </div>
          <div style={{ paddingTop: 8 }}>
            <div className="field-label" style={{ marginBottom: 6 }}>
              Beep volume {volDraft === 0 && <span style={{ color: "var(--text-3)", fontSize: 11.5, marginLeft: 4 }}>· off</span>}
            </div>
            <div className="slider-row">
              <Icon.Speaker style={{ color: volDraft === 0 ? "var(--text-4)" : "var(--text-3)" }} />
              <input type="range" min="0" max="100" value={volDraft}
                onChange={(e) => setVolDraft(parseInt(e.target.value, 10))}
                onMouseUp={commitVolume}
                onTouchEnd={commitVolume}
                onKeyUp={(e) => { if (e.key === "Enter" || e.key === " ") commitVolume(); }}
                className="slider" />
              <span className="slider-value">{volDraft}%</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

window.SettingsCard = SettingsCard;
window.MicMeter = MicMeter;
