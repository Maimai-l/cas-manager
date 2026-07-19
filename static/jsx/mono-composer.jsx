// ── Composer — flat, non-modal workbench for journal / final / SA / photos ─
// One panel docked at the bottom of the main panel. The type selector picks
// what gets created: a session journal, the Final Reflection, a Self-
// Assessment answer, or a photo album. This is the app's single creation
// surface — there are no more floating photo dialogs.
const I = window.I;
const A = window.MONO_ACCENT;
const N = window.MONO_NEUTRALS;
const Btn = window.MonoBtn;
const FieldLabel = window.MonoFieldLabel;
const PhotoThumb = window.MonoPhotoThumb;
const { StatusLine, useAsyncOp, wrapPlainAsHtml, stripHtml,
        Dropzone, DeleteChip } = window.MonoHelpers;
const API = window.API;

// Clipboard write. Inside pywebview's WebKit the browser APIs are unreliable:
// navigator.clipboard needs a live user gesture (gone after "Copy prompt"
// awaits its network build), and execCommand("copy") often returns true
// WITHOUT actually writing — so trusting it reports "Copied" over an empty
// clipboard. The Python side (pbcopy etc.) writes the real OS clipboard with no
// gesture/permission caveats, so it is the PRIMARY path; the browser APIs are
// only a fallback for a plain-browser dev session with no OS clipboard tool.
async function copyTextToClipboard(text) {
  if (!text) return false;
  try {
    const r = await API.copyClipboard(text);
    if (r && r.copied) return true;
  } catch (_) { /* backend unavailable — fall through to browser paths */ }
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_) { /* fall through */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    ta.style.top = "0";
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

const taStyle = (h) => ({
  width: "100%", height: h, padding: "9px 11px",
  border: "none", outline: "none", background: "transparent",
  fontSize: 12.5, lineHeight: 1.6,
  color: N.inkDeep, fontFamily: "inherit", resize: "none",
  boxSizing: "border-box",
});

const boxStyle = {
  background: "#fff",
  borderRadius: 5,
  boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.12)",
};

// Small button that flips to "Copied" / "Copy failed" for a moment.
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
  // Fixed width so the label swap (Copy prompt / Copied) never reflows
  // the row around it.
  const anchored = { width: 118, justifyContent: "center", whiteSpace: "nowrap" };
  return (
    <Btn icon={state === "ok" ? "check" : icon} primary={primary}
         onClick={handle} disabled={disabled}
         style={state === "fail"
           ? { ...anchored, background: "rgba(216,80,74,0.12)", color: "#a4332e" }
           : anchored}>
      {state === "ok" ? "Copied" : state === "fail" ? "Copy failed" : label}
    </Btn>
  );
}

function TabBtn({ active, icon, children, onClick }) {
  return (
    <button onClick={onClick} style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      padding: "4px 11px", borderRadius: 5, border: "none",
      fontSize: 11.5, fontWeight: 500,
      background: active ? "#fff" : "transparent",
      color: active ? N.inkDeep : N.inkMid,
      boxShadow: active ? "inset 0 0 0 1px rgba(0,0,0,0.12)" : "none",
      cursor: "pointer", fontFamily: "inherit",
      whiteSpace: "nowrap", flexShrink: 0,
      transition: "background 0.12s",
    }}>
      {icon && <I name={icon} size={11.5} stroke={1.8} />}
      {children}
    </button>
  );
}

const segStyle = {
  display: "inline-flex", gap: 2, padding: 2,
  background: "rgba(0,0,0,0.05)", borderRadius: 6, flexShrink: 0,
};

function Composer() {
  const ctx = React.useContext(window.MonoCtx);
  const payload = ctx.composer;           // null → hidden
  const exp = React.useMemo(() => {
    if (!payload) return null;
    return ctx.experiences.find((e) => e.id === payload.casId) || ctx.activeExp;
  }, [payload, ctx.experiences, ctx.activeExp]);

  if (!payload) return null;
  const key = `${payload.casId}-${payload.rid || "new"}`;
  return <ComposerInner key={key} payload={payload} exp={exp} ctx={ctx} />;
}

function ComposerInner({ payload, exp, ctx }) {
  const casId        = payload.casId;
  const rid          = payload.rid || null;           // editing / placeholder-filling
  const date         = payload.date || null;
  const editExisting = payload.existingText || null;  // editing an existing journal
  const isNew        = !rid && !editExisting;         // fresh composition → type selectable
  const expName      = (exp && (exp.name || `Experience ${exp.id}`)) || `Experience ${casId}`;

  const [mode, setMode] = React.useState(payload.mode || "write"); // "write" | "ai"
  const [kind, setKind] = React.useState(payload.kind || "journal");  // journal|final|sa|photos
  const [text, setText]     = React.useState(payload.initialText || "");  // write tab
  const [notes, setNotes]   = React.useState("");                          // ai tab
  const [result, setResult] = React.useState("");                          // pasted or generated
  const { loading, error, run } = useAsyncOp();

  // SA questions — loaded once when the SA type is first selected
  const [saQs, setSaQs]     = React.useState(null);   // null = not loaded
  const [saName, setSaName] = React.useState("");
  const saQ = (saQs || []).find((q) => q.name === saName) || null;

  React.useEffect(() => {
    if (kind !== "sa" || saQs !== null) return;
    run("Loading questions from ManageBac…", async () => {
      const qs = await API.saQuestions(casId);
      setSaQs(qs || []);
      if (qs && qs.length) {
        setSaName(qs[0].name);
        setText(qs[0].answer || "");
        setResult("");
      }
    }).catch(() => setSaQs([]));   // error shown via StatusLine
  }, [kind, saQs, run, casId]);

  function pickSA(name) {
    setSaName(name);
    const q = (saQs || []).find((x) => x.name === name);
    setText((q && q.answer) || "");
    setResult("");
  }

  const aiProvider = (ctx.status && ctx.status.ai_provider) || "prompt";
  const isManual   = aiProvider === "prompt";
  const isPhotos   = kind === "photos";
  const isFile     = kind === "file";
  const isSA       = kind === "sa";
  const isFinal    = isNew && kind === "final";
  const aiKind     = editExisting ? "edit" : (isFinal ? "final" : "reflection");
  const canBuild   = isSA ? !!saQ : (isFinal || !!notes.trim());

  const title =
    isFile       ? `New File · ${expName}` :
    isPhotos     ? `${rid ? "Edit" : "New"} Photos · ${expName}` :
    editExisting ? `Edit Journal · ${expName}` :
    rid          ? `Fill Placeholder · ${expName}${date ? ` · ${date}` : ""}` :
    isSA         ? `Self-Assessment · ${expName}` :
    isFinal      ? `Final Reflection · ${expName}` :
                   `New Journal · ${expName}`;

  // Copied by CopyBtn — the prompt itself is not displayed (nothing to edit
  // there); clicking again rebuilds and re-copies.
  async function buildPrompt() {
    let p;
    await run("Building prompt…", async () => {
      const r = isSA
        ? await API.saPrompt(casId, saQ.question, notes, saQ.answer || null)
        : await API.buildPrompt(casId, notes, aiKind, date, editExisting, isFinal);
      p = r.prompt;
    });
    return p;
  }

  async function generateDirect() {
    await run("Generating with AI…", async () => {
      const r = isSA
        ? await API.saGenerate(casId, saQ.question, notes, saQ.answer || null)
        : await API.generateAI(casId, notes, aiKind, date, editExisting, isFinal);
      setResult(r.result || "");
    });
  }

  async function send(body) {
    if (!body || !body.trim()) return;
    await run("Saving…", async () => {
      if (isSA) {
        // SA answers are plain text boxes — no <p> wrapping.
        await API.saveSA(casId, saName, stripHtml(body).trim());
      } else {
        const html = wrapPlainAsHtml(body);
        if (rid) {
          await API.editJournal(rid, casId, html, null);
        } else {
          await API.createJournal(casId, html, null);
        }
        await ctx.refreshAfterMutation();
      }
      ctx.closeComposer();
    });
  }

  const sendBody = mode === "write" ? text : result;
  const previewHtml = !isSA && mode === "ai" && result.trim() ? wrapPlainAsHtml(result) : "";

  return (
    <div className="mono-rise" style={{
      flexShrink: 0,
      borderTop: "1px solid rgba(0,0,0,0.10)",
      background: "#fafafa",
      maxHeight: "58%",
      display: "flex", flexDirection: "column",
    }}>
      {/* Header — title, type, tabs, close */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "9px 14px 8px",
      }}>
        <I name={isFile ? "file" : isPhotos ? "image" : editExisting ? "edit" : "pen"} size={13} stroke={1.8}
           style={{ color: N.inkMid, flexShrink: 0 }} />
        <span title={title} style={{
          fontSize: 12, fontWeight: 500, color: N.inkDeep,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>{title}</span>

        {isNew && (
          <div style={segStyle}>
            <TabBtn active={kind === "journal"} onClick={() => setKind("journal")}>Journal</TabBtn>
            <TabBtn active={kind === "final"}   onClick={() => setKind("final")}>Final</TabBtn>
            <TabBtn active={kind === "sa"}      onClick={() => setKind("sa")}>SA</TabBtn>
            <TabBtn active={kind === "photos"}  onClick={() => setKind("photos")}>Photos</TabBtn>
            <TabBtn active={kind === "file"}    onClick={() => setKind("file")}>Files</TabBtn>
          </div>
        )}

        {!isPhotos && !isFile && (
          <div style={segStyle}>
            <TabBtn active={mode === "write"} icon="pen" onClick={() => setMode("write")}>Write</TabBtn>
            <TabBtn active={mode === "ai"} icon="sparkle" onClick={() => setMode("ai")}>AI</TabBtn>
          </div>
        )}

        <div style={{ flex: 1 }} />
        <button onClick={ctx.closeComposer} className="mono-close" title="Close composer" style={{
          width: 20, height: 20, borderRadius: "50%", border: "none",
          background: "rgba(0,0,0,0.06)", color: "rgba(20,20,20,0.65)",
          display: "flex", alignItems: "center", justifyContent: "center",
          cursor: "pointer", fontFamily: "inherit", flexShrink: 0,
        }}>
          <I name="close" size={10} stroke={2} />
        </button>
      </div>

      {isPhotos ? (
        <PhotosPane key={`photos-${rid || "new"}`} casId={casId} rid={rid} ctx={ctx} />
      ) : isFile ? (
        <FilesPane key="files-new" casId={casId} ctx={ctx} />
      ) : (
      <React.Fragment>
      {/* Body — keyed so tab/type switches fade in (state lives above, so
          nothing is lost on the DOM swap) */}
      <div key={`${mode}-${kind}`} className="mono-fade"
           style={{ padding: "0 14px", overflow: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
        {/* SA — pick which question is being answered */}
        {isSA && saQs && saQs.length > 0 && (
          <select
            value={saName}
            onChange={(e) => pickSA(e.target.value)}
            style={{
              width: "100%", padding: "6px 9px",
              fontSize: 12, color: N.inkDeep, fontFamily: "inherit",
              background: "#fff", borderRadius: 5,
              border: "1px solid rgba(0,0,0,0.12)", outline: "none",
            }}>
            {saQs.map((q) => (
              <option key={q.name} value={q.name}>
                {(q.answer || "").trim() ? "● " : "○ "}
                {q.question.length > 120 ? q.question.slice(0, 120) + "…" : q.question}
              </option>
            ))}
          </select>
        )}
        {isSA && saQs && !saQs.length && !loading && (
          <div style={{ fontSize: 11.5, color: N.inkSoft, padding: "2px 0" }}>
            No Self-Assessment questions on this experience.
          </div>
        )}

        {mode === "write" ? (
          <div className="mono-box" style={boxStyle}>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={isSA ? "Write your answer here…" : "Write your reflection here…"}
              style={taStyle(150)}
            />
          </div>
        ) : (
          <React.Fragment>
            {/* Two boxes, aligned side by side. Each box's placeholder is the
                hint — no separate label above (that just repeated it). */}
            <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
              <div className="mono-box" style={{ ...boxStyle, flex: 1, minWidth: 0 }}>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder={
                    isSA         ? "What to emphasize (optional)" :
                    editExisting ? "What to change" :
                    isFinal      ? "Themes to emphasize" : "Your notes"
                  }
                  style={taStyle(110)}
                />
              </div>
              <div className="mono-box" style={{ ...boxStyle, flex: 1, minWidth: 0 }}>
                <textarea
                  value={result}
                  onChange={(e) => setResult(e.target.value)}
                  placeholder={isManual
                    ? "Paste the AI's response here"
                    : "The result appears here after Generate"}
                  style={taStyle(110)}
                />
              </div>
            </div>
            {previewHtml && (
              <div style={{
                padding: "9px 12px", background: "#fff", borderRadius: 5,
                fontSize: 12, lineHeight: 1.6, color: N.ink,
                boxShadow: `inset 0 0 0 1px rgba(0,0,0,0.12), inset 3px 0 0 0 ${A.solid}`,
                maxHeight: 120, overflow: "auto",
              }} dangerouslySetInnerHTML={{ __html: previewHtml }} />
            )}
          </React.Fragment>
        )}
      </div>

      {/* Footer — two columns mirror the notes/result boxes above: the AI
          action sits under the notes box (right edge), Cancel + Send under the
          result box. In Write mode there's no AI action, just Cancel + Send. */}
      <div style={{
        display: "flex", gap: 10, alignItems: "center",
        padding: "8px 14px 10px",
      }}>
        <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 8 }}>
          <StatusLine loading={loading} error={error} />
          <div style={{ flex: 1 }} />
          {mode === "ai" && (isManual ? (
            <CopyBtn primary label="Copy prompt" icon="copy"
                     disabled={!!loading || !canBuild}
                     onBefore={buildPrompt} />
          ) : (
            <Btn primary icon="sparkle" onClick={generateDirect}
                 disabled={!!loading || !canBuild}>Generate</Btn>
          ))}
        </div>
        <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center",
                      justifyContent: "flex-end", gap: 8 }}>
          <Btn onClick={ctx.closeComposer} disabled={!!loading}>Cancel</Btn>
          <Btn primary onClick={() => send(sendBody)}
               disabled={!!loading || !sendBody.trim() || (isSA && !saQ)}>
            {isSA ? "Save answer" : rid && !payload.isPlaceholderFill ? "Save to ManageBac" : "Send to ManageBac"}
          </Btn>
        </div>
      </div>
      </React.Fragment>
      )}
    </div>
  );
}

// ── Photos type — new album or edit an existing one, all in the dock ────
function PhotosPane({ casId, rid, ctx }) {
  const editing = !!rid;
  const [existing, setExisting]   = React.useState(editing ? null : []); // null=loading
  const [caption, setCaption]     = React.useState("");
  const [files, setFiles]         = React.useState([]);   // new File[]
  const [dragging, setDragging]   = React.useState(false);
  const fileRef = React.useRef(null);
  const { loading, error, run } = useAsyncOp();

  const reload = React.useCallback(async () => {
    if (!editing) return;
    await run("Loading photos…", async () => {
      const ps = await API.albumPhotos(rid, casId);
      setExisting(ps || []);
    });
  }, [editing, rid, casId, run]);
  React.useEffect(() => { reload(); }, [reload]);

  function addFiles(fs) {
    const imgs = Array.from(fs || []).filter((f) => f.type && f.type.startsWith("image/"));
    if (imgs.length) setFiles((prev) => [...prev, ...imgs]);
  }
  const totalMB = (files.reduce((a, f) => a + (f.size || 0), 0) / 1048576).toFixed(1) + " MB";

  async function deleteExisting(pid) {
    if (!window.confirm("Delete this photo from ManageBac?")) return;
    await run("Deleting…", async () => {
      await API.deletePhoto(rid, pid, casId);
      await reload();
      await ctx.refreshAfterMutation();
    });
  }

  async function submit() {
    if (!files.length) return;
    await run(`Uploading ${files.length} photo${files.length > 1 ? "s" : ""}…`, async () => {
      if (editing) {
        await API.addPhotos(rid, casId, files, caption);
      } else {
        await API.createAlbum(casId, files, files.map(() => caption), null, null);
      }
      await ctx.refreshAfterMutation();
      ctx.closeComposer();
    });
  }

  return (
    <React.Fragment>
      <div className="mono-fade" style={{ padding: "0 14px", overflow: "auto",
             display: "flex", flexDirection: "column", gap: 8 }}>
        {editing && (
          <div>
            <FieldLabel hint={existing ? `${existing.length} photo${existing.length === 1 ? "" : "s"}` : ""}>
              Existing photos
            </FieldLabel>
            <div style={{
              padding: 10, background: "#fff", borderRadius: 5,
              boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.12)",
              minHeight: 40,
            }}>
              {!existing && <div style={{ fontSize: 11, color: N.inkSoft }}>Loading…</div>}
              {existing && !existing.length && <div style={{ fontSize: 11, color: N.inkSoft }}>No photos in this album.</div>}
              {existing && !!existing.length && (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {existing.map((p) => (
                    <div key={p.id} style={{ position: "relative" }}>
                      <PhotoThumb url={p.s3_url} caption={p.caption} w={84} h={62} />
                      <DeleteChip onClick={() => deleteExisting(p.id)} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        <div className="mono-field" style={{
          background: "#fff", borderRadius: 5,
          boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.12)",
        }}>
          <input
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            placeholder={editing ? "Caption for new photos (optional)" : "Caption applied to every photo (optional)"}
            style={{ width: "100%", padding: "8px 11px", border: "none", outline: "none",
                     background: "transparent", fontSize: 12.5, color: N.inkDeep, fontFamily: "inherit" }}
          />
        </div>

        <Dropzone
          files={files}
          dragging={dragging}
          totalSize={totalMB}
          onPick={() => fileRef.current && fileRef.current.click()}
          onDragOver={(e) => { e.preventDefault(); if (!dragging) setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
          onRemove={(i) => setFiles((prev) => prev.filter((_, j) => j !== i))}
        />
        <input ref={fileRef} type="file" accept="image/*" multiple style={{ display: "none" }}
          onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
      </div>

      {/* Footer */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 14px 10px" }}>
        <StatusLine loading={loading} error={error} />
        <div style={{ flex: 1 }} />
        <Btn onClick={ctx.closeComposer} disabled={!!loading}>{editing ? "Done" : "Cancel"}</Btn>
        <Btn primary onClick={submit} disabled={!!loading || !files.length}>
          {files.length ? `${editing ? "Add" : "Upload"} ${files.length}` : (editing ? "Add" : "Upload")}
        </Btn>
      </div>
    </React.Fragment>
  );
}

// ── File type — upload any attachment(s) as a FileEvidence ──────────────
function fmtBytes(b) {
  if (!b && b !== 0) return "";
  if (b < 1024) return b + " B";
  if (b < 1048576) return (b / 1024).toFixed(0) + " KB";
  return (b / 1048576).toFixed(1) + " MB";
}

function FilesPane({ casId, ctx }) {
  const [files, setFiles]       = React.useState([]);
  const [note, setNote]         = React.useState("");
  const [dragging, setDragging] = React.useState(false);
  const fileRef = React.useRef(null);
  const { loading, error, run } = useAsyncOp();

  function addFiles(fs) {
    const arr = Array.from(fs || []);
    if (arr.length) setFiles((prev) => [...prev, ...arr]);
  }
  const totalMB = (files.reduce((a, f) => a + (f.size || 0), 0) / 1048576).toFixed(1) + " MB";

  async function submit() {
    if (!files.length) return;
    await run(`Uploading ${files.length} file${files.length > 1 ? "s" : ""}…`, async () => {
      await API.createFile(casId, files, null, note);
      await ctx.refreshAfterMutation();
      ctx.closeComposer();
    });
  }

  return (
    <React.Fragment>
      <div className="mono-fade" style={{ padding: "0 14px", overflow: "auto",
             display: "flex", flexDirection: "column", gap: 8 }}>
        <div className="mono-field" style={{
          background: "#fff", borderRadius: 5,
          boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.12)",
        }}>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Note (optional)"
            style={{ width: "100%", padding: "8px 11px", border: "none", outline: "none",
                     background: "transparent", fontSize: 12.5, color: N.inkDeep, fontFamily: "inherit" }}
          />
        </div>
        <div
          onDragOver={(e) => { e.preventDefault(); if (!dragging) setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
          onClick={() => !files.length && fileRef.current && fileRef.current.click()}
          style={{
            borderRadius: 5, padding: files.length ? 12 : 24,
            background: dragging ? "rgba(0,0,0,0.045)" : "#fff",
            boxShadow: dragging ? `inset 0 0 0 2px ${A.solid}` : "inset 0 0 0 1px rgba(0,0,0,0.12)",
            backgroundImage: !files.length && !dragging
              ? "repeating-linear-gradient(45deg, transparent 0 6px, rgba(0,0,0,0.035) 6px 12px)"
              : "none",
            cursor: files.length ? "default" : "pointer",
            transition: "all 0.15s",
          }}>
          {files.length ? (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between",
                     alignItems: "center", marginBottom: 8, padding: "0 2px" }}>
                <span style={{ fontSize: 11, fontWeight: 500, color: N.ink }}>
                  {files.length} file{files.length > 1 ? "s" : ""} · {totalMB}
                </span>
                <span onClick={() => fileRef.current && fileRef.current.click()}
                  style={{ fontSize: 10.5, color: N.ink, fontWeight: 500, cursor: "pointer",
                           display: "inline-flex", alignItems: "center", gap: 4,
                           textDecoration: "underline" }}>
                  <I name="upload" size={11} stroke={1.7} /> Add more
                </span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {files.map((f, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 8,
                         padding: "5px 8px", borderRadius: 5, background: "rgba(0,0,0,0.03)" }}>
                    <I name="file" size={13} stroke={1.6} style={{ color: N.inkSoft, flexShrink: 0 }} />
                    <span style={{ fontSize: 12, color: N.inkDeep, flex: 1, minWidth: 0,
                           overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {f.name}
                    </span>
                    <span style={{ fontSize: 10.5, color: N.inkSoft, flexShrink: 0 }}>{fmtBytes(f.size)}</span>
                    <DeleteChip onClick={(e) => { e.stopPropagation(); setFiles((p) => p.filter((_, j) => j !== i)); }} />
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div style={{ textAlign: "center", display: "flex", flexDirection: "column",
                   alignItems: "center", gap: 8 }}>
              <div style={{ width: 42, height: 42, borderRadius: 5,
                     background: dragging ? A.solid : "#fff", color: dragging ? A.onAccent : N.ink,
                     display: "flex", alignItems: "center", justifyContent: "center",
                     boxShadow: dragging ? "none" : "inset 0 0 0 1px rgba(0,0,0,0.12)",
                     transform: dragging ? "scale(1.08)" : "scale(1)", transition: "all 0.15s" }}>
                <I name="file" size={18} stroke={1.6} />
              </div>
              <div style={{ fontSize: 12.5, fontWeight: 500, color: N.inkDeep }}>
                {dragging ? "Drop files to add" : "Drag files here"}
              </div>
              <div style={{ fontSize: 11, color: N.inkSoft }}>
                {dragging ? "Release to upload"
                  : <>or <span style={{ color: N.inkDeep, fontWeight: 500, textDecoration: "underline" }}>browse</span> · any file type</>}
              </div>
            </div>
          )}
        </div>
        <input ref={fileRef} type="file" multiple style={{ display: "none" }}
          onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
      </div>

      {/* Footer */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 14px 10px" }}>
        <StatusLine loading={loading} error={error} />
        <div style={{ flex: 1 }} />
        <Btn onClick={ctx.closeComposer} disabled={!!loading}>Cancel</Btn>
        <Btn primary onClick={submit} disabled={!!loading || !files.length}>
          {files.length ? `Upload ${files.length}` : "Upload"}
        </Btn>
      </div>
    </React.Fragment>
  );
}

window.MonoComposer = Composer;
window.copyTextToClipboard = copyTextToClipboard;
