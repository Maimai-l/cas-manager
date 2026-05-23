// ── Mono modals — Journal, Photos, Edit Photos, AI Generate ─────────────
const I = window.I;
const A = window.MONO_ACCENT;
const N = window.MONO_NEUTRALS;
const ModalShell = window.MonoModalShell;
const FieldLabel = window.MonoFieldLabel;
const FieldShell = window.MonoFieldShell;
const Caret = window.MonoCaret;
const Btn = window.MonoBtn;
const Pill = window.MonoPill;
const StrandTag = window.MonoStrandTag;
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

// ── 1. New Journal — mode chooser, then write ─────────────────────────
function NewJournalModal({ mode = "choose" }) {
  const ctx = React.useContext(window.MonoCtx);
  const exp = ctx.activeExp;
  const strand  = (exp && exp.strand) || "activity";
  const strands = (exp && exp.strands && exp.strands.length) ? exp.strands : [strand];
  const expName = (exp && exp.name) || (exp && `Experience ${exp.id}`) || "Experience";

  if (mode === "choose") {
    return <JournalChooseModal exp={exp} expName={expName} strands={strands} />;
  }

  // Write mode — either NEW or EDIT existing (when modalPayload.rid is set)
  const editing  = !!(ctx.modalPayload && ctx.modalPayload.rid);
  const editRefl = editing ? ctx.modalPayload.refl : null;
  const editRid  = editing ? ctx.modalPayload.rid : null;
  const editCas  = editing ? ctx.modalPayload.casId : (exp && exp.id);

  const initialText = React.useMemo(() => {
    if (editRefl && editRefl.body_html) return _stripHtml(editRefl.body_html);
    return "";
  }, [editRefl]);

  const [text, setText] = React.useState(initialText);
  const { loading, error, run } = useAsyncOp();

  async function handleSave() {
    if (!text.trim()) return;
    const body = _wrapPlainAsHtml(text);
    await run(editing ? "Saving…" : "Posting…", async () => {
      if (editing) {
        await API.editJournal(editRid, editCas, body, null);
      } else {
        await API.createJournal(exp.id, body, null);
      }
      await ctx.refreshAfterMutation();
      ctx.close();
    });
  }

  // Open AI revise flow with the current text as `existing`
  function openAIRevise() {
    if (!editing) return;
    ctx.setModalPayload((prev) => ({
      ...prev,
      fillingRid:  editRid,
      fillingCas:  editCas,
      fillingDate: (editRefl && (editRefl.date_iso || null)) || null,
      editingExisting: text || _stripHtml((editRefl && editRefl.body_html) || ""),
      notes: "",
      prompt: "",
      pasted: "",
      generated: "",
    }));
    ctx.go("ai-1");
  }

  return (
    <ModalShell
      title={`${editing ? "Edit Journal" : "New Journal"} — ${expName}`}
      width={620}
      footer={<>
        {editing && <Btn icon="sparkle" onClick={openAIRevise} disabled={!!loading}>AI</Btn>}
        {!editing && <Btn onClick={() => ctx.go("journal-choose")} disabled={!!loading}>← Back</Btn>}
        {editing  && <Btn onClick={ctx.close} disabled={!!loading}>Cancel</Btn>}
        <Btn primary onClick={handleSave} disabled={!!loading || !text.trim()}>
          {editing ? "Save to ManageBac" : "Send to ManageBac"}
        </Btn>
      </>}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <StrandTag strands={strands} />
        <span style={{ fontSize: 11, color: N.inkSoft }}>
          {`${text.length} chars · auto ¶ wrap`}
        </span>
      </div>
      <FieldShell height={240} focused style={{ padding: 0 }}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Write your reflection here…"
          style={{
            width: "100%", height: 240, padding: "10px 12px",
            border: "none", outline: "none", background: "transparent",
            fontSize: 13.5, lineHeight: 1.65,
            color: N.inkDeep, fontFamily: "inherit", resize: "none",
            boxSizing: "border-box"
          }}
        />
      </FieldShell>
      <StatusLine loading={loading} error={error} />
    </ModalShell>);
}

// Mode-chooser screen of the "New Journal" flow. Lifted into its own
// component so it can own the `isFinal` checkbox state without re-mounting
// the rest of NewJournalModal across mode transitions.
function JournalChooseModal({ exp, expName, strands }) {
  const ctx = React.useContext(window.MonoCtx);
  const [isFinal, setIsFinal] = React.useState(false);

  function startAI() {
    if (isFinal) {
      ctx.setModalPayload((prev) => ({
        ...prev,
        finalMode: true,
        // Clear other transient state so the AI modal starts fresh
        notes: "", prompt: "", pasted: "", generated: "",
        editingExisting: null, fillingRid: null,
      }));
    } else {
      ctx.setModalPayload((prev) => ({ ...prev, finalMode: false }));
    }
    ctx.go("ai-1");
  }

  return (
    <ModalShell title={`New Journal — ${expName}`} width={620}
      footer={<><Btn onClick={ctx.close}>Cancel</Btn></>}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <StrandTag strands={strands} />
        <span style={{ fontSize: 11, color: N.inkSoft }}>How do you want to start?</span>
      </div>

      <label style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "8px 12px",
        background: isFinal ? "rgba(177,226,69,0.18)" : "rgba(255,255,255,0.6)",
        borderRadius: 9,
        boxShadow: isFinal
          ? `inset 0 0 0 1px ${A.solid}`
          : "inset 0 0 0 0.5px rgba(0,0,0,0.08)",
        cursor: "pointer",
        transition: "background 0.12s, box-shadow 0.12s",
      }}>
        <input
          type="checkbox"
          checked={isFinal}
          onChange={(e) => setIsFinal(e.target.checked)}
          style={{ width: 15, height: 15, cursor: "pointer", margin: 0 }}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: N.inkDeep }}>
            This is a Final Reflection
          </div>
        </div>
      </label>

      <div style={{ display: "flex", gap: 12, marginTop: 4 }}>
        <ModeCard
          onClick={() => ctx.go("journal-write")}
          icon="pen" title="Write it myself"
          sub="Plain editor. Auto-paragraph wrap on save." />
        <ModeCard
          onClick={startAI}
          icon="sparkle"
          title={isFinal ? "Generate Final Reflection" : "Generate with AI"}
          sub={isFinal
            ? "AI writes 4-question final reflection using all past sessions as evidence."
            : "Jot rough notes. AI writes the session reflection grounded in your LOs."}
          accent />
      </div>
    </ModalShell>);
}


function ModeCard({ icon, title, sub, accent, onClick }) {
  const [hovered, setHovered] = React.useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="mono-mode-card"
      style={{
        flex: 1, padding: "16px 14px 14px",
        borderRadius: 11, cursor: "pointer",
        background: hovered ? "rgba(177,226,69,0.32)" : "rgba(255,255,255,0.7)",
        boxShadow: hovered
          ? `inset 0 0 0 1px ${A.solid}, 0 1px 3px rgba(90,120,30,0.12)`
          : "inset 0 0 0 0.5px rgba(0,0,0,0.08)",
        color: N.inkDeep,
        display: "flex", flexDirection: "column", gap: 6,
        transition: "background 0.15s, box-shadow 0.15s, transform 0.12s"
      }}>
      <div style={{
        width: 32, height: 32, borderRadius: 8,
        background: "rgba(0,0,0,0.05)",
        color: N.inkDeep,
        display: "flex", alignItems: "center", justifyContent: "center"
      }}>
        <I name={icon} size={16} stroke={1.7} />
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, marginTop: 2 }}>{title}</div>
      <div style={{ fontSize: 11, color: N.inkMid, lineHeight: 1.45 }}>
        {sub}
      </div>
    </div>);
}

// ── 2. New Photos — drag-and-drop ───────────────────────────────────────
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

// ── 4. AI Generate — 3 steps ────────────────────────────────────────────
function AIGenerateModal({ step = 1 }) {
  const ctx = React.useContext(window.MonoCtx);
  const exp = ctx.activeExp;
  const strand  = (exp && exp.strand) || "activity";
  const strands = (exp && exp.strands && exp.strands.length) ? exp.strands : [strand];
  const expName = (exp && exp.name) || (exp && `Experience ${exp.id}`) || "Experience";

  // Payload carries notes / prompt / generated across steps + flow flags
  const payload = ctx.modalPayload || {};
  const fillingRid      = payload.fillingRid || null;   // placeholder fill OR journal revise
  const fillingCas      = payload.fillingCas || (exp && exp.id);
  const fillingDate     = payload.fillingDate || null;
  const editingExisting = payload.editingExisting || null;
  const finalMode       = !!payload.finalMode;

  // Resolve the AI kind. Three mutually-exclusive flows:
  //   editingExisting → 'edit'  (revise an existing journal)
  //   finalMode       → 'final' (4-question final reflection)
  //   otherwise       → 'reflection' (default session reflection)
  const aiKind = editingExisting ? "edit" : (finalMode ? "final" : "reflection");

  // Final reflections grow stronger when grounded in real session history —
  // load every past non-placeholder reflection from the local DB as context.
  const includeHistory = finalMode;

  const [notes, setNotes] = React.useState(payload.notes || "");
  const [prompt, setPrompt] = React.useState(payload.prompt || "");
  const [pasted, setPasted] = React.useState(payload.pasted || "");
  const [generated, setGenerated] = React.useState(payload.generated || "");
  const { loading, error, run } = useAsyncOp();

  const aiProvider = (ctx.status && ctx.status.ai_provider) || "prompt";
  const stepLabels =
    editingExisting ? ["Existing & Changes", "Prompt & Paste", "Revised"] :
    finalMode       ? ["Themes & Context",   "Prompt & Paste", "Final Reflection"] :
                      ["Notes & Instructions", "Prompt & Paste", "Result"];
  const modalTitle =
    editingExisting ? "AI Revise" :
    finalMode       ? "AI Final Reflection" :
                      "AI Generate";

  async function copyPrompt(text) {
    try { await navigator.clipboard.writeText(text); } catch (_) { /* ignore */ }
  }

  async function handleGenerate() {
    // Notes are mandatory except in final-mode where history is enough context.
    if (!notes.trim() && !finalMode) return;
    const cas = fillingCas;
    if (!cas) return;
    if (aiProvider === "prompt") {
      await run("Building prompt…", async () => {
        const r = await API.buildPrompt(cas, notes, aiKind, fillingDate, editingExisting, includeHistory);
        const p = r.prompt;
        setPrompt(p);
        await copyPrompt(p);
        ctx.setModalPayload((prev) => ({ ...prev, notes, prompt: p }));
        ctx.go("ai-2");
      });
    } else {
      await run("Generating with AI…", async () => {
        const r = await API.generateAI(cas, notes, aiKind, fillingDate, editingExisting, includeHistory);
        const g = r.result || "";
        setGenerated(g);
        ctx.setModalPayload((prev) => ({ ...prev, notes, generated: g }));
        ctx.go("ai-3");
      });
    }
  }

  function handleUsePaste() {
    if (!pasted.trim()) return;
    const html = _wrapPlainAsHtml(pasted);
    setGenerated(html);
    ctx.setModalPayload((prev) => ({ ...prev, pasted, generated: html }));
    ctx.go("ai-3");
  }

  async function handleSend() {
    if (!generated.trim()) return;
    const cas = fillingCas;
    await run("Sending to ManageBac…", async () => {
      if (fillingRid) {
        await API.editJournal(fillingRid, cas, generated, null);
      } else {
        await API.createJournal(cas, generated, null);
      }
      await ctx.refreshAfterMutation();
      ctx.close();
    });
  }

  return (
    <ModalShell width={620} title={`${modalTitle} · ${stepLabels[step - 1]}`}
      footer={
        step === 1 ? <>
          <Btn onClick={ctx.close} disabled={!!loading}>Cancel</Btn>
          <Btn primary icon="sparkle" onClick={handleGenerate}
               disabled={!!loading || (!notes.trim() && !finalMode)}>
            {aiProvider === "prompt" ? "Build prompt" : "Generate with AI"}
          </Btn>
        </> :
        step === 2 ? <>
          <Btn onClick={() => ctx.go("ai-1")} disabled={!!loading}>← Back</Btn>
          <Btn primary onClick={handleUsePaste} disabled={!!loading || !pasted.trim()}>Use this response</Btn>
        </> : <>
          <Btn onClick={() => ctx.go(aiProvider === "prompt" ? "ai-2" : "ai-1")} disabled={!!loading}>← Back</Btn>
          <Btn primary onClick={handleSend} disabled={!!loading || !generated.trim()}>
            Send to ManageBac
          </Btn>
        </>
      }>
      <Stepper labels={stepLabels} current={step} />

      {step === 1 && <>
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "8px 10px", borderRadius: 8,
          background: "rgba(0,0,0,0.04)",
          boxShadow: `inset 3px 0 0 0 ${A.solid}, inset 0 0 0 0.5px rgba(0,0,0,0.06)`
        }}>
          <StrandTag strands={strands} compact />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 11.5, fontWeight: 600, color: N.inkDeep }}>
              {expName}{fillingDate ? ` · ${fillingDate}` : ""}
            </div>
            <div style={{ fontSize: 10, color: N.inkSoft }}>
              {editingExisting ? `Revising journal #${fillingRid}` :
               finalMode       ? `Final reflection (with all past sessions as context)` :
               fillingRid      ? `Filling placeholder #${fillingRid}` :
                                 "New journal reflection"}
              {" · provider: " + aiProvider}
            </div>
          </div>
        </div>
        {editingExisting && (
          <div>
            <FieldLabel hint="read-only">Existing reflection</FieldLabel>
            <div style={{
              padding: "10px 12px", borderRadius: 8,
              background: "rgba(0,0,0,0.025)",
              boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.08)",
              fontSize: 12.5, lineHeight: 1.55,
              color: N.inkMid,
              maxHeight: 130, overflow: "auto",
              whiteSpace: "pre-wrap"
            }}>{editingExisting}</div>
          </div>
        )}
        <div>
          <FieldLabel hint={
            editingExisting ? "what to change / tone / focus" :
            finalMode       ? "themes / takeaways you want emphasized — history is loaded automatically" :
                              "≥ 20 chars recommended"
          }>
            {editingExisting ? "Changes / instructions" :
             finalMode       ? "Themes to emphasize (optional)" :
                               "Your rough notes"}
          </FieldLabel>
          <FieldShell height={120} focused style={{ padding: 0 }}>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder={
                editingExisting ? "e.g. tighten the second paragraph, emphasize teamwork more, shorten to 150 words" :
                finalMode       ? "e.g. focus on perseverance and LO5 (collaboration); reference the second-semester sessions more than the first" :
                                  "e.g. practiced chord transitions, learned G→D switch, 45 min"
              }
              style={{
                width: "100%", height: 120, padding: "10px 12px",
                border: "none", outline: "none", background: "transparent",
                fontSize: 13, lineHeight: 1.6,
                color: N.inkDeep, fontFamily: "inherit", resize: "none",
                boxSizing: "border-box"
              }}
            />
          </FieldShell>
        </div>
        <StatusLine loading={loading} error={error}
          hint={
            finalMode
              ? `Provider "${aiProvider}" — your full session history will be attached as context automatically.`
              : `Provider "${aiProvider}" — ${aiProvider === "prompt" ? "you'll paste the AI response back" : "the API call returns text directly"}.`
          } />
      </>}

      {step === 2 && <>
        <div>
          <FieldLabel hint="copied to clipboard">Full prompt</FieldLabel>
          <FieldShell height={140} mono style={{ padding: 0 }}>
            <textarea
              readOnly
              value={prompt}
              onClick={() => copyPrompt(prompt)}
              style={{
                width: "100%", height: 140, padding: "10px 12px",
                border: "none", outline: "none", background: "transparent",
                fontSize: 11.5, lineHeight: 1.55,
                color: N.inkDeep, resize: "none", boxSizing: "border-box",
                fontFamily: `"SF Mono", Menlo, monospace`
              }}
            />
          </FieldShell>
        </div>
        <div>
          <FieldLabel>Paste AI's response</FieldLabel>
          <FieldShell height={110} focused style={{ padding: 0 }}>
            <textarea
              value={pasted}
              onChange={(e) => setPasted(e.target.value)}
              placeholder="Paste plain text or <p> HTML from ChatGPT / Claude / DeepSeek…"
              style={{
                width: "100%", height: 110, padding: "10px 12px",
                border: "none", outline: "none", background: "transparent",
                fontSize: 12.5, lineHeight: 1.6,
                color: N.inkDeep, fontFamily: "inherit", resize: "none",
                boxSizing: "border-box"
              }}
            />
          </FieldShell>
        </div>
        <StatusLine error={error} hint="Click the prompt to copy it again." />
      </>}

      {step === 3 && <>
        <div>
          <FieldLabel hint={`${_stripHtml(generated).length} chars`}>Generated reflection</FieldLabel>
          <div style={{
            padding: "13px 15px",
            background: "rgba(255,255,255,0.85)",
            borderRadius: 9,
            fontSize: 13, lineHeight: 1.65,
            color: N.ink,
            boxShadow: `inset 0 0 0 0.5px rgba(0,0,0,0.08), inset 3px 0 0 0 ${A.solid}`,
            maxHeight: 260, overflow: "auto"
          }} dangerouslySetInnerHTML={{ __html: generated }} />
        </div>
        <StatusLine loading={loading} error={error} />
      </>}
    </ModalShell>);
}

function Stepper({ labels, current }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 2px" }}>
      {labels.map((l, i) => {
        const done = i + 1 < current, active = i + 1 === current;
        return (
          <React.Fragment key={i}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{
                width: 18, height: 18, borderRadius: "50%",
                background: active ? A.solid : done ? "rgba(20,20,20,0.85)" : "rgba(0,0,0,0.06)",
                color: active ? A.onAccent : done ? "#fff" : N.inkSoft,
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 10, fontWeight: 700
              }}>
                {done ? <I name="check" size={10} stroke={3} /> : i + 1}
              </div>
              <span style={{
                fontSize: 11, fontWeight: active ? 600 : 500,
                color: active ? N.inkDeep : N.inkSoft
              }}>{l}</span>
            </div>
            {i < labels.length - 1 && <div style={{ flex: 1, height: 1, background: "rgba(0,0,0,0.1)" }} />}
          </React.Fragment>);
      })}
    </div>);
}

window.NewJournalModal_Mono = NewJournalModal;
window.NewPhotosModal_Mono = NewPhotosModal;
window.EditPhotosModal_Mono = EditPhotosModal;
window.AIGenerateModal_Mono = AIGenerateModal;
