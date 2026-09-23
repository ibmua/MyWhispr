// Live transcript — full-width card with current-language indicator

function LiveTranscript({ state, livePreview, lastFinal, currentLang, trigger = "grave" }) {
  const triggerLabel = trigger === "grave" ? "`" : trigger;
  const recording = state === "RECORDING" || state === "STARTING";
  const busy = state === "TRANSCRIBING" || state === "TRANSCRIBING_NO_PASTE" ||
               state === "PASTING" || state === "STOPPING" || state === "STOPPING_NO_PASTE";
  const empty = !recording && !livePreview;
  const lang = (window.LANG_LABEL && window.LANG_LABEL[currentLang])
    || { name: currentLang ? currentLang : "Auto", code: (currentLang || "AUTO").toUpperCase(), color: "#60a5fa" };
  return (
    <section className={`card col-12 transcript-card ${recording ? "is-recording" : ""}`}>
      <div className="card-head">
        <div className="card-title">Live transcript</div>
        {currentLang && <span style={{ fontSize: 13, color: "var(--text-2)" }}>· {lang.name}</span>}
        <div className="card-spacer"></div>
        <div className="card-meta">
          {recording ? (
            <><span style={{ width: 7, height: 7, borderRadius: 999, background: "#f87171", display: "inline-block", marginRight: 4 }}></span>Recording</>
          ) : busy ? (
            <><span style={{ width: 7, height: 7, borderRadius: 999, background: "#fbbf24", display: "inline-block", marginRight: 4 }}></span>{state.toLowerCase().replace(/_/g, " ")}</>
          ) : (
            <>
              <span style={{ width: 7, height: 7, borderRadius: 999, background: "var(--text-3)", display: "inline-block", marginRight: 4 }}></span>
              Waiting for <span className="kbd" style={{ height: 18, minWidth: 18, fontSize: 11, marginLeft: 4, marginRight: 4 }}>{triggerLabel}</span> press
            </>
          )}
        </div>
      </div>
      <div className="card-sub">Hold the configured trigger to record. Release to transcribe.</div>
      <div className="transcript-window">
        {empty
          ? <div className="dictation-idle">
              <div className="voice-emblem" aria-hidden="true"><Icon.Logo /></div>
              <div><strong>{busy ? "Finishing your transcript…" : "Ready when you are"}</strong>
                <p>{busy ? "Your words will appear here shortly." : <>Hold <kbd className="kbd">{triggerLabel}</kbd> to start dictating</>}</p>
              </div>
            </div>
          : <>
              <span className="interim">{livePreview}</span>
              {recording && <span className="caret"></span>}
            </>
        }
      </div>
      {lastFinal && (
        <div className="transcript-last"><b>Latest transcript</b> {lastFinal}</div>
      )}
    </section>
  );
}

window.LiveTranscript = LiveTranscript;
