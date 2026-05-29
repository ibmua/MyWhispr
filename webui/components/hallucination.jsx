// Hallucination filter — toggle + editable phrase list modal

function HallucinationModal({ phrases, onSavePhrases, onClose }) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const remove = (i) => onSavePhrases(phrases.filter((_, idx) => idx !== i));
  const add = () => {
    const v = draft.trim();
    if (!v) return;
    if (phrases.some((p) => p.toLowerCase() === v.toLowerCase())) {
      setDraft("");
      return;
    }
    onSavePhrases([...phrases, v]);
    setDraft("");
    inputRef.current && inputRef.current.focus();
  };

  return ReactDOM.createPortal(
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">Hallucination filter — English phrases</div>
          <div className="card-spacer"></div>
          <span className="muted" style={{ fontSize: 12 }}>{phrases.length} {phrases.length === 1 ? "phrase" : "phrases"}</span>
          <button className="btn icon ghost sm" onClick={onClose}><Icon.X /></button>
        </div>
        <div className="modal-sub">
          Whisper sometimes invents text in silent or noisy segments — usually leftover phrases from its training data.
          Matching transcripts are dropped before they're typed.
        </div>
        <div className="modal-body">
          <div className="phrase-list">
            {phrases.length === 0 && (
              <div style={{ padding: "16px 12px", textAlign: "center", color: "var(--text-3)", fontSize: 12 }}>
                No phrases yet — add one below.
              </div>
            )}
            {phrases.map((p, i) => (
              <div key={i} className="phrase-row">
                <span className="phrase-text">{p}</span>
                <button className="phrase-remove" onClick={() => remove(i)} aria-label="Remove">
                  <Icon.X />
                </button>
              </div>
            ))}
          </div>
          <div className="phrase-add">
            <input
              ref={inputRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") add(); }}
              placeholder='Add a phrase, e.g. "Thanks for watching"'
            />
            <button className="btn" onClick={add}><Icon.Plus /> Add</button>
          </div>
        </div>
        <div className="modal-foot">
          <div className="spacer"></div>
          <button className="btn primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>,
    document.body
  );
}

function HallucinationRow({ on, setOn, phrases, onSavePhrases }) {
  const [open, setOpen] = useState(false);
  const count = phrases.length;
  return (
    <>
      <div className="field-row">
        <span className="field-label">
          Hallucination filter
          <button className="link-btn" onClick={() => setOpen(true)}>
            {count} {count === 1 ? "phrase" : "phrases"} ›
          </button>
        </span>
        <span className="field-input"><Toggle on={on} onChange={setOn} /></span>
      </div>
      {open && (
        <HallucinationModal
          phrases={phrases}
          onSavePhrases={onSavePhrases}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

window.HallucinationRow = HallucinationRow;
