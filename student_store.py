"""
student_store.py — per-student progress records (shared with the simulations).

This is the SAME module the sims use to save each student's progress and write a
completion record. The Director imports it read-only to auto-populate a game's
tracking roster from the encrypted completion files in Dropbox. Keep this copy in
sync with the one in the sims (they are identical by design).

Configuration (same secrets as the Director's storage layer):
  DB_ENCRYPTION_KEY, and either
  DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY + DROPBOX_APP_SECRET, or DROPBOX_ACCESS_TOKEN.
Optional: PROGRESS_ROOT (default "/JuicetificationProgress").
When unconfigured, every function is a safe no-op.
"""

from __future__ import annotations

import os
import re
import json
import hashlib
import time
import random
import threading
from datetime import datetime, timezone


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _cfg(name, default=None):
    val = os.environ.get(name)
    if val:
        return val
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return default


DB_ENCRYPTION_KEY = _cfg("DB_ENCRYPTION_KEY")
PROGRESS_ROOT = _cfg("PROGRESS_ROOT", "/JuicetificationProgress")
GAMES_ROOT = _cfg("GAMES_ROOT", "/JuicetificationGames")
_REFRESH = _cfg("DROPBOX_REFRESH_TOKEN")
_APP_KEY = _cfg("DROPBOX_APP_KEY")
_APP_SECRET = _cfg("DROPBOX_APP_SECRET")
_ACCESS = _cfg("DROPBOX_ACCESS_TOKEN")

_have_creds = bool((_REFRESH and _APP_KEY and _APP_SECRET) or _ACCESS)
ENABLED = bool(DB_ENCRYPTION_KEY and _have_creds)


def enabled() -> bool:
    return ENABLED


def game_code():
    try:
        import streamlit as st
        return st.query_params.get("game")
    except Exception:
        return None


def get_student_id():
    try:
        import streamlit as st
        sid = st.query_params.get("sid")
        return sid.strip() if sid else None
    except Exception:
        return None


def set_student_id(sid):
    sid = (sid or "").strip()
    if not sid:
        return
    try:
        import streamlit as st
        st.query_params["sid"] = sid
    except Exception:
        pass


def derive_seed(game, sid, lo=1, hi=10 ** 6):
    key = f"{game or ''}|{sid or ''}".encode("utf-8")
    h = hashlib.sha256(key).digest()
    span = max(1, hi - lo + 1)
    return lo + (int.from_bytes(h[:8], "big") % span)


def _slug(sid):
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", (sid or "").strip()).strip("_").lower()[:40]
    tag = hashlib.sha256((sid or "").encode()).hexdigest()[:8]
    return f"{s or 'student'}-{tag}"


# One Fernet and one Dropbox client per process, shared by every session. Building a client per
# call costs an OAuth token refresh each time (refresh-token mode); with ~30 concurrent students
# that is slow and burns the Dropbox app's rate limit. Both objects are thread-safe to share.
_lock = threading.Lock()
_FERNET = None
_CLIENT = None


def _fernet():
    global _FERNET
    if _FERNET is None:
        with _lock:
            if _FERNET is None:
                from cryptography.fernet import Fernet
                key = DB_ENCRYPTION_KEY
                if isinstance(key, str):
                    key = key.encode()
                _FERNET = Fernet(key)
    return _FERNET


def _client():
    global _CLIENT
    if _CLIENT is None:
        with _lock:
            if _CLIENT is None:
                import dropbox
                if _REFRESH:
                    _CLIENT = dropbox.Dropbox(oauth2_refresh_token=_REFRESH,
                                              app_key=_APP_KEY, app_secret=_APP_SECRET,
                                              timeout=20)
                else:
                    _CLIENT = dropbox.Dropbox(_ACCESS, timeout=20)
    return _CLIENT


def _with_retry(fn, attempts=4):
    """Call fn(), retrying with jittered exponential backoff on Dropbox rate limiting (HTTP 429)
    and transient network errors. Other API errors (e.g. path not found) propagate unchanged."""
    import dropbox
    import requests
    delay = 0.5
    for i in range(attempts):
        try:
            return fn()
        except dropbox.exceptions.RateLimitError as e:
            wait = float(getattr(e, "backoff", None) or delay)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            wait = delay
        if i == attempts - 1:
            raise
        time.sleep(wait + random.uniform(0, 0.25))
        delay *= 2


def _download(path):
    import dropbox
    try:
        _md, res = _with_retry(lambda: _client().files_download(path))
        return res.content
    except dropbox.exceptions.ApiError:
        return None


def _upload(path, data):
    import dropbox
    _with_retry(lambda: _client().files_upload(
        data, path, mode=dropbox.files.WriteMode.overwrite))


def _list_json(folder):
    import dropbox
    try:
        out = []
        res = _with_retry(lambda: _client().files_list_folder(folder))
        while True:
            for e in res.entries:
                if getattr(e, "name", "").endswith(".json"):
                    out.append(e.path_lower)
            if not res.has_more:
                break
            res = _with_retry(lambda c=res.cursor: _client().files_list_folder_continue(c))
        return out
    except dropbox.exceptions.ApiError:
        return []


def _progress_path(game, sid):
    return f"{PROGRESS_ROOT}/{game or 'nogame'}/{_slug(sid)}.json"


def _completion_path(game, sid):
    return f"{PROGRESS_ROOT}/{game or 'nogame'}/_completions/{_slug(sid)}.json"


def load(game, sid):
    if not ENABLED or not sid:
        return {}
    raw = _download(_progress_path(game, sid))
    if raw is None:
        return {}
    try:
        return json.loads(_fernet().decrypt(raw).decode())
    except Exception:
        return {}


def save(game, sid, state, progress=None, step=None, score=None):
    if not ENABLED or not sid:
        return False
    payload = dict(state)
    payload["_student"] = sid
    payload["_updated_at"] = _now_iso()
    if progress is not None:
        try:
            payload["_progress"] = max(0.0, min(1.0, float(progress)))
        except (TypeError, ValueError):
            pass
    if step is not None:
        payload["_step"] = str(step)
    if score is not None:
        payload["_score"] = score
    _upload(_progress_path(game, sid),
            _fernet().encrypt(json.dumps(payload, separators=(",", ":")).encode()))
    return True


def record_completion(game, sid, completion_code=None, score=None, extra=None):
    if not ENABLED or not sid:
        return False
    rec = {"student": sid, "completion_code": completion_code,
           "score": score, "extra": extra}
    _upload(_completion_path(game, sid),
            _fernet().encrypt(json.dumps(rec).encode()))
    return True


def _game_config_path(code):
    return f"{GAMES_ROOT}/{code}.json"


def save_game_config(code, payload):
    if not ENABLED or not code:
        return False
    _upload(_game_config_path(code),
            _fernet().encrypt(json.dumps(payload).encode()))
    return True


def load_game_config(code):
    if not ENABLED or not code:
        return None
    raw = _download(_game_config_path(code))
    if raw is None:
        return None
    try:
        return json.loads(_fernet().decrypt(raw).decode())
    except Exception:
        return None


def list_completions(game):
    if not ENABLED:
        return []
    folder = f"{PROGRESS_ROOT}/{game or 'nogame'}/_completions"
    out = []
    for path in _list_json(folder):
        raw = _download(path)
        if raw is None:
            continue
        try:
            out.append(json.loads(_fernet().decrypt(raw).decode()))
        except Exception:
            pass
    return out


def list_progress(game):
    if not ENABLED:
        return []
    folder = f"{PROGRESS_ROOT}/{game or 'nogame'}"
    out = []
    for path in _list_json(folder):
        raw = _download(path)
        if raw is None:
            continue
        try:
            d = json.loads(_fernet().decrypt(raw).decode())
            out.append({
                "student": d.get("_student"),
                "progress": d.get("_progress"),
                "updated_at": d.get("_updated_at"),
                "step": d.get("_step"),
                "score": d.get("_score"),
            })
        except Exception:
            pass
    return out
