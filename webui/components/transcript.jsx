// Live transcript — full-width card with current-language indicator

function LiveTranscript({ state, livePreview, lastFinal, currentLang }) {
  const recording = state === "RECORDING" || state === "STARTING";
  const busy = state === "TRANSCRIBING" || state === "TRANSCRIBING_NO_PASTE" ||
               state === "PASTING" || state === "STOPPING" || state === "STOPPING_NO_PASTE";
  const empty = !recording && !livePreview;
  const lang = (window.LANG_LABEL && window.LANG_LABEL[currentLang])
    || { name: currentLang ? currentLang : "Auto", code: (currentLang || "AUTO").toUpperCase(), color: "#60a5fa" };
  return (
    <section className="card col-12">
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
              Waiting for <span className="kbd" style={{ height: 18, minWidth: 18, fontSize: 11, marginLeft: 4, marginRight: 4 }}>`</span> press
            </>
          )}
        </div>
      </div>
      <div className="card-sub">Hold the configured trigger to record. Release to transcribe.</div>
      <div className="transcript-window">
        {empty
          ? <span className="placeholder">Waiting for input — hold <span style={{
              fontFamily: "var(--mono)", background: "var(--card-2)", padding: "1px 6px",
              borderRadius: 4, color: "var(--text-2)", border: "1px solid var(--border-soft)"
            }}>`</span> to dictate.</span>
          : <>
              <span className="interim">{livePreview}</span>
              {recording && <span className="caret"></span>}
            </>
        }
      </div>
      {lastFinal && (
        <div className="transcript-last"><b>Last:</b> {lastFinal}</div>
      )}
    </section>
  );
}

window.LiveTranscript = LiveTranscript;
