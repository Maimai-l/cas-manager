// ── Settings + Placeholders Hub (mono) ─────────────────────────────────
const I = window.I;
const A = window.MONO_ACCENT;
const N = window.MONO_NEUTRALS;
const S = window.MONO_STRAND;
const ModalShell = window.MonoModalShell;
const FieldLabel = window.MonoFieldLabel;
const FieldShell = window.MonoFieldShell;
const Btn = window.MonoBtn;
const Pill = window.MonoPill;
const StrandTag = window.MonoStrandTag;
const API = window.API;

// ── Settings ───────────────────────────────────────────────────────────
function SettingsModal({ tab = "account", onTab }) {
  const ctx = React.useContext(window.MonoCtx);
  return (
    <ModalShell title="Settings" width={720}
      footer={<><Btn onClick={ctx.close}>Done</Btn></>}
      bodyStyle={{ padding: 0 }}>
      <div style={{ display: "flex", height: 480, marginTop: -4 }}>
        <div style={{
          width: 160, padding: "14px 8px",
          background: "rgba(0,0,0,0.02)",
          borderRight: "0.5px solid " + N.hairline,
          display: "flex", flexDirection: "column", gap: 2
        }}>
          <SettingsTab icon="user"     label="Account"  active={tab === "account"}  onClick={() => onTab && onTab("account")} />
          <SettingsTab icon="sparkle"  label="AI"       active={tab === "ai"}       onClick={() => onTab && onTab("ai")} />
          <SettingsTab icon="pen"      label="Prompts"  active={tab === "prompts"}  onClick={() => onTab && onTab("prompts")} />
          <SettingsTab icon="settings" label="General"  active={tab === "general"}  onClick={() => onTab && onTab("general")} />
          <SettingsTab icon="trash"    label="Danger"   active={tab === "danger"}   onClick={() => onTab && onTab("danger")} />
        </div>

        <div style={{ flex: 1, padding: "18px 22px", display: "flex", flexDirection: "column", gap: 18, overflow: "auto" }}>
          {tab === "account" && <AccountPane />}
          {tab === "ai"      && <AIProviderPane />}
          {tab === "prompts" && <PromptsPane />}
          {tab === "general" && <GeneralPane />}
          {tab === "danger"  && <DangerPane />}
        </div>
      </div>
    </ModalShell>);
}

function SettingsTab({ icon, label, active, onClick }) {
  return (
    <div
      onClick={onClick}
      className="mono-settings-tab"
      style={{
        display: "flex", alignItems: "center", gap: 9,
        padding: "7px 10px", borderRadius: 7,
        fontSize: 12, fontWeight: active ? 600 : 500,
        color: active ? N.inkDeep : N.inkMid,
        background: active ? "rgba(255,255,255,0.8)" : "transparent",
        boxShadow: active ? "inset 0 0 0 0.5px rgba(0,0,0,0.08)" : "none",
        cursor: "pointer",
        transition: "background 0.12s"
      }}>
      <I name={icon} size={13} stroke={1.7} />
      <span>{label}</span>
    </div>);
}

// ── Account: login or re-login ─────────────────────────────────────────
function AccountPane() {
  const ctx = React.useContext(window.MonoCtx);
  const loggedIn = !!(ctx.status && ctx.status.logged_in);
  const baseUrl  = (ctx.config && ctx.config.base) || "";
  return (
    <>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: N.inkDeep, marginBottom: 2 }}>
          ManageBac connection
        </div>
        <div style={{ fontSize: 11, color: N.inkMid, lineHeight: 1.5 }}>
          Log in using your ManageBac email and password; CAS Manager will automatically renew the session in the background.
        </div>
      </div>

      {/* Show the configured URL only after login succeeds — the login form
          below has its own URL field for the first-time / re-login flow. */}
      {loggedIn && baseUrl && (
        <div>
          <FieldLabel hint="Loaded from cas_config.json">School base URL</FieldLabel>
          <FieldShell mono>{baseUrl}</FieldShell>
        </div>
      )}

      {loggedIn ? <LoggedInBlock /> : <LoginForm />}
    </>);
}

function LoggedInBlock() {
  const ctx = React.useContext(window.MonoCtx);
  const [reauth, setReauth] = React.useState(false);
  if (reauth) return <LoginForm onCancel={() => setReauth(false)} />;
  return (
    <div style={{
      padding: "12px 14px",
      background: "rgba(255,255,255,0.6)",
      borderRadius: 10,
      boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.06)",
      display: "flex", alignItems: "center", gap: 12
    }}>
      <div style={{
        width: 36, height: 36, borderRadius: 9,
        background: A.solid, color: A.onAccent,
        display: "flex", alignItems: "center", justifyContent: "center"
      }}>
        <I name="check" size={18} stroke={2.2} />
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: N.inkDeep }}>
          Connected to ManageBac
        </div>
        <div style={{ fontSize: 10.5, color: N.inkSoft }}>
          Session valid · {ctx.experiences.length} experiences cached
        </div>
      </div>
      <Btn onClick={() => setReauth(true)}>Re-login</Btn>
    </div>);
}

function LoginForm({ onCancel }) {
  const ctx = React.useContext(window.MonoCtx);
  // Pre-fill base URL from existing config (for re-login flow). New users
  // see an empty field with a generic placeholder.
  const [baseUrl, setBaseUrl]   = React.useState((ctx.config && ctx.config.base) || "");
  const [email, setEmail]       = React.useState("");
  const [password, setPassword] = React.useState("");
  const [loading, setLoading]   = React.useState(false);
  const [error, setError]       = React.useState(null);

  async function doLogin() {
    setError(null);
    if (!baseUrl.trim()) {
      setError("Please enter your school's ManageBac URL");
      return;
    }
    if (!email.trim() || !password) {
      setError("Please enter your email and password");
      return;
    }
    setLoading(true);
    try {
      // Server normalizes (prepends https://, strips trailing slash) and
      // validates the URL, then persists it to config on success.
      await API.login(email.trim(), password, baseUrl.trim());
      setPassword("");
      await ctx.onLoginSuccess();
      if (onCancel) onCancel();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      padding: "14px 14px 12px",
      background: "rgba(255,255,255,0.6)",
      borderRadius: 10,
      boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.06)",
      display: "flex", flexDirection: "column", gap: 10
    }}>
      <FieldLabel hint="In the form of https://<school>.managebac.cn / .com / .org">
       School ManageBac URL
      </FieldLabel>
      <FieldShell style={{ padding: 0 }}>
        <input
          type="url"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://yourschool.managebac.cn"
          style={inputStyle}
          autoComplete="url"
          spellCheck={false}
        />
      </FieldShell>

      <FieldLabel>Email</FieldLabel>
      <FieldShell style={{ padding: 0 }}>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="name@school.edu"
          style={inputStyle}
          autoComplete="username"
        />
      </FieldShell>

      <FieldLabel>Password</FieldLabel>
      <FieldShell style={{ padding: 0 }}>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
          style={inputStyle}
          autoComplete="current-password"
          onKeyDown={(e) => { if (e.key === "Enter") doLogin(); }}
        />
      </FieldShell>

      {error && (
        <div style={{ fontSize: 11.5, color: "#a4332e" }}>⚠ {error}</div>
      )}
      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", marginTop: 4 }}>
        {onCancel && <Btn onClick={onCancel} disabled={loading}>Cancel</Btn>}
        <Btn primary onClick={doLogin} disabled={loading}>
          {loading ? "Logging in…" : "login"}
        </Btn>
      </div>
      <div style={{ fontSize: 10.5, color: N.inkSoft, lineHeight: 1.5, marginTop: 4 }}>
        Credentials are stored only on this computer (mb_state.json) so the app can
        re-login automatically when the session expires — you won't need to type them again.
        The school URL is saved to the configuration after a successful login.
      </div>
    </div>);
}

const inputStyle = {
  width: "100%", padding: "8px 11px", border: "none", outline: "none",
  background: "transparent", fontSize: 13,
  color: "rgba(20,20,20,0.95)", fontFamily: "inherit",
  boxSizing: "border-box"
};

// ── AI provider ──────────────────────────────────────────────────────────
function AIProviderPane() {
  const ctx = React.useContext(window.MonoCtx);
  const provider = (ctx.config && ctx.config.ai_provider) || "prompt";
  const model    = (ctx.config && ctx.config.ai_model) || "";
  const ollamaModel  = (ctx.config && ctx.config.ollama_model) || "";
  const ollamaUrl    = (ctx.config && ctx.config.ollama_url) || "";
  const [saving, setSaving] = React.useState(false);
  const [error, setError]   = React.useState(null);

  async function patch(p) {
    setError(null); setSaving(true);
    try { await ctx.updateConfig(p); }
    catch (e) { setError(e.message || String(e)); }
    finally { setSaving(false); }
  }

  return (
    <>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: N.inkDeep, marginBottom: 2 }}>
          AI provider
        </div>
        <div style={{ fontSize: 11, color: N.inkMid }}>
          Choose how to generate reflections from your rough notes.
        </div>
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <ProviderCard active={provider === "prompt"}    onClick={() => patch({ ai_provider: "prompt" })}
          name="Prompt"     sub="Copy & paste — works with any AI" icon="copy" />
        <ProviderCard active={provider === "ollama"}    onClick={() => patch({ ai_provider: "ollama" })}
          name="Ollama"     sub="Local model on your Mac" icon="cpu" />
        <ProviderCard active={provider === "anthropic"} onClick={() => patch({ ai_provider: "anthropic" })}
          name="Anthropic"  sub="Claude API (ANTHROPIC_API_KEY)" icon="cloud" />
      </div>

      <div>
        <FieldLabel>Anthropic model</FieldLabel>
        <FieldShell mono style={{ padding: 0 }}>
          <input
            value={model}
            onChange={(e) => ctx.updateConfig({ ai_model: e.target.value }).catch((err) => setError(err.message))}
            placeholder="claude-opus-4-6"
            style={inputStyle}
          />
        </FieldShell>
      </div>

      <div>
        <FieldLabel hint="for ollama provider">Ollama model · URL</FieldLabel>
        <div style={{ display: "flex", gap: 8 }}>
          <FieldShell mono style={{ padding: 0, flex: 1 }}>
            <input
              value={ollamaModel}
              onChange={(e) => ctx.updateConfig({ ollama_model: e.target.value }).catch((err) => setError(err.message))}
              placeholder="llama3.2"
              style={inputStyle}
            />
          </FieldShell>
          <FieldShell mono style={{ padding: 0, flex: 1 }}>
            <input
              value={ollamaUrl}
              onChange={(e) => ctx.updateConfig({ ollama_url: e.target.value }).catch((err) => setError(err.message))}
              placeholder="http://localhost:11434"
              style={inputStyle}
            />
          </FieldShell>
        </div>
      </div>

      <div style={{ fontSize: 10.5, color: N.inkSoft, lineHeight: 1.5 }}>
        Want to customize the AI's writing style, word limit, required LOs to cover, etc.？Open the <b>Prompts</b> tab.
      </div>

      {saving && <div style={{ fontSize: 11, color: N.inkMid }}>Saving…</div>}
      {error  && <div style={{ fontSize: 11.5, color: "#a4332e" }}>⚠ {error}</div>}
    </>);
}

// ── Prompts pane (slot list + per-slot editor) ──────────────────────────
function PromptsPane() {
  const [slots, setSlots] = React.useState([]);     // [{slot, label, intent, description, default, body, is_customized, updated_at}]
  const [loading, setLoading] = React.useState(true);
  const [error, setError]   = React.useState(null);
  const [openSlot, setOpenSlot] = React.useState(null);  // which slot is expanded

  const reload = React.useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const data = await window.API.prompts();
      setSlots(data || []);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { reload(); }, [reload]);

  // Group by intent so future "proposal", "sa_question" land under their own header
  const grouped = React.useMemo(() => {
    const g = {};
    for (const s of slots) {
      const k = s.intent || "Other";
      (g[k] = g[k] || []).push(s);
    }
    return g;
  }, [slots]);

  return (
    <>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: N.inkDeep, marginBottom: 2 }}>
          System prompts
        </div>
        <div style={{ fontSize: 11, color: N.inkMid, lineHeight: 1.55 }}>
          Each prompt determines all AI behavior in the corresponding scenario. Click a prompt to expand and edit.
          <b>Reset</b> Will delete your custom version and restore the built-in default. 
          Each time you generate, the current experience's proposal and LO list will be automatically appended at the end.
        </div>
      </div>

      {loading && <div style={{ fontSize: 11.5, color: N.inkMid }}>Loading…</div>}
      {error  && <div style={{ fontSize: 11.5, color: "#a4332e" }}>⚠ {error}</div>}

      {!loading && Object.keys(grouped).map((intent) => (
        <div key={intent} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{
            fontSize: 10, fontWeight: 700, color: N.inkSoft,
            letterSpacing: 0.6, textTransform: "uppercase",
            marginTop: 4
          }}>{intent}</div>
          {grouped[intent].map((p) => (
            <PromptSlot
              key={p.slot}
              data={p}
              open={openSlot === p.slot}
              onToggle={() => setOpenSlot(openSlot === p.slot ? null : p.slot)}
              onChanged={reload}
            />
          ))}
        </div>
      ))}

      {!loading && !slots.length && (
        <div style={{ fontSize: 11.5, color: N.inkSoft }}>
          No prompts registered.
        </div>
      )}
    </>);
}

function PromptSlot({ data, open, onToggle, onChanged }) {
  const [draft, setDraft]     = React.useState(data.body);
  const [showDefault, setShowDefault] = React.useState(false);
  const [saving, setSaving]   = React.useState(false);
  const [error, setError]     = React.useState(null);
  const [hint, setHint]       = React.useState("");

  React.useEffect(() => { setDraft(data.body); }, [data.body, data.is_customized]);
  const dirty = draft !== data.body;

  async function save() {
    setError(null); setSaving(true); setHint("");
    try {
      await window.API.savePrompt(data.slot, draft);
      setHint("Saved");
      setTimeout(() => setHint(""), 1400);
      await onChanged();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    if (!data.is_customized) return;
    if (!window.confirm(`Reset “${data.label}” will delete your custom version and restore the built-in default.Confirm？`)) return;
    setError(null); setSaving(true); setHint("");
    try {
      await window.API.resetPrompt(data.slot);
      setHint("Default restored");
      setTimeout(() => setHint(""), 1400);
      await onChanged();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  function copyDefaultToDraft() {
    setDraft(data.default);
  }

  return (
    <div style={{
      borderRadius: 9,
      background: "rgba(255,255,255,0.65)",
      boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.06)",
      overflow: "hidden",
      transition: "background 0.12s"
    }}>
      {/* Header row — click to expand */}
      <div
        onClick={onToggle}
        style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "10px 12px", cursor: "pointer",
          fontFamily: "inherit"
        }}>
        <I name="pen" size={13} stroke={1.7} style={{ color: N.inkMid, flexShrink: 0 }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, color: N.inkDeep }}>{data.label}</div>
          <div style={{ fontSize: 10.5, color: N.inkSoft, marginTop: 2,
                        fontFamily: "ui-monospace, SF Mono, Menlo, monospace" }}>{data.slot}</div>
        </div>
        {data.is_customized ? (
          <span style={{
            fontSize: 10, fontWeight: 600,
            padding: "2px 8px", borderRadius: 99,
            background: A.solid, color: A.onAccent,
          }}>Customized</span>
        ) : (
          <span style={{
            fontSize: 10, fontWeight: 500,
            padding: "2px 8px", borderRadius: 99,
            background: "rgba(0,0,0,0.05)", color: N.inkMid,
          }}>Default</span>
        )}
        <span style={{
          fontSize: 10.5, color: N.inkMid, fontVariantNumeric: "tabular-nums",
          minWidth: 50, textAlign: "right"
        }}>{data.body.length}&nbsp;ch</span>
        <I name="chevron" size={12} stroke={1.8}
           style={{ color: N.inkSoft, transform: open ? "rotate(90deg)" : "rotate(0)", transition: "transform 0.15s" }} />
      </div>

      {open && (
        <div style={{ padding: "0 12px 12px", display: "flex", flexDirection: "column", gap: 10,
                      borderTop: "0.5px solid " + N.hairline }}>
          <div style={{ fontSize: 11, color: N.inkMid, lineHeight: 1.55, marginTop: 10 }}>
            {data.description}
          </div>

          {/* Default reference (collapsible) */}
          <div>
            <button
              onClick={() => setShowDefault(!showDefault)}
              style={{
                fontSize: 11, fontWeight: 500, color: N.ink,
                padding: "4px 9px", borderRadius: 6,
                background: "rgba(0,0,0,0.04)", border: "none",
                cursor: "pointer", fontFamily: "inherit",
                display: "inline-flex", alignItems: "center", gap: 5
              }}>
              <I name="chevron" size={10} stroke={2}
                 style={{ transform: showDefault ? "rotate(90deg)" : "rotate(0)", transition: "transform 0.15s" }} />
              {showDefault ? "Hide" : "Show"} built-in default ({data.default.length}&nbsp;ch)
            </button>
            {showDefault && (
              <div style={{
                marginTop: 6, padding: "10px 12px",
                background: "rgba(0,0,0,0.025)",
                borderRadius: 7,
                boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.06)",
                fontSize: 11.5, lineHeight: 1.55,
                color: N.inkMid,
                whiteSpace: "pre-wrap", wordBreak: "break-word",
                maxHeight: 200, overflow: "auto",
                fontFamily: "ui-monospace, SF Mono, Menlo, monospace"
              }}>{data.default}</div>
            )}
            <button
              onClick={copyDefaultToDraft}
              style={{
                marginTop: 6,
                fontSize: 10.5, fontWeight: 500, color: N.ink,
                padding: "3px 8px", borderRadius: 6,
                background: "rgba(255,255,255,0.85)", border: "none",
                boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.08)",
                cursor: "pointer", fontFamily: "inherit"
              }}>
              Copy default → editor
            </button>
          </div>

          {/* Editor */}
          <div>
            <FieldLabel hint={dirty ? "Unsaved changes" : (data.is_customized ? "Saved (customized)" : "Not customized · showing default")}>
              Your version
            </FieldLabel>
            <FieldShell height={260} style={{ padding: 0 }}>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                style={{
                  width: "100%", height: 260, padding: "12px 14px",
                  border: "none", outline: "none", background: "transparent",
                  fontSize: 12.5, lineHeight: 1.55,
                  color: N.inkDeep,
                  fontFamily: "ui-monospace, SF Mono, Menlo, monospace",
                  resize: "none", boxSizing: "border-box"
                }}
              />
            </FieldShell>
            <div style={{ fontSize: 10.5, color: N.inkSoft, marginTop: 4 }}>
              {draft.length} chars · {data.updated_at ? `last saved ${data.updated_at}` : "no override saved yet"}
            </div>
          </div>

          {/* Actions */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              onClick={reset}
              disabled={saving || !data.is_customized}
              title={data.is_customized ? "Delete override, fall back to built-in default" : "Already using default"}
              style={{
                padding: "6px 14px", borderRadius: 7, border: "none",
                background: "rgba(216,80,74,0.08)",
                color: "#a4332e",
                fontSize: 11.5, fontWeight: 500,
                cursor: (saving || !data.is_customized) ? "default" : "pointer",
                opacity: (saving || !data.is_customized) ? 0.4 : 1,
                boxShadow: "inset 0 0 0 0.5px rgba(216,80,74,0.25)",
                fontFamily: "inherit"
              }}>
              Reset to default
            </button>
            <div style={{ flex: 1 }} />
            {hint   && <span style={{ fontSize: 11.5, color: "#3d8a4f" }}>{hint}</span>}
            {saving && <span style={{ fontSize: 11.5, color: N.inkMid }}>Saving…</span>}
            {error  && <span style={{ fontSize: 11.5, color: "#a4332e" }}>⚠ {error}</span>}
            <button
              onClick={save}
              disabled={saving || !dirty}
              style={{
                padding: "6px 14px", borderRadius: 7, border: "none",
                background: dirty ? A.solid : "rgba(255,255,255,0.85)",
                color: dirty ? A.onAccent : N.ink,
                fontWeight: 600, fontSize: 11.5,
                cursor: (saving || !dirty) ? "default" : "pointer",
                opacity: (saving || !dirty) ? 0.5 : 1,
                boxShadow: dirty ? A.shadow : "inset 0 0 0 0.5px rgba(0,0,0,0.08)",
                fontFamily: "inherit"
              }}>
              Save override
            </button>
          </div>
        </div>
      )}
    </div>);
}

function ProviderCard({ name, sub, icon, active, onClick }) {
  return (
    <div
      onClick={onClick}
      className="mono-provider-card"
      data-active={active ? "1" : undefined}
      style={{
        flex: 1, padding: "12px 12px 10px",
        borderRadius: 10, cursor: "pointer",
        background: active ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.5)",
        boxShadow: active ? `inset 0 0 0 1.5px rgba(20,20,20,0.85)` : "inset 0 0 0 0.5px rgba(0,0,0,0.08)",
        transition: "background 0.12s, box-shadow 0.12s"
      }}>
      <div style={{
        width: 26, height: 26, borderRadius: 7,
        background: "rgba(0,0,0,0.05)",
        color: N.inkDeep,
        display: "flex", alignItems: "center", justifyContent: "center",
        marginBottom: 8
      }}>
        <I name={icon} size={13} stroke={1.7} />
      </div>
      <div style={{ fontSize: 12, fontWeight: 600, color: N.inkDeep, display: "flex", alignItems: "center", gap: 5 }}>
        {name}
        {active &&
          <span style={{
            width: 14, height: 14, borderRadius: "50%",
            background: A.solid, color: A.onAccent,
            display: "inline-flex", alignItems: "center", justifyContent: "center"
          }}>
            <I name="check" size={9} stroke={3} />
          </span>
        }
      </div>
      <div style={{ fontSize: 10, color: N.inkSoft, marginTop: 2, lineHeight: 1.4 }}>{sub}</div>
    </div>);
}

// ── General ─────────────────────────────────────────────────────────────
function GeneralPane() {
  const ctx = React.useContext(window.MonoCtx);
  const cfg = ctx.config || {};
  const [error, setError] = React.useState(null);
  function patch(p) { ctx.updateConfig(p).catch((e) => setError(e.message)); }
  return (
    <>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: N.inkDeep, marginBottom: 2 }}>General</div>
        <div style={{ fontSize: 11, color: N.inkMid }}>App-level settings stored in <code>cas_config.json</code>.</div>
      </div>
      <div>
        <FieldLabel hint="Switch school here · saves on blur">School base URL</FieldLabel>
        <FieldShell mono style={{ padding: 0 }}>
          <input
            // key forces re-mount when cfg.base updates from a successful login,
            // so the new value is reflected (defaultValue is uncontrolled).
            key={cfg.base || "empty"}
            defaultValue={cfg.base || ""}
            placeholder="https://yourschool.managebac.cn"
            onBlur={(e) => { if (e.target.value !== cfg.base) patch({ base: e.target.value }); }}
            style={inputStyle}
          />
        </FieldShell>
      </div>
      <div>
        <FieldLabel>Backup directory</FieldLabel>
        <FieldShell mono style={{ padding: 0 }}>
          <input
            defaultValue={cfg.backup_dir || ""}
            placeholder="mb_backup_out"
            onBlur={(e) => { if (e.target.value !== cfg.backup_dir) patch({ backup_dir: e.target.value }); }}
            style={inputStyle}
          />
        </FieldShell>
      </div>
      <div>
        <FieldLabel>Database stats</FieldLabel>
        <div style={{
          padding: "10px 12px", borderRadius: 8,
          background: "rgba(255,255,255,0.6)",
          boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.06)",
          fontSize: 11.5, color: N.ink, lineHeight: 1.6, fontFamily: "ui-monospace, SF Mono, monospace"
        }}>
          {ctx.status && ctx.status.stats
            ? Object.entries(ctx.status.stats).map(([k, v]) => <div key={k}>{k}: {v}</div>)
            : "(no stats)"}
        </div>
      </div>
      {error && <div style={{ fontSize: 11.5, color: "#a4332e" }}>⚠ {error}</div>}
    </>);
}

// ── Danger zone ─────────────────────────────────────────────────────────
function DangerPane() {
  const ctx = React.useContext(window.MonoCtx);
  const enabled = !!(ctx.config && ctx.config.danger_zone_enabled);
  const [error, setError] = React.useState(null);
  async function toggle(v) {
    setError(null);
    try { await ctx.updateConfig({ danger_zone_enabled: v }); }
    catch (e) { setError(e.message); }
  }
  return (
    <>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#a4332e", marginBottom: 2 }}>
          Danger Zone
        </div>
        <div style={{ fontSize: 11, color: N.inkMid, lineHeight: 1.55 }}>
          When enabled, a red <b>Delete</b> button will appear in the top-right corner of each reflection card, allowing you to delete the reflection directly from ManageBac.
Deletion cannot be undone — only enable this when you are <i>absolutely sure</i>.
        </div>
      </div>
      <div style={{
        padding: "14px 16px",
        borderRadius: 10,
        background: "rgba(216,80,74,0.08)",
        boxShadow: "inset 0 0 0 0.5px rgba(216,80,74,0.3)",
        display: "flex", alignItems: "center", gap: 12
      }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, color: "#7a1f1a" }}>
            Enable destructive actions
          </div>
          <div style={{ fontSize: 10.5, color: "#8b3e39", marginTop: 2 }}>
            Reflection cards will show a Delete button
          </div>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => toggle(e.target.checked)}
            style={{ width: 16, height: 16, cursor: "pointer" }}
          />
          <span style={{ fontSize: 12, fontWeight: 500, color: "#7a1f1a" }}>
            {enabled ? "Enabled" : "Disabled"}
          </span>
        </label>
      </div>
      {error && <div style={{ fontSize: 11.5, color: "#a4332e" }}>⚠ {error}</div>}
    </>);
}

// ── Placeholder Hub — collapsible right side panel (not a modal) ────────
function PlaceholderHubPanel() {
  const ctx = React.useContext(window.MonoCtx);
  const [schedules, setSchedules] = React.useState([]);
  const [queue, setQueue] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);

  const reload = React.useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [s, q] = await Promise.all([API.schedules(), API.queue()]);
      setSchedules(s || []);
      setQueue(q || []);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // Mounted only while open — also re-pull when the global pending count
  // changes (e.g. a placeholder got filled via the composer).
  React.useEffect(() => { reload(); }, [reload, ctx.pendingCount]);

  async function toggleSchedule(s, on) {
    setError(null);
    try {
      if (on) {
        await API.saveSchedule(s.cas_id, { enabled: true, interval_days: s.interval_days || 1 });
      } else {
        await API.deleteSchedule(s.cas_id);
      }
      await reload();
      await ctx.loadQueue();
    } catch (e) { setError(e.message); }
  }

  async function stepInterval(s, delta) {
    const next = Math.max(1, Math.min(60, (s.interval_days || 1) + delta));
    if (next === s.interval_days) return;
    try {
      await API.saveSchedule(s.cas_id, { enabled: !!s.enabled, interval_days: next });
      await reload();
    } catch (e) { setError(e.message); }
  }

  async function runOne(cas_id) {
    setError(null);
    try {
      await API.placeholder(cas_id);
      await reload();
      await ctx.refreshAfterMutation();
    } catch (e) { setError(e.message); }
  }

  async function runAllDue() {
    setError(null);
    try {
      await API.runAllDue();
      await reload();
      await ctx.refreshAfterMutation();
    } catch (e) { setError(e.message); }
  }

  function openFill(q) {
    // Open the flat composer (AI tab) pre-targeted at the placeholder —
    // also switches the main panel to that experience. The panel stays
    // open so the user can work through the queue item by item.
    ctx.openComposer({
      mode: "ai",
      casId: q.cas_id,
      rid: q.rid,
      date: q.group_date || null,
      isPlaceholderFill: true,
    });
  }

  // Combine schedules with all experiences so users can enable new ones
  const activeExps = (ctx.experiences || []).filter((e) => !e.is_completed);
  const schedByCas = {}; (schedules || []).forEach((s) => { schedByCas[s.cas_id] = s; });
  const fullSchedList = activeExps.map((e) => {
    const s = schedByCas[e.id];
    return s
      ? { ...s, exp: e, on: !!s.enabled, everyDays: s.interval_days || 1 }
      : { cas_id: e.id, exp: e, on: false, everyDays: 1, interval_days: 1, last_run_date: null };
  });

  const Glass = window.MonoGlass;
  return (
    <Glass style={{
      width: 300, borderRadius: 14, flexShrink: 0,
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{
        padding: "12px 14px 10px",
        borderBottom: "0.5px solid " + N.hairline,
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <I name="tray" size={14} stroke={1.7} style={{ color: N.inkMid }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: N.inkDeep, letterSpacing: -0.1 }}>
            Placeholders
          </div>
          <div style={{ fontSize: 10, color: N.inkSoft, marginTop: 1 }}>
            {loading ? "Loading…"
                     : `${queue.length} pending · ${fullSchedList.filter((s) => s.on).length} active schedules`}
          </div>
        </div>
        <button onClick={ctx.toggleHub} className="mono-close" title="Collapse panel" style={{
          width: 20, height: 20, borderRadius: "50%", border: "none",
          background: "rgba(0,0,0,0.06)", color: "rgba(20,20,20,0.65)",
          display: "flex", alignItems: "center", justifyContent: "center",
          cursor: "pointer", fontFamily: "inherit", flexShrink: 0,
        }}>
          <I name="chevron" size={10} stroke={2} />
        </button>
      </div>

      {/* Scrollable body — Queue first (primary action), Schedules below */}
      <div style={{ flex: 1, overflow: "auto", padding: "12px 12px 10px",
                    display: "flex", flexDirection: "column", gap: 10 }}>
        <PaneHeader icon="inbox" title="Queue" sub="Click an item to fill it with the composer" />
        {!loading && !queue.length && (
          <div style={{ fontSize: 11, color: N.inkSoft, padding: "4px 2px" }}>
            No pending placeholders. All caught up!
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {queue.map((q) => {
            const qExp = ctx.experiences.find((e) => e.id === q.cas_id) || {};
            const qStrands = qExp.strands && qExp.strands.length
              ? qExp.strands
              : [qExp.strand || "activity"];
            return (
              <QueueRow
                key={q.rid}
                date={q.group_date}
                strands={qStrands}
                exp={q.name || `Exp ${q.cas_id}`}
                source="Placeholder"
                preview={q.body_html}
                onStart={() => openFill(q)}
              />
            );
          })}
        </div>

        <div style={{ height: 1, background: N.hairline, margin: "4px 0" }} />

        <PaneHeader icon="repeat" title="Schedules"
                    sub="Auto-create placeholder reflections at intervals" />
        {!loading && !fullSchedList.length && (
          <div style={{ fontSize: 11, color: N.inkSoft }}>No active experiences.</div>
        )}
        {fullSchedList.map((s) =>
          <ScheduleRow
            key={s.cas_id}
            exp={s.exp.name || `Exp ${s.cas_id}`}
            strands={s.exp.strands && s.exp.strands.length
                     ? s.exp.strands
                     : [s.exp.strand || "activity"]}
            everyDays={s.everyDays}
            next={s.last_run_date ? `+${s.everyDays}d after ${s.last_run_date}` : "—"}
            on={s.on}
            onToggle={() => toggleSchedule(s, !s.on)}
            onStep={(d) => stepInterval(s, d)}
            onRunNow={() => runOne(s.cas_id)}
          />
        )}
      </div>

      {/* Footer */}
      <div style={{
        padding: "8px 12px",
        borderTop: "0.5px solid " + N.hairline,
        display: "flex", alignItems: "center", gap: 8,
      }}>
        {error && <span style={{ fontSize: 10.5, color: "#a4332e", flex: 1,
                                 overflow: "hidden", textOverflow: "ellipsis",
                                 whiteSpace: "nowrap" }}>⚠ {error}</span>}
        <div style={{ flex: 1 }} />
        <Btn onClick={runAllDue} disabled={loading}>▶ Run all due</Btn>
      </div>
    </Glass>);
}

function PaneHeader({ icon, title, sub }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 10, paddingBottom: 4 }}>
      <div style={{ flex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <I name={icon} size={13} stroke={1.7} style={{ color: N.inkMid }} />
          <span style={{ fontSize: 13.5, fontWeight: 700, color: N.inkDeep, letterSpacing: -0.2 }}>{title}</span>
        </div>
        <div style={{ fontSize: 10.5, color: N.inkSoft, marginTop: 2 }}>{sub}</div>
      </div>
    </div>);
}

function Toggle({ on, onClick }) {
  return (
    <div
      onClick={onClick}
      style={{
        width: 32, height: 18, borderRadius: 99,
        background: on ? "rgba(20,20,20,0.9)" : "rgba(0,0,0,0.18)",
        position: "relative", cursor: "pointer",
        transition: "background 0.2s",
        flexShrink: 0
      }}>
      <div style={{
        position: "absolute", top: 2, left: on ? 16 : 2,
        width: 14, height: 14, borderRadius: "50%",
        background: "#fff",
        boxShadow: "0 1px 2px rgba(0,0,0,0.2)",
        transition: "left 0.2s"
      }} />
    </div>);
}

function ScheduleRow({ exp, strands, everyDays, next, on, onToggle, onStep, onRunNow }) {
  return (
    <div className="mono-schedule-row" style={{
      padding: "11px 12px", borderRadius: 10,
      background: on ? "rgba(255,255,255,0.7)" : "rgba(255,255,255,0.4)",
      boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.06)",
      opacity: on ? 1 : 0.7,
      display: "flex", flexDirection: "column", gap: 8,
      flexShrink: 0,
      transition: "background 0.15s"
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <StrandTag strands={strands} compact />
        <span style={{
          fontSize: 12, fontWeight: 600, color: N.inkDeep,
          flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"
        }}>{exp}</span>
        <Toggle on={on} onClick={onToggle} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 10.5, color: N.inkMid }}>Every</span>
        <div style={{
          display: "inline-flex", alignItems: "stretch",
          background: "rgba(255,255,255,0.85)", borderRadius: 6,
          boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.1)",
          fontSize: 11, overflow: "hidden"
        }}>
          <button onClick={() => onStep && onStep(-1)} style={stepperBtn}>−</button>
          <span className="tnum" style={{
            padding: "2px 9px", display: "inline-flex", alignItems: "center",
            fontWeight: 600, color: N.inkDeep, minWidth: 18, justifyContent: "center"
          }}>{everyDays}</span>
          <button onClick={() => onStep && onStep(1)} style={stepperBtn}>+</button>
        </div>
        <span style={{ fontSize: 10.5, color: N.inkMid }}>days</span>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: on ? N.inkDeep : N.inkSoft, fontWeight: 500 }}>
          {on ? next : "off"}
        </span>
        <button
          onClick={onRunNow}
          title="Create a placeholder reflection now"
          style={{
            fontSize: 10.5, padding: "3px 8px", borderRadius: 6,
            background: "rgba(255,255,255,0.85)",
            border: "none", color: N.ink, cursor: "pointer",
            fontFamily: "inherit", fontWeight: 500,
            boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.1)"
          }}>▶ Now</button>
      </div>
    </div>);
}

const stepperBtn = {
  padding: "2px 9px", border: "none", background: "transparent",
  fontSize: 13, color: N.ink, cursor: "pointer",
  fontWeight: 500, fontFamily: "inherit"
};

function QueueRow({ date, strands, exp, source, preview, onStart }) {
  const previewText = React.useMemo(() => {
    const d = document.createElement("div");
    d.innerHTML = preview || "";
    const t = (d.textContent || "").trim();
    return t.length > 80 ? t.slice(0, 80) + "…" : t;
  }, [preview]);
  return (
    <div
      className="mono-queue-row"
      onClick={onStart}
      style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "9px 12px", borderRadius: 9,
        background: "rgba(255,255,255,0.65)",
        boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.06)",
        flexShrink: 0,
        cursor: "pointer", transition: "background 0.15s"
      }}>
      <StrandTag strands={strands} compact />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 12, fontWeight: 600, color: N.inkDeep,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"
        }}>{exp}</div>
        <div style={{ fontSize: 10, color: N.inkSoft, display: "flex", gap: 6, marginTop: 1 }}>
          <span className="tnum">{date}</span>
          <span>·</span>
          <span>{source}</span>
        </div>
        {previewText && (
          <div style={{ fontSize: 10.5, color: N.inkMid, marginTop: 3, fontStyle: "italic",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{previewText}</div>
        )}
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); onStart && onStart(); }}
        style={{
          fontSize: 10.5, padding: "3px 10px", borderRadius: 6,
          background: A.solid, color: A.onAccent,
          border: "none", cursor: "pointer", fontWeight: 600,
          fontFamily: "inherit"
        }}>
        Start here
      </button>
    </div>);
}

window.SettingsModal_Mono = SettingsModal;
window.MonoPlaceholderPanel = PlaceholderHubPanel;
