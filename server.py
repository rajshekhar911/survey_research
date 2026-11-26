#!/usr/bin/env python3
"""Survey backend: consent -> product-choice screens -> thank-you/debrief.

Standard library only: http.server + sqlite3. Run:

    ADMIN_PASSWORD='choose-a-long-password' python3 server.py --port 8000

Participant site:  http://HOST:PORT/            (panel links: /?pid=ID&src=PANEL)
Admin dashboard:   http://HOST:PORT/admin       (HTTP basic auth, user "admin")
"""
import argparse
import base64
import csv
import hashlib
import hmac
import io
import json
import math
import os
import re
import secrets
import sqlite3
import statistics
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import design

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
STIMULI = design.load_stimuli()
N_TASKS = int(SETTINGS.get("n_tasks", 8))
MAX_BODY = 16 * 1024
MAX_EVENTS = 300
TASK_PAGES = {f"task_{i}" for i in range(N_TASKS)}
EVENT_TYPES = {"verify_open", "verify_close", "visibility_hidden", "visibility_visible"}

CONFIG = {"db": None, "admin_user": "admin", "admin_password": "", "salt": ""}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS respondents (
  id TEXT PRIMARY KEY,
  token TEXT UNIQUE NOT NULL,
  pid TEXT, source TEXT,
  seed INTEGER, design TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'started',
  current_page TEXT, created_at TEXT, updated_at TEXT, completed_at TEXT,
  user_agent TEXT, viewport TEXT, ip_hash TEXT,
  completion_code TEXT, flags TEXT
);
CREATE INDEX IF NOT EXISTS ix_resp_pid ON respondents(pid);
CREATE TABLE IF NOT EXISTS choices (
  respondent_id TEXT NOT NULL, task_index INTEGER NOT NULL,
  chosen_pos INTEGER NOT NULL, rt_ms INTEGER,
  created_at TEXT, PRIMARY KEY (respondent_id, task_index)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, respondent_id TEXT NOT NULL,
  page TEXT, type TEXT, detail TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_resp ON events(respondent_id);
"""


def db():
    con = sqlite3.connect(CONFIG["db"], timeout=15)
    con.row_factory = sqlite3.Row
    return con


def init_db(path):
    CONFIG["db"] = str(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = db()
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    con.commit()
    con.close()
    salt_file = Path(path).parent / ".salt"
    if not salt_file.exists():
        salt_file.write_text(secrets.token_hex(16))
        os.chmod(salt_file, 0o600)
    CONFIG["salt"] = salt_file.read_text().strip()


# ------------------------------------------------------------------- helpers

class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def clean_text(v, limit=200):
    return "" if v is None else str(v).replace("\x00", "")[:limit]


def clean_detail(obj):
    """Events carry small flat objects only."""
    if not isinstance(obj, dict) or len(obj) > 10:
        return {}
    out = {}
    for k, v in obj.items():
        if isinstance(v, (bool, int)) or v is None:
            out[clean_text(k, 30)] = v
        elif isinstance(v, float) and math.isfinite(v):
            out[clean_text(k, 30)] = v
        else:
            out[clean_text(k, 30)] = clean_text(v, 100)
    return out


def get_resp(con, token):
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{20,80}", token):
        raise ApiError(401, "invalid session")
    row = con.execute("SELECT * FROM respondents WHERE token=?", (token,)).fetchone()
    if row is None:
        raise ApiError(401, "session not found")
    return row


def redirect_url(template, code, pid):
    if not template:
        return ""
    return template.replace("{code}", code or "").replace("{pid}", pid or "")


def client_state(con, row):
    d = json.loads(row["design"])
    state = {
        "token": row["token"],
        "status": row["status"],
        "current_page": row["current_page"],
        "design": {"tasks": d["tasks"]},
        "categories": design.public_categories(STIMULI),
    }
    if row["status"] == "completed":
        state["completion_code"] = row["completion_code"]
        state["redirect"] = redirect_url(SETTINGS.get("completion_redirect"),
                                         row["completion_code"], row["pid"])
    return state


def public_settings():
    keys = ["study_title", "institution", "researcher_name", "contact_email",
            "ethics_ref", "estimated_minutes", "n_tasks"]
    return {k: SETTINGS.get(k) for k in keys}


# ------------------------------------------------------------- participant API

def api_start(body, handler):
    if body.get("consent") is not True:
        raise ApiError(400, "consent required")
    pid = clean_text(body.get("pid"), 100) or None
    source = clean_text(body.get("src"), 60) or None
    con = db()
    try:
        if pid:
            prev = con.execute(
                "SELECT * FROM respondents WHERE pid=? ORDER BY created_at DESC LIMIT 1",
                (pid,)).fetchone()
            if prev is not None:  # same panel ID: resume instead of a second entry
                return client_state(con, prev)
        seed = secrets.randbits(48)
        d = design.generate_design(STIMULI, seed, n_tasks=N_TASKS)
        rid = secrets.token_hex(8)
        token = secrets.token_urlsafe(32)
        ip_hash = hashlib.sha256((CONFIG["salt"] + handler.client_ip()).encode()).hexdigest()[:16]
        ts = now()
        con.execute(
            "INSERT INTO respondents (id, token, pid, source, seed, design, status,"
            " current_page, created_at, updated_at, user_agent, viewport, ip_hash)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, token, pid, source, seed, json.dumps(d), "started", "task_0", ts, ts,
             clean_text(handler.headers.get("User-Agent"), 300),
             clean_text(body.get("viewport"), 40), ip_hash))
        con.commit()
        row = con.execute("SELECT * FROM respondents WHERE id=?", (rid,)).fetchone()
        return client_state(con, row)
    finally:
        con.close()


def api_resume(body, handler):
    con = db()
    try:
        return client_state(con, get_resp(con, body.get("token")))
    finally:
        con.close()


def api_choice(body, handler):
    try:
        t = int(body.get("task"))
        pos = int(body.get("chosen_pos"))
    except (TypeError, ValueError):
        raise ApiError(400, "task and chosen_pos must be numbers")
    if not (0 <= t < N_TASKS and 0 <= pos < design.N_ALTS):
        raise ApiError(400, "out of range")
    ms = body.get("ms")
    ms = int(ms) if isinstance(ms, (int, float)) and 0 <= ms < 10**8 else None
    con = db()
    try:
        row = get_resp(con, body.get("token"))
        if row["status"] != "started":
            raise ApiError(409, f"survey already {row['status']}")
        ts = now()
        con.execute(
            "INSERT INTO choices (respondent_id, task_index, chosen_pos, rt_ms, created_at)"
            " VALUES (?,?,?,?,?) ON CONFLICT(respondent_id, task_index) DO UPDATE SET"
            " chosen_pos=excluded.chosen_pos, rt_ms=excluded.rt_ms, created_at=excluded.created_at",
            (row["id"], t, pos, ms, ts))
        nxt = f"task_{t + 1}" if t + 1 < N_TASKS else "finish"
        con.execute("UPDATE respondents SET current_page=?, updated_at=? WHERE id=?",
                    (nxt, ts, row["id"]))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


def api_event(body, handler):
    etype = body.get("type")
    if etype not in EVENT_TYPES:
        raise ApiError(400, "unknown event")
    con = db()
    try:
        row = get_resp(con, body.get("token"))
        n = con.execute("SELECT COUNT(*) FROM events WHERE respondent_id=?",
                        (row["id"],)).fetchone()[0]
        if n >= MAX_EVENTS:
            return {"ok": True, "dropped": True}
        con.execute("INSERT INTO events (respondent_id, page, type, detail, created_at)"
                    " VALUES (?,?,?,?,?)",
                    (row["id"], clean_text(body.get("page"), 40), etype,
                     json.dumps(clean_detail(body.get("detail") or {})), now()))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


def compute_flags(con, row):
    choices = [r["chosen_pos"] for r in con.execute(
        "SELECT chosen_pos FROM choices WHERE respondent_id=? ORDER BY task_index", (row["id"],))]
    duration = (datetime.now(timezone.utc)
                - datetime.fromisoformat(row["created_at"])).total_seconds()
    flags = {
        "duration_s": int(duration),
        "speeder": duration < SETTINGS.get("min_seconds", 40),
        "position_straightline": len(set(choices)) == 1,
    }
    flags["quality_pass"] = not flags["speeder"]
    return flags


def api_complete(body, handler):
    con = db()
    try:
        row = get_resp(con, body.get("token"))
        if row["status"] == "completed":
            return client_state(con, row)
        n = con.execute("SELECT COUNT(*) FROM choices WHERE respondent_id=?",
                        (row["id"],)).fetchone()[0]
        if n < N_TASKS:
            raise ApiError(409, f"survey incomplete: {N_TASKS - n} screens left")
        flags = compute_flags(con, row)
        code = "C" + secrets.token_hex(4).upper()
        ts = now()
        con.execute("UPDATE respondents SET status='completed', completed_at=?, updated_at=?,"
                    " current_page='finish', completion_code=?, flags=? WHERE id=?",
                    (ts, ts, code, json.dumps(flags), row["id"]))
        con.commit()
        row = con.execute("SELECT * FROM respondents WHERE id=?", (row["id"],)).fetchone()
        return client_state(con, row)
    finally:
        con.close()


# ------------------------------------------------------------------ admin API

def admin_stats():
    con = db()
    try:
        counts = {r["status"]: r["n"] for r in con.execute(
            "SELECT status, COUNT(*) n FROM respondents GROUP BY status")}
        done = con.execute("SELECT * FROM respondents WHERE status='completed'").fetchall()
        flags = [json.loads(r["flags"] or "{}") for r in done]
        durations = [f.get("duration_s", 0) for f in flags]
        flag_counts = {k: sum(1 for f in flags if f.get(k))
                       for k in ["speeder", "position_straightline", "quality_pass"]}
        per_day = [dict(r) for r in con.execute(
            "SELECT substr(completed_at,1,10) day, COUNT(*) n FROM respondents"
            " WHERE status='completed' GROUP BY day ORDER BY day")]
        good = {r["id"]: json.loads(r["design"]) for r in done
                if json.loads(r["flags"] or "{}").get("quality_pass")}
        shown, chosen = {}, {}
        for c in con.execute("SELECT respondent_id, task_index, chosen_pos FROM choices"):
            d = good.get(c["respondent_id"])
            if d is None:
                continue
            for a in d["tasks"][c["task_index"]]["alts"]:
                for attr in ("claim", "affect", "brand_type", "price_mult", "rating"):
                    key = (attr, str(a[attr]))
                    shown[key] = shown.get(key, 0) + 1
                    if a["pos"] == c["chosen_pos"]:
                        chosen[key] = chosen.get(key, 0) + 1
        shares = {}
        for (attr, level), n in sorted(shown.items()):
            shares.setdefault(attr, []).append(
                {"level": level, "shown": n, "chosen": chosen.get((attr, level), 0),
                 "share": round(chosen.get((attr, level), 0) / n, 3)})
        return {
            "counts": counts,
            "total": sum(counts.values()),
            "completed": len(done),
            "median_minutes": round(statistics.median(durations) / 60, 1) if durations else None,
            "flags": flag_counts,
            "per_day": per_day,
            "choice_shares": shares,
        }
    finally:
        con.close()


def admin_task(query):
    """One choice task for the stimulus viewer (screenshots for the agent study)."""
    try:
        t = int((query.get("t") or ["0"])[0])
        seed = int((query.get("seed") or ["1"])[0])
    except ValueError:
        raise ApiError(400, "t and seed must be numbers")
    if not 0 <= t < N_TASKS:
        raise ApiError(400, "t out of range")
    if query.get("r"):
        con = db()
        try:
            row = con.execute("SELECT design FROM respondents WHERE id=?",
                              (query["r"][0],)).fetchone()
        finally:
            con.close()
        if row is None:
            raise ApiError(404, "respondent not found")
        d = json.loads(row["design"])
    else:
        d = design.generate_design(STIMULI, seed, n_tasks=N_TASKS)
    return {"task": d["tasks"][t], "categories": design.public_categories(STIMULI)}


# ------------------------------------------------------------------- exports

def safe_cell(v):
    """Neutralise spreadsheet formula injection in text cells."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def to_csv(rows, columns=None):
    buf = io.StringIO()
    if columns is None:
        columns = []
        for r in rows:
            for k in r:
                if k not in columns:
                    columns.append(k)
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: safe_cell(r.get(k)) for k in columns})
    return buf.getvalue()


def export(name):
    con = db()
    try:
        resp = {r["id"]: r for r in con.execute("SELECT * FROM respondents")}

        if name == "respondents.csv":
            rows = []
            for r in resp.values():
                f = json.loads(r["flags"] or "{}")
                rows.append({"respondent_id": r["id"], "pid": r["pid"], "source": r["source"],
                             "status": r["status"], "current_page": r["current_page"],
                             "created_at": r["created_at"], "completed_at": r["completed_at"],
                             "viewport": r["viewport"], "user_agent": r["user_agent"],
                             "ip_hash": r["ip_hash"], "seed": r["seed"],
                             "completion_code": r["completion_code"],
                             **{f"flag_{k}": v for k, v in f.items()}})
            return to_csv(rows), "text/csv"

        if name == "choices_long.csv":
            rows = []
            for c in con.execute("SELECT * FROM choices ORDER BY respondent_id, task_index"):
                r = resp.get(c["respondent_id"])
                if r is None:
                    continue
                task = json.loads(r["design"])["tasks"][c["task_index"]]
                f = json.loads(r["flags"] or "{}")
                for a in task["alts"]:
                    rows.append({"respondent_id": r["id"], "pid": r["pid"], "status": r["status"],
                                 "quality_pass": f.get("quality_pass"),
                                 "task_index": c["task_index"], "category": task["category"],
                                 "alt_pos": a["pos"], "brand": a["brand"],
                                 "brand_type": a["brand_type"], "fictitious": a["fictitious"],
                                 "affect": a["affect"], "claim": a["claim"], "price": a["price"],
                                 "price_mult": a["price_mult"],
                                 "log_price_rel": round(math.log(a["price_mult"]), 5),
                                 "rating": a["rating"], "reviews": a["reviews"],
                                 "warranty_years": a["warranty_years"],
                                 "chosen": int(a["pos"] == c["chosen_pos"]),
                                 "rt_ms": c["rt_ms"]})
            return to_csv(rows), "text/csv"

        if name == "events.csv":
            rows = [dict(e) for e in con.execute("SELECT * FROM events ORDER BY id")]
            return to_csv(rows), "text/csv"

        if name == "choice_sets.json":
            # exact choice sets + human choices: input for the agent study (Study 1)
            ch = {}
            for c in con.execute("SELECT * FROM choices"):
                ch.setdefault(c["respondent_id"], {})[c["task_index"]] = c["chosen_pos"]
            out = []
            for r in resp.values():
                if r["status"] != "completed":
                    continue
                d = json.loads(r["design"])
                out.append({"respondent_id": r["id"], "seed": r["seed"],
                            "flags": json.loads(r["flags"] or "{}"),
                            "tasks": [{**t, "chosen_pos": ch.get(r["id"], {}).get(i)}
                                      for i, t in enumerate(d["tasks"])]})
            return json.dumps({"categories": design.public_categories(STIMULI),
                               "respondents": out}, ensure_ascii=False, indent=1), \
                "application/json"
    finally:
        con.close()
    raise ApiError(404, "unknown export")


EXPORTS = ["respondents.csv", "choices_long.csv", "events.csv", "choice_sets.json"]


# ------------------------------------------------------------------- server

CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self' "
                                "'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
                                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
}

PUBLIC_POST = {"/api/start": api_start, "/api/resume": api_resume,
               "/api/choice": api_choice, "/api/event": api_event,
               "/api/complete": api_complete}


class Handler(BaseHTTPRequestHandler):
    server_version = "SurveyServer/1.0"
    trust_proxy = False

    def log_message(self, fmt, *args):  # no query strings in logs (may hold pid)
        sys.stderr.write("%s %s %s\n" % (self.log_date_time_string(),
                                         self.command, urlparse(self.path).path))

    def client_ip(self):
        if self.trust_proxy and self.headers.get("X-Forwarded-For"):
            return self.headers["X-Forwarded-For"].split(",")[0].strip()
        return self.client_address[0]

    def send(self, status, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_static(self, rel):
        path = (STATIC / rel).resolve()
        if STATIC.resolve() not in path.parents or not path.is_file():
            return self.send(404, {"error": "not found"})
        self.send(200, path.read_bytes(), CONTENT_TYPES.get(path.suffix, "application/octet-stream"))

    def is_admin(self):
        pw = CONFIG["admin_password"]
        auth = self.headers.get("Authorization", "")
        if not pw or not auth.startswith("Basic "):
            return False
        try:
            user, _, given = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
        except Exception:
            return False
        return (hmac.compare_digest(user, CONFIG["admin_user"])
                and hmac.compare_digest(given.encode(), pw.encode()))

    def require_admin(self):
        if self.is_admin():
            return True
        self.send(401, {"error": "authentication required"},
                  extra={"WWW-Authenticate": 'Basic realm="survey-admin", charset="UTF-8"'})
        return False

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "request too large")
        try:
            body = json.loads(self.rfile.read(length) if length else b"{}")
        except json.JSONDecodeError:
            raise ApiError(400, "invalid JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "invalid body")
        return body

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        p = url.path
        try:
            if p in ("/", "/index.html"):
                return self.send_static("index.html")
            if p.startswith("/static/"):
                return self.send_static(p[len("/static/"):])
            if p == "/api/settings":
                return self.send(200, public_settings())
            if p == "/healthz":
                return self.send(200, {"ok": True})
            if p.startswith("/admin"):
                if not self.require_admin():
                    return
                if p in ("/admin", "/admin/"):
                    return self.send_static("admin.html")
                if p == "/admin/stimulus":
                    # task data embedded (no fetch) so headless browsers can screenshot it
                    data = json.dumps(admin_task(parse_qs(url.query)), ensure_ascii=False)
                    data = data.replace("<", "\\u003c")
                    html = (STATIC / "stimulus.html").read_text(encoding="utf-8").replace(
                        "<!--TASK_DATA-->",
                        f'<script type="application/json" id="task-data">{data}</script>')
                    return self.send(200, html, "text/html; charset=utf-8")
                if p == "/admin/api/stats":
                    return self.send(200, admin_stats())
                if p.startswith("/admin/export/"):
                    name = p.rsplit("/", 1)[1]
                    if name not in EXPORTS:
                        raise ApiError(404, "unknown export")
                    body, ctype = export(name)
                    stamp = datetime.now().strftime("%Y%m%d-%H%M")
                    return self.send(200, body, ctype + "; charset=utf-8", extra={
                        "Content-Disposition": f'attachment; filename="{stamp}_{name}"'})
            return self.send(404, {"error": "not found"})
        except ApiError as e:
            return self.send(e.status, {"error": e.message})

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            if p in PUBLIC_POST:
                return self.send(200, PUBLIC_POST[p](self.read_json(), self))
            return self.send(404, {"error": "not found"})
        except ApiError as e:
            return self.send(e.status, {"error": e.message})
        except Exception as e:  # never leak internals to participants
            sys.stderr.write(f"ERROR {p}: {e!r}\n")
            return self.send(500, {"error": "server error, please try again"})


def make_server(host, port, db_path, admin_password, trust_proxy=False):
    init_db(db_path)
    CONFIG["admin_password"] = admin_password
    Handler.trust_proxy = trust_proxy
    return ThreadingHTTPServer((host, port), Handler)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--db", default=os.environ.get("SURVEY_DB", str(ROOT / "data" / "survey.db")))
    ap.add_argument("--trust-proxy", action="store_true",
                    help="use X-Forwarded-For (only behind your own reverse proxy)")
    args = ap.parse_args()
    pw = os.environ.get("ADMIN_PASSWORD", "")
    if not pw:
        pw = secrets.token_urlsafe(12)
        print(f"ADMIN_PASSWORD not set; generated for this run: {pw}", flush=True)
    srv = make_server(args.host, args.port, args.db, pw, args.trust_proxy)
    print(f"Survey running at http://{args.host}:{args.port}/  (admin: /admin, user 'admin')",
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
