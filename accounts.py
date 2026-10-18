"""Local accounts stored in the XAMPP MariaDB database."""

from __future__ import annotations

import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from pathlib import Path

import pymysql
from flask import abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from pymysql.err import IntegrityError, OperationalError
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent
REVIEW_DIR = ROOT / "storage" / "reviews"
DB_NAME = os.environ.get("FLYLEAF_DB_NAME", "flyleaf")
ADMIN_EMAIL = "silatanuikipngetich@gmail.com"
FREE_DAILY_UPLOADS = 5
_READY = False
_SCHEMA_ERROR = ""

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_REVIEW_ID = re.compile(r"^[a-f0-9]{16,64}$")
_GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
_GOOGLE_CLIENT: dict | None = None


def database_error() -> str:
    if _SCHEMA_ERROR:
        return _SCHEMA_ERROR
    if os.environ.get("FLYLEAF_DB_USER") or os.environ.get("FLYLEAF_DB_HOST"):
        return "Flyleaf could not open its database. Check the database name, user, and password for this server."
    return "Flyleaf could not reach the local database. Start MySQL in XAMPP and try again."


def _socket_path(host: str) -> str:
    chosen = os.environ.get("FLYLEAF_DB_SOCKET", "").strip()
    if chosen:
        return chosen
    if host != "localhost":
        return ""
    for candidate in ("/var/lib/mysql/mysql.sock", "/tmp/mysql.sock", "/var/run/mysqld/mysqld.sock"):
        if os.path.exists(candidate):
            return candidate
    return ""


def _settings(with_database: bool) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_]+", DB_NAME):
        raise RuntimeError("The database name is not valid.")
    settings = {
        "user": os.environ.get("FLYLEAF_DB_USER", "root"),
        "password": os.environ.get("FLYLEAF_DB_PASSWORD", ""),
        "database": DB_NAME if with_database else None,
        "charset": "utf8mb4",
        "autocommit": True,
        "cursorclass": pymysql.cursors.DictCursor,
    }
    host = os.environ.get("FLYLEAF_DB_HOST", "127.0.0.1").strip() or "127.0.0.1"
    socket_path = _socket_path(host)
    if socket_path:
        settings["unix_socket"] = socket_path
    else:
        settings["host"] = host
        settings["port"] = int(os.environ.get("FLYLEAF_DB_PORT", "3306"))
    return settings


def _connect(with_database: bool = True):
    return pymysql.connect(**_settings(with_database))


def ensure_schema() -> None:
    global _READY, _SCHEMA_ERROR
    if _READY:
        return
    # A hosting account cannot create a database. Use the one assigned in cPanel.
    try:
        bare = _connect(with_database=False)
    except OperationalError:
        bare = None
    if bare is not None:
        try:
            with bare.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
        except OperationalError:
            pass
        finally:
            bare.close()

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
                    email VARCHAR(255) NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    display_name VARCHAR(80) NOT NULL,
                    role VARCHAR(16) NOT NULL DEFAULT 'member',
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY email (email)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_work (
                    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
                    user_id INT UNSIGNED NOT NULL,
                    title VARCHAR(160) NOT NULL,
                    kind VARCHAR(16) NOT NULL,
                    source_text MEDIUMTEXT NOT NULL,
                    result_json MEDIUMTEXT NOT NULL,
                    flagged_percent SMALLINT NULL,
                    uncertain_percent SMALLINT NULL,
                    review_key VARCHAR(64) NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    KEY user_created (user_id, id),
                    UNIQUE KEY user_review (user_id, review_key),
                    CONSTRAINT saved_work_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            _ensure_google_columns(cur)
    finally:
        conn.close()
    _READY = True
    _SCHEMA_ERROR = ""


def _ensure_google_columns(cur) -> None:
    cur.execute(
        """
        SELECT COLUMN_NAME, IS_NULLABLE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME='users'
        """,
        (DB_NAME,),
    )
    columns = {row["COLUMN_NAME"]: row["IS_NULLABLE"] for row in cur.fetchall()}
    if columns.get("password_hash") == "NO":
        cur.execute("ALTER TABLE users MODIFY password_hash VARCHAR(255) NULL")
    if "google_sub" not in columns:
        cur.execute("ALTER TABLE users ADD COLUMN google_sub VARCHAR(255) NULL")
        cur.execute("ALTER TABLE users ADD UNIQUE KEY google_sub (google_sub)")


def _cursor():
    ensure_schema()
    return _connect()


def _public_user(row: dict | None) -> dict | None:
    if row is None:
        return None
    email = row["email"]
    created = row.get("created_at")
    return {
        "id": int(row["id"]),
        "email": email,
        "display_name": row["display_name"],
        "role": "admin" if email.lower() == ADMIN_EMAIL else "member",
        "has_password": bool(row.get("password_hash")),
        "created_at": created,
        "created_label": created.strftime("%d %b %Y") if created else "",
    }


def current_user() -> dict | None:
    if hasattr(g, "account"):
        return g.account
    g.account = None
    try:
        user_id = int(session.get("user_id"))
    except (TypeError, ValueError):
        return None
    try:
        conn = _cursor()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, email, password_hash, display_name, role, created_at FROM users WHERE id=%s",
                    (user_id,),
                )
                g.account = _public_user(cur.fetchone())
        finally:
            conn.close()
    except OperationalError:
        g.account = None
    return g.account


def csrf_token() -> str:
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(24)
        session["csrf"] = token
    return token


def _csrf_ok() -> bool:
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
    expected = session.get("csrf") or ""
    return bool(expected) and secrets.compare_digest(sent, expected)


def _secret() -> str:
    path = ROOT / "storage" / "session.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 32:
            return value
    value = secrets.token_hex(32)
    path.write_text(value, encoding="utf-8")
    return value


def _clean_email(value: str) -> str:
    email = (value or "").strip().lower()
    if not _EMAIL.fullmatch(email) or len(email) > 255:
        raise ValueError("Enter a valid email address.")
    return email


def _clean_name(value: str, email: str) -> str:
    name = " ".join((value or "").split())
    if not name:
        name = email.split("@", 1)[0]
    name = re.sub(r"[^\w .'-]", "", name, flags=re.UNICODE).strip()
    return (name or "Reader")[:80]


def _title_from(source: str) -> str:
    line = " ".join(source.split())
    if len(line) <= 80:
        return line or "Untitled draft"
    return line[:77].rstrip() + "..."


def _percent(value) -> int | None:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, number))


def _trim_check(result: dict) -> dict:
    sentences = []
    for item in (result.get("sentences") or [])[:500]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")[:2000]
        label = item.get("label") if item.get("label") in {"ai", "uncertain", "human"} else "human"
        try:
            probability = max(0.0, min(1.0, float(item.get("ai_probability") or 0)))
        except (TypeError, ValueError):
            probability = 0.0
        sentences.append({"text": text, "label": label, "ai_probability": round(probability, 4)})
    warnings = [str(item)[:240] for item in (result.get("warnings") or [])[:8] if str(item).strip()]
    confidence = str(result.get("confidence") or "low")
    if confidence not in {"low", "moderate", "high"}:
        confidence = "low"
    return {
        "flagged_percent": _percent(result.get("flagged_percent")) or 0,
        "uncertain_percent": _percent(result.get("uncertain_percent")) or 0,
        "confidence": confidence,
        "warnings": warnings,
        "word_count": _word_count(result.get("word_count")),
        "sentences": sentences,
    }


def _trim_rewrite(result: dict) -> dict:
    return {
        "text": str(result.get("text") or "")[:200_000],
        "word_count": _word_count(result.get("word_count")),
        "before_flagged": _percent(result.get("before_flagged")) or 0,
        "before_uncertain": _percent(result.get("before_uncertain")) or 0,
        "after_flagged": _percent(result.get("after_flagged")) or 0,
        "after_uncertain": _percent(result.get("after_uncertain")) or 0,
    }


def _word_count(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(number, 2_000_000))


def authenticate(email: str, password: str) -> dict | None:
    cleaned = _clean_email(email)
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, password_hash, display_name, role, created_at FROM users WHERE email=%s",
                (cleaned,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    digest = row.get("password_hash") or ""
    if not digest or not check_password_hash(digest, password or ""):
        return None
    return _public_user(row)


def register_user(email: str, password: str, name: str) -> dict:
    cleaned = _clean_email(email)
    if len(password or "") < 8:
        raise ValueError("Use at least 8 characters.")
    display = _clean_name(name, cleaned)
    digest = generate_password_hash(password)
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email=%s", (cleaned,))
            if cur.fetchone():
                raise ValueError("An account with that email already exists. Log in instead.")
            cur.execute(
                "INSERT INTO users (email, password_hash, display_name, role) VALUES (%s, %s, %s, 'member')",
                (cleaned, digest, display),
            )
            user_id = cur.lastrowid
    finally:
        conn.close()
    return {"id": int(user_id), "email": cleaned, "display_name": display, "role": "member"}


def seed_admin(email: str, password: str, display_name: str) -> None:
    """Create or update the local admin. The password is stored only as a hash."""
    cleaned = _clean_email(email)
    if len(password or "") < 8:
        raise ValueError("Use at least 8 characters.")
    display = _clean_name(display_name, cleaned)
    digest = generate_password_hash(password)
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email=%s", (cleaned,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE users SET password_hash=%s, display_name=%s, role='admin' WHERE id=%s",
                    (digest, display, row["id"]),
                )
            else:
                cur.execute(
                    "INSERT INTO users (email, password_hash, display_name, role) VALUES (%s, %s, %s, 'admin')",
                    (cleaned, digest, display),
                )
    finally:
        conn.close()


def google_configured() -> bool:
    return _google_client() is not None


def _google_client() -> dict | None:
    global _GOOGLE_CLIENT
    if _GOOGLE_CLIENT is not None:
        return _GOOGLE_CLIENT or None
    client_id = os.environ.get("FLYLEAF_GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("FLYLEAF_GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        path = ROOT / "storage" / "google_client.json"
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            saved = {}
        client_id = str(saved.get("client_id") or "").strip()
        client_secret = str(saved.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        _GOOGLE_CLIENT = {}
        return None
    _GOOGLE_CLIENT = {"client_id": client_id, "client_secret": client_secret}
    return _GOOGLE_CLIENT


def login_google(email: str, name: str, subject: str) -> dict:
    cleaned = _clean_email(email)
    google_sub = (subject or "").strip()
    if not google_sub or len(google_sub) > 255:
        raise ValueError("Google did not confirm that account.")
    display = _clean_name(name, cleaned)
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, display_name, role, created_at FROM users WHERE google_sub=%s",
                (google_sub,),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "SELECT id, email, display_name, role, created_at, google_sub FROM users WHERE email=%s",
                    (cleaned,),
                )
                row = cur.fetchone()
                if row:
                    if row.get("google_sub") and row["google_sub"] != google_sub:
                        raise ValueError("That email is already linked to a different Google account.")
                    cur.execute("UPDATE users SET google_sub=%s WHERE id=%s", (google_sub, row["id"]))
                else:
                    cur.execute(
                        "INSERT INTO users (email, password_hash, display_name, role, google_sub) VALUES (%s, NULL, %s, 'member', %s)",
                        (cleaned, display, google_sub),
                    )
                    return {
                        "id": int(cur.lastrowid),
                        "email": cleaned,
                        "display_name": display,
                        "role": "member",
                    }
    except IntegrityError as exc:
        raise ValueError("An account with that email already exists. Log in instead.") from exc
    finally:
        conn.close()
    return _public_user(row)


def _google_identity(code: str, redirect_uri: str) -> dict:
    client = _google_client()
    if client is None:
        raise ValueError("Google sign-in is not configured.")
    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode()
    token_request = urllib.request.Request(_GOOGLE_TOKEN, data=body, method="POST")
    try:
        with urllib.request.urlopen(token_request, timeout=20) as response:
            token = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("Google sign-in did not finish. Try again.") from exc
    access = str(token.get("access_token") or "")
    if not access:
        raise ValueError("Google sign-in did not finish. Try again.")
    info_request = urllib.request.Request(
        _GOOGLE_USERINFO,
        headers={"Authorization": f"Bearer {access}"},
    )
    try:
        with urllib.request.urlopen(info_request, timeout=20) as response:
            profile = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("Google did not share an email address.") from exc
    if profile.get("email_verified") is False:
        raise ValueError("That Google email is not verified.")
    return profile


def _sign_in(user: dict) -> None:
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["csrf"] = secrets.token_urlsafe(24)


def _safe_next(value: str | None) -> str:
    target = value or ""
    if target.startswith("/") and not target.startswith("//") and not re.search(r"[\s\\]", target):
        return target
    return url_for("dashboard")


def list_saved(user_id: int, kind: str | None = None) -> list[dict]:
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT id, title, kind, flagged_percent, uncertain_percent, review_key, created_at
                FROM saved_work
                WHERE user_id=%s
            """
            params: list = [user_id]
            if kind:
                sql += " AND kind=%s"
                params.append(kind)
            sql += " ORDER BY created_at DESC, id DESC LIMIT 500"
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()
    return [_saved_summary(row) for row in rows]


def uploads_today(user_id: int) -> int:
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS total
                FROM saved_work
                WHERE user_id=%s AND kind='pdf' AND created_at >= CURDATE()
                """,
                (user_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return int(row["total"]) if row else 0


def _usage(user_id: int) -> dict:
    used = uploads_today(user_id)
    left = max(0, FREE_DAILY_UPLOADS - used)
    return {
        "uploads_used": used,
        "uploads_left": left,
        "uploads_limit": FREE_DAILY_UPLOADS,
    }


def _saved_summary(row: dict) -> dict:
    created = row["created_at"]
    return {
        "id": int(row["id"]),
        "title": row["title"],
        "kind": row["kind"],
        "kind_label": {"check": "Check", "rewrite": "Rewrite", "pdf": "PDF report"}.get(row["kind"], "Saved"),
        "flagged_percent": row["flagged_percent"],
        "uncertain_percent": row["uncertain_percent"],
        "review_key": row.get("review_key") or "",
        "created_label": created.strftime("%d %b %Y, %I:%M %p") if created else "",
        "created_order": created.strftime("%Y-%m-%d %H:%M:%S") if created else "",
    }


def get_saved(item_id: int, user: dict) -> dict | None:
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, title, kind, source_text, result_json, review_key, created_at
                FROM saved_work WHERE id=%s
                """,
                (item_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    if int(row["user_id"]) != int(user["id"]) and user.get("role") != "admin":
        return None
    import json

    try:
        result = json.loads(row["result_json"])
    except json.JSONDecodeError:
        result = {}
    created = row["created_at"]
    return {
        "id": int(row["id"]),
        "title": row["title"],
        "kind": row["kind"],
        "source_text": row["source_text"],
        "result": result if isinstance(result, dict) else {},
        "review_key": row["review_key"],
        "created_label": created.strftime("%d %b %Y, %H:%M") if created else "",
    }


def saved_id_for_review(user_id: int, review_id: str) -> int | None:
    if not _REVIEW_ID.fullmatch(review_id or ""):
        return None
    try:
        conn = _cursor()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM saved_work WHERE user_id=%s AND review_key=%s",
                    (user_id, review_id),
                )
                row = cur.fetchone()
        finally:
            conn.close()
    except OperationalError:
        return None
    return int(row["id"]) if row else None


def delete_saved(item_id: int, user: dict) -> bool:
    item = get_saved(item_id, user)
    if item is None:
        return False
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM saved_work WHERE id=%s", (item_id,))
    finally:
        conn.close()
    return True


def insert_saved(user_id: int, title: str, kind: str, source: str, result: dict, review_key: str | None, flagged, uncertain) -> int:
    import json

    conn = _cursor()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO saved_work
                    (user_id, title, kind, source_text, result_json, flagged_percent, uncertain_percent, review_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    title[:160],
                    kind,
                    source,
                    json.dumps(result),
                    flagged,
                    uncertain,
                    review_key,
                ),
            )
            return int(cur.lastrowid)
    finally:
        conn.close()


def _file_title(name: str) -> str:
    base = Path(str(name or "")).name.replace("\x00", "").strip()
    base = re.sub(r"[^\w .\-()]+", "", base, flags=re.UNICODE).strip(" .")
    return (base or "draft")[:160]


def keep_document(user_id: int, filename: str, result: dict, review_id: str) -> int:
    del result
    title = _file_title(filename)
    if not title.lower().endswith(".pdf"):
        raise ValueError("Upload a PDF. Flyleaf keeps a report for PDF files.")
    if not review_id or not _REVIEW_ID.fullmatch(review_id):
        raise ValueError("That file did not produce a PDF report.")
    existing = saved_id_for_review(user_id, review_id)
    if existing:
        return existing
    if uploads_today(user_id) >= FREE_DAILY_UPLOADS:
        raise ValueError("The free plan includes 5 PDF uploads a day. Try again tomorrow.")
    meta = REVIEW_DIR / f"{review_id}.json"
    pdf = REVIEW_DIR / f"{review_id}.pdf"
    if not meta.is_file() or not pdf.is_file():
        raise ValueError("That report is no longer on this computer.")
    summary = json.loads(meta.read_text(encoding="utf-8"))
    stored = {
        "filename": title,
        "flagged_percent": _percent(summary.get("flagged_percent")) or 0,
        "uncertain_percent": _percent(summary.get("uncertain_percent")) or 0,
        "confidence": summary.get("confidence") or "",
        "word_count": _word_count(summary.get("word_count")),
        "page_count": int(summary.get("page_count") or 0),
        "review_id": review_id,
    }
    return insert_saved(
        user_id,
        str(summary.get("filename") or title)[:160],
        "pdf",
        title,
        stored,
        review_id,
        stored["flagged_percent"],
        stored["uncertain_percent"],
    )


def update_profile(user_id: int, name: str, email: str, current_password: str, new_password: str) -> None:
    cleaned = _clean_email(email)
    display = _clean_name(name, cleaned)
    new_password = new_password or ""
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, password_hash FROM users WHERE id=%s",
                (user_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("That account is no longer available.")
            if cleaned != (row["email"] or "").lower():
                cur.execute("SELECT id FROM users WHERE email=%s", (cleaned,))
                taken = cur.fetchone()
                if taken and int(taken["id"]) != int(user_id):
                    raise ValueError("An account with that email already exists.")
            digest = row.get("password_hash") or ""
            if new_password:
                if len(new_password) < 8:
                    raise ValueError("Use at least 8 characters.")
                if digest and not check_password_hash(digest, current_password or ""):
                    raise ValueError("The current password does not match.")
                digest = generate_password_hash(new_password)
            role = "admin" if cleaned == ADMIN_EMAIL else "member"
            cur.execute(
                "UPDATE users SET email=%s, display_name=%s, password_hash=%s, role=%s WHERE id=%s",
                (cleaned, display, digest or None, role, user_id),
            )
    finally:
        conn.close()


def list_users() -> list[dict]:
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.email, u.display_name, u.role, u.created_at, COUNT(s.id) AS saved_count
                FROM users u
                LEFT JOIN saved_work s ON s.user_id = u.id
                GROUP BY u.id, u.email, u.display_name, u.role, u.created_at
                ORDER BY u.id
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    people = []
    for row in rows:
        created = row["created_at"]
        people.append(
            {
                "id": int(row["id"]),
                "email": row["email"],
                "display_name": row["display_name"],
                "role": row["role"],
                "saved_count": int(row["saved_count"]),
                "created_label": created.strftime("%d %b %Y, %H:%M") if created else "",
            }
        )
    return people


def find_user(user_id: int) -> dict | None:
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, display_name, role, created_at FROM users WHERE id=%s",
                (user_id,),
            )
            return _public_user(cur.fetchone())
    finally:
        conn.close()


def _db_page(template: str, **context):
    try:
        ensure_schema()
    except OperationalError:
        return render_template("auth.html", mode="offline", error=database_error()), 503
    return render_template(template, **context)


def init_accounts(app) -> None:
    app.secret_key = _secret()
    app.permanent_session_lifetime = timedelta(days=14)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    @app.context_processor
    def inject_account():
        return {"account": current_user(), "csrf_token": csrf_token(), "google_ready": google_configured()}

    @app.get("/login")
    def login():
        if current_user():
            return redirect(url_for("saved_list"))
        return _db_page("auth.html", mode="login", error="", next_url=_safe_next(request.args.get("next")))

    @app.post("/login")
    def login_post():
        if not _csrf_ok():
            abort(400)
        nxt = _safe_next(request.form.get("next"))
        try:
            user = authenticate(request.form.get("email") or "", request.form.get("password") or "")
        except ValueError:
            user = None
        except OperationalError:
            return render_template("auth.html", mode="offline", error=database_error()), 503
        if user is None:
            return render_template(
                "auth.html",
                mode="login",
                error="That email or password does not match.",
                next_url=nxt,
                email=request.form.get("email") or "",
            )
        _sign_in(user)
        return redirect(nxt)

    @app.get("/register")
    def register():
        if current_user():
            return redirect(url_for("saved_list"))
        return _db_page("auth.html", mode="register", error="")

    @app.post("/register")
    def register_post():
        if not _csrf_ok():
            abort(400)
        email = request.form.get("email") or ""
        name = request.form.get("name") or ""
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        try:
            if password != confirm:
                raise ValueError("Those passwords do not match.")
            user = register_user(email, password, name)
        except ValueError as exc:
            return render_template("auth.html", mode="register", error=str(exc), email=email, name=name)
        except OperationalError:
            return render_template("auth.html", mode="offline", error=database_error()), 503
        _sign_in(user)
        return redirect(url_for("saved_list"))

    @app.get("/auth/google")
    def google_start():
        if not google_configured():
            return _db_page("auth.html", mode="login", error="Google sign-in is not configured on this computer.", next_url="")
        state = secrets.token_urlsafe(24)
        session["google_state"] = state
        session["google_next"] = _safe_next(request.args.get("next"))
        query = urllib.parse.urlencode(
            {
                "client_id": _google_client()["client_id"],
                "redirect_uri": url_for("google_callback", _external=True),
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "prompt": "select_account",
            }
        )
        return redirect(f"{_GOOGLE_AUTH}?{query}")

    @app.get("/auth/google/callback")
    def google_callback():
        expected = session.get("google_state") or ""
        sent = request.args.get("state") or ""
        nxt = session.get("google_next") or ""
        if request.args.get("error"):
            return render_template(
                "auth.html",
                mode="login",
                error="Google sign-in was cancelled.",
                next_url=_safe_next(nxt),
            )
        if not expected or not sent or not secrets.compare_digest(sent, expected):
            return render_template(
                "auth.html",
                mode="login",
                error="Google sign-in expired. Try again.",
                next_url=_safe_next(nxt),
            )
        try:
            profile = _google_identity(request.args.get("code") or "", url_for("google_callback", _external=True))
            user = login_google(profile.get("email") or "", profile.get("name") or "", profile.get("sub") or "")
        except ValueError as exc:
            return render_template("auth.html", mode="login", error=str(exc), next_url=_safe_next(nxt))
        except OperationalError:
            return render_template("auth.html", mode="offline", error=database_error()), 503
        _sign_in(user)
        return redirect(_safe_next(nxt))

    @app.post("/logout")
    def logout():
        if not _csrf_ok():
            abort(400)
        session.clear()
        return redirect(url_for("home"))

    @app.get("/dashboard")
    def dashboard():
        user = current_user()
        if user is None:
            return redirect(url_for("login", next="/dashboard"))
        try:
            items = list_saved(user["id"], "pdf")
            usage = _usage(user["id"])
        except OperationalError:
            return render_template("auth.html", mode="offline", error=database_error()), 503
        return render_template("dashboard.html", items=items, **usage)

    @app.get("/plans")
    def plans_page():
        user = current_user()
        if user is None:
            return redirect(url_for("login", next="/plans"))
        try:
            usage = _usage(user["id"])
        except OperationalError:
            return render_template("auth.html", mode="offline", error=database_error()), 503
        return render_template("plans.html", **usage)

    @app.get("/account")
    def account_page():
        user = current_user()
        if user is None:
            return redirect(url_for("login", next="/account"))
        try:
            usage = _usage(user["id"])
        except OperationalError:
            return render_template("auth.html", mode="offline", error=database_error()), 503
        return render_template("account.html", error="", **usage)

    @app.post("/account")
    def account_post():
        if not _csrf_ok():
            abort(400)
        user = current_user()
        if user is None:
            return redirect(url_for("login", next="/account"))
        new_password = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        try:
            if new_password or confirm:
                if new_password != confirm:
                    raise ValueError("Those passwords do not match.")
            update_profile(
                user["id"],
                request.form.get("name") or "",
                request.form.get("email") or "",
                request.form.get("current_password") or "",
                new_password,
            )
        except ValueError as exc:
            try:
                usage = _usage(user["id"])
            except OperationalError:
                return render_template("auth.html", mode="offline", error=database_error()), 503
            return render_template("account.html", error=str(exc), **usage)
        except OperationalError:
            return render_template("auth.html", mode="offline", error=database_error()), 503
        if hasattr(g, "account"):
            del g.account
        flash("Your account was updated.")
        return redirect(url_for("account_page"))

    @app.get("/saved")
    def saved_list():
        user = current_user()
        if user is None:
            return redirect(url_for("login", next="/dashboard"))
        return redirect(url_for("dashboard"))

    @app.get("/saved/<int:item_id>")
    def saved_item(item_id: int):
        user = current_user()
        if user is None:
            return redirect(url_for("login", next=f"/saved/{item_id}"))
        try:
            item = get_saved(item_id, user)
        except OperationalError:
            return render_template("auth.html", mode="offline", error=database_error()), 503
        if item is None:
            abort(404)
        if item["kind"] == "pdf" and item.get("review_key"):
            pdf = REVIEW_DIR / f"{item['review_key']}.pdf"
            if pdf.is_file():
                return redirect(url_for("review", review_id=item["review_key"]))
        return render_template("saved_item.html", item=item)

    @app.post("/saved/<int:item_id>/delete")
    def saved_delete(item_id: int):
        if not _csrf_ok():
            abort(400)
        user = current_user()
        if user is None:
            return redirect(url_for("login"))
        try:
            removed = delete_saved(item_id, user)
        except OperationalError:
            flash(database_error())
            return redirect(url_for("saved_list"))
        if not removed:
            abort(404)
        flash("That document was removed.")
        return redirect(_safe_next(request.form.get("next") or "/dashboard"))

    @app.post("/api/saved")
    def save_api():
        user = current_user()
        if user is None:
            return jsonify({"error": "Sign in to save this check."}), 401
        if not _csrf_ok():
            return jsonify({"error": "The page expired. Reload it and try again."}), 400
        payload = request.get_json(silent=True) or {}
        kind = payload.get("kind")
        source = str(payload.get("source_text") or "").replace("\x00", "").strip()
        result = payload.get("result") if isinstance(payload.get("result"), dict) else None
        if kind in {"check", "rewrite"}:
            return jsonify({"error": "Pasted text stays on the checker. Upload a PDF to keep a report."}), 400
        if kind not in {"check", "rewrite"} or result is None or not source:
            return jsonify({"error": "There is nothing to save yet."}), 400
        if len(source) > 200_000:
            return jsonify({"error": "That draft is too long to save."}), 400
        try:
            if kind == "check":
                stored = _trim_check(result)
                flagged = stored["flagged_percent"]
                uncertain = stored["uncertain_percent"]
            else:
                stored = _trim_rewrite(result)
                if not stored["text"]:
                    return jsonify({"error": "There is nothing to save yet."}), 400
                flagged = stored["after_flagged"]
                uncertain = stored["after_uncertain"]
            item_id = insert_saved(user["id"], _title_from(source), kind, source, stored, None, flagged, uncertain)
        except OperationalError:
            return jsonify({"error": database_error()}), 503
        return jsonify({"id": item_id, "url": url_for("saved_item", item_id=item_id)})

    @app.post("/api/documents")
    def save_document_api():
        user = current_user()
        if user is None:
            return jsonify({"error": "Sign in to keep a document."}), 401
        if not _csrf_ok():
            return jsonify({"error": "The page expired. Reload it and try again."}), 400
        payload = request.get_json(silent=True) or {}
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        filename = _file_title(str(payload.get("filename") or result.get("filename") or "draft"))
        review_id = str(payload.get("review_id") or result.get("review_id") or "")
        try:
            item_id = keep_document(user["id"], filename, result, review_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except OperationalError:
            return jsonify({"error": database_error()}), 503
        return jsonify({"id": item_id, "url": url_for("dashboard")})

    @app.get("/saved/<int:item_id>/download")
    def saved_download(item_id: int):
        user = current_user()
        if user is None:
            return redirect(url_for("login", next="/dashboard"))
        try:
            item = get_saved(item_id, user)
        except OperationalError:
            return render_template("auth.html", mode="offline", error=database_error()), 503
        if item is None:
            abort(404)
        if item.get("review_key"):
            return redirect(url_for("review_download", review_id=item["review_key"]))
        name = _file_title(item["title"]).replace('"', "")
        if "." not in name:
            name = f"{name}.txt"
        return app.response_class(
            item["source_text"],
            mimetype="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.post("/review/<review_id>/save")
    def save_review(review_id: str):
        if not _csrf_ok():
            abort(400)
        user = current_user()
        if user is None:
            return redirect(url_for("login", next=f"/review/{review_id}"))
        if not _REVIEW_ID.fullmatch(review_id):
            abort(404)
        import json

        meta = REVIEW_DIR / f"{review_id}.json"
        pdf = REVIEW_DIR / f"{review_id}.pdf"
        if not meta.is_file() or not pdf.is_file():
            abort(404)
        try:
            summary = json.loads(meta.read_text(encoding="utf-8"))
            existing = saved_id_for_review(user["id"], review_id)
            if existing:
                flash("This report is already in your saved work.")
                return redirect(url_for("review", review_id=review_id))
            filename = str(summary.get("filename") or "draft.pdf")[:160]
            stored = {
                "filename": filename,
                "flagged_percent": _percent(summary.get("flagged_percent")) or 0,
                "uncertain_percent": _percent(summary.get("uncertain_percent")) or 0,
                "confidence": summary.get("confidence") or "",
                "word_count": _word_count(summary.get("word_count")),
                "page_count": int(summary.get("page_count") or 0),
                "review_id": review_id,
            }
            insert_saved(
                user["id"],
                filename,
                "pdf",
                filename,
                stored,
                review_id,
                stored["flagged_percent"],
                stored["uncertain_percent"],
            )
        except IntegrityError:
            flash("This report is already in your saved work.")
            return redirect(url_for("review", review_id=review_id))
        except (OperationalError, json.JSONDecodeError, ValueError):
            flash(database_error())
            return redirect(url_for("review", review_id=review_id))
        flash("This report is in your saved work.")
        return redirect(url_for("review", review_id=review_id))

    @app.get("/admin")
    def admin_page():
        user = current_user()
        if user is None:
            return redirect(url_for("login", next="/admin"))
        if user.get("role") != "admin":
            abort(404)
        try:
            people = list_users()
        except OperationalError:
            return render_template("auth.html", mode="offline", error=database_error()), 503
        return render_template("admin.html", people=people)

    @app.get("/admin/users/<int:user_id>")
    def admin_user(user_id: int):
        user = current_user()
        if user is None:
            return redirect(url_for("login", next=f"/admin/users/{user_id}"))
        if user.get("role") != "admin":
            abort(404)
        try:
            owner = find_user(user_id)
            items = list_saved(user_id) if owner else None
        except OperationalError:
            return render_template("auth.html", mode="offline", error=database_error()), 503
        if owner is None:
            abort(404)
        return render_template(
            "saved.html",
            heading=f"Saved by {owner['display_name']}",
            owner=owner,
            items=items,
            admin_view=True,
        )

    try:
        ensure_schema()
    except OperationalError as exc:
        global _SCHEMA_ERROR
        _SCHEMA_ERROR = database_error()
        app.logger.warning("Local accounts database is not ready: %s", exc)
