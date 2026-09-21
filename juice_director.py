# juice_director.py — shared config loader for Juicetification Director.
# Drop this file, unchanged, into every simulation repo.
import base64, json, urllib.request
import streamlit as st

def _coerce(spec, value):
    t = spec.get("type")
    try:
        if t == "int":   value = int(value)
        elif t == "float": value = float(value)
        elif t == "bool": value = bool(value)
        elif t == "list": value = list(value)
        # str/other: leave as-is
    except (TypeError, ValueError):
        return spec["default"]
    if "min" in spec and value < spec["min"]: value = spec["min"]
    if "max" in spec and value > spec["max"]: value = spec["max"]
    if "choices" in spec and value not in spec["choices"]: return spec["default"]
    return value

def _defaults(manifest):
    return {k: s["default"] for k, s in manifest["params"].items()}

def _validate(manifest, raw):
    out = _defaults(manifest)
    for k, v in (raw or {}).items():
        if k in manifest["params"]:
            out[k] = _coerce(manifest["params"][k], v)
    return out

def resolve_config(manifest, fetch=None):
    """Return (params, context).
    params  = built-in defaults overridden by the instructor's config.
    context = {'game': code|None, 'section': str|None, 'seed': int|None}.
    Resolution: ?cfg=<b64 json>  →  ?game=<code> via fetch(code)  →  defaults.
    With no cfg/game param present, params == built-in defaults (app unchanged)."""
    qp = st.query_params
    ctx = {"game": qp.get("game"), "section": qp.get("sec"), "seed": None}
    if qp.get("seed"):
        try: ctx["seed"] = int(qp.get("seed"))
        except ValueError: pass

    raw = None
    if qp.get("cfg"):
        try:
            raw = json.loads(base64.urlsafe_b64decode(qp.get("cfg").encode()).decode())
        except Exception:
            raw = None
    elif qp.get("game") and fetch is not None:
        try:
            payload = fetch(qp.get("game"))     # {'params': {...}, 'seed': int|None}
            raw = (payload or {}).get("params")
            if ctx["seed"] is None:
                ctx["seed"] = (payload or {}).get("seed")
        except Exception:
            raw = None
    return _validate(manifest, raw), ctx

def serve_manifest_if_requested(manifest):
    """If the URL has ?manifest=1, emit the manifest JSON and stop. Lets the
    Director discover/refresh this app's parameter schema with no shared code."""
    if st.query_params.get("manifest"):
        st.json(manifest)
        st.stop()

def encode_cfg(params):
    """Helper the Director uses to build a self-contained ?cfg= link."""
    return base64.urlsafe_b64encode(
        json.dumps(params, separators=(",", ":")).encode()).decode()

# Optional default fetch for ?game= lookups when a shared HTTP endpoint exists.
def http_fetch(base_url):
    def _f(code):
        with urllib.request.urlopen(f"{base_url}/config?game={code}", timeout=5) as r:
            return json.loads(r.read().decode())
    return _f
