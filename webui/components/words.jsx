// Custom words card + Footer

function CustomWordsCard({ words, onSave }) {
  const [draft, setDraft] = useState("");
  const [focused, setFocused] = useState(false);
  const inputRef = useRef(null);

  const parseWords = (text) => text
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean);

  const commitAll = () => {
    const incoming = parseWords(draft);
    if (incoming.length === 0) { setDraft(""); return; }
    const existing = new Set(words.map((w) => w.toLowerCase()));
    const fresh = [];
    for (const w of incoming) {
      const key = w.toLowerCase();
      if (!existing.has(key)) { existing.add(key); fresh.push(w); }
    }
    if (fresh.length) onSave([...words, ...fresh]);
    setDraft("");
  };

  const remove = (w) => onSave(words.filter((x) => x !== w));
  const previewCount = parseWords(draft).length;
  const expanded = focused || draft.length > 0;

  return (
    <section className="card col-12">
      <div className="card-head custom-words-head">
        <div className="card-title">Custom words</div>
        <div className="desc">These words improve recognition. Use short, specific terms — separate with commas or new lines.</div>
        <div className="words-count muted">{words.length}</div>
      </div>

      <div className={`words-input-wrap ${expanded ? "expanded" : ""}`}>
        <textarea
          ref={inputRef}
          className="words-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => { setFocused(false); commitAll(); }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault(); commitAll(); inputRef.current?.blur();
            } else if (e.key === "Enter" && !e.shiftKey && !draft.includes("\n")) {
              e.preventDefault(); commitAll();
            } else if (e.key === "Escape") {
              e.preventDefault(); setDraft(""); inputRef.current?.blur();
            }
          }}
          placeholder={expanded
            ? "Type a word and press Enter. Paste a list (commas or newlines) to add many at once."
            : "Add words…"}
          rows={expanded ? 3 : 1}
        />
        {previewCount > 0 && (
          <div className="words-input-hint">
            <span>{previewCount} word{previewCount === 1 ? "" : "s"} ready · press Enter</span>
          </div>
        )}
      </div>

      <div className="chips">
        {words.length === 0 && (
          <span className="muted" style={{ fontSize: 12.5, padding: "4px 0" }}>
            No custom words yet.
          </span>
        )}
        {words.map((w) => (
          <span key={w} className="chip">
            {w}
            <span className="x" onClick={() => remove(w)}><Icon.X /></span>
          </span>
        ))}
      </div>
    </section>
  );
}

function Footer({ webConfig, version }) {
  const host = (webConfig && webConfig.host) || "127.0.0.1";
  const port = (webConfig && webConfig.port) || 16666;
  return (
    <footer className="app-footer">
      <span>MyWhispr {version && <span style={{ fontFamily: "var(--mono)", color: "var(--text-2)" }}>{version}</span>}</span>
      <span className="links">
        <a href="/api/status" target="_blank" rel="noreferrer">Status JSON</a>
        <a href="/api/config" target="_blank" rel="noreferrer">Config JSON</a>
      </span>
      <div className="right">
        <span className="muted">Loopback only — {host}:{port}</span>
      </div>
    </footer>
  );
}

window.CustomWordsCard = CustomWordsCard;
window.Footer = Footer;
