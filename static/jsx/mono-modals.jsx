// ── Shared modal/dock primitives ────────────────────────────────────────
// The journal / AI / SA / photos flows all live in the flat bottom Composer
// (mono-composer.jsx). This file only holds the reusable pieces they share:
// status line, async hook, HTML helpers, and the photo dropzone.
const I = window.I;
const A = window.MONO_ACCENT;
const N = window.MONO_NEUTRALS;

// ── Shared error / loading bar ──────────────────────────────────────────
function StatusLine({ loading, error, hint }) {
  if (!loading && !error && !hint) return null;
  return (
    <div style={{
      fontSize: 11.5, lineHeight: 1.45,
      color: error ? "#a4332e" : N.inkMid,
      padding: "4px 2px"
    }}>
      {loading && <span style={{ marginRight: 6 }}>⏳ {loading}</span>}
      {error   && <span>⚠ {error}</span>}
      {!loading && !error && hint && <span>{hint}</span>}
    </div>
  );
}

// Helper hook: run an async op with loading/error UI
function useAsyncOp() {
  const [loading, setLoading] = React.useState(null);
  const [error, setError]     = React.useState(null);
  const run = React.useCallback(async (label, fn) => {
    setLoading(label || "Working…");
    setError(null);
    try {
      const r = await fn();
      setLoading(null);
      return r;
    } catch (e) {
      setLoading(null);
      const msg = e && e.message ? e.message : String(e);
      setError(msg === "session_expired" ? "Login expired, please go to Settings to log in again" : msg);
      throw e;
    }
  }, []);
  return { loading, error, run, clearError: () => setError(null) };
}

// Plain text → <p> HTML
function _wrapPlainAsHtml(text) {
  const t = (text || "").trim();
  if (!t) return "";
  if (t.startsWith("<")) return t;
  return t.split(/\n+/).filter((l) => l.trim()).map((l) => `<p>${l.trim()}</p>`).join("");
}

// Strip HTML tags (for display in textarea)
function _stripHtml(html) {
  const d = document.createElement("div");
  d.innerHTML = html || "";
  return d.textContent || d.innerText || "";
}

// ── Photo dropzone (used by the Composer's Photos type) ─────────────────
function Dropzone({ files, dragging, totalSize, onPick, onDragOver, onDragLeave, onDrop, onRemove }) {
  const filled = files.length > 0;
  return (
    <div
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      style={{
        borderRadius: 5, padding: filled ? 14 : 24,
        background: dragging ? "rgba(0,0,0,0.045)" : "#fff",
        boxShadow: dragging
          ? `inset 0 0 0 2px ${A.solid}`
          : "inset 0 0 0 1px rgba(0,0,0,0.12)",
        backgroundImage: !filled && !dragging
          ? `repeating-linear-gradient(45deg, transparent 0 6px, rgba(0,0,0,0.035) 6px 12px)`
          : "none",
        transition: "all 0.15s"
      }}>
      {filled ? (
        <div>
          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            marginBottom: 10, padding: "0 2px"
          }}>
            <span style={{ fontSize: 11, fontWeight: 500, color: N.ink }}>
              {files.length} photo{files.length > 1 ? "s" : ""} · {totalSize}
            </span>
            <span
              onClick={onPick}
              style={{
                fontSize: 10.5, color: N.ink, fontWeight: 500,
                display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer",
                textDecoration: "underline"
              }}>
              <I name="upload" size={11} stroke={1.7} />
              Add more
            </span>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {files.map((f, i) =>
              <FilePreview key={i} file={f} onRemove={() => onRemove(i)} />
            )}
          </div>
        </div>
      ) : (
        <div
          onClick={onPick}
          style={{
            textAlign: "center", display: "flex", flexDirection: "column",
            alignItems: "center", gap: 8, cursor: "pointer"
          }}>
          <div style={{
            width: 42, height: 42, borderRadius: 5,
            background: dragging ? A.solid : "#fff",
            color: dragging ? A.onAccent : N.ink,
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: dragging ? "none" : "inset 0 0 0 1px rgba(0,0,0,0.12)",
            transform: dragging ? "scale(1.08)" : "scale(1)",
            transition: "all 0.15s"
          }}>
            <I name="upload" size={20} stroke={1.5} />
          </div>
          <div style={{ fontSize: 12.5, fontWeight: 500, color: N.inkDeep }}>
            {dragging ? "Drop photos to add" : "Drag photos here"}
          </div>
          <div style={{ fontSize: 11, color: N.inkSoft }}>
            {dragging
              ? "Release to upload"
              : <>or <span style={{ color: N.inkDeep, fontWeight: 500, textDecoration: "underline" }}>browse</span> · JPG / PNG / HEIC</>}
          </div>
        </div>
      )}
    </div>);
}

function FilePreview({ file, onRemove }) {
  const [url, setUrl] = React.useState(null);
  React.useEffect(() => {
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);
  return (
    <div style={{ position: "relative" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{
          width: 92, height: 68, borderRadius: 5,
          background: "linear-gradient(135deg,#3a3a3a,#1a1a1a)",
          overflow: "hidden",
        }}>
          {url && <img src={url} alt={file.name} style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />}
        </div>
        <div style={{
          fontSize: 9.5, color: N.inkMid, textAlign: "center",
          maxWidth: 92, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"
        }}>{file.name}</div>
      </div>
      <DeleteChip onClick={(e) => { e.stopPropagation(); onRemove(); }} />
    </div>);
}

function DeleteChip({ onClick }) {
  return (
    <div
      onClick={onClick}
      style={{
        position: "absolute", top: -5, right: -5,
        width: 18, height: 18, borderRadius: "50%",
        background: "rgba(20,20,20,0.85)",
        color: "#fff",
        display: "flex", alignItems: "center", justifyContent: "center",
        cursor: "pointer",
        boxShadow: "0 1px 3px rgba(0,0,0,0.2)"
      }}>
      <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
        <path d="M6 6 18 18M18 6 6 18" />
      </svg>
    </div>);
}

// Shared UI helpers — also used by mono-composer.jsx (loaded after this file)
window.MonoHelpers = {
  StatusLine,
  useAsyncOp,
  wrapPlainAsHtml: _wrapPlainAsHtml,
  stripHtml: _stripHtml,
  Dropzone,
  FilePreview,
  DeleteChip,
};
