// ── Root: mono prototype with state + modal routing ────────────────────
const MonoCtx = window.MonoCtx;
const N = window.MONO_NEUTRALS;
const AppShell = window.MonoAppShell;
const API = window.API;

function Prototype() {
  // modal target: null | "journal-choose" | "journal-write" | "photos-new" |
  //               "photos-edit" | "ai-1" | "ai-2" | "ai-3" |
  //               "settings" | "placeholders"
  const [modal, setModal] = React.useState(null);
  const [activeId, setActiveId] = React.useState(null);
  const [settingsTab, setSettingsTab] = React.useState("account");

  // ── App data ────────────────────────────────────────────────────────────
  const [status, setStatus] = React.useState({ logged_in: false, ai_provider: "prompt" });
  const [appState, setAppState] = React.useState("loading");      // loading|ok|unauthed|error
  const [syncState, setSyncState] = React.useState("idle");        // idle|syncing|error
  const [config, setConfig] = React.useState({});
  const [experiences, setExperiences] = React.useState([]);
  const [reflections, setReflections] = React.useState([]);
  const [reflLoading, setReflLoading] = React.useState(false);
  const [pendingCount, setPendingCount] = React.useState(0);

  // Transient state shared between modals (esp. AI 3-step flow + photo edit)
  const [modalPayload, setModalPayload] = React.useState({});

  // ── Loaders ────────────────────────────────────────────────────────────
  const loadStatus = React.useCallback(async () => {
    try {
      const s = await API.status();
      setStatus(s);
      return s;
    } catch (_) {
      setStatus({ logged_in: false, ai_provider: "prompt" });
      return { logged_in: false };
    }
  }, []);

  const loadConfig = React.useCallback(async () => {
    try {
      const c = await API.getConfig();
      setConfig(c || {});
      return c;
    } catch (_) { return {}; }
  }, []);

  const loadExperiences = React.useCallback(async () => {
    try {
      const exps = await API.experiences();
      setExperiences(exps || []);
      return exps || [];
    } catch (e) {
      if (String(e.message).includes("session")) setAppState("unauthed");
      return [];
    }
  }, []);

  const loadQueue = React.useCallback(async () => {
    try {
      const q = await API.queue();
      setPendingCount((q || []).length);
    } catch (_) { /* non-fatal */ }
  }, []);

  const loadReflections = React.useCallback(async (cas_id) => {
    if (!cas_id) { setReflections([]); return; }
    setReflLoading(true);
    try {
      const r = await API.reflections(cas_id);
      setReflections(r || []);
    } catch (e) {
      if (String(e.message).includes("session")) setAppState("unauthed");
      setReflections([]);
    } finally {
      setReflLoading(false);
    }
  }, []);

  // ── Boot sequence ───────────────────────────────────────────────────────
  React.useEffect(() => {
    (async () => {
      const s = await loadStatus();
      await loadConfig();
      if (!s.logged_in) { setAppState("unauthed"); return; }
      setAppState("ok");
      const exps = await loadExperiences();
      await loadQueue();
      // pick the first non-completed experience by default
      if (exps.length) {
        const first = exps.find((e) => !e.is_completed) || exps[0];
        if (first) setActiveId(first.id);
      }
      // Background sync
      setSyncState("syncing");
      try {
        await API.syncAll();
        await loadExperiences();
        await loadQueue();
        setSyncState("idle");
      } catch (e) {
        setSyncState("error");
        if (String(e.message).includes("session")) setAppState("unauthed");
      }
    })();
  }, []);

  // Reload reflections when active experience changes
  React.useEffect(() => { loadReflections(activeId); }, [activeId, loadReflections]);

  // ── Mutations ──────────────────────────────────────────────────────────
  const syncOne = React.useCallback(async (cas_id) => {
    setSyncState("syncing");
    try {
      await API.syncOne(cas_id);
      await loadExperiences();
      if (activeId === cas_id) await loadReflections(cas_id);
      setSyncState("idle");
    } catch (e) {
      setSyncState("error");
      if (String(e.message).includes("session")) setAppState("unauthed");
    }
  }, [activeId, loadExperiences, loadReflections]);

  const syncAll = React.useCallback(async () => {
    setSyncState("syncing");
    try {
      await API.syncAll();
      await loadExperiences();
      if (activeId) await loadReflections(activeId);
      await loadQueue();
      setSyncState("idle");
    } catch (e) {
      setSyncState("error");
      if (String(e.message).includes("session")) setAppState("unauthed");
    }
  }, [activeId, loadExperiences, loadReflections, loadQueue]);

  // After any CUD: pull a fresh sync from ManageBac for the active experience
  // (otherwise the local DB doesn't have the new/edited reflection yet) and
  // refresh experiences + placeholder queue. If there's no active experience,
  // fall back to a full sync.
  const refreshAfterMutation = React.useCallback(async () => {
    setSyncState("syncing");
    try {
      if (activeId) {
        await API.syncOne(activeId);
      } else {
        await API.syncAll();
      }
      await loadExperiences();
      if (activeId) await loadReflections(activeId);
      await loadQueue();
      setSyncState("idle");
    } catch (e) {
      setSyncState("error");
      if (String(e.message).includes("session")) setAppState("unauthed");
    }
  }, [activeId, loadReflections, loadExperiences, loadQueue]);

  const onLoginSuccess = React.useCallback(async () => {
    const s = await loadStatus();
    if (s.logged_in) {
      setAppState("ok");
      await loadConfig();
      const exps = await loadExperiences();
      if (exps.length && !activeId) {
        const first = exps.find((e) => !e.is_completed) || exps[0];
        if (first) setActiveId(first.id);
      }
      setSyncState("syncing");
      try {
        await API.syncAll();
        await loadExperiences();
        await loadQueue();
        setSyncState("idle");
      } catch (_) {
        setSyncState("error");
      }
    }
  }, [activeId, loadConfig, loadExperiences, loadQueue, loadStatus]);

  const updateConfig = React.useCallback(async (patch) => {
    const next = { ...config, ...patch };
    setConfig(next);
    try {
      await API.saveConfig(patch);
      await loadStatus();
    } catch (e) {
      setConfig(config);
      throw e;
    }
  }, [config, loadStatus]);

  // ── Modal helpers ──────────────────────────────────────────────────────
  const close = React.useCallback(() => {
    setModal(null);
    setModalPayload({});
  }, []);
  const go = React.useCallback((target, payload) => {
    if (payload) setModalPayload((prev) => ({ ...prev, ...payload }));
    setModal(target);
  }, []);

  const activeExp = experiences.find((e) => e.id === activeId) || null;

  // Status dot color
  const dotKind =
    appState === "unauthed" || appState === "error" ? "red" :
    syncState === "syncing" ? "yellow" :
    syncState === "error"   ? "red" :
    "green";

  const ctxValue = {
    close, go, set: setModal,
    // data
    status, appState, syncState, config,
    experiences, activeId, activeExp, reflections, reflLoading,
    pendingCount, modalPayload,
    // setters
    setActiveId, setModalPayload,
    // mutations
    syncOne, syncAll, updateConfig, refreshAfterMutation, onLoginSuccess,
    loadReflections, loadExperiences, loadQueue, loadStatus,
  };

  let modalEl = null;
  if      (modal === "journal-choose") modalEl = <window.NewJournalModal_Mono mode="choose" />;
  else if (modal === "journal-write")  modalEl = <window.NewJournalModal_Mono mode="write" />;
  else if (modal === "photos-new")     modalEl = <window.NewPhotosModal_Mono />;
  else if (modal === "photos-edit")    modalEl = <window.EditPhotosModal_Mono />;
  else if (modal === "ai-1")           modalEl = <window.AIGenerateModal_Mono step={1} />;
  else if (modal === "ai-2")           modalEl = <window.AIGenerateModal_Mono step={2} />;
  else if (modal === "ai-3")           modalEl = <window.AIGenerateModal_Mono step={3} />;
  else if (modal === "settings")       modalEl = <window.SettingsModal_Mono tab={settingsTab} onTab={setSettingsTab} />;
  else if (modal === "placeholders")   modalEl = <window.PlaceholderHubModal_Mono />;

  return (
    <MonoCtx.Provider value={ctxValue}>
      <div style={{
        position: "fixed", inset: 0,
        background: N.bg,
        overflow: "hidden",
      }}>
        <AppShell
          activeId={activeId}
          activeExp={activeExp}
          experiences={experiences}
          reflections={reflections}
          reflLoading={reflLoading}
          pendingCount={pendingCount}
          dotKind={dotKind}
          appState={appState}
          onSelect={setActiveId}
          onOpenJournal={() => setModal("journal-choose")}
          onOpenPhotos={() => setModal("photos-new")}
          onOpenSettings={() => setModal("settings")}
          onOpenPlaceholders={() => setModal("placeholders")}
          onEditRefl={(r) => {
            setModalPayload({ rid: r.id, casId: activeId, refl: r });
            setModal(r.kind === "album" ? "photos-edit" : "journal-write");
          }}
        />
        {modalEl}
      </div>
    </MonoCtx.Provider>
  );
}

ReactDOM.createRoot(document.getElementById("mono-proto-root")).render(<Prototype />);
