// ── Mono modals — Journal, Photos, Edit Photos, AI Generate ─────────────
const I = window.I;
const A = window.MONO_ACCENT;
const N = window.MONO_NEUTRALS;
const ModalShell = window.MonoModalShell;
const FieldLabel = window.MonoFieldLabel;
const FieldShell = window.MonoFieldShell;
const Btn = window.MonoBtn;
const PhotoThumb = window.MonoPhotoThumb;
const API = window.API;

// ── Shared error / loading bar (rendered inside ModalShell body) ────────
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

// ── New Photos — drag-and-drop ──────────────────────────────────────────
// (The journal + AI flows live in mono-composer.jsx — flat, non-modal.)
function NewPhotosModal() {
  const ctx = React.useContext(window.MonoCtx);
  const exp = ctx.activeExp;
  const strand = (exp && exp.strand) || "activity";
  const expName = (exp && exp.name) || (exp && `Experience ${exp.id}`) || "Experience";

  const [caption, setCaption] = React.useState("");
  const [files, setFiles]     = React.useState([]); // File[]
  const [dragging, setDragging] = React.useState(false);
  const fileRef = React.useRef(null);
  const { loading, error, run } = useAsyncOp();

  function addFiles(fs) {
    const imgs = Array.from(fs || []).filter((f) => f.type && f.type.startsWith("image/"));
    if (imgs.length) setFiles((prev) => [...prev, ...imgs]);
  }

  function removeAt(idx) {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  }

  function totalSize() {
    const bytes = files.reduce((acc, f) => acc + (f.size || 0), 0);
    return (bytes / 1024 / 1024).toFixed(1) + " MB";
  }

  async function handleUpload() {
    if (!files.length || !exp) return;
    const captions = files.map(() => caption);
    await run(`Uploading ${files.length} photo${files.length > 1 ? "s" : ""}…`, async () => {
      await API.createAlbum(exp.id, files, captions, null, null);
      await ctx.refreshAfterMutation();
      ctx.close();
    });
  }

  return (
    <ModalShell title={`New Photos — ${expName}`} width={620}
      footer={<>
        <Btn onClick={ctx.close} disabled={!!loading}>Cancel</Btn>
        <Btn primary onClick={handleUpload} disabled={!!loading || !files.length}>
          {files.length ? `Upload ${files.length} photo${files.length > 1 ? "s" : ""}` : "Upload"}
        </Btn>
      </>}>
      <div>
        <FieldLabel hint="applied to every uploaded photo">Caption (optional)</FieldLabel>
        <FieldShell style={{ padding: 0 }}>
          <input
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            placeholder="e.g. Week 3 · Field practice"
            style={{
              width: "100%", padding: "8px 11px", border: "none", outline: "none",
              background: "transparent", fontSize: 12.5,
              color: N.inkDeep, fontFamily: "inherit"
            }}
          />
        </FieldShell>
      </div>

      <Dropzone
        files={files}
        dragging={dragging}
        totalSize={totalSize()}
        onPick={() => fileRef.current && fileRef.current.click()}
        onDragOver={(e) => { e.preventDefault(); if (!dragging) setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          addFiles(e.dataTransfer.files);
        }}
        onRemove={removeAt}
      />
      <input
        ref={fileRef}
        type="file" accept="image/*" multiple
        style={{ display: "none" }}
        onChange={(e) => {
          addFiles(e.target.files);
          e.target.value = "";
        }}
      />

      <StatusLine loading={loading} error={error} />
    </ModalShell>);
}

function Dropzone({ files, dragging, totalSize, onPick, onDragOver, onDragLeave, onDrop, onRemove }) {
  const filled = files.length > 0;
  return (
    <div
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      style={{
        borderRadius: 11, padding: filled ? 14 : 28,
        background: dragging ? "rgba(0,0,0,0.04)" : "rgba(255,255,255,0.6)",
        boxShadow: dragging
          ? `inset 0 0 0 2px ${A.solid}`
          : "inset 0 0 0 1px rgba(0,0,0,0.1)",
        backgroundImage: !filled && !dragging
          ? `repeating-linear-gradient(45deg, transparent 0 6px, rgba(0,0,0,0.04) 6px 12px)`
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
            alignItems: "center", gap: 10, cursor: "pointer"
          }}>
          <div style={{
            width: 48, height: 48, borderRadius: 12,
            background: dragging ? A.solid : "rgba(255,255,255,0.85)",
            color: dragging ? A.onAccent : N.ink,
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: dragging ? "none" : "inset 0 0 0 0.5px rgba(0,0,0,0.08)",
            transform: dragging ? "scale(1.08)" : "scale(1)",
            transition: "all 0.15s"
          }}>
            <I name="upload" size={24} stroke={1.5} />
          </div>
          <div style={{ fontSize: 13.5, fontWeight: 600, color: N.inkDeep }}>
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
          width: 92, height: 68, borderRadius: 8,
          background: "linear-gradient(135deg,#3a3a3a,#1a1a1a)",
          overflow: "hidden",
          boxShadow: "inset 0 0 0 0.5px rgba(255,255,255,0.15)"
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
        boxShadow: "0 1px 3px rgba(0,0,0,0.2), inset 0 0 0 0.5px rgba(255,255,255,0.15)"
      }}>
      <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
        <path d="M6 6 18 18M18 6 6 18" />
      </svg>
    </div>);
}

// ── 3. Edit Photos — existing album, add or remove ──────────────────────
function EditPhotosModal() {
  const ctx = React.useContext(window.MonoCtx);
  const rid    = ctx.modalPayload && ctx.modalPayload.rid;
  const casId  = ctx.modalPayload && ctx.modalPayload.casId;
  const date   = (ctx.modalPayload && ctx.modalPayload.refl && (ctx.modalPayload.refl.date_iso || ctx.modalPayload.refl.group_date)) || "";
  const [photos, setPhotos] = React.useState([]);
  const [newFiles, setNewFiles] = React.useState([]);
  const [newCaption, setNewCaption] = React.useState("");
  const [dragging, setDragging] = React.useState(false);
  const fileRef = React.useRef(null);
  const { loading: listLoading, error: listError, run: listRun } = useAsyncOp();
  const { loading: opLoading, error: opError, run: opRun } = useAsyncOp();

  const reload = React.useCallback(async () => {
    if (!rid || !casId) return;
    await listRun("Loading photos…", async () => {
      const ps = await API.albumPhotos(rid, casId);
      setPhotos(ps || []);
    });
  }, [rid, casId, listRun]);

  React.useEffect(() => { reload(); }, [reload]);

  async function deleteOne(photoId) {
    if (!window.confirm("Delete this photo from ManageBac?")) return;
    await opRun("Deleting…", async () => {
      await API.deletePhoto(rid, photoId, casId);
      await reload();
    });
  }

  function addFiles(fs) {
    const imgs = Array.from(fs || []).filter((f) => f.type && f.type.startsWith("image/"));
    if (imgs.length) setNewFiles((prev) => [...prev, ...imgs]);
  }

  async function uploadNew() {
    if (!newFiles.length) return;
    await opRun(`Uploading ${newFiles.length}…`, async () => {
      await API.addPhotos(rid, casId, newFiles, newCaption);
      setNewFiles([]); setNewCaption("");
      await reload();
      await ctx.refreshAfterMutation();
    });
  }

  return (
    <ModalShell title={`Edit Photos · ${date || "Album"}`} width={620}
      footer={<>
        <Btn onClick={ctx.close} disabled={!!opLoading}>Close</Btn>
        <Btn primary onClick={uploadNew} disabled={!!opLoading || !newFiles.length}>
          {newFiles.length ? `Upload ${newFiles.length}` : "Upload"}
        </Btn>
      </>}>
      <FieldLabel hint={`${photos.length} photo${photos.length === 1 ? "" : "s"}`}>Existing photos</FieldLabel>
      <div style={{
        padding: "12px",
        background: "rgba(255,255,255,0.6)",
        borderRadius: 11,
        boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.06)"
      }}>
        {listLoading && <div style={{ fontSize: 11, color: N.inkSoft }}>{listLoading}</div>}
        {!listLoading && !photos.length && (
          <div style={{ fontSize: 11, color: N.inkSoft }}>No photos in this album.</div>
        )}
        {!!photos.length && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {photos.map((p) =>
              <div key={p.id} style={{ position: "relative" }}>
                <PhotoThumb url={p.s3_url} caption={p.caption} w={92} h={68} />
                <DeleteChip onClick={() => deleteOne(p.id)} />
              </div>
            )}
          </div>
        )}
      </div>
      <StatusLine error={listError} />

      <FieldLabel hint="optional">Caption for new photos</FieldLabel>
      <FieldShell style={{ padding: 0 }}>
        <input
          value={newCaption}
          onChange={(e) => setNewCaption(e.target.value)}
          placeholder="e.g. Cool-down stretch"
          style={{
            width: "100%", padding: "8px 11px", border: "none", outline: "none",
            background: "transparent", fontSize: 12.5,
            color: N.inkDeep, fontFamily: "inherit"
          }}
        />
      </FieldShell>

      <Dropzone
        files={newFiles}
        dragging={dragging}
        totalSize={`${(newFiles.reduce((a, f) => a + f.size, 0) / 1024 / 1024).toFixed(1)} MB`}
        onPick={() => fileRef.current && fileRef.current.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
        onRemove={(i) => setNewFiles((prev) => prev.filter((_, j) => j !== i))}
      />
      <input
        ref={fileRef}
        type="file" accept="image/*" multiple
        style={{ display: "none" }}
        onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }}
      />

      <StatusLine loading={opLoading} error={opError} />
    </ModalShell>);
}

window.NewPhotosModal_Mono = NewPhotosModal;
window.EditPhotosModal_Mono = EditPhotosModal;

// Shared UI helpers — also used by mono-composer.jsx (loaded after this file)
window.MonoHelpers = {
  StatusLine,
  useAsyncOp,
  wrapPlainAsHtml: _wrapPlainAsHtml,
  stripHtml: _stripHtml,
};
