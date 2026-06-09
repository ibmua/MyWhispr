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

function cleanShortcutKeys(arr, modes) {
  const modeMap = modes || {};
  return (arr || []).map(k => {
    const mode = k.short_mode && modeMap[k.short_mode] ? modeMap[k.short_mode] : {};
    const type = k.type || k.kind || "language";
    return {
      code: Number(k.code),
      binding: k.binding,
      label: k.label,
      type,
      language: k.language || mode.language || k.switch_language || (type === "language" ? k.short_mode : "") || "auto",
      command: k.command || mode.command || "",
    };
  }).filter(k => Number.isFinite(k.code) && k.code > 0);
}

function cloneShortcutKeys(arr) {
  return cleanShortcutKeys(arr).map(k => ({ ...k }));
}

function shortcutSignature(entry) {
  if (!entry) return "";
  return JSON.stringify({
    code: Number(entry.code),
    binding: entry.binding || "",
    label: entry.label || "",
    type: entry.type || "language",
    language: entry.language || "auto",
    command: entry.command || "",
  });
}

function ModifierRow({ m, langName, onEdit, onDelete }) {
  const isScript = m.kind === "script";
  const isNostream = m.kind === "nostream";
  const isLowercase = m.kind === "lowercase_initial";
  return (
    <div className="modifier-row" onClick={onEdit} role="button">
      <span className="kbd">`</span>
      <span className="sc-plus">+</span>
      <span className="kbd" style={{ minWidth: 32 }}>{m.keyLabel || "?"}</span>
      <span className="sc-arrow">→</span>
      <span className="modifier-target">
        {isLowercase ? (
          <>
            <span className="muted" style={{ fontSize: 11 }}>make first letter</span>{" "}
            <span style={{ color: "var(--text)" }}>lowercase</span>
          </>
        ) : isNostream ? (
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

function ModifierEditModal({ initial, existingKeys, languages, onAutosave, onDelete, onRevert, onDone }) {
  const isNew = !initial;
  const [keyInfo, setKeyInfo] = useState(initial ? {
    label: initial.keyLabel,
    binding: initial.binding,
    code: initial.code,
  } : null);
  const [kind, setKind] = useState(
    initial?.kind === "nostream" ? "nostream" :
    initial?.kind === "lowercase_initial" ? "lowercase_initial" :
    initial?.kind === "script" ? "script" :
    "lang"
  );
  const [langCode, setLangCode] = useState(initial?.kind === "lang" ? (initial.language || "en") : "en");
  const [scriptLanguage] = useState(initial?.kind === "script" ? (initial.language || "auto") : "auto");
  const [scriptCmd, setScriptCmd] = useState(initial?.kind === "script" ? (initial.command || "") : "");
  const [capturing, setCapturing] = useState(isNew && !initial?.keyLabel);
  const [conflict, setConflict] = useState(null);
  const [saveState, setSaveState] = useState("idle");
  const [saveError, setSaveError] = useState("");
  const saveTimer = useRef(null);
  const pendingSave = useRef(null);
  const drainPromise = useRef(null);
  const mounted = useRef(true);
  const lastSubmitted = useRef(initial ? shortcutSignature({
    code: initial.code,
    binding: initial.binding,
    label: initial.keyLabel,
    type: initial.kind === "lang" ? "language" : initial.kind,
    language: initial.kind === "lang" || initial.kind === "script" ? (initial.language || "auto") : "auto",
    command: initial.command || "",
  }) : "");

  const buildEntry = useCallback(() => {
    if (!keyInfo) return null;
    if (kind === "script" && !scriptCmd.trim()) return null;
    const type = kind === "lang" ? "language" : kind === "script" ? "script" : kind;
    return {
      code: keyInfo.code,
      binding: keyInfo.binding,
      label: keyInfo.label,
      type,
      language: kind === "lang" ? langCode : kind === "script" ? scriptLanguage : "auto",
      command: kind === "script" ? scriptCmd.trim() : "",
    };
  }, [keyInfo, kind, langCode, scriptLanguage, scriptCmd]);

  const drainSaves = useCallback(() => {
    if (drainPromise.current) return drainPromise.current;
    drainPromise.current = (async () => {
      if (mounted.current) {
        setSaveState("saving");
        setSaveError("");
      }
      try {
        while (pendingSave.current) {
          const next = pendingSave.current;
          pendingSave.current = null;
          const ok = await onAutosave(next);
          if (!ok) {
            if (mounted.current) {
              setSaveState("error");
              setSaveError("Save failed");
            }
            return false;
          }
          lastSubmitted.current = shortcutSignature(next);
        }
        if (mounted.current) setSaveState("saved");
        return true;
      } finally {
        drainPromise.current = null;
      }
    })();
    return drainPromise.current;
  }, [onAutosave]);

  const queueSave = useCallback((entry) => {
    pendingSave.current = entry;
    return drainSaves();
  }, [drainSaves]);

  useEffect(() => {
    return () => {
      mounted.current = false;
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, []);

  useEffect(() => {
    if (!capturing) return;
    const onKey = (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.key === "Escape") { setCapturing(false); return; }
      const info = DOM_KEY_TO_EVDEV[e.code];
      if (!info) return;
      const taken = existingKeys.find(k => k.binding === info.binding);
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
  }, [capturing, existingKeys]);

  const draftEntry = buildEntry();
  const canSave = !!draftEntry;
  const draftSignature = draftEntry ? shortcutSignature(draftEntry) : "";

  useEffect(() => {
    if (!draftEntry) return undefined;
    if (draftSignature === lastSubmitted.current) return undefined;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    setSaveState("pending");
    setSaveError("");
    saveTimer.current = setTimeout(() => {
      queueSave(draftEntry);
    }, kind === "script" ? 520 : 180);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [draftSignature, kind, queueSave]);

  const handleDone = useCallback(async () => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    const entry = buildEntry();
    if (entry && shortcutSignature(entry) !== lastSubmitted.current) {
      const ok = await queueSave(entry);
      if (!ok) return;
    } else if (drainPromise.current) {
      const ok = await drainPromise.current;
      if (!ok) return;
    }
    onDone();
  }, [buildEntry, queueSave, onDone]);

  useEffect(() => {
    const onKey = (e) => {
      if (capturing) return;
      if (e.key === "Escape") {
        e.preventDefault();
        handleDone();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handleDone, capturing]);

  const handleRevert = async () => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    pendingSave.current = null;
    setSaveState("saving");
    setSaveError("");
    if (drainPromise.current) {
      await drainPromise.current;
    }
    const ok = await onRevert();
    if (!ok && mounted.current) {
      setSaveState("error");
      setSaveError("Revert failed");
    }
  };

  const handleDelete = async () => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    pendingSave.current = null;
    if (drainPromise.current) await drainPromise.current;
    onDelete();
  };

  return ReactDOM.createPortal(
    <div className="modal-backdrop" onClick={handleDone}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ width: 480 }}>
        <div className="modal-head">
          <div className="modal-title">{isNew ? "Add shortcut" : "Edit shortcut"}</div>
          <div className="card-spacer"></div>
          <button className="btn icon ghost sm" onClick={handleDone}><Icon.X /></button>
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
              <button className={`seg ${kind === "lowercase_initial" ? "on" : ""}`} onClick={() => setKind("lowercase_initial")}>Lowercase</button>
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
          ) : kind === "lowercase_initial" ? (
            <div className="edit-field">
              <label className="edit-label">Session modifier</label>
              <div className="nostream-card">
                <div className="nostream-card-head">
                  <span className="kbd">`</span>
                  <span className="sc-plus">+</span>
                  <span className="kbd" style={{ minWidth: 36 }}>{keyInfo?.label || "…"}</span>
                  <span className="sc-arrow">→</span>
                  <span className="nostream-tag">lowercase first letter</span>
                </div>
                <div className="edit-hint" style={{ marginTop: 8 }}>
                  Tap this key mid-session to make the first cased letter lowercase in live output and the final pasted transcript. It uses Unicode casing, so Ukrainian and other alphabets are handled without ASCII-only rules.
                </div>
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
            <button className="btn sm danger" onClick={handleDelete}><Icon.Trash /> Remove</button>
          )}
          <span className={`autosave-status ${saveState === "error" ? "error" : ""}`}>
            {saveState === "pending" ? "Pending" :
             saveState === "saving" ? "Saving" :
             saveState === "saved" ? "Saved" :
             saveState === "error" ? (saveError || "Save failed") : ""}
          </span>
          <div className="spacer"></div>
          <button className="btn sm ghost" onClick={handleRevert}>Revert</button>
          <button className="btn primary" onClick={handleDone} disabled={!canSave && isNew}>
            Done
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
  const modes = (config && config.modes) || {};
  const keys = cleanShortcutKeys(combo.keys || [], modes);
  const languages = (shortcuts && shortcuts.languages) || [];
  const langName = (code) => {
    const f = languages.find(l => l.code === code);
    return f ? f.name : code;
  };
  const triggerLabel = trig.binding === "grave" ? "Grave" : (trig.binding || "?");
  const triggerKeyLabel = trig.binding === "grave" ? "`" : (trig.binding || "?").charAt(0).toUpperCase() + (trig.binding || "").slice(1);

  const [capturing, setCapturing] = useState(false);
  const [editing, setEditing] = useState(null);
  const editingRef = useRef(null);

  useEffect(() => {
    editingRef.current = editing;
  }, [editing]);

  useEffect(() => {
    if (!capturing) return undefined;
    function onKeyDown(e) {
      e.preventDefault();
      e.stopPropagation();
      if (e.key === "Escape") {
        setCapturing(false);
        return;
      }
      const info = DOM_KEY_TO_EVDEV[e.code];
      setCapturing(false);
      if (!info) return;
      onChangeTriggerKey(info);
    }
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [capturing, onChangeTriggerKey]);

  const openEditor = (index) => {
    const baselineKeys = cloneShortcutKeys(keys);
    setEditing({
      index,
      baselineKeys,
      currentKeys: cloneShortcutKeys(baselineKeys),
    });
  };

  const remove = (idx) => onCommitCombo(cleanShortcutKeys(keys.filter((_, i) => i !== idx)), { label: "Shortcut removed" });

  const autosaveEditing = useCallback(async (entry) => {
    const prev = editingRef.current;
    if (!prev) return false;
    const nextKeys = cloneShortcutKeys(prev.currentKeys);
    const targetIndex = prev.index === null ? nextKeys.length : prev.index;
    if (prev.index === null) {
      nextKeys.push(entry);
    } else {
      nextKeys[targetIndex] = entry;
    }
    const nextEditing = {
      ...prev,
      index: targetIndex,
      currentKeys: cloneShortcutKeys(nextKeys),
    };
    editingRef.current = nextEditing;
    setEditing(nextEditing);
    return await onCommitCombo(cleanShortcutKeys(nextKeys), {
      silent: true,
      errorPrefix: "Shortcut autosave failed",
    });
  }, [onCommitCombo]);

  const revertEditing = useCallback(async () => {
    const prev = editingRef.current;
    if (!prev) return false;
    const ok = await onCommitCombo(cloneShortcutKeys(prev.baselineKeys), {
      label: "Shortcuts reverted",
      errorPrefix: "Shortcut revert failed",
    });
    if (ok) {
      editingRef.current = null;
      setEditing(null);
    }
    return ok;
  }, [onCommitCombo]);

  const closeEditing = useCallback(() => {
    editingRef.current = null;
    setEditing(null);
  }, []);

  const removeFromModal = async () => {
    const prev = editingRef.current;
    if (!prev || prev.index === null) {
      closeEditing();
      return;
    }
    const nextKeys = cloneShortcutKeys(prev.currentKeys).filter((_, i) => i !== prev.index);
    const ok = await onCommitCombo(cleanShortcutKeys(nextKeys), {
      label: "Shortcut removed",
      errorPrefix: "Shortcut remove failed",
    });
    if (ok) closeEditing();
  };

  const modalKey = editing && editing.index !== null ? editing.currentKeys[editing.index] : null;
  const existingKeys = editing
    ? editing.currentKeys
      .map((k, i) => ({ binding: k.binding, index: i }))
      .filter(k => k.index !== editing.index)
    : [];

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
              kind: k.type === "script" ? "script" : k.type === "nostream" ? "nostream" : k.type === "lowercase_initial" ? "lowercase_initial" : "language",
              language: k.language || "auto",
              command: k.command || "",
            };
            return (
              <ModifierRow
                key={`${k.code}-${i}`}
                m={m}
                langName={langName(m.language)}
                onEdit={() => openEditor(i)}
                onDelete={() => remove(i)}
              />
            );
          })}
        </div>
      </div>

      <div className="shortcuts-footer">
        <button className="btn sm" onClick={() => openEditor(null)}>
          <Icon.Plus /> Add
        </button>
        <span className="muted" style={{ marginLeft: 8 }}>
          {keys.length} {keys.length === 1 ? "modifier" : "modifiers"} configured
        </span>
      </div>

      {editing && (
        <ModifierEditModal
          initial={modalKey ? (() => {
            const k = modalKey;
            return {
              keyLabel: k.label || k.binding,
              binding: k.binding,
              code: k.code,
              kind: k.type === "script" ? "script" : k.type === "nostream" ? "nostream" : k.type === "lowercase_initial" ? "lowercase_initial" : "lang",
              language: k.language || "auto",
              command: k.command || "",
            };
          })() : null}
          existingKeys={existingKeys}
          languages={languages}
          onAutosave={autosaveEditing}
          onDelete={removeFromModal}
          onRevert={revertEditing}
          onDone={closeEditing}
        />
      )}
    </section>
  );
}

window.ShortcutsCard = ShortcutsCard;
window.DOM_KEY_TO_EVDEV = DOM_KEY_TO_EVDEV;
window.DEFAULT_TRIGGER = DEFAULT_TRIGGER;
