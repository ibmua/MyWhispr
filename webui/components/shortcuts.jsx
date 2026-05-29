// Shortcuts card — wired to /api/shortcuts + /api/shortcuts/{trigger}/combo

const DEFAULT_TRIGGER = "grave";

const DOM_KEY_TO_EVDEV = {
  Backquote: { label: "`", binding: "grave", keycode: 41 },
  Escape: { label: "Esc", binding: "Escape", keycode: 1 },
  Tab: { label: "Tab", binding: "Tab", keycode: 15 },
  Enter: { label: "Enter", binding: "Return", keycode: 28 },
  Space: { label: "Space", binding: "space", keycode: 57 },
  Minus: { label: "-", binding: "minus", keycode: 12 },
  Equal: { label: "=", binding: "equal", keycode: 13 },
  BracketLeft: { label: "[", binding: "bracketleft", keycode: 26 },
  BracketRight: { label: "]", binding: "bracketright", keycode: 27 },
  Backslash: { label: "\\", binding: "backslash", keycode: 43 },
  Semicolon: { label: ";", binding: "semicolon", keycode: 39 },
  Quote: { label: "'", binding: "apostrophe", keycode: 40 },
  Comma: { label: ",", binding: "comma", keycode: 51 },
  Period: { label: ".", binding: "period", keycode: 52 },
  Slash: { label: "/", binding: "slash", keycode: 53 },
};
for (let d = 0; d <= 9; d += 1) DOM_KEY_TO_EVDEV["Digit" + d] = { label: String(d), binding: String(d), keycode: d === 0 ? 11 : d + 1 };
const LETTER_CODES = { A:30,B:48,C:46,D:32,E:18,F:33,G:34,H:35,I:23,J:36,K:37,L:38,M:50,N:49,O:24,P:25,Q:16,R:19,S:31,T:20,U:22,V:47,W:17,X:45,Y:21,Z:44 };
for (const L of Object.keys(LETTER_CODES)) DOM_KEY_TO_EVDEV["Key" + L] = { label: L, binding: L.toLowerCase(), keycode: LETTER_CODES[L] };
for (let f = 1; f <= 12; f += 1) DOM_KEY_TO_EVDEV["F" + f] = { label: "F" + f, binding: "F" + f, keycode: f <= 10 ? f + 58 : (f === 11 ? 87 : 88) };

function ModifierRow({ m, langName, onEdit, onDelete }) {
  const isScript = m.kind === "script";
  const isNostream = m.kind === "nostream";
  return (
    <div className="modifier-row" onClick={onEdit} role="button">
      <span className="kbd">`</span>
      <span className="sc-plus">+</span>
      <span className="kbd" style={{ minWidth: 32 }}>{m.keyLabel || "?"}</span>
      <span className="sc-arrow">→</span>
      <span className="modifier-target">
        {isNostream ? (
          <>
            <span className="muted" style={{ fontSize: 11 }}>switch to</span>{" "}
            <span style={{ color: "var(--text)" }}>non-streaming</span>
          </>
        ) : isScript ? (
          <>
            <span className="muted" style={{ fontSize: 11 }}>script</span>{" "}
            <span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{m.command || "(empty)"}</span>
          </>
        ) : (
          <>
            <span style={{ color: "var(--text)" }}>{langName || m.language}</span>
            <span className="muted" style={{ marginLeft: 4 }}>({m.language})</span>
          </>
        )}
      </span>
      <span className="modifier-actions">
        <button
          className="icon-btn"
          onClick={(e) => { e.stopPropagation(); onEdit(); }}
          title="Edit"
        ><Icon.Settings /></button>
        <button
          className="icon-btn danger"
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          title="Remove"
        ><Icon.X /></button>
      </span>
    </div>
  );
}

function ModifierEditModal({ initial, existingKeys, languages, onSave, onDelete, onClose }) {
  const isNew = !initial;
  const [keyInfo, setKeyInfo] = useState(initial ? {
    label: initial.keyLabel,
    binding: initial.binding,
    code: initial.code,
  } : null);
  const [kind, setKind] = useState(initial?.kind === "nostream" ? "nostream" : initial?.kind === "script" ? "script" : "lang");
  const [langCode, setLangCode] = useState(initial?.kind === "lang" ? (initial.language || "en") : "en");
  const [scriptCmd, setScriptCmd] = useState(initial?.kind === "script" ? (initial.command || "") : "");
  const [capturing, setCapturing] = useState(isNew && !initial?.keyLabel);
  const [conflict, setConflict] = useState(null);

  useEffect(() => {
    const onKey = (e) => {
      if (capturing) return;
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, capturing]);

  useEffect(() => {
    if (!capturing) return;
    const onKey = (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.key === "Escape") { setCapturing(false); return; }
      const info = DOM_KEY_TO_EVDEV[e.code];
      if (!info) return;
      const taken = existingKeys.find(
        k => k.binding === info.binding && (!initial || k.binding !== initial.binding)
      );
      if (taken) {
        setConflict(info.label);
        setCapturing(false);
        return;
      }
      setConflict(null);
      setKeyInfo({ label: info.label, binding: info.binding, code: info.keycode });
      setCapturing(false);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [capturing, existingKeys, initial]);

  const canSave = !!keyInfo && (
    kind === "lang" ? !!langCode :
    kind === "script" ? !!scriptCmd.trim() :
    true
  );

  const handleSave = () => {
    if (!keyInfo) { setCapturing(true); return; }
    if (!canSave) return;
    const type = kind === "lang" ? "language" : kind === "script" ? "script" : "nostream";
    onSave({
      code: keyInfo.code,
      binding: keyInfo.binding,
      label: keyInfo.label,
      type,
      language: kind === "lang" ? langCode : "auto",
      command: kind === "script" ? scriptCmd.trim() : "",
    });
  };

  return ReactDOM.createPortal(
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ width: 480 }}>
        <div className="modal-head">
          <div className="modal-title">{isNew ? "Add shortcut" : "Edit shortcut"}</div>
          <div className="card-spacer"></div>
          <button className="btn icon ghost sm" onClick={onClose}><Icon.X /></button>
        </div>

        <div className="modal-body">
          <div className="edit-field">
            <label className="edit-label">Trigger key</label>
            <div className="key-capture">
              <span className="kbd big">`</span>
              <span className="sc-plus">+</span>
              <button
                className={`key-slot ${capturing ? "capturing" : ""} ${!keyInfo && !capturing ? "empty" : ""}`}
                onClick={() => { setCapturing(true); setConflict(null); }}
              >
                {capturing
                  ? <span className="cap-prompt">Press any key…</span>
                  : keyInfo
                    ? <span className="kbd" style={{ minWidth: 36 }}>{keyInfo.label}</span>
                    : <span className="cap-prompt muted">Click and press a key</span>}
              </button>
              {keyInfo && !capturing && (
                <button className="link-btn" onClick={() => { setCapturing(true); setConflict(null); }}>
                  Change
                </button>
              )}
            </div>
            {conflict && (
              <div className="edit-error">
                <span className="kbd">{conflict}</span> is already used by another shortcut.
              </div>
            )}
            <div className="edit-hint">This key, while holding <span className="kbd" style={{ height: 18, minWidth: 18, fontSize: 11 }}>`</span>, triggers the action below.</div>
          </div>

          <div className="edit-field">
            <label className="edit-label">Action</label>
            <div className="seg-control">
              <button className={`seg ${kind === "lang" ? "on" : ""}`} onClick={() => setKind("lang")}>Language</button>
              <button className={`seg ${kind === "script" ? "on" : ""}`} onClick={() => setKind("script")}>Script</button>
              <button className={`seg ${kind === "nostream" ? "on" : ""}`} onClick={() => setKind("nostream")}>Non-Streaming</button>
            </div>
          </div>

          {kind === "lang" ? (
            <div className="edit-field">
              <label className="edit-label">Transcribe in</label>
              <div className="lang-grid">
                {(languages || []).map(l => (
                  <button
                    key={l.code}
                    className={`lang-pick ${langCode === l.code ? "on" : ""}`}
                    onClick={() => setLangCode(l.code)}
                  >
                    <span className="lang-pick-code">{l.code.toUpperCase()}</span>
                    <span className="lang-pick-name">{l.name}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : kind === "script" ? (
            <div className="edit-field">
              <label className="edit-label">Command</label>
              <input
                className="edit-input"
                placeholder="my-script --flag"
                value={scriptCmd}
                onChange={(e) => setScriptCmd(e.target.value)}
              />
              <div className="edit-hint">
                Receives the transcript on stdin. Stdout is treated as the replacement transcript.
              </div>
            </div>
          ) : (
            <div className="edit-field">
              <label className="edit-label">Session modifier</label>
              <div className="nostream-card">
                <div className="nostream-card-head">
                  <span className="kbd">`</span>
                  <span className="sc-plus">+</span>
                  <span className="kbd" style={{ minWidth: 36 }}>{keyInfo?.label || "…"}</span>
                  <span className="sc-arrow">→</span>
                  <span className="nostream-tag">non-streaming</span>
                </div>
                <div className="edit-hint" style={{ marginTop: 8 }}>
                  Tap this key mid-session to switch the current dictation to non-streaming — anything already streamed is backspaced out and the rest of the transcript is buffered and pasted only when you release the trigger. Language stays whatever the session was already using.
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="modal-foot">
          {!isNew && (
            <button className="btn sm danger" onClick={onDelete}><Icon.Trash /> Remove</button>
          )}
          <div className="spacer"></div>
          <button className="btn sm ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={handleSave} disabled={!canSave}>
            {isNew ? "Add shortcut" : "Save"}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

function ShortcutsCard({ config, shortcuts, onCommitCombo, onChangeTriggerKey, busy }) {
  const trig = (config && config.triggers && config.triggers[DEFAULT_TRIGGER]) || {};
  const combo = trig.combo || {};
  const keys = combo.keys || [];
  const languages = (shortcuts && shortcuts.languages) || [];
  const langName = (code) => {
    const f = languages.find(l => l.code === code);
    return f ? f.name : code;
  };
  const triggerLabel = trig.binding === "grave" ? "Grave" : (trig.binding || "?");
  const triggerKeyLabel = trig.binding === "grave" ? "`" : (trig.binding || "?").charAt(0).toUpperCase() + (trig.binding || "").slice(1);

  const [capturing, setCapturing] = useState(false);
  const [editing, setEditing] = useState(null); // { index } or { index: null } for add

  useEffect(() => {
    if (!capturing) return undefined;
    function onKeyDown(e) {
      e.preventDefault();
      e.stopPropagation();
      const info = DOM_KEY_TO_EVDEV[e.code];
      setCapturing(false);
      if (!info) return;
      onChangeTriggerKey(info);
    }
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [capturing, onChangeTriggerKey]);

  const cleanKeys = (arr) => arr.map(k => ({
    code: Number(k.code),
    binding: k.binding,
    label: k.label,
    type: k.type || "language",
    language: k.language || "auto",
    command: k.command || "",
  })).filter(k => Number.isFinite(k.code) && k.code > 0);

  const remove = (idx) => onCommitCombo(cleanKeys(keys.filter((_, i) => i !== idx)));

  const save = (entry) => {
    let next;
    if (editing.index === null) {
      next = [...keys, entry];
    } else {
      next = keys.map((k, i) => i === editing.index ? entry : k);
    }
    onCommitCombo(cleanKeys(next));
    setEditing(null);
  };

  const removeFromModal = () => {
    if (editing.index !== null) remove(editing.index);
    setEditing(null);
  };

  const existingKeys = keys.map(k => ({ binding: k.binding }));

  return (
    <section className="card col-5">
      <div className="card-head">
        <div className="card-title">Shortcuts</div>
        <div className="card-spacer"></div>
      </div>

      <div className="trigger-block">
        <div className="trigger-label">Hold trigger</div>
        <div className="trigger-row">
          <span className="kbd big">{triggerKeyLabel}</span>
          <div className="trigger-meta">
            <div className="trigger-name">{triggerLabel}</div>
            <div className="trigger-desc">Recording starts when held</div>
          </div>
          <button className="btn sm" onClick={() => setCapturing(true)} disabled={busy}>
            {capturing ? "Press key…" : "Change"}
          </button>
        </div>
        {capturing && <div className="capture-banner">Press a key (Esc to cancel)…</div>}
      </div>

      <div className="modifiers-block">
        <div className="modifiers-label">
          <span>While holding, press</span>
        </div>
        <div className="modifier-list">
          {keys.length === 0 && (
            <div className="muted" style={{ fontSize: 12, padding: "8px 4px" }}>
              No modifiers configured.
            </div>
          )}
          {keys.map((k, i) => {
            const m = {
              keyLabel: k.label || k.binding,
              binding: k.binding,
              code: k.code,
              kind: k.type === "script" ? "script" : k.type === "nostream" ? "nostream" : "language",
              language: k.language || "auto",
              command: k.command || "",
            };
            return (
              <ModifierRow
                key={`${k.code}-${i}`}
                m={m}
                langName={langName(m.language)}
                onEdit={() => setEditing({ index: i })}
                onDelete={() => remove(i)}
              />
            );
          })}
        </div>
      </div>

      <div className="shortcuts-footer">
        <button className="btn sm" onClick={() => setEditing({ index: null })}>
          <Icon.Plus /> Add
        </button>
        <span className="muted" style={{ marginLeft: 8 }}>
          {keys.length} {keys.length === 1 ? "modifier" : "modifiers"} configured
        </span>
      </div>

      {editing && (
        <ModifierEditModal
          initial={editing.index !== null ? (() => {
            const k = keys[editing.index];
            return {
              keyLabel: k.label || k.binding,
              binding: k.binding,
              code: k.code,
              kind: k.type === "script" ? "script" : k.type === "nostream" ? "nostream" : "lang",
              language: k.language || "auto",
              command: k.command || "",
            };
          })() : null}
          existingKeys={existingKeys}
          languages={languages}
          onSave={save}
          onDelete={removeFromModal}
          onClose={() => setEditing(null)}
        />
      )}
    </section>
  );
}

window.ShortcutsCard = ShortcutsCard;
window.DOM_KEY_TO_EVDEV = DOM_KEY_TO_EVDEV;
window.DEFAULT_TRIGGER = DEFAULT_TRIGGER;
