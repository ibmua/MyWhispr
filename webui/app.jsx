// MyWhispr control-panel app — wired to the real daemon HTTP API

function App() {
  const [snap, setSnap] = useState(null);          // /api/status
  const [config, setConfig] = useState(null);      // /api/config
  const [models, setModels] = useState(null);      // /api/models
  const [shortcuts, setShortcuts] = useState(null);// /api/shortcuts
  const [audioSources, setAudioSources] = useState(null); // /api/audio_sources
  const [shareConfig, setShareConfig] = useState(null); // /api/transcription_api/client_config
  const [history, setHistory] = useState([]);
  const [online, setOnline] = useState(true);
  const [notice, setNotice] = useState(null);      // {kind, text} | null
  const [modelBusy, setModelBusy] = useState(false);

  const noticeTimer = useRef(null);
  const flashNotice = useCallback((text, kind) => {
    setNotice(text ? { text, kind: kind || "info" } : null);
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    if (text) noticeTimer.current = setTimeout(() => setNotice(null), 2800);
  }, []);

  const reloadConfig = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([
        API.getJSON("/api/config"),
        API.getJSON("/api/shortcuts"),
      ]);
      setConfig(c);
      setShortcuts(s);
    } catch (e) {
      flashNotice("Config reload failed: " + e.message, "error");
    }
  }, [flashNotice]);

  const reloadModels = useCallback(async () => {
    try {
      setModels(await API.getJSON("/api/models"));
    } catch (e) {
      // surfaced via offline state
    }
  }, []);

  const reloadAudioSources = useCallback(async () => {
    try {
      setAudioSources(await API.getJSON("/api/audio_sources"));
    } catch (e) {
      // surfaced via offline state
    }
  }, []);

  const reloadShareConfig = useCallback(async () => {
    try {
      setShareConfig(await API.getJSON("/api/transcription_api/client_config"));
    } catch (e) {
      // surfaced via offline state
    }
  }, []);

  // initial load
  useEffect(() => {
    reloadConfig();
    reloadModels();
    reloadAudioSources();
    reloadShareConfig();
  }, [reloadConfig, reloadModels, reloadAudioSources, reloadShareConfig]);

  // poll status + history
  useEffect(() => {
    let cancelled = false;
    let modelsTick = 0;
    async function tick() {
      try {
        const [s, h] = await Promise.all([
          API.getJSON("/api/status"),
          API.getJSON("/api/history"),
        ]);
        if (cancelled) return;
        setSnap(s);
        setHistory(h.items || []);
        if (modelsTick++ % 6 === 0) {
          try { setModels(await API.getJSON("/api/models")); } catch (e) { /* ignored */ }
          try { setShareConfig(await API.getJSON("/api/transcription_api/client_config")); } catch (e) { /* ignored */ }
        }
        setOnline(true);
      } catch (e) {
        if (!cancelled) setOnline(false);
      } finally {
        if (!cancelled) setTimeout(tick, POLL_MS);
      }
    }
    tick();
    return () => { cancelled = true; };
  }, []);

  // config writes
  const writeConfig = useCallback(async (key, value) => {
    try {
      const r = await API.postJSON("/api/config/" + encodeURIComponent(key), { value });
      if (!r.ok) throw new Error(r.reason || "setting rejected");
      await reloadConfig();
      await reloadShareConfig();
    } catch (e) {
      flashNotice("Save failed: " + e.message, "error");
    }
  }, [reloadConfig, reloadShareConfig, flashNotice]);

  const switchModel = useCallback(async (name) => {
    setModelBusy(true);
    flashNotice("Selecting " + name + "…");
    try {
      const r = await API.postJSON("/api/model/warm", { model: name });
      if (!r.ok) throw new Error(r.last_error || r.reason || "model switch failed");
      await reloadConfig();
      await reloadModels();
      flashNotice("Model: " + name);
    } catch (e) {
      flashNotice("Model switch failed: " + e.message, "error");
    } finally {
      setModelBusy(false);
    }
  }, [reloadConfig, reloadModels, flashNotice]);

  const unloadModel = useCallback(async () => {
    setModelBusy(true);
    try {
      await API.postJSON("/api/model/unload", {});
      await reloadModels();
      flashNotice("Model unloaded");
    } catch (e) {
      flashNotice("Unload failed: " + e.message, "error");
    } finally {
      setModelBusy(false);
    }
  }, [reloadModels, flashNotice]);

  const saveExternalModel = useCallback(async (draft) => {
    setModelBusy(true);
    try {
      const r = await API.postJSON("/api/models/external", draft);
      if (!r.ok) throw new Error(r.reason || "save failed");
      await reloadConfig();
      await reloadModels();
      flashNotice("API model saved");
    } catch (e) {
      flashNotice("API model failed: " + e.message, "error");
    } finally {
      setModelBusy(false);
    }
  }, [reloadConfig, reloadModels, flashNotice]);

  const deleteModel = useCallback(async (name) => {
    if (!window.confirm("Delete model " + name + "?")) return;
    setModelBusy(true);
    try {
      const r = await API.delJSON("/api/models/" + encodeURIComponent(name));
      if (!r.ok) throw new Error(r.reason || "delete failed");
      await reloadConfig();
      await reloadModels();
      flashNotice("Model deleted");
    } catch (e) {
      flashNotice("Delete failed: " + e.message, "error");
    } finally {
      setModelBusy(false);
    }
  }, [reloadConfig, reloadModels, flashNotice]);

  const saveCustomWords = useCallback(async (words) => {
    try {
      const r = await API.postJSON("/api/config/custom_words", { words });
      if (!r.ok) throw new Error(r.reason || "save failed");
      await reloadConfig();
    } catch (e) {
      flashNotice("Custom words failed: " + e.message, "error");
    }
  }, [reloadConfig, flashNotice]);

  const saveHallucinationPhrases = useCallback(async (phrases) => {
    try {
      const r = await API.postJSON("/api/config/" + encodeURIComponent("hallucination_filter.phrases.en"), { value: phrases });
      if (!r.ok) throw new Error(r.reason || "save failed");
      await reloadConfig();
    } catch (e) {
      flashNotice("Phrases failed: " + e.message, "error");
    }
  }, [reloadConfig, flashNotice]);

  const retranslate = useCallback(async (model, missingOnly) => {
    try {
      const r = await API.postJSON("/api/history/retranslate", {
        model, limit: 20, missing_only: !!missingOnly,
      });
      if (!r.ok) throw new Error(r.reason || "retranslate rejected");
      flashNotice("Retranscribe queued");
    } catch (e) {
      flashNotice("Retranscribe failed: " + e.message, "error");
    }
  }, [flashNotice]);

  const clearHistory = useCallback(async () => {
    if (!window.confirm("Clear in-memory history?")) return;
    try {
      await API.postJSON("/api/history/clear", {});
      setHistory([]);
      flashNotice("History cleared");
    } catch (e) {
      flashNotice("Clear failed: " + e.message, "error");
    }
  }, [flashNotice]);

  const copyText = useCallback(async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      flashNotice("Copied");
    } catch (e) {
      flashNotice("Copy failed: " + e.message, "error");
    }
  }, [flashNotice]);

  const commitCombo = useCallback(async (keys) => {
    try {
      const r = await API.postJSON("/api/shortcuts/" + encodeURIComponent(DEFAULT_TRIGGER) + "/combo", { keys });
      if (!r.ok) throw new Error(r.reason || "failed");
      await reloadConfig();
      flashNotice("Shortcut updated");
    } catch (e) {
      flashNotice("Shortcut failed: " + e.message, "error");
    }
  }, [reloadConfig, flashNotice]);

  const changeTriggerKey = useCallback(async (info) => {
    try {
      const cfg = (config && config.triggers && config.triggers[DEFAULT_TRIGGER]) || {};
      const r = await API.postJSON("/api/shortcuts/" + encodeURIComponent(DEFAULT_TRIGGER), {
        binding: info.binding,
        keycode: info.keycode,
        default_type: "language",
        default_language: cfg.default_mode || cfg.language || "en",
      });
      if (!r.ok) throw new Error(r.reason || "failed");
      await reloadConfig();
      flashNotice("Trigger set to " + info.label);
    } catch (e) {
      flashNotice("Trigger change failed: " + e.message, "error");
    }
  }, [config, reloadConfig, flashNotice]);

  // derived values
  const ready = !!(config && models && shortcuts);
  const activeModel = (snap && (snap.current_model || (snap.primary_server && snap.primary_server.loaded_model)))
    || (config && config.default_model)
    || "";
  const loadedModel = (snap && snap.primary_server && snap.primary_server.loaded_model) || "";
  const modelLoaded = !!loadedModel && !!(snap && snap.primary_server && (snap.primary_server.running || snap.primary_server.ready));
  const state = snap ? snap.state : "OFFLINE";
  const livePreview = (snap && snap.live_preview) || "";
  const lastFinal = (snap && snap.last_transcript) || "";
  const currentLang = (snap && snap.current_language) || "";
  const transcribing = state === "RECORDING" || state === "STARTING";

  const hallucinationPhrases = (getPath(config, "hallucination_filter.phrases.en") || []);
  const devices = (snap && snap.device_names) || [];

  const onRefresh = () => { reloadConfig(); reloadModels(); reloadAudioSources(); reloadShareConfig(); flashNotice("Refreshed"); };

  if (!ready && !snap) {
    return (
      <div className="app">
        <Header state={online ? "IDLE" : "OFFLINE"} model="" online={online} onRefresh={onRefresh} />
        <main className="grid">
          <section className="card col-12">
            <div className="muted">{online ? "Loading…" : "Daemon HTTP API is not reachable."}</div>
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="app">
      <Header
        state={state}
        model={activeModel}
        online={online}
        onRefresh={onRefresh}
        modelLoaded={modelLoaded}
      />
      {notice && (
        <div className={`app-notice ${notice.kind === "error" ? "error" : ""}`}>{notice.text}</div>
      )}
      {!online && (
        <div className="app-notice error">Daemon HTTP API is not reachable. Reconnecting…</div>
      )}
      <main className="grid">
        <LiveTranscript
          state={state}
          livePreview={livePreview}
          lastFinal={lastFinal}
          currentLang={currentLang}
        />

        <ModelsCard
          models={models}
          activeModel={activeModel}
          onSelect={switchModel}
          onUnload={unloadModel}
          onSaveExternal={saveExternalModel}
          onDeleteModel={deleteModel}
          busy={modelBusy}
        />
        <DaemonStatus
          snap={snap}
        />

        <SettingsCard
          config={config}
          onWrite={writeConfig}
          hallucinationPhrases={hallucinationPhrases}
          onSaveHallucinationPhrases={saveHallucinationPhrases}
          devices={devices}
          audioSources={audioSources}
          onReloadAudioSources={reloadAudioSources}
          transcribing={transcribing}
          shareConfig={shareConfig}
          onCopy={copyText}
        />
        <ShortcutsCard
          config={config}
          shortcuts={shortcuts}
          onCommitCombo={commitCombo}
          onChangeTriggerKey={changeTriggerKey}
          busy={modelBusy}
        />

        <HistoryCard
          history={history}
          activeModel={activeModel}
          models={models}
          onCopy={copyText}
          onClear={clearHistory}
          onRetranslate={retranslate}
          retranslate={snap && snap.retranslate}
        />

        <CustomWordsCard
          words={(config && config.custom_words) || []}
          onSave={saveCustomWords}
        />
      </main>
      <Footer webConfig={config && config.web} version={config && config.version} />
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
