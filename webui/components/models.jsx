// Models card + Daemon status card

const MODEL_ICONS = { turbo: "Bolt", large: "Brain", small: "Leaf" };
const MODEL_DESC = {
  turbo: { desc: "Fastest", subdesc: "Best for most tasks" },
  large: { desc: "Best accuracy", subdesc: null },
  small: { desc: "Lightweight", subdesc: "Offline" },
};

const LANGUAGE_FLAGS = {
  af: { flag: "🇿🇦", label: "Afrikaans" },
  am: { flag: "🇪🇹", label: "Amharic" },
  ar: { flag: "🇸🇦", label: "Arabic" },
  as: { flag: "🇮🇳", label: "Assamese" },
  az: { flag: "🇦🇿", label: "Azerbaijani" },
  ba: { flag: "🇷🇺", label: "Bashkir" },
  be: { flag: "🇧🇾", label: "Belarusian" },
  bg: { flag: "🇧🇬", label: "Bulgarian" },
  bn: { flag: "🇧🇩", label: "Bengali" },
  bo: { flag: "🇨🇳", label: "Tibetan" },
  br: { flag: "🇫🇷", label: "Breton" },
  bs: { flag: "🇧🇦", label: "Bosnian" },
  ca: { flag: "🇪🇸", label: "Catalan" },
  cs: { flag: "🇨🇿", label: "Czech" },
  cy: { flag: "🇬🇧", label: "Welsh" },
  da: { flag: "🇩🇰", label: "Danish" },
  de: { flag: "🇩🇪", label: "German" },
  el: { flag: "🇬🇷", label: "Greek" },
  en: { flag: "🇺🇸", label: "English" },
  es: { flag: "🇪🇸", label: "Spanish" },
  et: { flag: "🇪🇪", label: "Estonian" },
  eu: { flag: "🇪🇸", label: "Basque" },
  fa: { flag: "🇮🇷", label: "Persian" },
  fi: { flag: "🇫🇮", label: "Finnish" },
  fil: { flag: "🇵🇭", label: "Filipino" },
  fo: { flag: "🇫🇴", label: "Faroese" },
  fr: { flag: "🇫🇷", label: "French" },
  gl: { flag: "🇪🇸", label: "Galician" },
  gu: { flag: "🇮🇳", label: "Gujarati" },
  ha: { flag: "🇳🇬", label: "Hausa" },
  haw: { flag: "🇺🇸", label: "Hawaiian" },
  he: { flag: "🇮🇱", label: "Hebrew" },
  hi: { flag: "🇮🇳", label: "Hindi" },
  hr: { flag: "🇭🇷", label: "Croatian" },
  ht: { flag: "🇭🇹", label: "Haitian Creole" },
  hu: { flag: "🇭🇺", label: "Hungarian" },
  hy: { flag: "🇦🇲", label: "Armenian" },
  id: { flag: "🇮🇩", label: "Indonesian" },
  is: { flag: "🇮🇸", label: "Icelandic" },
  it: { flag: "🇮🇹", label: "Italian" },
  ja: { flag: "🇯🇵", label: "Japanese" },
  jw: { flag: "🇮🇩", label: "Javanese" },
  ka: { flag: "🇬🇪", label: "Georgian" },
  kk: { flag: "🇰🇿", label: "Kazakh" },
  km: { flag: "🇰🇭", label: "Khmer" },
  kn: { flag: "🇮🇳", label: "Kannada" },
  ko: { flag: "🇰🇷", label: "Korean" },
  la: { flag: "🇻🇦", label: "Latin" },
  lb: { flag: "🇱🇺", label: "Luxembourgish" },
  ln: { flag: "🇨🇩", label: "Lingala" },
  lo: { flag: "🇱🇦", label: "Lao" },
  lt: { flag: "🇱🇹", label: "Lithuanian" },
  lv: { flag: "🇱🇻", label: "Latvian" },
  mg: { flag: "🇲🇬", label: "Malagasy" },
  mi: { flag: "🇳🇿", label: "Maori" },
  mk: { flag: "🇲🇰", label: "Macedonian" },
  ml: { flag: "🇮🇳", label: "Malayalam" },
  mn: { flag: "🇲🇳", label: "Mongolian" },
  mr: { flag: "🇮🇳", label: "Marathi" },
  ms: { flag: "🇲🇾", label: "Malay" },
  mt: { flag: "🇲🇹", label: "Maltese" },
  my: { flag: "🇲🇲", label: "Burmese" },
  ne: { flag: "🇳🇵", label: "Nepali" },
  nl: { flag: "🇳🇱", label: "Dutch" },
  nn: { flag: "🇳🇴", label: "Nynorsk" },
  no: { flag: "🇳🇴", label: "Norwegian" },
  oc: { flag: "🇫🇷", label: "Occitan" },
  pa: { flag: "🇮🇳", label: "Punjabi" },
  pl: { flag: "🇵🇱", label: "Polish" },
  ps: { flag: "🇦🇫", label: "Pashto" },
  pt: { flag: "🇵🇹", label: "Portuguese" },
  ro: { flag: "🇷🇴", label: "Romanian" },
  ru: { flag: "🇷🇺", label: "Russian" },
  sa: { flag: "🇮🇳", label: "Sanskrit" },
  sd: { flag: "🇵🇰", label: "Sindhi" },
  si: { flag: "🇱🇰", label: "Sinhala" },
  sk: { flag: "🇸🇰", label: "Slovak" },
  sl: { flag: "🇸🇮", label: "Slovenian" },
  sn: { flag: "🇿🇼", label: "Shona" },
  so: { flag: "🇸🇴", label: "Somali" },
  sq: { flag: "🇦🇱", label: "Albanian" },
  sr: { flag: "🇷🇸", label: "Serbian" },
  su: { flag: "🇮🇩", label: "Sundanese" },
  sv: { flag: "🇸🇪", label: "Swedish" },
  sw: { flag: "🇹🇿", label: "Swahili" },
  ta: { flag: "🇮🇳", label: "Tamil" },
  te: { flag: "🇮🇳", label: "Telugu" },
  tg: { flag: "🇹🇯", label: "Tajik" },
  th: { flag: "🇹🇭", label: "Thai" },
  tk: { flag: "🇹🇲", label: "Turkmen" },
  tl: { flag: "🇵🇭", label: "Tagalog" },
  tr: { flag: "🇹🇷", label: "Turkish" },
  tt: { flag: "🇷🇺", label: "Tatar" },
  uk: { flag: "🇺🇦", label: "Ukrainian" },
  ur: { flag: "🇵🇰", label: "Urdu" },
  uz: { flag: "🇺🇿", label: "Uzbek" },
  vi: { flag: "🇻🇳", label: "Vietnamese" },
  yi: { flag: "🇮🇱", label: "Yiddish" },
  yo: { flag: "🇳🇬", label: "Yoruba" },
  yue: { flag: "🇭🇰", label: "Cantonese" },
  zh: { flag: "🇨🇳", label: "Chinese" },
};
const LANGUAGE_SLOT_CAPACITY = 56;
const LANGUAGE_OVERFLOW_RESERVED_SLOTS = 2;
const LANGUAGE_PRIORITY = ["uk", "en"];
const USE_FLAG_IMAGES = typeof navigator !== "undefined"
  && /windows/i.test(`${navigator.userAgent || ""} ${navigator.platform || ""}`);

function flagCountryCode(flag) {
  const chars = Array.from(String(flag || ""));
  if (chars.length !== 2) return "";
  const letters = chars.map((ch) => {
    const cp = ch.codePointAt(0);
    if (cp < 0x1F1E6 || cp > 0x1F1FF) return "";
    return String.fromCharCode(97 + cp - 0x1F1E6);
  });
  return letters.every(Boolean) ? letters.join("") : "";
}

function modelIconName(name) {
  const n = String(name || "").toLowerCase();
  if (n.includes("api") || n.includes("gpt") || n.includes("cloud")) return "Bolt";
  if (n.includes("qwen") || n.includes("cohere") || n.includes("granite") || n.includes("canary") || n.includes("seamless")) return "Brain";
  if (n.includes("parakeet")) return "Bolt";
  if (n.includes("small") || n.includes("base") || n.includes("tiny")) return "Leaf";
  if (n.includes("turbo")) return "Bolt";
  if (n.includes("large") || n.includes("medium")) return "Brain";
  return MODEL_ICONS[name] || "Bolt";
}

function modelMeta(name) {
  const n = String(name || "").toLowerCase();
  if (MODEL_DESC[name]) return MODEL_DESC[name];
  if (n.includes("gpt-4o") || n.includes("transcribe")) return { desc: "External API", subdesc: "Cloud" };
  if (n.includes("qwen3-asr-1.7")) return { desc: "High accuracy", subdesc: "Qwen GPU" };
  if (n.includes("qwen3-asr-0.6")) return { desc: "Fast compact", subdesc: "Qwen GPU" };
  if (n.includes("parakeet")) return { desc: "Fast multilingual", subdesc: "NVIDIA TDT" };
  if (n.includes("granite")) return { desc: "Multilingual", subdesc: "IBM Granite" };
  if (n.includes("cohere")) return { desc: "Long-form ASR", subdesc: "Cohere" };
  if (n.includes("canary-1b-v2")) return { desc: "25-language ASR", subdesc: "NVIDIA NeMo" };
  if (n.includes("canary")) return { desc: "English ASR", subdesc: "NVIDIA NeMo" };
  if (n.includes("seamless-m4t-v2")) return { desc: "Massively multilingual", subdesc: "Meta SeamlessM4T" };
  if (n.includes("turbo") && n.includes("q5")) return { desc: "Fast compact", subdesc: "Turbo Q5" };
  if (n.includes("turbo") && n.includes("q8")) return { desc: "Fast higher fidelity", subdesc: "Turbo Q8" };
  if (n.includes("turbo")) return { desc: "Fastest", subdesc: "Turbo" };
  if (n.includes("large-v2")) return { desc: "Older large", subdesc: "Comparison" };
  if (n.includes("large")) return { desc: "High accuracy", subdesc: n.includes("q5") ? "Q5" : null };
  if (n.includes("medium")) return { desc: "Balanced", subdesc: n.includes(".en") ? "English" : (n.includes("q5") ? "Q5" : null) };
  if (n.includes("small")) return { desc: "Lightweight", subdesc: n.includes("q5") ? "Q5" : null };
  return { desc: "", subdesc: null };
}

function languageBadges(languages) {
  const badges = (languages || [])
    .map((code) => {
      const key = String(code || "").trim();
      if (!key) return null;
      const meta = LANGUAGE_FLAGS[key] || { flag: key.toUpperCase(), label: key };
      return { code: key, text: key.toUpperCase(), country: flagCountryCode(meta.flag), ...meta };
    })
    .filter(Boolean);
  return [
    ...LANGUAGE_PRIORITY.flatMap((code) => badges.filter((b) => b.code === code)),
    ...badges.filter((b) => !LANGUAGE_PRIORITY.includes(b.code)),
  ];
}

function ModelCard({ m, active, onSelect, onDelete, onDownload, busy }) {
  const IconComp = Icon[modelIconName(m.name)] || Icon.Bolt;
  const fallbackMeta = modelMeta(m.name);
  const meta = {
    desc: m.description || fallbackMeta.desc,
    subdesc: m.subdescription || fallbackMeta.subdesc,
  };
  const langs = languageBadges(m.languages);
  const visibleLimit = langs.length > LANGUAGE_SLOT_CAPACITY
    ? LANGUAGE_SLOT_CAPACITY - LANGUAGE_OVERFLOW_RESERVED_SLOTS
    : LANGUAGE_SLOT_CAPACITY;
  const visibleLangs = langs.slice(0, visibleLimit);
  const hiddenLangCount = Math.max(0, langs.length - visibleLangs.length);
  const selectable = m.selectable !== false && m.exists !== false;
  const dl = m.download || null;
  const downloading = !!(dl && dl.state === "downloading");
  const downloadable = !!(m.downloadable || m.download_url || (m.cached === false && m.repo_id));
  const unavailable = !!m.unavailable_reason && m.selectable === false;
  const missingDownload = m.exists === false || m.cached === false;
  const needsDownload = !unavailable && downloadable && missingDownload && !downloading;
  const interactive = !unavailable && (selectable || needsDownload);
  const dlPct = downloading && dl.total_bytes > 0
    ? Math.min(100, Math.round((dl.downloaded_bytes / dl.total_bytes) * 100))
    : null;
  const className = [
    "model-card",
    active && "active",
    m.running && "running",
    needsDownload && "downloadable",
    !interactive && "missing",
    (busy || downloading) && "busy",
  ].filter(Boolean).join(" ");
  let badge = "ready";
  if (m.backend === "external_api" && !m.api_key_configured && m.api_key_required !== false) badge = "key missing";
  else if (downloading) badge = dlPct === null ? "downloading…" : `downloading ${dlPct}%`;
  else if (unavailable) badge = "server missing";
  else if (dl && dl.state === "error" && missingDownload) badge = "download failed";
  else if (needsDownload) badge = "download";
  else if (m.cached === false) badge = "not cached";
  else if (!selectable) badge = "missing";
  else if (m.running) badge = "running";
  else if (active) badge = "active";
  const backend = m.backend && m.backend !== "whisper.cpp" ? m.backend.replace(/_/g, " ") : "";
  const title = !interactive
    ? (m.unavailable_reason || "model unavailable")
    : needsDownload
      ? `${m.label || m.name} — click to download${m.repo_id ? ` ${m.repo_id}` : ""} and switch to it`
      : `${m.label || m.name}${backend ? ` (${backend})` : ""}${m.install_hint ? `\n${m.install_hint}` : ""}`;
  const handleClick = () => {
    if (busy || downloading || !interactive) return;
    if (needsDownload && onDownload) onDownload(m.name);
    else if (selectable) onSelect(m.name);
  };
  return (
    <div
      className={className}
      onClick={handleClick}
      title={title}
    >
      <div className="model-top">
        <span className="model-icon"><IconComp /></span>
        <span className="model-name">{m.label || m.name}</span>
        {m.backend === "external_api" && !m.builtin && (
          <button
            className="icon-btn model-delete"
            title="Delete external model"
            onClick={(e) => { e.stopPropagation(); onDelete && onDelete(m.name); }}
            disabled={busy}
          >
            <Icon.Trash />
          </button>
        )}
        <span className="badge">{badge}</span>
      </div>
      <div className="model-size">
        {m.backend === "whisper.cpp"
          ? fmt.bytes(m.size_bytes)
          : (m.backend === "external_api"
              ? "External API"
              : [m.device || "GPU", m.dtype, backend].filter(Boolean).join(" · "))}
      </div>
      <div className="model-desc">
        {meta.desc}{meta.subdesc && <><span className="dot">•</span>{meta.subdesc}</>}
      </div>
      {m.backend === "external_api" && (
        <div className="model-api-line">
          {(m.provider || "API")} <span className="dot">•</span> {m.api_model || m.name}
        </div>
      )}
      {langs.length > 0 && (
        <div
          className="model-languages"
          title={langs.map((l) => `${l.label} (${l.code})`).join(", ")}
          aria-label={`Supported languages: ${langs.map((l) => l.label).join(", ")}`}
        >
          {visibleLangs.map((l) => (
            <span
              className={`lang-flag ${USE_FLAG_IMAGES && l.country ? "image" : "emoji"}`}
              key={l.code}
              title={`${l.label} (${l.code})`}
            >
              {USE_FLAG_IMAGES && l.country ? (
                <>
                  <img
                    src={`/static/flags/4x3/${l.country}.svg`}
                    alt={l.flag}
                    onError={(e) => {
                      e.currentTarget.style.display = "none";
                      const fallback = e.currentTarget.nextElementSibling;
                      if (fallback) fallback.style.display = "inline";
                    }}
                  />
                  <span className="lang-code-fallback">{l.text}</span>
                </>
              ) : l.flag}
            </span>
          ))}
          {hiddenLangCount > 0 && (
            <span className="lang-more" title={`${hiddenLangCount} more languages`}>
              +{hiddenLangCount}
            </span>
          )}
        </div>
      )}
      <div className="model-path" title={m.path}>{m.path}</div>
    </div>
  );
}

function ExternalApiModelForm({ onSave, busy }) {
  const [open, setOpen] = useState(false);
  const [jsonDraft, setJsonDraft] = useState("");
  const [jsonError, setJsonError] = useState("");
  const [draft, setDraft] = useState({
    name: "remote-large-q5",
    label: "Remote Whisper Large Q5",
    provider: "LAN whisper.cpp",
    api_base_url: "http://192.168.50.100:18178",
    endpoint: "/inference",
    api_model: "large-q5",
    api_key_env: "",
    api_key: "",
    api_key_required: false,
    send_model: false,
    response_format: "verbose_json",
    extra_fields: { temperature: "0.0" },
    languages: "en,uk",
    live_preview: true,
  });
  const update = (key, value) => setDraft((d) => ({ ...d, [key]: value }));
  const loadJson = () => {
    try {
      const parsed = JSON.parse(jsonDraft);
      let name = draft.name;
      let spec = parsed;
      if (parsed && typeof parsed === "object" && !parsed.backend) {
        const entries = Object.entries(parsed);
        if (entries.length > 0) {
          name = entries[0][0];
          spec = entries[0][1];
        }
      }
      if (!spec || typeof spec !== "object" || Array.isArray(spec)) throw new Error("expected a model object");
      setDraft((d) => ({
        ...d,
        name,
        label: spec.label || d.label || name,
        provider: spec.provider || d.provider,
        api_base_url: spec.api_base_url || d.api_base_url,
        endpoint: spec.endpoint || d.endpoint,
        api_model: spec.api_model || d.api_model || name,
        api_key_env: spec.api_key_env || "",
        api_key: spec.api_key || "",
        api_key_required: spec.api_key_required !== undefined ? !!spec.api_key_required : d.api_key_required,
        send_model: spec.send_model !== undefined ? !!spec.send_model : d.send_model,
        response_format: spec.response_format || d.response_format,
        extra_fields: spec.extra_fields && typeof spec.extra_fields === "object" ? spec.extra_fields : d.extra_fields,
        languages: Array.isArray(spec.languages) ? spec.languages.join(",") : (spec.languages || d.languages),
        live_preview: spec.live_preview !== undefined ? !!spec.live_preview : d.live_preview,
      }));
      setJsonError("");
    } catch (e) {
      setJsonError(e.message || "invalid JSON");
    }
  };
  const submit = async () => {
    await onSave({
      ...draft,
      languages: draft.languages.split(",").map((s) => s.trim()).filter(Boolean),
    });
    setDraft((d) => ({ ...d, api_key: "" }));
    setOpen(false);
  };
  return (
    <div className={`external-model-editor ${open ? "open" : ""}`}>
      <button className="btn sm ghost" onClick={() => setOpen(!open)} disabled={busy}>
        <Icon.Plus /> API model
      </button>
      {open && (
        <div className="external-model-grid">
          <label>
            <span>Name</span>
            <input value={draft.name} onChange={(e) => update("name", e.target.value)} />
          </label>
          <label>
            <span>Label</span>
            <input value={draft.label} onChange={(e) => update("label", e.target.value)} />
          </label>
          <label>
            <span>Provider</span>
            <input value={draft.provider} onChange={(e) => update("provider", e.target.value)} />
          </label>
          <label>
            <span>API model</span>
            <input value={draft.api_model} onChange={(e) => update("api_model", e.target.value)} />
          </label>
          <label className="span-2">
            <span>Base URL</span>
            <input value={draft.api_base_url} onChange={(e) => update("api_base_url", e.target.value)} />
          </label>
          <label>
            <span>Endpoint</span>
            <input value={draft.endpoint} onChange={(e) => update("endpoint", e.target.value)} />
          </label>
          <label>
            <span>Key env</span>
            <input value={draft.api_key_env} onChange={(e) => update("api_key_env", e.target.value)} />
          </label>
          <label>
            <span>API key</span>
            <input type="password" value={draft.api_key} onChange={(e) => update("api_key", e.target.value)} placeholder="optional" />
          </label>
          <label>
            <span>Languages</span>
            <input value={draft.languages} onChange={(e) => update("languages", e.target.value)} />
          </label>
          <label className="external-toggle">
            <span>Live preview</span>
            <Toggle on={draft.live_preview} onChange={(v) => update("live_preview", v)} />
          </label>
          <label className="span-2">
            <span>Import JSON</span>
            <textarea value={jsonDraft} onChange={(e) => setJsonDraft(e.target.value)} rows="5" />
          </label>
          <div className="external-import span-2">
            <button className="btn sm ghost" onClick={loadJson} disabled={busy || !jsonDraft.trim()}>Load JSON</button>
            {jsonError && <span>{jsonError}</span>}
          </div>
          <div className="external-actions span-2">
            <button className="btn primary sm" onClick={submit} disabled={busy}>Save API model</button>
            <button className="btn sm ghost" onClick={() => setOpen(false)} disabled={busy}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

function ModelsCard({ models, activeModel, onSelect, onDownload, onUnload, onSaveExternal, onDeleteModel, busy }) {
  const items = (models && models.items) || [];
  const anyRunning = items.some((m) => m.running);
  return (
    <section className="card col-7">
      <div className="card-head">
        <div className="card-title">Models</div>
        <div className="card-spacer"></div>
        {anyRunning && (
          <button className="btn sm ghost" onClick={onUnload} disabled={busy}>
            Unload
          </button>
        )}
      </div>
      <ExternalApiModelForm onSave={onSaveExternal} busy={busy} />
      <div className="model-row">
        {items.length === 0
          ? <div className="muted" style={{ padding: 12 }}>No models configured.</div>
          : items.map((m) => (
              <ModelCard
                key={m.name}
                m={m}
                active={activeModel === m.name}
                onSelect={onSelect}
                onDelete={onDeleteModel}
                onDownload={onDownload}
                busy={busy}
              />
            ))
        }
      </div>
      <div className="selected-model-line">
        Selected model: <b>{activeModel || "—"}</b>
        {models && models.server && models.server.last_error
          ? <span className="inline-error" style={{ marginLeft: 8 }}>{models.server.last_error}</span>
          : null}
      </div>
    </section>
  );
}

function DaemonStatus({ snap }) {
  const primary = (snap && snap.primary_server) || {};
  const topbar = (snap && snap.topbar) || {};
  const devices = (snap && snap.device_names) || [];
  const inflight = primary.inflight || 0;
  const gpu = (primary.gpu && primary.gpu.device_report) || {};
  const gpuLoaded = primary.gpu && primary.gpu.running && primary.gpu.loaded_model;
  const vram = gpu.memory_reserved || gpu.memory_allocated || 0;
  return (
    <section className="card col-5">
      <div className="card-head">
        <div className="card-title">Daemon status</div>
        <div className="card-spacer"></div>
        <div className="card-meta">
          <span style={{ width: 7, height: 7, borderRadius: 999, background: snap ? "#22c55e" : "#6b7585", display: "inline-block", marginRight: 4 }}></span>
          {snap ? "Running" : "Offline"}
        </div>
      </div>
      <div className="kv">
        <div className="row"><span className="key">PID</span><span className="val mono">{snap ? (snap.pid || "—") : "—"}</span></div>
        <div className="row"><span className="key">Top bar</span>
          <span className={`val ${topbar.enabled ? "green" : ""}`}>{topbar.enabled ? "enabled" : "disabled"}</span>
        </div>

        <div className="row"><span className="key">Uptime</span><span className="val tabular">{snap ? fmt.uptime(snap.uptime_seconds) : "—"}</span></div>
        <div className="row"><span className="key">Whisper port</span><span className="val mono">{primary.port || "—"}</span></div>
        <div className="row"><span className="key">History items</span><span className="val tabular">{snap ? (snap.history_count || 0) : 0}</span></div>

        <div className="row"><span className="key">Backend</span>
          <span className="val mono">{primary.active_backend || "—"}{primary.loaded_model ? ` (${primary.loaded_model})` : ""}</span>
        </div>
        <div className="row"><span className="key">GPU</span>
          <span className={`val ${gpu.cuda_available ? "green" : ""}`}>
            {gpu.gpu_name ? gpu.gpu_name : (gpuLoaded ? "CPU only" : "—")}
          </span>
        </div>
        <div className="row"><span className="key">VRAM in use</span>
          <span className="val tabular">{gpuLoaded && vram ? fmt.bytes(vram) : "—"}</span>
        </div>

        <div className="row"><span className="key">Inflight requests</span><span className="val tabular">{inflight}</span></div>
        <div className="row"><span className="key">Server</span>
          <span className="val mono">{primary.running ? `http://127.0.0.1:${primary.port}` : "idle"}</span>
        </div>

        <div className="row last"><span className="key">Devices</span>
          <span className="val tabular">
            {devices.length} <Icon.Mic style={{ verticalAlign: -2, marginLeft: 4, color: "var(--text-3)" }}/>
            {devices.length > 0 && (
              <span className="muted" style={{ marginLeft: 4, fontSize: 11.5 }}>
                {devices.slice(0, 2).join(", ")}{devices.length > 2 ? `, +${devices.length - 2}` : ""}
              </span>
            )}
          </span>
        </div>
        <div className="row last"><span className="key">State</span>
          <span className="val mono">{(snap && snap.state) ? snap.state.toLowerCase().replace(/_/g, " ") : "offline"}</span>
        </div>
      </div>
      {snap && snap.error
        ? <div className="inline-error">{snap.error}</div>
        : null}
    </section>
  );
}

window.ModelsCard = ModelsCard;
window.DaemonStatus = DaemonStatus;
