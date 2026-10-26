#!/usr/bin/env python3
"""
cas_offline_export.py — Merge one or more CAS Manager databases into a single
offline archive you can open in any browser, without ManageBac.

    python3 cas_offline_export.py A.db B.db C.db -o CAS_offline

Writes:
    CAS_offline/index.html    every experience, proposal and reflection
    CAS_offline/photos/       any photos that could still be downloaded
    CAS_offline/merged.json   all merged data, machine-readable

Merging: rows are matched by their ManageBac id. When the same reflection
appears in several databases, the copy with text (and the latest sync) wins,
so a reflection that only survives in an older database is still kept.

Only the Python standard library is used. The input databases are opened
read-only and never modified.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import html
import json
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path


# ── Reading ──────────────────────────────────────────────────────────────────

def _rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return []
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]


def read_db(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return {t: _rows(conn, t)
                for t in ("experiences", "reflections", "photos", "drafts")}
    finally:
        conn.close()


def _loads(s, default):
    try:
        v = json.loads(s) if s else default
        return v if isinstance(v, type(default)) else default
    except (TypeError, ValueError):
        return default


def _has_text(body: str | None) -> bool:
    return bool(re.sub(r"<[^>]+>|&nbsp;|\s", "", body or ""))


# ── Merging ──────────────────────────────────────────────────────────────────

def merge(dbs: list[tuple[str, dict]]) -> dict:
    exps: dict[int, dict] = {}
    refls: dict[int, dict] = {}
    photos: dict[int, dict[str, dict]] = {}   # reflection id -> s3 key -> photo
    drafts: dict[tuple, dict] = {}

    for label, db in dbs:
        for e in db["experiences"]:
            cur = exps.get(e["id"])
            score = (bool(e.get("proposal_text")), e.get("synced_at") or "")
            if cur is None or score > cur["_score"]:
                exps[e["id"]] = {**e, "_score": score, "_source": label}

        for r in db["reflections"]:
            cur = refls.get(r["id"])
            score = (_has_text(r.get("body_html")),
                     r.get("files_json") not in (None, "", "[]"),
                     r.get("synced_at") or "")
            sources = (cur["_sources"] if cur else []) + [label]
            if cur is None or score > cur["_score"]:
                refls[r["id"]] = {**r, "_score": score, "_source": label,
                                  "_sources": sources}
            else:
                cur["_sources"] = sources

        for p in db["photos"]:
            url = p.get("s3_url") or ""
            if not url:
                continue
            # The S3 object key is stable; only the signature in the query
            # string changes between syncs. Keep every URL variant to try.
            key = url.split("?", 1)[0]
            slot = photos.setdefault(p["reflection_id"], {})
            item = slot.setdefault(key, {"key": key, "urls": [],
                                         "caption": "", "file": None})
            if url not in item["urls"]:
                item["urls"].append(url)
            if p.get("caption") and not item["caption"]:
                item["caption"] = p["caption"]

        for d in db["drafts"]:
            k = (d.get("cas_id"), d.get("note"), d.get("created_at"))
            cur = drafts.get(k)
            if cur is None or (d.get("ai_result") and not cur.get("ai_result")):
                drafts[k] = d

    # Reflections whose experience row is missing still get a section.
    for r in refls.values():
        exps.setdefault(r["cas_id"], {"id": r["cas_id"],
                                      "name": f"Experience {r['cas_id']}",
                                      "_source": "?"})
    return {"experiences": exps, "reflections": refls,
            "photos": photos, "drafts": list(drafts.values())}


# ── Photo download ───────────────────────────────────────────────────────────

def _ext(key: str) -> str:
    m = re.search(r"\.(jpe?g|png|gif|webp|heic|heif|bmp|tiff?)$", key, re.I)
    return "." + m.group(1).lower() if m else ".jpg"


def _fetch(item: dict, out_dir: Path) -> str | None:
    name = hashlib.md5(item["key"].encode()).hexdigest()[:16] + _ext(item["key"])
    dest = out_dir / name
    if dest.exists() and dest.stat().st_size > 0:
        return name
    for url in item["urls"] + [item["key"]]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            if data and not data.lstrip().startswith(b"<"):   # not an XML error page
                dest.write_bytes(data)
                return name
        except Exception:
            continue
    return None


def download_photos(photos: dict, out_dir: Path) -> tuple[int, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    items = [it for slot in photos.values() for it in slot.values()]
    if not items:
        return 0, 0
    ok = 0
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_fetch, it, out_dir): it for it in items}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            futs[fut]["file"] = fut.result()
            ok += futs[fut]["file"] is not None
            print(f"\r  photos: {i}/{len(items)} tried, {ok} saved", end="", flush=True)
    print()
    return ok, len(items)


# ── HTML ─────────────────────────────────────────────────────────────────────

_SCRIPT_RE = re.compile(r"<(script|iframe|object|embed)\b.*?(</\1>|$)", re.I | re.S)
_ON_ATTR_RE = re.compile(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)


def _clean_body(body: str) -> str:
    return _ON_ATTR_RE.sub("", _SCRIPT_RE.sub("", body or ""))


def _esc(s) -> str:
    return html.escape(str(s or ""))


_KIND_LABEL = {"journal": "Journal", "album": "Album", "file": "File",
               "website": "Website", "video": "Video", "unknown": "Entry"}

_CSS = """
:root{--bg:#fafaf8;--card:#fff;--ink:#1c1c1a;--muted:#6b6b66;--line:#e4e3de;--accent:#2f6f5e;--chip:#eef3f1}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--ink:#ecebe6;--muted:#a19f98;--line:#33322f;--accent:#7cc2ad;--chip:#243330}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:32px 16px 80px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:22px;margin:0}
.muted{color:var(--muted);font-size:14px}
nav{margin:24px 0 40px;padding:16px;background:var(--card);border:1px solid var(--line);border-radius:12px}
nav ol{margin:8px 0 0;padding-left:22px}nav a{color:var(--accent);text-decoration:none}
section.exp{margin:0 0 56px}
.exp-head{border-bottom:2px solid var(--accent);padding-bottom:8px;margin-bottom:16px}
.chip{display:inline-block;background:var(--chip);color:var(--accent);font-size:12px;padding:2px 8px;border-radius:99px;margin:4px 4px 0 0}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:0 0 16px}
summary{cursor:pointer;font-weight:600}
.refl{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:0 0 14px}
.refl-meta{display:flex;gap:10px;flex-wrap:wrap;font-size:13px;color:var(--muted);margin-bottom:6px}
.refl-body{overflow-wrap:anywhere}.refl-body img{max-width:100%}
.photos{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;margin-top:10px}
.photos figure{margin:0}.photos img{width:100%;border-radius:6px;display:block}
.photos figcaption{font-size:12px;color:var(--muted)}
.lost{font-size:13px;color:var(--muted);border:1px dashed var(--line);border-radius:6px;padding:6px 10px;margin-top:8px}
pre.draft{white-space:pre-wrap;font:inherit;margin:6px 0 0}
"""


def render(m: dict, title: str, stats: dict) -> str:
    exps = sorted(m["experiences"].values(),
                  key=lambda e: (e.get("is_completed") or 0, e.get("name") or ""))
    by_exp: dict[int, list[dict]] = {}
    for r in m["reflections"].values():
        by_exp.setdefault(r["cas_id"], []).append(r)
    drafts_by_exp: dict[int, list[dict]] = {}
    for d in m["drafts"]:
        drafts_by_exp.setdefault(d.get("cas_id"), []).append(d)

    out = [f"<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>{_esc(title)}</title><style>{_CSS}</style></head><body><div class='wrap'>",
           f"<h1>{_esc(title)}</h1>",
           f"<p class='muted'>生成于 {datetime.now():%Y-%m-%d %H:%M} · "
           f"{stats['exps']} 个 experience · {stats['with_text']} 条有正文的 reflection"
           f"（共 {stats['refls']} 条，含空白占位）· 照片 {stats['ph_ok']}/{stats['ph_all']} 张已保存</p>",
           "<nav><strong>目录</strong><ol>"]
    for e in exps:
        n = sum(_has_text(r.get("body_html")) for r in by_exp.get(e["id"], []))
        out.append(f"<li><a href='#e{e['id']}'>{_esc(e.get('name'))}</a> "
                   f"<span class='muted'>· {n} 条</span></li>")
    out.append("</ol></nav>")

    for e in exps:
        out.append(f"<section class='exp' id='e{e['id']}'><div class='exp-head'>"
                   f"<h2>{_esc(e.get('name'))}</h2><div>")
        if e.get("strand"):
            out.append(f"<span class='chip'>{_esc(e['strand'])}</span>")
        out.append(f"<span class='chip'>{'已完成' if e.get('is_completed') else '进行中'}</span>")
        if e.get("is_deleted"):
            out.append("<span class='chip'>ManageBac 上已删除</span>")
        out.append(f"<span class='chip'>ManageBac ID {e['id']}</span></div></div>")

        if e.get("proposal_text"):
            out.append(f"<details><summary>Proposal</summary>"
                       f"<pre class='draft'>{_esc(e['proposal_text'])}</pre></details>")
        los = _loads(e.get("lo_names"), [])
        if los:
            out.append("<details><summary>Learning Outcomes</summary><ul>"
                       + "".join(f"<li>{_esc(x)}</li>" for x in los) + "</ul></details>")

        rs = sorted(by_exp.get(e["id"], []), key=lambda r: r["id"])
        empty = 0
        for r in rs:
            body = r.get("body_html") or ""
            phs = list(m["photos"].get(r["id"], {}).values())
            files = _loads(r.get("files_json"), [])
            if not _has_text(body) and not phs and not files:
                empty += 1
                continue
            out.append("<article class='refl'><div class='refl-meta'>"
                       f"<span>{_esc(r.get('group_date') or '无日期')}</span>"
                       f"<span>{_KIND_LABEL.get(r.get('kind'), 'Entry')}</span>"
                       f"<span>#{r['id']}</span></div>")
            if _has_text(body):
                out.append(f"<div class='refl-body'>{_clean_body(body)}</div>")
            if phs:
                saved = [p for p in phs if p.get("file")]
                if saved:
                    out.append("<div class='photos'>")
                    for p in saved:
                        out.append(f"<figure><a href='photos/{p['file']}'>"
                                   f"<img loading='lazy' src='photos/{p['file']}' alt=''></a>"
                                   + (f"<figcaption>{_esc(p['caption'])}</figcaption>" if p["caption"] else "")
                                   + "</figure>")
                    out.append("</div>")
                lost = [p for p in phs if not p.get("file")]
                if lost:
                    caps = "；".join(_esc(p["caption"]) for p in lost if p["caption"])
                    out.append(f"<div class='lost'>{len(lost)} 张照片未能下载"
                               + (f"（说明：{caps}）" if caps else "") + "</div>")
            if files:
                out.append("<div class='lost'>附件（文件本体未保存）："
                           + "；".join(f"{_esc(f.get('name'))} {_esc(f.get('size'))}" for f in files)
                           + "</div>")
            out.append("</article>")
        if empty:
            out.append(f"<p class='muted'>另有 {empty} 条空白占位 reflection 未显示。</p>")

        ds = [d for d in drafts_by_exp.get(e["id"], []) if d.get("note") or d.get("ai_result")]
        if ds:
            out.append(f"<details><summary>软件里的草稿（{len(ds)}）</summary>")
            for d in sorted(ds, key=lambda d: d.get("created_at") or ""):
                out.append(f"<div class='refl'><div class='refl-meta'><span>{_esc(d.get('created_at'))}</span>"
                           f"<span>{_esc(d.get('status'))}</span></div>"
                           f"<strong>笔记</strong><pre class='draft'>{_esc(d.get('note'))}</pre>")
                if d.get("ai_result"):
                    out.append(f"<strong>生成结果</strong><pre class='draft'>{_esc(d['ai_result'])}</pre>")
                out.append("</div>")
            out.append("</details>")
        out.append("</section>")
    out.append("</div></body></html>")
    return "\n".join(out)


# ── Main ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dbs", nargs="+", type=Path, help="cas_data.db files to merge")
    ap.add_argument("-o", "--out", type=Path, default=Path("CAS_offline"))
    ap.add_argument("--title", default="My CAS Portfolio")
    ap.add_argument("--no-download", action="store_true",
                    help="skip trying to download photos")
    a = ap.parse_args(argv)

    loaded = []
    for p in a.dbs:
        if not p.exists():
            print(f"skip (not found): {p}", file=sys.stderr)
            continue
        db = read_db(p)
        print(f"read {p.name}: {len(db['experiences'])} experiences, "
              f"{len(db['reflections'])} reflections, {len(db['photos'])} photos, "
              f"{len(db['drafts'])} drafts")
        loaded.append((p.name, db))
    if not loaded:
        print("no databases read", file=sys.stderr)
        return 1

    m = merge(loaded)
    a.out.mkdir(parents=True, exist_ok=True)
    ph_all = sum(len(s) for s in m["photos"].values())
    ph_ok = 0
    if not a.no_download:
        ph_ok, ph_all = download_photos(m["photos"], a.out / "photos")

    stats = {"exps": len(m["experiences"]), "refls": len(m["reflections"]),
             "with_text": sum(_has_text(r.get("body_html")) for r in m["reflections"].values()),
             "ph_ok": ph_ok, "ph_all": ph_all}
    (a.out / "index.html").write_text(render(m, a.title, stats), encoding="utf-8")

    def _plain(d: dict) -> dict:
        return {k: v for k, v in d.items() if k != "_score"}
    dump = {"experiences": [_plain(e) for e in m["experiences"].values()],
            "reflections": [_plain(r) for r in m["reflections"].values()],
            "photos": {str(k): list(v.values()) for k, v in m["photos"].items()},
            "drafts": m["drafts"]}
    (a.out / "merged.json").write_text(json.dumps(dump, ensure_ascii=False, indent=1),
                                       encoding="utf-8")

    print(f"\nmerged: {stats['exps']} experiences, {stats['refls']} reflections "
          f"({stats['with_text']} with text), photos saved {ph_ok}/{ph_all}")
    print(f"open: {(a.out / 'index.html').resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
