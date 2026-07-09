// ── Mono shell: sidebar + main panel + reflection card + base components ─
const I = window.I;
const A = window.MONO_ACCENT;
const N = window.MONO_NEUTRALS;
const S = window.MONO_STRAND;

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
function GradientBg({ children }) {
  return (
    <div style={{
      position: "absolute", inset: 0, overflow: "hidden",
      background: N.bg
    }}>
      <div style={{
        position: "absolute", top: "-20%", left: "-15%",
        width: 600, height: 600, borderRadius: "50%",
        background: "radial-gradient(circle, rgba(0,0,0,0.04) 0%, transparent 65%)",
        filter: "blur(40px)"
      }} />
      <div style={{
        position: "absolute", top: "5%", right: "-10%",
        width: 540, height: 540, borderRadius: "50%",
        background: "radial-gradient(circle, rgba(177,226,69,0.12) 0%, transparent 65%)",
        filter: "blur(40px)"
      }} />
      <div style={{
        position: "absolute", bottom: "-20%", left: "20%",
        width: 480, height: 480, borderRadius: "50%",
        background: "radial-gradient(circle, rgba(0,0,0,0.035) 0%, transparent 65%)",
        filter: "blur(40px)"
      }} />
      {children}
    </div>);
}

function Glass({ style, children, blur = 38, ...rest }) {
  return (
    <div style={{
      background: N.glass,
      backdropFilter: `blur(${blur}px) saturate(180%)`,
      WebkitBackdropFilter: `blur(${blur}px) saturate(180%)`,
      boxShadow: "inset 0 0 0 0.5px rgba(255,255,255,0.7), inset 0 0 0 0.5px rgba(0,0,0,0.04)",
      ...style
    }} {...rest}>{children}</div>);
}

function Pill({ children, accent, style }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      fontSize: 10.5, fontWeight: 500,
      padding: "2px 8px", borderRadius: 99,
      background: accent ? A.solid : N.chipBg,
      color: accent ? A.onAccent : N.inkMid,
      whiteSpace: "nowrap",
      ...style
    }}>{children}</span>);
}

// Accepts either:
//   strand:  "activity"             (single strand, legacy)
//   strands: ["creativity","activity"]  (canonical-order array)
// Renders one icon + one label for single-strand, or stacked icons +
// "Creativity · Activity" label for multi-strand. No new icons added —
// just reuses the 3 existing strand glyphs.
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
        minWidth: 20, borderRadius: 6,
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
      padding: "2.5px 9px 2.5px 7px", borderRadius: 99,
      background: N.chipBg, color: N.ink,
      ...style
    }}>
      {list.map((s) => <I key={s} name={S[s].icon} size={11} stroke={1.7} />)}
      {list.map((s) => S[s].label).join(" · ")}
    </span>);
}

// Buttons — primary = solid accent, secondary = white glass, ghost = transparent.
function Btn({ children, primary, ghost, icon, iconRight, onClick, style, title, disabled }) {
  const base = {
    padding: "5px 12px", borderRadius: 7, border: "none",
    fontSize: 11.5, fontWeight: 500,
    cursor: disabled ? "default" : "pointer",
    opacity: disabled ? 0.5 : 1,
    display: "inline-flex", alignItems: "center", gap: 5,
    fontFamily: "inherit"
  };
  let look = {};
  if (primary) {
    look = {
      background: A.solid, color: A.onAccent,
      fontWeight: 600, boxShadow: A.shadow
    };
  } else if (ghost) {
    look = {
      background: "transparent", color: N.ink
    };
  } else {
    look = {
      background: "rgba(255,255,255,0.85)", color: N.ink,
      boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.08)"
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
        width: w, height: h, borderRadius: 8,
        background: "linear-gradient(135deg,#3a3a3a,#1a1a1a)",
        position: "relative", overflow: "hidden",
        boxShadow: "inset 0 0 0 0.5px rgba(255,255,255,0.15)"
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
        width: w, height: h, borderRadius: 8,
        background: `linear-gradient(135deg, ${tint} 0%, ${tint}99 100%)`,
        position: "relative", overflow: "hidden",
        boxShadow: "inset 0 0 0 0.5px rgba(255,255,255,0.15)"
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
    <Glass style={{
      width: 240, borderRadius: 14,
      display: "flex", flexDirection: "column", overflow: "hidden"
    }}>
      <div style={{ padding: "12px 14px 6px" }}>
        <div style={{
          fontSize: 10, fontWeight: 700,
          letterSpacing: 0.6, textTransform: "uppercase",
          color: N.inkSoft
        }}>Experiences</div>
        <div style={{
          marginTop: 8, display: "flex", alignItems: "center", gap: 6,
          height: 26, padding: "0 9px",
          background: "rgba(255,255,255,0.75)",
          borderRadius: 7,
          fontSize: 11.5,
          boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.06)"
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

      <div style={{ flex: 1, overflowY: "auto", padding: "8px 0 10px" }}>
        {active.map((e) =>
          <SidebarItem key={e.id} exp={e} active={e.id === activeId} onClick={() => onSelect(e.id)} />
        )}
        {!active.length && !q && (
          <div style={{ padding: "12px 14px", fontSize: 11, color: N.inkSoft, lineHeight: 1.5 }}>
            {syncState === "syncing" ? "Syncing experiences…" : "No experiences yet."}
          </div>
        )}
        {completed.length > 0 && (
          <div style={{
            padding: "12px 16px 4px", fontSize: 10,
            fontWeight: 700, color: N.inkSoft,
            letterSpacing: 0.6, textTransform: "uppercase"
          }}>Completed</div>
        )}
        {completed.map((e) =>
          <SidebarItem key={e.id} exp={e} active={e.id === activeId} onClick={() => onSelect(e.id)} />
        )}
        {deleted.length > 0 && (
          <div style={{
            padding: "12px 16px 4px", fontSize: 10,
            fontWeight: 700, color: "#a4332e",
            letterSpacing: 0.6, textTransform: "uppercase"
          }}>Deleted</div>
        )}
        {deleted.map((e) =>
          <SidebarItem key={e.id} exp={e} active={e.id === activeId} onClick={() => onSelect(e.id)} />
        )}
      </div>
    </Glass>);
}

// Top-right toolbar (Online pill, sync icon, tray, settings)
const _TOOLBAR_BTN_STYLE = {
  width: 28, height: 28, borderRadius: 7,
  border: "none", background: "rgba(255,255,255,0.6)",
  color: "rgba(20,20,20,0.6)", cursor: "pointer",
  display: "flex", alignItems: "center", justifyContent: "center",
  boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.06)",
  fontFamily: "inherit",
  transition: "background 0.12s, color 0.12s"
};

function TopRightToolbar({ dotKind, pendingCount, onOpenPlaceholders, onOpenSettings }) {
  const ctx = React.useContext(window.MonoCtx);
  const hubOpen = !!ctx.hubOpen;
  const dotColor =
    dotKind === "green"  ? "#b1e245" :
    dotKind === "yellow" ? "#e7c64a" : "#d8504a";
  const dotLabel =
    dotKind === "green"  ? "Online" :
    dotKind === "yellow" ? "Syncing" : "Offline";
  const dotGlow =
    dotKind === "green"  ? "0 0 0 2px rgba(177,226,69,0.28), inset 0 0 0 0.5px rgba(255,255,255,0.4)" :
    dotKind === "yellow" ? "0 0 0 2px rgba(231,198,74,0.28), inset 0 0 0 0.5px rgba(255,255,255,0.4)" :
                           "0 0 0 2px rgba(216,80,74,0.28),  inset 0 0 0 0.5px rgba(255,255,255,0.4)";
  return (
    <div style={{
      position: "absolute", top: 14, right: 18, zIndex: 4,
      display: "flex", alignItems: "center", gap: 10
    }}>
      <span
        title={`Status: ${dotLabel}`}
        style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          height: 28, padding: "0 12px 0 10px", borderRadius: 99,
          background: "rgba(255,255,255,0.7)",
          boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.07)",
          fontSize: 11, fontWeight: 600, color: N.ink,
          letterSpacing: 0.1, lineHeight: 1,
        }}>
        <span style={{
          width: 8, height: 8, borderRadius: "50%",
          background: dotColor,
          boxShadow: dotGlow
        }} />
        {dotLabel}
      </span>
      <button
        title={`Placeholders${pendingCount ? ` · ${pendingCount} pending` : ""} — ${hubOpen ? "hide" : "show"} panel`}
        onClick={onOpenPlaceholders}
        style={{
          ..._TOOLBAR_BTN_STYLE, position: "relative",
          ...(hubOpen ? {
            background: "rgba(255,255,255,0.95)",
            color: "rgba(20,20,20,0.85)",
            boxShadow: "inset 0 0 0 1px rgba(20,20,20,0.35)",
          } : {}),
        }}>
        <I name="tray" size={15} stroke={1.7} />
        {pendingCount > 0 ? (
          <span style={{
            position: "absolute", top: 1, right: 1,
            width: 7, height: 7, borderRadius: "50%",
            background: A.solid,
            boxShadow: "0 0 0 1.5px rgba(255,255,255,0.95)"
          }} />
        ) : null}
      </button>
      <button
        title="Settings"
        onClick={onOpenSettings}
        style={_TOOLBAR_BTN_STYLE}>
        <I name="settings" size={15} stroke={1.7} />
      </button>
    </div>
  );
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
        display: "flex", alignItems: "center", gap: 10,
        padding: "7px 10px 7px 11px", borderRadius: 7,
        margin: "1px 8px", cursor: "pointer",
        background: active ? "rgba(255,255,255,0.85)" : "transparent",
        boxShadow: active ? "inset 0 0 0 0.5px rgba(0,0,0,0.07), inset 3px 0 0 0 " + A.solid : "none",
        opacity: isDeleted ? 0.5 : 1,
        position: "relative",
        transition: "background 0.12s, opacity 0.12s"
      }}>
      <I name={meta.icon} size={13} stroke={1.7} style={{ color: N.inkMid, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 12.5, fontWeight: active ? 600 : 500,
          color: N.inkDeep,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          textDecoration: isDeleted ? "line-through" : "none",
        }}>{exp.name || `Experience ${exp.id}`}</div>
        <div style={{ fontSize: 10, color: N.inkSoft, marginTop: 1 }}>
          {subline}
        </div>
      </div>
      <span className="tnum" style={{
        fontSize: 10.5, padding: "1px 0", borderRadius: 99,
        background: N.chipBg, color: N.inkMid,
        fontWeight: 500,
        width: 26, textAlign: "center", flexShrink: 0
      }}>{exp.reflection_count || 0}</span>
    </div>);
}

// ── Main panel ──────────────────────────────────────────────────────────
function MainPanel({
  activeExp, reflections, reflLoading,
  onOpenJournal, onOpenPhotos, onEditRefl, onSyncOne,
  onOpenSettings, onOpenPlaceholders, pendingCount,
  dangerZone, onDeleteRefl, appState, dotKind
}) {
  const toolbar = (
    <TopRightToolbar
      dotKind={dotKind}
      pendingCount={pendingCount}
      onOpenPlaceholders={onOpenPlaceholders}
      onOpenSettings={onOpenSettings}
    />
  );

  if (appState === "unauthed") {
    return (
      <Glass style={{
        flex: 1, borderRadius: 14, overflow: "hidden", position: "relative",
        display: "flex", alignItems: "center", justifyContent: "center"
      }}>
        {toolbar}
        <div style={{ textAlign: "center", maxWidth: 360, color: N.inkMid, padding: 24 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: N.inkDeep, marginBottom: 6 }}>Not logged into ManageBac</div>
          <div style={{ fontSize: 12, lineHeight: 1.55 }}>
            Click the ⚙ in the top-right corner to open Settings, Account, enter your ManageBac credentials, and then data can be synced.
          </div>
        </div>
      </Glass>
    );
  }
  if (!activeExp) {
    return (
      <Glass style={{
        flex: 1, borderRadius: 14, overflow: "hidden", position: "relative",
        display: "flex", alignItems: "center", justifyContent: "center"
      }}>
        {toolbar}
        <div style={{ textAlign: "center", color: N.inkSoft, fontSize: 12 }}>
          {reflLoading ? "Loading…" : "Select an experience from the sidebar."}
        </div>
      </Glass>
    );
  }
  const strands = _strandsOf(activeExp);
  const los     = activeExp.lo_display || [];
  return (
    <Glass style={{
      flex: 1, borderRadius: 14, overflow: "hidden",
      display: "flex", flexDirection: "column", position: "relative"
    }}>
      {toolbar}
      <div style={{
        padding: "16px 22px 14px",
        borderBottom: "0.5px solid " + N.hairline,
        display: "flex", alignItems: "flex-end", gap: 14
      }}>
        {/* paddingRight reserves room for the absolute-positioned toolbar */}
        <div style={{ flex: 1, minWidth: 0, paddingRight: 200 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <StrandTag strands={strands} />
            <span style={{ fontSize: 11, color: N.inkSoft }}>· {activeExp.reflection_count || 0} reflections</span>
          </div>
          <h2 style={{ margin: "6px 0 0", fontSize: 22, fontWeight: 700, letterSpacing: -0.4, color: N.inkDeep }}>
            {activeExp.name || `Experience ${activeExp.id}`}
          </h2>
          <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
            {los.map((lo) =>
              <span key={lo} style={{
                fontSize: 10.5, padding: "2px 8px", borderRadius: 99,
                background: "rgba(0,0,0,0.04)", color: N.inkMid
              }}>{lo}</span>
            )}
          </div>
        </div>
        {/* Action buttons — hidden for completed experiences (ManageBac
            rejects new reflections on locked CAS activities). A muted
            "Completed" pill takes their place so the user still knows why. */}
        {activeExp.is_completed ? (
          <div style={{ alignSelf: "flex-end" }}>
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              fontSize: 11, fontWeight: 500,
              padding: "4px 10px", borderRadius: 99,
              background: "rgba(0,0,0,0.05)", color: N.inkMid,
            }}>
              <I name="check" size={11} stroke={2} />
              Completed · read-only
            </span>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 8, alignSelf: "flex-end" }}>
            <Btn icon="pen"   onClick={onOpenJournal}>+ New Journal</Btn>
            <Btn icon="image" onClick={onOpenPhotos}>+ New Photo</Btn>
          </div>
        )}
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: "16px 22px", display: "flex", flexDirection: "column", gap: 10 }}>
        {reflLoading ? (
          <div style={{ color: N.inkSoft, fontSize: 11, padding: 8 }}>Loading reflections…</div>
        ) : null}
        {(!reflLoading && !reflections.length) ? (
          <div style={{ color: N.inkSoft, fontSize: 12, padding: 24, textAlign: "center" }}>
            No reflections yet. Use <b>+ New Journal</b> or <b>+ New Photo</b> above to add the first one.
          </div>
        ) : null}
        {reflections.map((r) =>
          <ReflCard
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
    </Glass>);
}

function ReflCard({ refl, casId, onEdit, dangerZone, onDelete, onPhotoError }) {
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
      background: N.card,
      backdropFilter: "blur(20px) saturate(170%)",
      WebkitBackdropFilter: "blur(20px) saturate(170%)",
      borderRadius: 11,
      boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.05), 0 1px 3px rgba(0,0,0,0.04)",
      opacity: refl.is_placeholder ? 0.82 : 1,
      overflow: "hidden", position: "relative",
      flexShrink: 0,
      transition: "background 0.15s, box-shadow 0.15s"
    }}>
      {refl.is_placeholder ? (
        <div style={{
          position: "absolute", top: 0, bottom: 0, left: 0, width: 3,
          background: A.solid
        }} />
      ) : null}
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 14px 7px" }}>
        <div style={{
          width: 24, height: 24, borderRadius: 6,
          background: "rgba(0,0,0,0.05)", color: N.inkMid,
          display: "flex", alignItems: "center", justifyContent: "center"
        }}>
          <I name={isAlbum ? "image" : "pen"} size={13} stroke={1.6} />
        </div>
        <div>
          <div className="tnum" style={{ fontSize: 12, fontWeight: 600, color: N.inkDeep }}>
            {dateStr || "—"}
          </div>
          <div style={{ fontSize: 10, color: N.inkSoft }}>{subline}</div>
        </div>
        {refl.is_placeholder ? <Pill accent>Placeholder</Pill> : null}
        <div style={{ flex: 1 }} />
        {copyable && (
          <button
            className="mono-refl-edit"
            onClick={copyBody}
            title="Copy reflection text — e.g. to feed an AI chat"
            style={{
              fontSize: 10.5, padding: "3px 9px 3px 7px", borderRadius: 6,
              background: copied === "fail" ? "rgba(216,80,74,0.1)" : "rgba(0,0,0,0.04)",
              border: "none",
              color: copied === "fail" ? "#a4332e" : N.ink,
              cursor: "pointer",
              display: "inline-flex", alignItems: "center", gap: 4,
              fontFamily: "inherit",
              transition: "background 0.15s"
            }}>
            <I name={copied === "ok" ? "check" : "copy"} size={10} stroke={1.8} />
            {copied === "ok" ? "Copied" : copied === "fail" ? "Failed" : "Copy"}
          </button>
        )}
        {editable && (
          <button
            className="mono-refl-edit"
            onClick={onEdit}
            style={{
              fontSize: 10.5, padding: "3px 9px 3px 7px", borderRadius: 6,
              background: "rgba(0,0,0,0.04)", border: "none",
              color: N.ink, cursor: "pointer",
              display: "inline-flex", alignItems: "center", gap: 4,
              fontFamily: "inherit",
              transition: "background 0.15s"
            }}>
            <I name="pen" size={10} stroke={1.8} /> Edit
          </button>
        )}
        {dangerZone && (
          <button
            className="mono-refl-edit"
            onClick={onDelete}
            title="Delete reflection (Danger Zone)"
            style={{
              fontSize: 10.5, padding: "3px 9px 3px 7px", borderRadius: 6,
              background: "rgba(216,80,74,0.1)", border: "none",
              color: "#a4332e", cursor: "pointer",
              display: "inline-flex", alignItems: "center", gap: 4,
              fontFamily: "inherit",
              transition: "background 0.15s"
            }}>
            <I name="trash" size={10} stroke={1.8} /> Delete
          </button>
        )}
      </div>
      {isAlbum ? (
        photos.length ? (
          <div style={{ padding: "4px 14px 12px", display: "flex", gap: 8, flexWrap: "wrap" }}>
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
          <div style={{ padding: "0 14px 12px", fontSize: 11.5, color: N.inkSoft, fontStyle: "italic" }}>
            (empty album — try Sync)
          </div>
        )
      ) : (
        refl.body_html ? (
          <div style={{
            padding: "0 14px 12px", fontSize: 12.5, lineHeight: 1.6,
            color: N.ink
          }} dangerouslySetInnerHTML={{ __html: refl.body_html }} />
        ) : (
          <div style={{ padding: "0 14px 12px", fontSize: 11.5, color: N.inkSoft, fontStyle: "italic" }}>
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
      width: "100%", height: "100%", position: "relative",
      overflow: "hidden",
      background: N.bg
    }}>
      <GradientBg>
        <div style={{
          position: "absolute", top: 14, bottom: 14, left: 14, right: 14,
          display: "flex", gap: 14
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
          {/* Placeholder Hub — collapsible side panel instead of a modal */}
          {ctx.hubOpen && <window.MonoPlaceholderPanel />}
        </div>
      </GradientBg>
    </div>);
}

window.MonoAppShell = AppShell;
window.MonoBtn = Btn;
window.MonoPill = Pill;
window.MonoStrandTag = StrandTag;
window.MonoPhoto = MonoPhoto;
window.MonoPhotoThumb = PhotoThumb;
window.MonoGlass = Glass;
