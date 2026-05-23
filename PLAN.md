# CAS Manager — Dev Build Plan

## 目标
将 `New_design_interface/` 里的视觉原型接入真实后端，交付一个可以完整操作的 Web App。
保留原型的所有视觉组件（CSS、布局、颜色系统），用真实 API 替换所有 mock 数据和交互逻辑。

## 项目现状

### 目录结构
```
CAS_manager_dev/          ← 开发目录（git dev 分支）
├── cas_api.py            ← ManageBac HTTP 层（requests + BeautifulSoup）
├── cas_controller.py     ← 业务逻辑层
├── cas_db.py             ← SQLite 本地缓存
├── cas_web.py            ← Flask 服务器（port 5173）
├── cas_errors.py         ← 统一错误类
├── mb_login.py           ← 登录模块（email/password → auth_token）
├── mb_state.json         ← session 存储（gitignored）
├── cas_config.json       ← 用户配置（gitignored）
├── cas_data.db           ← 本地数据库（gitignored）
└── templates/
    └── index.html        ← 旧 GUI（待替换）

New_design_interface/     ← 视觉原型（只读参考，不直接修改）
├── CAS Manager - Mono Prototype.html
├── mono-prototype.jsx    ← 主组件
├── mono-shell.jsx        ← 布局：侧边栏 + 主面板
├── mono-modals.jsx       ← 所有 Modal 组件
├── mono-modal-shell.jsx  ← Modal 容器
├── mono-settings-hub.jsx ← Settings + Placeholder Hub
├── mono-theme.jsx        ← 主题 token
├── icons.jsx             ← 图标
└── data.jsx              ← Mock 数据（参考数据结构用）
```

### 已完成的后端改动（dev 分支）
- `mb_login.py`：email + password 直接登录，返回 1 年期 auth_token
- `cas_api.py`：`refresh_session()` 静默刷新；`build_session()` 修复空 domain bug
- `cas_controller.py`：session 过期时自动 refresh
- `cas_errors.py`：统一错误类 `SessionExpiredError`、`ScraperError`

### ManageBac 认证机制（已逆向）
- `POST https://<school>.managebac.cn/sessions.json`
  - body: `{"auth_type":"password","login":"email","password":"pwd","client_type":"ios","app_version":"2.20.2","lang":"zh"}`
  - 返回：`share_auth_token` + `_managebac_session` cookie（有效期 1 年）
- CAS 操作走普通 web 接口（非 mobile API），需要 `_managebac_session` + `X-CSRF-Token`

---

## 分阶段任务

---

### Phase 1：后端 API 规范化

**目标：让 API 返回前端可以直接用的数据格式。**

#### 1.1 统一字段命名和日期格式

修改 `cas_web.py` 中所有返回体：
- `cas_id` → `id`（向前端暴露时统一用 `id`）
- `group_date` 保持原始英文格式（如 "March 17, 2026"），同时增加 `date_iso` 字段（"2026-03-17"）
- `lo_names` 保持原样，增加 `lo_display` 字段，格式为 `["LO1 · Strengths & Growth", ...]`（按 LO 序号前缀拼接）

LO 序号对照（`cas_api.py` 里的 `LO_IDS`）：
```
142285 → "LO1 · Strengths & Growth"
142286 → "LO2 · Challenge & Skills"
142287 → "LO3 · Initiative & Planning"
142288 → "LO4 · Commitment & Perseverance"
142289 → "LO5 · Collaborative Skills"
142290 → "LO6 · Global Engagement"
142291 → "LO7 · Ethics"
```

**`GET /api/experiences` 响应格式（目标）：**
```json
{
  "ok": true,
  "data": [
    {
      "id": 17581110,
      "name": "Badminton Club",
      "strand": "activity",
      "is_completed": false,
      "reflection_count": 5,
      "lo_display": ["LO1 · Strengths & Growth", "LO5 · Collaborative Skills"],
      "synced_at": "2026-05-22T10:30:00"
    }
  ]
}
```

**`GET /api/experiences/<id>/reflections` 响应格式（目标）：**
```json
{
  "ok": true,
  "data": [
    {
      "id": 29472229,
      "kind": "journal",
      "group_date": "March 17, 2026",
      "date_iso": "2026-03-17",
      "body_html": "<p>...</p>",
      "body_preview": "首150字纯文本预览...",
      "photo_list": [
        {"id": 123, "caption": "...", "s3_url": "https://..."}
      ],
      "lo_display": ["LO1 · Strengths & Growth"],
      "is_placeholder": false
    }
  ]
}
```

#### 1.2 登录端点重写

`cas_web.py` 的 `/api/login/start` 改为接收 email + password：

```python
@app.route("/api/login/start", methods=["POST"])
def api_login_start():
    import mb_login
    data = request.get_json() or {}
    email = data.get("email", "").strip()
    password = data.get("password", "")
    if not email or not password:
        return _err("请填写邮箱和密码", 400)
    try:
        state = mb_login.login_with_password(email, password,
                                              ctrl.ctrl_config()["base"])
        mb_login.save_state(state)
        return _ok({"message": "登录成功"})
    except RuntimeError as e:
        return _err(str(e), 401)
```

去掉 `/api/login/confirm` 端点（不再需要）。
`/api/login/status` 保留，只返回 `{"logged_in": bool}`。

#### 1.3 图片上传改为 multipart

`/api/experiences/<id>/album` 现在接收本地路径字符串，改为接收真实文件：

```python
@app.route("/api/experiences/<int:cas_id>/album", methods=["POST"])
def api_create_album(cas_id):
    # 从 multipart form 读取文件
    files = request.files.getlist("photos")
    captions = request.form.getlist("captions")
    lo_ids = json.loads(request.form.get("lo_ids", "[]"))
    date = request.form.get("date") or None

    if not files:
        return _err("请选择至少一张图片", 400)

    photos = []
    for i, f in enumerate(files):
        caption = captions[i] if i < len(captions) else ""
        photos.append((f.filename, f.read(), caption))

    # 调 cas_api.create_album(s, base, cas_id, csrf, lo_ids, photos, date)
    ...
```

`/api/reflections/<rid>/album/photos` (POST) 同样改为 multipart。

#### 1.4 新增 DELETE /api/reflections/<rid>

```python
@app.route("/api/reflections/<int:rid>", methods=["DELETE"])
def api_delete_reflection(rid):
    cas_id = request.args.get("cas_id", type=int)
    if not cas_id:
        return _err("缺少 cas_id 参数", 400)
    # 从 config 检查 danger_zone_enabled
    cfg = ctrl.ctrl_config()
    if not cfg.get("danger_zone_enabled", False):
        return _err("删除功能未开启，请在设置中开启 Danger Zone", 403)
    try:
        ctrl.ctrl_delete_reflection(cas_id, rid)
        return _ok()
    except Exception as e:
        return _err(str(e))
```

在 `cas_controller.py` 中实现 `ctrl_delete_reflection(cas_id, rid)`，调用 `cas_api.delete_reflection()` 并从 DB 删除记录。

#### 1.5 修复 cas_api.py 中已知 bug

按优先级修复：

**a. `lo_names_to_ids()` 兜底不能返回全部 LO**（[cas_api.py:499](cas_api.py#L499)）
```python
# 改为：匹配不到时返回空列表，调用方自行决定默认值
return ids  # 不再 fallback 到 list(LO_IDS.values())
```

**b. `enrich()` body 提取失败不静默**（[cas_api.py:416](cas_api.py#L416)）
```python
# textarea 没找到时抛出 ScraperError 而不是静默
if not body_found:
    raise ScraperError(f"rid={entry.rid}: body textarea not found, ManageBac DOM may have changed")
```

**c. `cleanup_placeholders()` 不吃掉所有异常**（[cas_api.py:814](cas_api.py#L814)）
```python
except ScraperError:
    pass  # DOM 解析失败时跳过该条目
except Exception as e:
    raise  # session 失效等严重错误要往上抛
```

**d. `parse_proposal()` 重复 import 清理**（[cas_api.py:185](cas_api.py#L185)）
```python
# 删掉函数内的 import html as _html，顶部已有
```

#### 1.6 `cas_config.json` 增加新字段

在 `cas_controller.py` 的 `_CONFIG_DEFAULTS` 里增加：
```python
"danger_zone_enabled": False,
"ai_system_prompt": "",   # 用户自定义 system prompt，空字符串=使用默认
```

`ctrl_ai_generate()` 里，如果 `ai_system_prompt` 非空，将其注入到 AI 调用的 system message。

---

### Phase 2：新 GUI 集成到 Flask

**目标：Flask 改为 serve 新 GUI，旧 `templates/index.html` 退役。**

#### 2.1 目录调整

在 `CAS_manager_dev/` 下新建：
```
static/
  ├── jsx/          ← 从 New_design_interface/ 复制过来的 JSX 文件
  │   ├── api.js              ← 新建
  │   ├── mono-prototype.jsx
  │   ├── mono-shell.jsx
  │   ├── mono-modals.jsx
  │   ├── mono-modal-shell.jsx
  │   ├── mono-settings-hub.jsx
  │   ├── mono-theme.jsx
  │   └── icons.jsx
  └── (其他静态资源)

templates/
  └── index.html    ← 替换为新 GUI 入口
```

#### 2.2 新 `templates/index.html`

参考 `New_design_interface/CAS Manager - Mono Prototype.html` 的结构，但把 JSX src 改为指向 `static/jsx/`：

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>CAS Manager</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <!-- 样式直接从原型复制 <style> 块 -->
</head>
<body>
<div id="mono-proto-root"></div>
<script src="https://unpkg.com/react@18.3.1/umd/react.development.js" ...></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js" ...></script>
<script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js" ...></script>
<script type="text/babel" src="/static/jsx/api.js"></script>
<script type="text/babel" src="/static/jsx/icons.jsx"></script>
<script type="text/babel" src="/static/jsx/mono-theme.jsx"></script>
<script type="text/babel" src="/static/jsx/mono-shell.jsx"></script>
<script type="text/babel" src="/static/jsx/mono-modal-shell.jsx"></script>
<script type="text/babel" src="/static/jsx/mono-modals.jsx"></script>
<script type="text/babel" src="/static/jsx/mono-settings-hub.jsx"></script>
<script type="text/babel" src="/static/jsx/mono-prototype.jsx"></script>
</body>
</html>
```

#### 2.3 `cas_web.py` 调整

```python
app = Flask(__name__, static_folder="static", template_folder="templates")

@app.route("/")
def index():
    return render_template("index.html")
```

---

### Phase 3：写 api.js

新建 `static/jsx/api.js`，所有组件通过它访问后端，不直接写 fetch。

```javascript
// api.js — CAS Manager API client
// 所有方法返回 Promise<data>，失败时 throw Error(message)

const _base = "";  // 同源，空字符串即可

async function _req(method, path, body, isForm = false) {
  const opts = { method, headers: {} };
  if (body) {
    if (isForm) {
      opts.body = body;  // FormData
    } else {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
  }
  const r = await fetch(_base + path, opts);
  const json = await r.json();
  if (!json.ok) throw new Error(json.error || "请求失败");
  return json.data;
}

const get  = (path)        => _req("GET",    path);
const post = (path, body)  => _req("POST",   path, body);
const del  = (path)        => _req("DELETE", path);
const postForm = (path, form) => _req("POST", path, form, true);

window.API = {
  // Status & config
  status:       () => get("/api/status"),
  getConfig:    () => get("/api/config"),
  saveConfig:   (cfg) => post("/api/config", cfg),

  // Login
  loginStatus:  () => get("/api/login/status"),
  login:        (email, password) => post("/api/login/start", { email, password }),

  // Experiences
  experiences:  () => get("/api/experiences"),
  experience:   (id) => get(`/api/experiences/${id}`),
  syncAll:      () => post("/api/sync/all"),
  syncOne:      (id) => post(`/api/sync/${id}`),

  // Reflections
  reflections:  (id) => get(`/api/experiences/${id}/reflections`),
  deleteRefl:   (rid, cas_id) => del(`/api/reflections/${rid}?cas_id=${cas_id}`),

  // Journal
  createJournal: (cas_id, body_html, lo_ids) =>
    post(`/api/experiences/${cas_id}/journal`, { body_html, lo_ids }),
  editJournal:   (rid, cas_id, body_html, lo_ids) =>
    post(`/api/reflections/${rid}/edit`, { cas_id, body_html, lo_ids }),

  // Album
  createAlbum: (cas_id, files, captions, lo_ids, date) => {
    const form = new FormData();
    files.forEach((f, i) => {
      form.append("photos", f);
      form.append("captions", captions[i] || "");
    });
    form.append("lo_ids", JSON.stringify(lo_ids));
    if (date) form.append("date", date);
    return postForm(`/api/experiences/${cas_id}/album`, form);
  },
  addPhotos: (rid, cas_id, files, caption) => {
    const form = new FormData();
    files.forEach(f => form.append("photos", f));
    form.append("caption", caption || "");
    form.append("cas_id", cas_id);
    return postForm(`/api/reflections/${rid}/album/photos`, form);
  },
  deletePhoto: (rid, photo_id, cas_id) =>
    del(`/api/reflections/${rid}/album/photos/${photo_id}?cas_id=${cas_id}`),

  // AI
  buildPrompt:  (cas_id, notes, kind, date) =>
    post("/api/ai/prompt", { cas_id, notes, kind, date }),
  generateAI:   (cas_id, notes, kind, date) =>
    post("/api/ai/generate", { cas_id, notes, kind, date }),

  // Queue & schedules
  queue:          () => get("/api/queue"),
  placeholder:    (cas_id) => post("/api/placeholder/run", { cas_id }),
  schedules:      () => get("/api/schedules"),
  saveSchedule:   (cas_id, data) => post(`/api/schedules/${cas_id}`, data),
  deleteSchedule: (cas_id) => del(`/api/schedules/${cas_id}`),
};
```

---

### Phase 4：改造 JSX 组件

从 `New_design_interface/` 复制所有 JSX 到 `static/jsx/`，然后逐一改造。

#### 4.1 mono-prototype.jsx（根组件）

替换 `useState` 里的 mock 数据初始化：

```javascript
// 删除
// const [experiences, setExperiences] = useState(EXPERIENCES);

// 改为
const [experiences, setExperiences] = useState([]);
const [status, setStatus] = useState("loading"); // "loading"|"ok"|"error"|"unauthed"
const [syncStatus, setSyncStatus] = useState("idle"); // "idle"|"syncing"|"error"

useEffect(() => {
  API.status()
    .then(s => {
      if (!s.logged_in) { setStatus("unauthed"); return; }
      setStatus("ok");
      return API.experiences();
    })
    .then(exps => { if (exps) setExperiences(exps); })
    .then(() => {
      setSyncStatus("syncing");
      return API.syncAll();
    })
    .then(() => {
      setSyncStatus("idle");
      return API.experiences();
    })
    .then(exps => { if (exps) setExperiences(exps); })
    .catch(e => {
      if (e.message?.includes("session")) setStatus("unauthed");
      else setSyncStatus("error");
    });
}, []);
```

**状态指示点**（传给 Header/UserDock）：
- `status === "unauthed"` → 红点
- `syncStatus === "syncing"` → 黄点
- `status === "ok" && syncStatus === "idle"` → 绿点

#### 4.2 mono-shell.jsx（侧边栏 + 主面板）

侧边栏：
- `experiences` prop 直接渲染（数据已是真实数据）
- 选中 experience 时：`API.reflections(id)` 获取反思列表
- 搜索框：本地过滤 `experiences` 数组，不需要 API

主面板：
- 反思卡片根据 `kind` 渲染（journal 显示 `body_preview`，album 显示图片网格）
- 图片 src 用 `photo.s3_url`，加 `onError` 回调（URL 过期时触发 `API.syncOne(cas_id)`）

#### 4.3 mono-modals.jsx

**NewJournalModal（手写模式）：**
```javascript
async function handleSave(bodyHtml, loIds) {
  setLoading(true);
  try {
    await API.createJournal(activeCasId, bodyHtml, loIds);
    await refreshReflections();
    onClose();
  } catch (e) {
    setError(e.message);
  } finally {
    setLoading(false);
  }
}
```

**AIGenerateModal（三步流程）：**
- Step 1：笔记输入（本地状态）
- Step 2：`API.buildPrompt()` → 展示 prompt 让用户复制到 AI
- Step 3：用户粘贴 AI 回复 → `API.createJournal()` 提交

如果 AI provider 是 anthropic/ollama（`status.ai_provider !== "prompt"`）：
- Step 2 直接调 `API.generateAI()` → 跳到 Step 3 展示结果

**NewPhotosModal（图片上传）：**
```javascript
// 拖拽区域
function handleDrop(e) {
  e.preventDefault();
  const files = [...e.dataTransfer.files].filter(f => f.type.startsWith("image/"));
  setSelectedFiles(prev => [...prev, ...files]);
}

// 上传
async function handleUpload() {
  setLoading(true);
  try {
    await API.createAlbum(activeCasId, selectedFiles, captions, loIds, date);
    await refreshReflections();
    onClose();
  } catch (e) {
    setError(e.message);
  } finally {
    setLoading(false);
  }
}
```

#### 4.4 mono-settings-hub.jsx

**Settings → Account tab：**

替换原来的"open browser + confirm"流程：
```javascript
const [email, setEmail] = useState("");
const [password, setPassword] = useState("");
const [loginState, setLoginState] = useState("idle"); // "idle"|"loading"|"ok"|"error"

async function handleLogin() {
  setLoginState("loading");
  try {
    await API.login(email, password);
    setLoginState("ok");
    // 触发外层重新拉取 status
    onLoginSuccess();
  } catch (e) {
    setLoginState("error");
    setLoginError(e.message);
  }
}
```

UI 展示：
- 未登录（status = unauthed）：显示邮箱/密码表单 + 登录按钮
- 已登录：显示"已连接 ✓" + "重新登录"按钮

**Settings → AI tab：**
新增 system prompt 文本区（对应 `config.ai_system_prompt`）：
```javascript
<textarea
  placeholder="留空使用默认 prompt。在此输入你的学校对 CAS 反思格式的特殊要求..."
  value={config.ai_system_prompt}
  onChange={e => updateConfig("ai_system_prompt", e.target.value)}
  rows={5}
/>
```

**Settings → Danger Zone（新增 tab 或折叠区）：**
```javascript
<div style={{borderTop: "1px solid rgba(0,0,0,0.08)", paddingTop: 16, marginTop: 16}}>
  <div style={{color: "#c0392b", fontWeight: 600, marginBottom: 8}}>Danger Zone</div>
  <label style={{display:"flex", alignItems:"center", gap: 8}}>
    <input type="checkbox"
      checked={config.danger_zone_enabled}
      onChange={e => updateConfig("danger_zone_enabled", e.target.checked)} />
    开启删除功能（在反思卡片上显示删除按钮）
  </label>
</div>
```

**Placeholder Hub：**
- 打开时：并行调 `API.schedules()` + `API.queue()`
- "Start here" 按钮：带 `{rid, body_html, group_date}` 跳转到 AIGenerateModal step 1，预填笔记区

---

### Phase 5：Loading / Error 状态

每个 Modal 需要统一的 loading 和 error 展示，复用原型里已有的 `mono-modal-shell.jsx` 容器。

**建议在 `mono-modal-shell.jsx` 里加 footer slot：**
```javascript
// Modal footer 传 loading 时显示 spinner，传 error 时显示红色提示
function ModalShell({ title, onClose, loading, error, children, footer }) {
  return (
    <div ...>
      {/* header */}
      <div ...>{title}</div>
      {/* body */}
      <div ...>{children}</div>
      {/* error */}
      {error && <div style={{color:"#c0392b", padding:"8px 0"}}>{error}</div>}
      {/* footer */}
      <div ...>{footer}</div>
    </div>
  );
}
```

---

### Phase 6：收尾

#### 6.1 验证 端到端流程
按顺序测试每个用户流：
1. 打开 App → 未登录 → Settings 输密码 → 登录成功 → 绿点
2. 侧边栏显示 experiences → 点击 → 显示反思列表
3. 新建 journal（手写）→ 提交 → 列表更新
4. 新建 journal（AI prompt 模式）→ 三步完成 → 列表更新
5. 新建 album → 拖拽上传图片 → 提交 → 列表更新
6. Settings → AI tab → 填 system prompt → 保存 → 再次生成验证生效
7. Settings → Danger Zone → 开启删除 → 反思卡片出现删除按钮 → 删除成功

#### 6.2 旧文件清理
- 删除或归档 `mb_login_signal.py`（已被 `mb_login.py` 替代）
- `templates/index.html` 替换为新 GUI 入口后，旧文件移到 `archive/`

#### 6.3 git commit 规范
每完成一个 Phase 提交一次：
```
git add <相关文件>
git commit -m "Phase N: 简短描述"
```

---

## 注意事项

1. **不要修改 `New_design_interface/` 里的文件**，只从中复制到 `static/jsx/`
2. **不要重构视觉组件**，只替换数据来源和事件处理函数
3. **每个 API 调用都要有 loading 和 error 状态**，不能让用户看到空白
4. **图片 s3_url 会过期**，`<img onError>` 需要触发 syncOne 并刷新
5. 测试时后端跑在 `python cas_web.py`（port 5173），前端同源不需要 CORS

## 完成标志

所有 Phase 6.1 的流程跑通，无 console error，提交到 dev 分支。
