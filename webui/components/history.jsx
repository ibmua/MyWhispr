// History card — multi-line entries with audio, language badge, retranslate

const LANG_LABEL = {
  en: { name: "English", color: "#60a5fa" },
  uk: { name: "Ukrainian", color: "#fbbf24" },
  es: { name: "Spanish", color: "#f472b6" },
  fr: { name: "French", color: "#a78bfa" },
  de: { name: "German", color: "#34d399" },
  ru: { name: "Russian", color: "#f87171" },
  it: { name: "Italian", color: "#10b981" },
  pt: { name: "Portuguese", color: "#fb923c" },
  pl: { name: "Polish", color: "#22d3ee" },
  ja: { name: "Japanese", color: "#e879f9" },
  zh: { name: "Chinese", color: "#fcd34d" },
  ko: { name: "Korean", color: "#a3e635" },
};

function langMeta(code) {
  const c = String(code || "").toLowerCase();
  const m = LANG_LABEL[c];
  return m
    ? { name: m.name, code: c.toUpperCase(), color: m.color }
    : { name: c || "—", code: (c || "??").toUpperCase(), color: "#94a3b8" };
}

function LangBadge({ lang }) {
  const meta = langMeta(lang);
  return (
    <span
      className="lang-badge"
      title={meta.name}
      style={{
        color: meta.color,
        background: `color-mix(in oklab, ${meta.color} 14%, transparent)`,
        borderColor: `color-mix(in oklab, ${meta.color} 32%, transparent)`,
      }}
    >
      {meta.code}
    </span>
  );
}

function HistoryEntry({ item, activeModel, onCopy, onDelete, audioOpen, onToggleAudio }) {
  const alt = item.alternate || {};
  const alternates = Array.isArray(item.alternates) && item.alternates.length
    ? item.alternates
    : (alt.text || alt.status ? [alt] : []);
  const hasAlt = alternates.length > 0;
  const [expanded, setExpanded] = useState(true);
  const lang = item.language || item.mode || "";
  return (
    <div className="history-entry">
      <div className="history-meta">
        <span className="h-time">{fmt.clock(item.created_at)}</span>
        {item.generation_ms ? <span className="h-gen" title="Whisper request to response">{fmt.ms(item.generation_ms)}</span> : null}
        {lang && <LangBadge lang={lang} />}
        <span className="h-model" data-model={item.model}>{item.model || "—"}</span>
        <span className="h-dur">{fmt.dur(item.duration_seconds)}</span>
        {item.failed_reason
          ? <span className="lang-badge" style={{ color: "var(--danger)", borderColor: "rgba(248,113,113,0.35)", background: "var(--danger-soft)" }}>{item.failed_reason}</span>
          : null}
        <div className="h-spacer"></div>
        <div className="h-actions">
          {item.has_audio && (
            <button className="icon-btn" title={audioOpen ? "Hide audio" : "Play audio"} onClick={() => onToggleAudio(item.id)}>
              <Icon.Play />
            </button>
          )}
          <button className="icon-btn" title="Copy" onClick={() => onCopy(item.text || "")}><Icon.Copy /></button>
          <button className="icon-btn danger" title="Delete (note: in-memory only via Clear)" disabled style={{ opacity: 0.3 }}>
            <Icon.Trash />
          </button>
        </div>
      </div>
      <div className="history-text">{item.text || "(no text)"}</div>
      {audioOpen && item.audio_url && (
        <div className="audio-row">
          <audio controls preload="none" src={item.audio_url} autoPlay />
        </div>
      )}
      {item.script && item.script.output ? (
        <div className="history-text script-output">[script] {item.script.output}</div>
      ) : null}
      {hasAlt && (
        <div className="history-retrans">
          <div
            className="retrans-head"
            onClick={() => setExpanded(!expanded)}
            role="button"
          >
            <svg className={`chev ${expanded ? "open" : ""}`} width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9"/>
            </svg>
            <span className="retrans-label">
              {alternates.some((r) => r.status && r.status !== "done")
                ? "Retranscribing"
                : "Retranscriptions"}
            </span>
            <span className="retrans-count">{alternates.length}</span>
          </div>
          {expanded && (
            <div className="retrans-list">
              {alternates.map((result, idx) => (
                <div className="retrans-item" key={result.id || `${result.model || activeModel}-${idx}`}>
                  <div className="retrans-item-head">
                    <span className="h-model" data-model={result.model}>{result.model || activeModel || "—"}</span>
                    {result.created_at && <span className="retrans-clock">{fmt.clock(result.created_at)}</span>}
                    {result.generation_ms ? <span className="retrans-gen" title="Whisper request to response">{fmt.ms(result.generation_ms)}</span> : null}
                    {result.status && result.status !== "done" && <span className="retrans-status">{result.status}</span>}
                    {result.text && result.text === item.text && <span className="retrans-same">identical</span>}
                  </div>
                  <div className="history-text retrans-text">
                    {result.error
                      ? <span className="inline-error">{result.error}</span>
                      : result.text
                        ? (result.text === item.text
                            ? <span className="muted">(no changes from original)</span>
                            : result.text)
                        : <span className="muted">…</span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function HistoryCard({ history, activeModel, models, onCopy, onClear, onRetranslate, retranslate }) {
  const [filter, setFilter] = useState("all");
  const [audioOpen, setAudioOpen] = useState(null);
  const [retranslateModel, setRetranslateModel] = useState("");

  const filtered = useMemo(() => {
    if (filter === "all") return history;
    return history.filter((h) => (h.language || h.mode) === filter);
  }, [history, filter]);

  const langs = useMemo(() => {
    const set = new Set(history.map((h) => h.language || h.mode).filter(Boolean));
    return Array.from(set);
  }, [history]);

  const modelOptions = useMemo(() => {
    return ((models && models.items) || []).filter((m) => m.exists);
  }, [models]);

  useEffect(() => {
    if (!modelOptions.length) {
      setRetranslateModel("");
      return;
    }
    const current = retranslateModel || activeModel;
    if (!current || !modelOptions.some((m) => m.name === current)) {
      setRetranslateModel(
        modelOptions.some((m) => m.name === activeModel) ? activeModel : modelOptions[0].name
      );
    }
  }, [modelOptions, activeModel, retranslateModel]);

  const onToggleAudio = (id) => setAudioOpen((cur) => (cur === id ? null : id));

  const retr = retranslate || {};
  const retrActive = !!retr.active;
  const selectedModel = retranslateModel || activeModel || (modelOptions[0] && modelOptions[0].name) || "";

  return (
    <section className="card col-12">
      <div className="card-head">
        <div className="card-title">History</div>
        <span className="history-head-meta">{history.length} {history.length === 1 ? "item" : "items"}</span>
        <div className="card-spacer"></div>

        {langs.length > 0 && (
          <div className="history-filters">
            <button className={`filter-pill ${filter === "all" ? "on" : ""}`} onClick={() => setFilter("all")}>
              All
            </button>
            {langs.map((l) => (
              <button key={l} className={`filter-pill ${filter === l ? "on" : ""}`} onClick={() => setFilter(l)}>
                {langMeta(l).code}
              </button>
            ))}
          </div>
        )}

        <select
          className="device-select retrans-model-select"
          value={selectedModel}
          onChange={(e) => setRetranslateModel(e.target.value)}
          disabled={retrActive || !modelOptions.length}
          title="Retranscription model"
        >
          {modelOptions.map((m) => (
            <option key={m.name} value={m.name}>{m.name}</option>
          ))}
        </select>
        <button
          className="btn sm"
          onClick={() => onRetranslate(selectedModel, false)}
          disabled={retrActive || !history.length || !selectedModel}
          title={`Retranscribe all items with ${selectedModel || "selected model"}`}
        >
          <Icon.Translate /> Retranscribe all
        </button>
        <button
          className="btn sm ghost"
          onClick={() => onRetranslate(selectedModel, true)}
          disabled={retrActive || !history.length || !selectedModel}
          title={`Retranscribe items without a completed ${selectedModel || "selected"} result`}
        >
          Missing
        </button>
        <button className="btn sm danger" onClick={onClear} disabled={!history.length}>
          <Icon.Trash /> Clear
        </button>
      </div>

      {retrActive && (
        <div className="history-tip">
          <Icon.Translate className="ic" /> Retranscribing with <b>{retr.model}</b> — {retr.stage} {retr.done}/{retr.total}
        </div>
      )}

      <div className="history-list">
        {filtered.length === 0 && (
          <div className="history-empty">
            {history.length === 0
              ? "No dictations retained yet."
              : "No transcripts in this view."}
          </div>
        )}
        {filtered.map((item) => (
          <HistoryEntry
            key={item.id}
            item={item}
            activeModel={activeModel}
            onCopy={onCopy}
            audioOpen={audioOpen === item.id}
            onToggleAudio={onToggleAudio}
          />
        ))}
      </div>

      <div className="history-tip">
        <Icon.Translate className="ic" /> Retranscribe keeps every run so repeated model comparisons stay visible.
      </div>
    </section>
  );
}

window.HistoryCard = HistoryCard;
