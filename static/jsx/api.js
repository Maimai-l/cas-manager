// api.js — CAS Manager API client.
// All methods return Promise<data>; failures throw Error(json.error || HTTP status).
// Use window.API.* from components — do not call fetch directly.

(function () {
  const _base = "";  // same-origin

  async function _req(method, path, body, isForm, _isRetry) {
    const opts = { method, headers: {} };
    if (body !== undefined && body !== null) {
      if (isForm) {
        opts.body = body;  // FormData; browser sets multipart boundary
      } else {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
    }
    let resp;
    try {
      resp = await fetch(_base + path, opts);
    } catch (e) {
      throw new Error("network_error: " + (e.message || e));
    }
    let json;
    try {
      json = await resp.json();
    } catch (_) {
      throw new Error(`http_${resp.status}: response was not JSON`);
    }
    if (!json.ok) {
      // A session_expired response invalidates the server-side session cache;
      // one retry lets the backend walk its recovery chain (token refresh →
      // saved-credential re-login) without bothering the user.
      if (json.error === "session_expired" && !_isRetry) {
        return _req(method, path, body, isForm, true);
      }
      const err = new Error(json.error || `http_${resp.status}`);
      err.status = resp.status;
      err.detail = json.detail || "";
      err.path   = json.path || "";
      throw err;
    }
    return json.data;
  }

  const get      = (path)        => _req("GET",    path);
  const post     = (path, body)  => _req("POST",   path, body);
  const put      = (path, body)  => _req("PUT",    path, body);
  const del      = (path)        => _req("DELETE", path);
  const postForm = (path, form)  => _req("POST",   path, form, true);

  window.API = {
    // ── System & config ─────────────────────────────────────────────────
    status:       () => get("/api/status"),
    getConfig:    () => get("/api/config"),
    saveConfig:   (cfg) => post("/api/config", cfg),

    // ── Login ───────────────────────────────────────────────────────────
    loginStatus:  () => get("/api/login/status"),
    login:        (email, password, base) =>
                    post("/api/login/start", { email, password, base }),

    // ── Experiences ─────────────────────────────────────────────────────
    experiences:  () => get("/api/experiences"),
    experience:   (id) => get(`/api/experiences/${id}`),
    syncExperiences: () => post("/api/sync/experiences", {}),  // list only (fast)
    syncAll:      () => post("/api/sync/all", {}),
    syncOne:      (id) => post(`/api/sync/${id}`, {}),

    // ── Reflections ─────────────────────────────────────────────────────
    reflections:  (id) => get(`/api/experiences/${id}/reflections`),
    deleteRefl:   (rid, cas_id) => del(`/api/reflections/${rid}?cas_id=${cas_id}`),

    // ── Journal ─────────────────────────────────────────────────────────
    createJournal: (cas_id, body_html, lo_ids) =>
      post(`/api/experiences/${cas_id}/journal`, { body_html, lo_ids }),
    editJournal:   (rid, cas_id, body_html, lo_ids) =>
      post(`/api/reflections/${rid}/edit`, { cas_id, body_html, lo_ids }),

    // ── Album ───────────────────────────────────────────────────────────
    // files = File[], captions = string[], lo_ids = number[]|null
    createAlbum: (cas_id, files, captions, lo_ids, date) => {
      const form = new FormData();
      files.forEach((f, i) => {
        form.append("photos", f);
        form.append("captions", (captions && captions[i]) || "");
      });
      if (lo_ids) form.append("lo_ids", JSON.stringify(lo_ids));
      if (date)   form.append("date", date);
      return postForm(`/api/experiences/${cas_id}/album`, form);
    },
    addPhotos: (rid, cas_id, files, caption) => {
      const form = new FormData();
      files.forEach(f => form.append("photos", f));
      form.append("caption", caption || "");
      form.append("cas_id", String(cas_id));
      return postForm(`/api/reflections/${rid}/album/photos`, form);
    },
    albumPhotos:  (rid, cas_id) => get(`/api/reflections/${rid}/album/photos?cas_id=${cas_id}`),
    deletePhoto: (rid, photo_id, cas_id) =>
      del(`/api/reflections/${rid}/album/photos/${photo_id}?cas_id=${cas_id}`),

    // ── Files ───────────────────────────────────────────────────────────
    // files = File[] (any type), lo_ids = number[]|null
    createFile: (cas_id, files, lo_ids, date) => {
      const form = new FormData();
      files.forEach((f) => form.append("files", f));
      if (lo_ids) form.append("lo_ids", JSON.stringify(lo_ids));
      if (date)   form.append("date", date);
      return postForm(`/api/experiences/${cas_id}/file`, form);
    },

    // ── AI ──────────────────────────────────────────────────────────────
    // For kind="edit", pass `existing` (current journal body) — AI revises it
    // using `notes` as modification instructions.
    // For kind="final" (or any kind where past reflections should ground the
    // output), pass include_history=true; the server loads all non-placeholder
    // reflections for cas_id from the local DB and injects them as context.
    buildPrompt:  (cas_id, notes, kind, date, existing, include_history) =>
      post("/api/ai/prompt", {
        cas_id, notes, kind: kind || "reflection", date, existing,
        include_history: !!include_history,
      }),
    generateAI:   (cas_id, notes, kind, date, existing, include_history) =>
      post("/api/ai/generate", {
        cas_id, notes, kind: kind || "reflection", date, existing,
        include_history: !!include_history,
      }),

    // ── Self-Assessment answers ─────────────────────────────────────────
    saQuestions: (cas_id) => get(`/api/experiences/${cas_id}/sa`),
    saveSA:      (cas_id, name, text) => post(`/api/experiences/${cas_id}/sa`, { name, text }),
    saPrompt:    (cas_id, question, notes, existing) =>
      post("/api/ai/sa_prompt",   { cas_id, question, notes, existing }),
    saGenerate:  (cas_id, question, notes, existing) =>
      post("/api/ai/sa_generate", { cas_id, question, notes, existing }),

    // ── Prompts (system-prompt slot management) ────────────────────────
    prompts:        ()           => get("/api/prompts"),
    prompt:         (slot)       => get(`/api/prompts/${encodeURIComponent(slot)}`),
    savePrompt:     (slot, body) => put(`/api/prompts/${encodeURIComponent(slot)}`, { body }),
    resetPrompt:    (slot)       => del(`/api/prompts/${encodeURIComponent(slot)}`),

    // ── Queue & schedules ───────────────────────────────────────────────
    queue:          () => get("/api/queue"),
    placeholder:    (cas_id) => post("/api/placeholder/run", { cas_id }),
    runAllDue:      () => post("/api/placeholder/run", {}),
    schedules:      () => get("/api/schedules"),
    saveSchedule:   (cas_id, data) => post(`/api/schedules/${cas_id}`, data),
    deleteSchedule: (cas_id) => del(`/api/schedules/${cas_id}`),
  };
})();
