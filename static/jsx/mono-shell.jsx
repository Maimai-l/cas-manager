// ── Mono shell: sidebar + main panel + reflection rows + base components ─
// Layout model (macOS Notes-like): full-bleed columns joined edge-to-edge
// with 1px separators — no floating panels, no gaps. Containers are square;
// controls (buttons, inputs, chips) keep a small 4–5px radius.
const I = window.I;
const A = window.MONO_ACCENT;
const N = window.MONO_NEUTRALS;
const S = window.MONO_STRAND;

// Warm neutral palette — a paper-white system, not cold gray. Borders and
// fills carry a faint warm tint so the flat surfaces read alive, not ashen.
const BG = {
  sidebar: "#f3f1ec",   // warm paper
  bar:     "#f8f6f1",   // toolbars / docks / footers
  main:    "#fffefc",   // content
  hover:   "rgba(60,48,30,0.05)",
  active:  "rgba(60,48,30,0.09)",
};
const SEP = "1px solid rgba(60,48,30,0.13)";   // warm hairline separator
const R   = 5;                                  // control corner radius
window.MONO_BG = BG;

// Pull the experience's strand list as a canonical-order array of valid keys.
// Falls back to ["activity"] if nothing usable is present so the existing
// icon-rendering code never sees an empty list.
function _strandsOf(exp) {
  const arr = (exp && Array.isArray(exp.strands) ? exp.strands : null)
    || (exp && exp.strand ? [exp.strand] : []);
  const out = [];
  for (const s of arr) {
    const k = String(s || "").toLowerCase();
    if (S[k] && !out.includes(k)) out.push(k);
  }
  return out.length ? out : ["activity"];
}

// Single-strand convenience for the sidebar's left-side icon (where multi-icon
// stacking would be too cramped). Returns the experience's primary strand.
function _primaryStrand(exp) {
  return _strandsOf(exp)[0];
}

// ── Atoms ────────────────────────────────────────────────────────────────
// Kept for API compatibility: plain solid surface now (no blur, no blobs).
function GradientBg({ children }) {
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", background: N.bg }}>
      {children}
    </div>);
}

function Glass({ style, children, blur, ...rest }) {
  return (
    <div style={{ background: "#fff", ...style }} {...rest}>{children}</div>);
}

function Pill({ children, accent, style }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      fontSize: 10.5, fontWeight: 500,
      padding: "2px 8px", borderRadius: 4,
      background: accent ? A.solid : N.chipBg,
      color: accent ? A.onAccent : N.inkMid,
      whiteSpace: "nowrap", flexShrink: 0,
      ...style
    }}>{children}</span>);
}

// Accepts either:
//   strand:  "activity"             (single strand, legacy)
//   strands: ["creativity","activity"]  (canonical-order array)
// Anchored: never wraps, never shrinks — stays where it's put.
function StrandTag({ strand, strands, compact, style }) {
  const list = (strands && strands.length)
    ? strands.filter((s) => S[s])
    : (strand && S[strand] ? [strand] : []);
  if (list.length === 0) return null;

  const tooltip = list.map((s) => S[s].label).join(" · ");

  if (compact) {
    return (
      <span title={tooltip} style={{
        height: 20, padding: list.length > 1 ? "0 5px" : 0,
        minWidth: 20, borderRadius: 4,
        background: N.chipBg, color: N.ink,
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        gap: 3,
        flexShrink: 0, ...style
      }}>
        {list.map((s) => <I key={s} name={S[s].icon} size={11} stroke={1.7} />)}
      </span>);
  }
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      fontSize: 11, fontWeight: 500,
      padding: "2.5px 9px 2.5px 7px", borderRadius: 4,
      background: N.chipBg, color: N.ink,
      whiteSpace: "nowrap", flexShrink: 0,
      ...style
    }}>
      {list.map((s) => <I key={s} name={S[s].icon} size={11} stroke={1.7} />)}
      {list.map((s) => S[s].label).join(" · ")}
    </span>);
}

// Buttons — macOS-like: small radius, solid fills, hairline border.
function Btn({ children, primary, ghost, icon, iconRight, onClick, style, title, disabled }) {
  const base = {
    padding: "5px 12px", borderRadius: R, border: "none",
    fontSize: 11.5, fontWeight: 500,
    cursor: disabled ? "default" : "pointer",
    opacity: disabled ? 0.5 : 1,
    display: "inline-flex", alignItems: "center", gap: 5,
    whiteSpace: "nowrap", flexShrink: 0,
    fontFamily: "inherit"
  };
  let look = {};
  if (primary) {
    look = { background: A.solid, color: A.onAccent };
  } else if (ghost) {
    look = { background: "transparent", color: N.ink };
  } else {
    look = {
      background: "#fff", color: N.ink,
      boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.12)"
    };
  }
  return (
    <button
      title={title}
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      style={{ ...base, ...look, ...style }}>
      {icon && <I name={icon} size={12} stroke={1.7} />}
      {children}
      {iconRight && <I name={iconRight} size={12} stroke={1.7} />}
    </button>);
}

// Real photo thumb — img with onError fallback that triggers a sync
function PhotoThumb({ url, caption, w = 88, h = 64, onLoadError }) {
  const [errored, setErrored] = React.useState(false);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{
        width: w, height: h, borderRadius: R,
        background: "linear-gradient(135deg,#3a3a3a,#1a1a1a)",
        position: "relative", overflow: "hidden",
      }}>
        {url && !errored ? (
          <img
            src={url}
            alt={caption || ""}
            style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
            onError={() => { setErrored(true); if (onLoadError) onLoadError(); }}
          />
        ) : (
          <div style={{
            position: "absolute", inset: 0,
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "rgba(255,255,255,0.45)"
          }}>
            <I name="image" size={20} stroke={1.5} />
          </div>
        )}
      </div>
      {caption &&
        <div style={{
          fontSize: 9.5, color: N.inkMid, textAlign: "center",
          maxWidth: w, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"
        }}>{caption}</div>
      }
    </div>);
}

// Legacy MonoPhoto (sketch-style) kept for modal previews of in-memory selections
function MonoPhoto({ caption, idx, w = 88, h = 64 }) {
  const tints = ["#3a3a3a", "#535353", "#6a6a6a", "#828282"];
  const tint = tints[idx % tints.length];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{
        width: w, height: h, borderRadius: R,
        background: `linear-gradient(135deg, ${tint} 0%, ${tint}99 100%)`,
        position: "relative", overflow: "hidden",
      }}>
        <div style={{
          position: "absolute", left: 0, right: 0, bottom: 0, height: "45%",
          background: "rgba(0,0,0,0.18)",
          clipPath: "polygon(0 60%, 18% 30%, 35% 55%, 58% 20%, 78% 45%, 100% 30%, 100% 100%, 0 100%)"
        }} />
        <div style={{
          position: "absolute", top: "20%", right: "18%",
          width: 14, height: 14, borderRadius: "50%",
          background: "rgba(255,255,255,0.55)"
        }} />
      </div>
      {caption &&
        <div style={{
          fontSize: 9.5, color: N.inkMid, textAlign: "center",
          maxWidth: w, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"
        }}>{caption}</div>
      }
    </div>);
}

// ── Sidebar ──────────────────────────────────────────────────────────────
function Sidebar({ experiences, activeId, onSelect, syncState }) {
  const [query, setQuery] = React.useState("");
  const q = query.trim().toLowerCase();
  const filtered = q
    ? experiences.filter((e) => (e.name || "").toLowerCase().includes(q))
    : experiences;
  const active    = filtered.filter((e) => !e.is_completed && !e.is_deleted);
  const completed = filtered.filter((e) =>  e.is_completed && !e.is_deleted);
  const deleted   = filtered.filter((e) =>  e.is_deleted);
  return (
    <div style={{
      width: 230, flexShrink: 0,
      background: BG.sidebar,
      borderRight: SEP,
      display: "flex", flexDirection: "column", overflow: "hidden"
    }}>
      {/* 42px header — aligns with the main toolbar + hub header so the top
          separator is one continuous line across all three columns */}
      <div style={{
        height: 42, flexShrink: 0, boxSizing: "border-box",
        padding: "0 10px", display: "flex", alignItems: "center",
        borderBottom: SEP,
      }}>
        <div style={{
          flex: 1, display: "flex", alignItems: "center", gap: 6,
          height: 26, padding: "0 8px",
          background: "rgba(60,48,30,0.06)",
          borderRadius: R + 1,
          fontSize: 11.5,
        }}>
          <I name="search" size={12} stroke={1.8} style={{ color: N.inkSoft }} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search"
            style={{
              flex: 1, minWidth: 0,
              border: "none", outline: "none", background: "transparent",
              fontSize: 11.5, color: N.inkDeep, fontFamily: "inherit"
            }}
          />
        </div>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "4px 0 10px" }}>
        {active.map((e) =>
          <SidebarItem key={e.id} exp={e} active={e.id === activeId} onClick={() => onSelect(e.id)} />
        )}
        {!active.length && !q && (
          <div style={{ padding: "12px 14px", fontSize: 11, color: N.inkSoft, lineHeight: 1.5 }}>
            {syncState === "syncing" ? "Syncing experiences…" : "No experiences yet."}
          </div>
        )}
        {completed.length > 0 && <SectionLabel>Completed</SectionLabel>}
        {completed.map((e) =>
          <SidebarItem key={e.id} exp={e} active={e.id === activeId} onClick={() => onSelect(e.id)} />
        )}
        {deleted.length > 0 && <SectionLabel danger>Deleted</SectionLabel>}
        {deleted.map((e) =>
          <SidebarItem key={e.id} exp={e} active={e.id === activeId} onClick={() => onSelect(e.id)} />
        )}
      </div>
    </div>);
}

function SectionLabel({ children, danger }) {
  return (
    <div style={{
      padding: "12px 14px 5px", marginTop: 4,
      borderTop: SEP,
      fontSize: 10.5, color: danger ? "#a4332e" : N.inkSoft,
    }}>{children}</div>);
}

function SidebarItem({ exp, active, onClick }) {
  const strands  = _strandsOf(exp);
  const primary  = strands[0];
  const meta     = S[primary];
  // Multi-strand: "Creativity · Activity"; single: "Activity"
  const strandLabel = strands.map((s) => S[s].label).join(" · ");
  const isDeleted = !!exp.is_deleted;
  const subline =
    isDeleted ? `${strandLabel} · removed`
              : strandLabel + (exp.is_completed ? " · done" : "");
  return (
    <div
      className={active ? "mono-sb-item active" : "mono-sb-item"}
      onClick={onClick}
      title={isDeleted ? "Not seen in the latest ManageBac sync" : undefined}
      style={{
        display: "flex", alignItems: "center", gap: 9,
        padding: "8px 12px", cursor: "pointer",
        background: active ? BG.active : "transparent",
        boxShadow: active ? ("inset 2px 0 0 0 " + A.solid) : "none",
        opacity: isDeleted ? 0.5 : 1,
        transition: "background 0.12s, opacity 0.12s"
      }}>
      <I name={meta.icon} size={13} stroke={1.7} style={{ color: N.inkMid, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 12.5, fontWeight: 500,
          color: N.inkDeep,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          textDecoration: isDeleted ? "line-through" : "none",
        }}>{exp.name || `Experience ${exp.id}`}</div>
        <div style={{ fontSize: 10, color: N.inkSoft, marginTop: 1,
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {subline}
        </div>
      </div>
      <span className="tnum" style={{
        fontSize: 10.5, color: N.inkSoft,
        width: 22, textAlign: "right", flexShrink: 0
      }}>{exp.reflection_count || 0}</span>
    </div>);
}

// ── Toolbar — a real in-flow bar at the top of the main column ───────────
const _TOOLBAR_BTN_STYLE = {
  width: 26, height: 26, borderRadius: R,
  border: "none", background: "transparent",
  color: "rgba(20,20,20,0.6)", cursor: "pointer",
  display: "flex", alignItems: "center", justifyContent: "center",
  flexShrink: 0,
  fontFamily: "inherit",
  transition: "background 0.12s, color 0.12s"
};

function Toolbar({ dotKind, onOpenSettings, children }) {
  const dotColor =
    dotKind === "green"  ? "#8bc34a" :
    dotKind === "yellow" ? "#e7c64a" : "#d8504a";
  const dotLabel =
    dotKind === "green"  ? "Online" :
    dotKind === "yellow" ? "Syncing" : "Offline";
  return (
    <div style={{
      height: 42, flexShrink: 0,
      display: "flex", alignItems: "center", gap: 8,
      padding: "0 14px",
      borderBottom: SEP,
      background: BG.bar,
    }}>
      <span
        title={`Status: ${dotLabel}`}
        style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          fontSize: 11, color: N.inkMid, flexShrink: 0,
        }}>
        <span style={{
          width: 8, height: 8, borderRadius: "50%",
          background: dotColor,
        }} />
        {dotLabel}
      </span>
      <div style={{ flex: 1 }} />
      {children}
      <button
        title="Settings"
        onClick={onOpenSettings}
        className="mono-tray"
        style={_TOOLBAR_BTN_STYLE}>
        <I name="settings" size={15} stroke={1.7} />
      </button>
    </div>
  );
}

// ── Main panel ──────────────────────────────────────────────────────────
function MainPanel({
  activeExp, reflections, reflLoading,
  onOpenJournal, onOpenPhotos, onEditRefl, onSyncOne,
  onOpenSettings, onOpenPlaceholders, pendingCount,
  dangerZone, onDeleteRefl, appState, dotKind
}) {
  const frame = {
    flex: 1, minWidth: 0,
    background: BG.main,
    display: "flex", flexDirection: "column", overflow: "hidden",
  };

  if (appState === "unauthed") {
    return (
      <div style={frame}>
        <Toolbar dotKind={dotKind} onOpenSettings={onOpenSettings} />
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ textAlign: "center", maxWidth: 360, color: N.inkMid, padding: 24 }}>
            <div style={{ fontSize: 15, fontWeight: 500, color: N.inkDeep, marginBottom: 6 }}>Not logged into ManageBac</div>
            <div style={{ fontSize: 12, lineHeight: 1.55 }}>
              Open Settings (⚙ top right) → Account, enter your ManageBac credentials, and your data will sync.
            </div>
          </div>
        </div>
      </div>
    );
  }
  if (!activeExp) {
    return (
      <div style={frame}>
        <Toolbar dotKind={dotKind} onOpenSettings={onOpenSettings} />
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
                      color: N.inkSoft, fontSize: 12 }}>
          {reflLoading ? "Loading…" : "Select an experience from the sidebar."}
        </div>
      </div>
    );
  }
  const strands = _strandsOf(activeExp);
  const los     = activeExp.lo_display || [];
  return (
    <div style={frame}>
      <Toolbar dotKind={dotKind} onOpenSettings={onOpenSettings}>
        {activeExp.is_completed ? (
          <Pill>
            <I name="check" size={11} stroke={2} />
            Completed · read-only
          </Pill>
        ) : (
          <React.Fragment>
            <Btn icon="pen"   onClick={onOpenJournal}>+ New Entry</Btn>
            <Btn icon="image" onClick={onOpenPhotos}>+ New Photo</Btn>
          </React.Fragment>
        )}
      </Toolbar>

      {/* Header — title, then one anchored meta line (never wraps) */}
      <div style={{
        padding: "14px 22px 12px",
        borderBottom: SEP,
        background: BG.main,
        flexShrink: 0,
      }}>
        <h2 style={{
          margin: 0, fontSize: 20, fontWeight: 500, letterSpacing: -0.3,
          color: N.inkDeep,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>
          {activeExp.name || `Experience ${activeExp.id}`}
        </h2>
        <div style={{
          marginTop: 7,
          display: "flex", alignItems: "center", gap: 6,
          whiteSpace: "nowrap", overflow: "hidden",
        }}>
          <StrandTag strands={strands} />
          <span style={{ fontSize: 11, color: N.inkSoft, flexShrink: 0 }}>
            · {activeExp.reflection_count || 0} reflections
          </span>
          {los.map((lo) =>
            <span key={lo} style={{
              fontSize: 10.5, padding: "2.5px 8px", borderRadius: 4,
              background: "rgba(0,0,0,0.04)", color: N.inkMid,
              whiteSpace: "nowrap", flexShrink: 0,
            }}>{lo}</span>
          )}
        </div>
      </div>

      {/* Reflection rows — flat, joined with hairlines (no floating cards).
          Keyed by experience so switching fades the new list in (and resets
          scroll to the top). */}
      <div key={activeExp.id} className="mono-fade" style={{ flex: 1, overflow: "auto" }}>
        {reflLoading ? (
          <div style={{ color: N.inkSoft, fontSize: 11, padding: "12px 22px" }}>Loading reflections…</div>
        ) : null}
        {(!reflLoading && !reflections.length) ? (
          <div style={{ color: N.inkSoft, fontSize: 12, padding: 32, textAlign: "center" }}>
            No reflections yet. Use <b>+ New Journal</b> or <b>+ New Photo</b> above to add the first one.
          </div>
        ) : null}
        {reflections.map((r) =>
          <ReflRow
            key={r.id}
            refl={r}
            casId={activeExp.id}
            onEdit={() => onEditRefl(r)}
            dangerZone={dangerZone}
            onDelete={() => onDeleteRefl(r)}
            onPhotoError={() => onSyncOne(activeExp.id)}
          />
        )}
      </div>

      {/* Flat, non-modal journal workbench — replaces the old modal chain */}
      <window.MonoComposer />
    </div>);
}

// Small fixed-width action button for reflection rows: the label swap
// (Copy → Copied) must not shift its neighbours.
function RowBtn({ icon, label, onClick, danger, title, width = 62 }) {
  return (
    <button
      className="mono-refl-edit"
      onClick={onClick}
      title={title}
      style={{
        fontSize: 10.5, height: 22, width, borderRadius: R - 1,
        background: danger ? "rgba(216,80,74,0.1)" : "rgba(0,0,0,0.04)",
        border: "none",
        color: danger ? "#a4332e" : N.ink,
        cursor: "pointer",
        display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 4,
        whiteSpace: "nowrap", flexShrink: 0,
        fontFamily: "inherit",
        transition: "background 0.15s"
      }}>
      <I name={icon} size={10} stroke={1.8} /> {label}
    </button>);
}

function ReflRow({ refl, casId, onEdit, dangerZone, onDelete, onPhotoError }) {
  const isAlbum  = refl.kind === "album";
  const photos   = refl.photo_list || [];
  const dateStr  = refl.date_iso || refl.group_date || "";
  const subline  = isAlbum
    ? `Photos · ${photos.length}`
    : (refl.kind === "journal" ? "Journal entry" : (refl.kind || "entry"));
  const editable = refl.kind === "journal" || refl.kind === "album";
  const copyable = !isAlbum && !!(refl.body_text || refl.body_html);
  const [copied, setCopied] = React.useState(null); // null | "ok" | "fail"

  async function copyBody() {
    const text = refl.body_text
      || (() => { const d = document.createElement("div"); d.innerHTML = refl.body_html || ""; return d.textContent || ""; })();
    const ok = await window.copyTextToClipboard(text);
    setCopied(ok ? "ok" : "fail");
    setTimeout(() => setCopied(null), 1600);
  }

  return (
    <div className="mono-refl-card" style={{
      borderBottom: SEP,
      opacity: refl.is_placeholder ? 0.85 : 1,
      position: "relative",
      transition: "background 0.15s"
    }}>
      {refl.is_placeholder ? (
        <div style={{
          position: "absolute", top: 0, bottom: 0, left: 0, width: 3,
          background: A.solid
        }} />
      ) : null}
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 22px 6px" }}>
        <I name={isAlbum ? "image" : "pen"} size={13} stroke={1.6}
           style={{ color: N.inkSoft, flexShrink: 0 }} />
        <span className="tnum" style={{ fontSize: 12, fontWeight: 500, color: N.inkDeep, flexShrink: 0 }}>
          {dateStr || "—"}
        </span>
        <span style={{ fontSize: 10.5, color: N.inkSoft, flexShrink: 0 }}>{subline}</span>
        {refl.is_placeholder ? <Pill accent>Placeholder</Pill> : null}
        <div style={{ flex: 1 }} />
        {copyable && (
          <RowBtn
            icon={copied === "ok" ? "check" : "copy"}
            label={copied === "ok" ? "Copied" : copied === "fail" ? "Failed" : "Copy"}
            danger={copied === "fail"}
            title="Copy reflection text — e.g. to feed an AI chat"
            onClick={copyBody}
          />
        )}
        {editable && <RowBtn icon="pen" label="Edit" onClick={onEdit} width={54} />}
        {dangerZone && (
          <RowBtn icon="trash" label="Delete" danger width={64}
                  title="Delete reflection (Danger Zone)" onClick={onDelete} />
        )}
      </div>
      {isAlbum ? (
        photos.length ? (
          <div style={{ padding: "4px 22px 12px", display: "flex", gap: 8, flexWrap: "wrap" }}>
            {photos.map((p) =>
              <PhotoThumb
                key={p.id}
                url={p.s3_url || p.url}
                caption={p.caption}
                onLoadError={onPhotoError}
              />
            )}
          </div>
        ) : (
          <div style={{ padding: "0 22px 10px", fontSize: 11.5, color: N.inkSoft, fontStyle: "italic" }}>
            (empty album — try Sync)
          </div>
        )
      ) : (
        refl.body_html ? (
          <div style={{
            padding: "0 22px 10px", fontSize: 12.5, lineHeight: 1.6,
            color: N.ink
          }} dangerouslySetInnerHTML={{ __html: refl.body_html }} />
        ) : (
          <div style={{ padding: "0 22px 10px", fontSize: 11.5, color: N.inkSoft, fontStyle: "italic" }}>
            (no body — try Sync)
          </div>
        )
      )}
    </div>);
}

// ── Top-level shell ─────────────────────────────────────────────────────
function AppShell(props) {
  const ctx = React.useContext(window.MonoCtx);
  const dangerZone = !!(ctx.config && ctx.config.danger_zone_enabled);
  const onDeleteRefl = React.useCallback(async (r) => {
    if (!window.confirm(`Are you sure you want to delete this reflection? (rid=${r.id})\nThis action cannot be undone.`)) return;
    try {
      await window.API.deleteRefl(r.id, props.activeId);
      await ctx.refreshAfterMutation();
    } catch (e) {
      alert("Delete failed:" + (e.message || e));
    }
  }, [ctx, props.activeId]);
  return (
    <div style={{
      width: "100%", height: "100%",
      display: "flex", alignItems: "stretch",
      overflow: "hidden",
      background: BG.main
    }}>
      <Sidebar
        experiences={props.experiences}
        activeId={props.activeId}
        onSelect={props.onSelect}
        syncState={ctx.syncState}
      />
      <MainPanel
        activeExp={props.activeExp}
        reflections={props.reflections}
        reflLoading={props.reflLoading}
        onOpenJournal={props.onOpenJournal}
        onOpenPhotos={props.onOpenPhotos}
        onEditRefl={props.onEditRefl}
        onSyncOne={ctx.syncOne}
        onOpenSettings={props.onOpenSettings}
        onOpenPlaceholders={props.onOpenPlaceholders}
        pendingCount={props.pendingCount}
        dotKind={props.dotKind}
        dangerZone={dangerZone}
        onDeleteRefl={onDeleteRefl}
        appState={props.appState}
      />
      {/* Placeholder Hub — permanent rail strip, expands into a panel */}
      <window.MonoPlaceholderPanel />
    </div>);
}

window.MonoAppShell = AppShell;
window.MonoBtn = Btn;
window.MonoPill = Pill;
window.MonoStrandTag = StrandTag;
window.MonoPhoto = MonoPhoto;
window.MonoPhotoThumb = PhotoThumb;
window.MonoGlass = Glass;
window.MONO_SEP = SEP;
window.MONO_R = R;
