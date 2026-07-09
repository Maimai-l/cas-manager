// ── Composer — flat, non-modal journal workbench ────────────────────────
// Replaces the old 5-screen modal chain (journal-choose / journal-write /
// ai-1 / ai-2 / ai-3). Docks at the bottom of the main panel so past
// reflections stay visible (and copyable) while writing.
const I = window.I;
const A = window.MONO_ACCENT;
const N = window.MONO_NEUTRALS;
const Btn = window.MonoBtn;
const FieldLabel = window.MonoFieldLabel;
const { StatusLine, useAsyncOp, wrapPlainAsHtml, stripHtml } = window.MonoHelpers;
const API = window.API;

// Clipboard with fallback — navigator.clipboard can fail inside pywebview,
// and copying is a core operation here, so never fail silently.
async function copyTextToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_) {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch (_) {
      return false;
    }
  }
}

const taStyle = (h) => ({
  width: "100%", height: h, padding: "9px 11px",
  border: "none", outline: "none", background: "transparent",
  fontSize: 12.5, lineHeight: 1.6,
  color: N.inkDeep, fontFamily: "inherit", resize: "none",
  boxSizing: "border-box",
});

const boxStyle = {
  background: "rgba(255,255,255,0.78)",
  borderRadius: 8,
  boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.1)",
};

// Small button that flips to "Copied ✓" / "Copy failed" for a moment.
function CopyBtn({ getText, label = "Copy", primary, icon = "copy", disabled, onBefore }) {
  const [state, setState] = React.useState(null); // null | "ok" | "fail"
  async function handle() {
    let text;
    try {
      text = onBefore ? await onBefore() : undefined;
    } catch (_) {
      return; // onBefore surfaces its own error via useAsyncOp
    }
    if (text === undefined) text = getText ? getText() : "";
    if (!text) return;
    const ok = await copyTextToClipboard(text);
    setState(ok ? "ok" : "fail");
    setTimeout(() => setState(null), 1600);
  }
  return (
    <Btn icon={state === "ok" ? "check" : icon} primary={primary}
         onClick={handle} disabled={disabled}
         style={state === "fail" ? { background: "rgba(216,80,74,0.12)", color: "#a4332e" } : undefined}>
      {state === "ok" ? "Copied ✓" : state === "fail" ? "Copy failed" : label}
    </Btn>
  );
}

function TabBtn({ active, icon, children, onClick }) {
  return (
    <button onClick={onClick} style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      padding: "4px 11px", borderRadius: 6, border: "none",
      fontSize: 11.5, fontWeight: 500,
      background: active ? "rgba(255,255,255,0.95)" : "transparent",
      color: active ? N.inkDeep : N.inkMid,
      boxShadow: active ? "inset 0 0 0 0.5px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.05)" : "none",
      cursor: "pointer", fontFamily: "inherit",
      transition: "background 0.12s",
    }}>
      <I name={icon} size={11.5} stroke={1.8} />
      {children}
    </button>
  );
}

function Composer() {
  const ctx = React.useContext(window.MonoCtx);
  const payload = ctx.composer;           // null → hidden
  const exp = React.useMemo(() => {
    if (!payload) return null;
    return ctx.experiences.find((e) => e.id === payload.casId) || ctx.activeExp;
  }, [payload, ctx.experiences, ctx.activeExp]);

  if (!payload) return null;
  return <ComposerInner key={`${payload.casId}-${payload.rid || "new"}`} payload={payload} exp={exp} ctx={ctx} />;
}

function ComposerInner({ payload, exp, ctx }) {
  const casId        = payload.casId;
  const rid          = payload.rid || null;           // editing / placeholder-filling
  const date         = payload.date || null;
  const existingText = payload.existingText || null;  // set → AI mode revises
  const expName      = (exp && (exp.name || `Experience ${exp.id}`)) || `Experience ${casId}`;

  const [mode, setMode]       = React.useState(payload.mode || "write"); // "write" | "ai"
  const [isFinal, setIsFinal] = React.useState(!!payload.isFinal);
  const [text, setText]       = React.useState(payload.initialText || "");   // write tab
  const [notes, setNotes]     = React.useState("");                           // ai tab
  const [prompt, setPrompt]   = React.useState("");
  const [result, setResult]   = React.useState("");                           // pasted or generated
  const { loading, error, run } = useAsyncOp();

  const aiProvider = (ctx.status && ctx.status.ai_provider) || "prompt";
  const isManual   = aiProvider === "prompt";
  const aiKind     = existingText ? "edit" : (isFinal ? "final" : "reflection");
  const includeHistory = isFinal && !existingText;
  const canBuild   = !!notes.trim() || (isFinal && !existingText);

  const title =
    existingText ? `Edit Journal · ${expName}` :
    rid          ? `Fill Placeholder · ${expName}${date ? ` · ${date}` : ""}` :
                   `New Journal · ${expName}`;

  async function buildPrompt() {
    // Returned text is copied by CopyBtn; also shown in the prompt box below.
    let p;
    await run("Building prompt…", async () => {
      const r = await API.buildPrompt(casId, notes, aiKind, date, existingText, includeHistory);
      p = r.prompt;
      setPrompt(p);
    });
    return p;
  }

  async function generateDirect() {
    await run("Generating with AI…", async () => {
      const r = await API.generateAI(casId, notes, aiKind, date, existingText, includeHistory);
      setResult(r.result || "");
    });
  }

  async function send(body) {
    if (!body || !body.trim()) return;
    const html = wrapPlainAsHtml(body);
    await run(rid ? "Saving…" : "Posting…", async () => {
      if (rid) {
        await API.editJournal(rid, casId, html, null);
      } else {
        await API.createJournal(casId, html, null);
      }
      await ctx.refreshAfterMutation();
      ctx.closeComposer();
    });
  }

  const sendBody = mode === "write" ? text : result;
  const previewHtml = mode === "ai" && result.trim() ? wrapPlainAsHtml(result) : "";

  return (
    <div style={{
      flexShrink: 0,
      borderTop: "0.5px solid " + N.hairline,
      background: "rgba(255,255,255,0.55)",
      backdropFilter: "blur(24px) saturate(170%)",
      WebkitBackdropFilter: "blur(24px) saturate(170%)",
      maxHeight: "58%",
      display: "flex", flexDirection: "column",
    }}>
      {/* Header — title, tabs, final toggle, close */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "9px 14px 8px",
      }}>
        <I name={existingText ? "edit" : "pen"} size={13} stroke={1.8} style={{ color: N.inkMid }} />
        <span style={{
          fontSize: 12, fontWeight: 500, color: N.inkDeep,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>{title}</span>

        <div style={{
          display: "inline-flex", gap: 2, padding: 2,
          background: "rgba(0,0,0,0.05)", borderRadius: 8,
        }}>
          <TabBtn active={mode === "write"} icon="pen" onClick={() => setMode("write")}>Write</TabBtn>
          <TabBtn active={mode === "ai"} icon="sparkle" onClick={() => setMode("ai")}>AI</TabBtn>
        </div>

        {mode === "ai" && !existingText && (
          <label style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            fontSize: 11, fontWeight: 500, color: isFinal ? N.inkDeep : N.inkMid,
            padding: "3px 9px", borderRadius: 99, cursor: "pointer",
            background: isFinal ? "rgba(177,226,69,0.28)" : "rgba(0,0,0,0.04)",
            boxShadow: isFinal ? `inset 0 0 0 1px ${A.solid}` : "none",
            transition: "background 0.12s",
          }}>
            <input type="checkbox" checked={isFinal}
                   onChange={(e) => setIsFinal(e.target.checked)}
                   style={{ width: 12, height: 12, margin: 0, cursor: "pointer" }} />
            Final Reflection
          </label>
        )}

        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 10.5, color: N.inkSoft }}>
          {mode === "ai" ? `provider: ${aiProvider}` : `${text.length} chars · auto ¶ wrap`}
        </span>
        <button onClick={ctx.closeComposer} className="mono-close" title="Close composer" style={{
          width: 20, height: 20, borderRadius: "50%", border: "none",
          background: "rgba(0,0,0,0.06)", color: "rgba(20,20,20,0.65)",
          display: "flex", alignItems: "center", justifyContent: "center",
          cursor: "pointer", fontFamily: "inherit",
        }}>
          <I name="close" size={10} stroke={2} />
        </button>
      </div>

      {/* Body */}
      <div style={{ padding: "0 14px", overflow: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
        {mode === "write" ? (
          <div style={boxStyle}>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Write your reflection here…"
              style={taStyle(150)}
            />
          </div>
        ) : (
          <div style={{ display: "flex", gap: 10, alignItems: "stretch" }}>
            {/* Left column — notes + prompt */}
            <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
              <FieldLabel hint={
                existingText ? "what to change / tone / focus" :
                isFinal      ? "optional — history attached automatically" :
                               "≥ 20 chars recommended"
              }>
                {existingText ? "Changes / instructions" :
                 isFinal      ? "Themes to emphasize" : "Your rough notes"}
              </FieldLabel>
              <div style={{ ...boxStyle, flex: 1 }}>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder={
                    existingText ? "e.g. tighten the second paragraph, emphasize teamwork more" :
                    isFinal      ? "e.g. focus on perseverance and LO5 (collaboration)" :
                                   "e.g. practiced chord transitions, learned G→D switch, 45 min"
                  }
                  style={taStyle(110)}
                />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                {isManual ? (
                  <CopyBtn primary label="Copy prompt" icon="copy"
                           disabled={!!loading || !canBuild}
                           onBefore={buildPrompt} />
                ) : (
                  <Btn primary icon="sparkle" onClick={generateDirect}
                       disabled={!!loading || !canBuild}>Generate</Btn>
                )}
                {isManual && prompt && (
                  <span style={{ fontSize: 10.5, color: N.inkSoft }}>
                    {prompt.length} chars — paste it into any AI, then paste the answer →
                  </span>
                )}
              </div>
              {isManual && prompt && (
                <div style={{
                  ...boxStyle, maxHeight: 76, overflow: "auto",
                  padding: "7px 10px", cursor: "copy",
                  fontFamily: `"SF Mono", Menlo, monospace`,
                  fontSize: 10.5, lineHeight: 1.5, color: N.inkMid,
                  whiteSpace: "pre-wrap", wordBreak: "break-word",
                }}
                  title="Click to copy again"
                  onClick={() => copyTextToClipboard(prompt)}>
                  {prompt}
                </div>
              )}
            </div>

            {/* Right column — AI response + live preview */}
            <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
              <FieldLabel hint={isManual ? "plain text or <p> HTML" : "editable"}>
                {isManual ? "Paste AI's response" : "Generated reflection"}
              </FieldLabel>
              <div style={{ ...boxStyle, flex: 1 }}>
                <textarea
                  value={result}
                  onChange={(e) => setResult(e.target.value)}
                  placeholder={isManual
                    ? "Paste the response from ChatGPT / Claude / DeepSeek here…"
                    : "Click Generate — the result lands here and can be edited"}
                  style={taStyle(110)}
                />
              </div>
              {previewHtml && (
                <div style={{
                  padding: "9px 12px",
                  background: "rgba(255,255,255,0.85)",
                  borderRadius: 8,
                  fontSize: 12, lineHeight: 1.6, color: N.ink,
                  boxShadow: `inset 0 0 0 0.5px rgba(0,0,0,0.08), inset 3px 0 0 0 ${A.solid}`,
                  maxHeight: 120, overflow: "auto",
                }} dangerouslySetInnerHTML={{ __html: previewHtml }} />
              )}
            </div>
          </div>
        )}

        {existingText && mode === "ai" && (
          <div style={{
            padding: "6px 10px", borderRadius: 7,
            background: "rgba(0,0,0,0.025)",
            boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.06)",
            fontSize: 11, lineHeight: 1.5, color: N.inkMid,
            maxHeight: 60, overflow: "auto", whiteSpace: "pre-wrap",
          }}>
            <b style={{ color: N.ink }}>Existing:</b> {existingText}
          </div>
        )}
      </div>

      {/* Footer */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "8px 14px 10px",
      }}>
        <StatusLine loading={loading} error={error} />
        <div style={{ flex: 1 }} />
        <Btn onClick={ctx.closeComposer} disabled={!!loading}>Cancel</Btn>
        <Btn primary onClick={() => send(sendBody)}
             disabled={!!loading || !sendBody.trim()}>
          {rid && !payload.isPlaceholderFill ? "Save to ManageBac" : "Send to ManageBac"}
        </Btn>
      </div>
    </div>
  );
}

window.MonoComposer = Composer;
window.copyTextToClipboard = copyTextToClipboard;
