// ── Modal shell + form primitives (mono) ────────────────────────────────
const I = window.I;
const A = window.MONO_ACCENT;
const N = window.MONO_NEUTRALS;

function ModalShell({ title, children, footer, width = 560, bodyStyle, onClose }) {
  const ctx = React.useContext(window.MonoCtx);
  const handleClose = onClose || ctx.close;
  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}
      style={{
        position: "absolute", inset: 0, zIndex: 50,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "rgba(20,20,20,0.18)",
        backdropFilter: "blur(2px)",
        WebkitBackdropFilter: "blur(2px)",
      }}>
      <div style={{
        width, maxHeight: 720,
        borderRadius: 14,
        background: "rgba(252,252,252,0.85)",
        backdropFilter: "blur(40px) saturate(180%)",
        WebkitBackdropFilter: "blur(40px) saturate(180%)",
        boxShadow: "inset 0 0 0 0.5px rgba(255,255,255,0.7), 0 24px 60px rgba(0,0,0,0.22), 0 0 0 0.5px rgba(0,0,0,0.06)",
        display: "flex", flexDirection: "column", overflow: "hidden",
        position: "relative",
      }}>
        <button onClick={handleClose} className="mono-close" style={{
          position: "absolute", top: 11, right: 12, zIndex: 2,
          width: 22, height: 22, borderRadius: "50%",
          border: "none", cursor: "pointer",
          background: "rgba(0,0,0,0.06)",
          color: "rgba(20,20,20,0.65)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontFamily: "inherit",
          transition: "background 0.12s",
        }}>
          <I name="close" size={11} stroke={2} />
        </button>

        <div style={{
          padding: "12px 44px 11px",
          display: "flex", alignItems: "center", gap: 10,
          borderBottom: "0.5px solid " + N.hairline,
        }}>
          <div style={{
            flex: 1, textAlign: "center",
            fontSize: 12.5, fontWeight: 500,
            color: N.ink, letterSpacing: -0.1,
          }}>{title}</div>
        </div>

        <div style={{
          flex: 1, minHeight: 0, overflow: "auto",
          padding: "16px 18px",
          display: "flex", flexDirection: "column", gap: 12,
          ...(bodyStyle || {}),
        }}>{children}</div>

        {footer && (
          <div style={{
            padding: "10px 14px",
            borderTop: "0.5px solid " + N.hairline,
            display: "flex", justifyContent: "flex-end", gap: 7,
            background: "rgba(255,255,255,0.3)",
          }}>{footer}</div>
        )}
      </div>
    </div>
  );
}

function FieldLabel({ children, hint }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 5 }}>
      <label style={{
        fontSize: 11, fontWeight: 500,
        color: N.inkMid, letterSpacing: 0.1,
      }}>{children}</label>
      {hint && <span style={{ fontSize: 10, color: "rgba(20,20,20,0.45)" }}>{hint}</span>}
    </div>
  );
}

function FieldShell({ children, height, mono, focused, style }) {
  return (
    <div style={{
      background: "rgba(255,255,255,0.78)",
      borderRadius: 8,
      padding: "8px 11px",
      minHeight: height,
      fontSize: mono ? 11.5 : 12.5,
      lineHeight: 1.55,
      color: N.inkDeep,
      fontFamily: mono ? `"SF Mono", Menlo, monospace` : "inherit",
      boxShadow: focused
        ? "inset 0 0 0 1px rgba(20,20,20,0.4), 0 0 0 3px rgba(0,0,0,0.06)"
        : "inset 0 0 0 0.5px rgba(0,0,0,0.1), inset 0 0.5px 0 rgba(255,255,255,0.6)",
      ...style,
    }}>{children}</div>
  );
}

function Caret() {
  return (
    <span style={{
      display: "inline-block",
      width: 1.5, height: "1.05em",
      background: N.inkDeep,
      verticalAlign: "text-bottom",
      marginLeft: 1,
    }} />
  );
}

window.MonoModalShell = ModalShell;
window.MonoFieldLabel = FieldLabel;
window.MonoFieldShell = FieldShell;
window.MonoCaret = Caret;
