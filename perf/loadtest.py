"""Streamlit-protocol concurrent-user load tester.

Each simulated student opens a real Streamlit WebSocket session (the same protobuf
BackMsg/ForwardMsg protocol the browser uses), so the server does exactly the work a real
browser session causes: a full script run per interaction, widget state, media files,
deferred downloads. What it does NOT do is render in a browser (client-side cost).

Usage:
  python loadtest.py --url http://127.0.0.1:8501 --users 10 --think 1.0 --out result.json
  --mode lab     : each user walks the whole lab (navigate every screen + representative actions)
  --mode open    : burst - every user opens the app at the same instant, then one navigation
  --static       : also download index.html + the JS/CSS bundles each user (first-visit cost)
"""
import argparse, asyncio, json, random, re, statistics, time, urllib.request, sys
import websockets
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from streamlit.proto.WidgetStates_pb2 import WidgetState


def http_get(url):
    t = time.perf_counter()
    with urllib.request.urlopen(url, timeout=120) as r:
        body = r.read()
    return time.perf_counter() - t, body


class User:
    def __init__(self, uid, base, think, query, rec):
        self.uid, self.base, self.think, self.query, self.rec = uid, base, think, query, rec
        self.ws = None
        self.widgets = {}          # key suffix -> element proto (latest run)
        self.states = {}           # widget id -> WidgetState (persisted like the frontend)
        self.downloads = {}        # label -> (url, deferred_id)
        self.errors = 0
        self._pending = None
        self._reader = None
        self._op_futs = {}
        self.session_id = ''

    async def connect(self):
        ws_url = self.base.replace("http", "ws", 1) + "/_stcore/stream"
        self.ws = await websockets.connect(ws_url, subprotocols=["streamlit"], max_size=2**28,
                                           open_timeout=120, ping_interval=None)
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        try:
            async for raw in self.ws:
                fm = ForwardMsg(); fm.ParseFromString(raw)
                kind = fm.WhichOneof("type")
                if kind == "delta" and fm.delta.WhichOneof("type") == "new_element":
                    el = fm.delta.new_element
                    et = el.WhichOneof("type")
                    if et == "exception":
                        self.errors += 1
                        self.rec["exceptions"].append(el.exception.message[:200])
                    sub = getattr(el, et, None)
                    wid = getattr(sub, "id", "") if sub is not None else ""
                    if wid:
                        key = wid.split("-", 2)[-1] if wid.startswith("$$ID-") else wid
                        self.widgets[key] = (et, sub)
                    if et == "download_button":
                        self.downloads[sub.label] = (sub.url, sub.deferred_file_id)
                elif kind == "new_session":
                    self.session_id = fm.new_session.initialize.session_id
                elif kind == "script_finished":
                    if self._pending and not self._pending.done():
                        self._pending.set_result(fm.script_finished)
                elif kind == "backend_operation_response":
                    f = self._op_futs.pop(fm.backend_operation_response.request_id, None)
                    if f and not f.done():
                        f.set_result(fm.backend_operation_response)
        except websockets.ConnectionClosed:
            pass

    def _wid(self, key):
        et, sub = self.widgets[key]
        return sub.id

    async def rerun(self, label, extra=None):
        bm = BackMsg()
        cs = bm.rerun_script
        cs.query_string = self.query
        for ws_ in self.states.values():
            cs.widget_states.widgets.append(ws_)
        for ws_ in (extra or []):
            cs.widget_states.widgets.append(ws_)
        self.downloads = {}
        self._pending = asyncio.get_running_loop().create_future()
        t = time.perf_counter()
        await self.ws.send(bm.SerializeToString())
        try:
            await asyncio.wait_for(self._pending, timeout=180)
            self.rec["lat"].setdefault(label, []).append(time.perf_counter() - t)
        except asyncio.TimeoutError:
            self.errors += 1
            self.rec["timeouts"] += 1

    def _set(self, key, **val):
        if key not in self.widgets:
            self.rec["missing"].append(key); return None
        st_ = WidgetState(id=self._wid(key), **{k: v for k, v in val.items() if k != "dbl_arr"})
        if "dbl_arr" in val:
            st_.double_array_value.data.extend(val["dbl_arr"])
        self.states[st_.id] = st_
        return st_

    async def set_and_rerun(self, label, key, **val):
        if self._set(key, **val) is not None:
            await self.rerun(label)

    async def click(self, label, key):
        if key not in self.widgets:
            self.rec["missing"].append(key); return
        await self.rerun(label, [WidgetState(id=self._wid(key), trigger_value=True)])

    async def download(self, label_contains, rec_label):
        for lab, (url, dfid) in self.downloads.items():
            if label_contains in lab:
                t = time.perf_counter()
                if dfid:
                    rid = f"r{random.random()}"
                    bm = BackMsg(); req = bm.backend_operation_request
                    req.request_id = rid; req.session_id = self.session_id; req.deferred_file.file_id = dfid
                    fut = asyncio.get_running_loop().create_future(); self._op_futs[rid] = fut
                    await self.ws.send(bm.SerializeToString())
                    resp = await asyncio.wait_for(fut, 120)
                    url = resp.deferred_file.url
                    if not url:
                        self.errors += 1
                        self.rec["exceptions"].append(f"deferred:{resp.error_msg}:{resp.error_reason}")
                        return
                dt_, body = await asyncio.to_thread(http_get, self.base + url)
                self.rec["lat"].setdefault(rec_label, []).append(time.perf_counter() - t)
                self.rec["dl_bytes"][rec_label] = len(body)
                return
        self.rec["missing"].append("download:" + label_contains)

    async def pause(self):
        await asyncio.sleep(random.uniform(0.5 * self.think, 1.5 * self.think))

    async def nav(self, screen_label):
        await self.set_and_rerun("navigate", "nav", string_value=screen_label)


SCREENS = ["📖 Start Here", "1 · Forecasting", "2 · Qualitative", "3 · Naïve", "4 · Moving Avg",
           "5 · Exp. Smoothing", "6 · Linear Trend", "7 · Seasonality", "8 · Seasonality+Trend",
           "9 · Regression", "10 · Accuracy", "11 · Model Selection", "🏪 Run Juicetification",
           "🎓 Debrief", "📝 Final Report"]


async def lab_walk(u: User, static, mode):
    if static:
        t = time.perf_counter()
        _, html = await asyncio.to_thread(http_get, u.base + "/")
        assets = re.findall(rb'(?:src|href)="(\./?static/[^"]+)"', html)
        for a in assets:
            await asyncio.to_thread(http_get, u.base + "/" + a.decode().lstrip("./"))
        u.rec["lat"].setdefault("static_assets", []).append(time.perf_counter() - t)
    t0 = time.perf_counter()
    await u.connect()
    await u.rerun("open")
    u.rec["lat"].setdefault("connect+open", []).append(time.perf_counter() - t0)
    if mode == "open":
        await u.pause(); await u.nav(SCREENS[4]); return
    await u.pause()
    await u.download("Excel practice workbook", "download_workbook")
    await u.set_and_rerun("type_answer", "ti_rf_s_pred",
                          string_value="Weekends are low, weekdays high; events and exams drive spikes.")
    for i, s in enumerate(SCREENS[1:], start=1):
        await u.pause(); await u.nav(s)
        if i == 3:
            await u.pause()
            await u.set_and_rerun("type_number", "ni_in_r3_sat", double_value=300.0)
            await u.click("check_answer", "btn_r3_sat")
            await u.set_and_rerun("type_formula", "ti_xl_r3_sat", string_value="=F5")
            await u.click("check_formula", "xlb_r3_sat")
        elif i == 4:
            await u.pause(); await u.set_and_rerun("slider", "sl_r4w", dbl_arr=[6.0])
        elif i == 5:
            await u.pause(); await u.set_and_rerun("slider", "sl_r5a", dbl_arr=[0.6])
        elif i == 6:
            await u.pause(); await u.set_and_rerun("slider", "sl_lt_h", dbl_arr=[8.0])
        elif i == 11:
            await u.pause(); await u.set_and_rerun("select", "sb_r9pick", string_value="seasonal")
        elif i == 14:
            await u.pause(); await u.download("submission PDF", "download_pdf")
    await u.ws.close()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8501")
    ap.add_argument("--users", type=int, default=1)
    ap.add_argument("--think", type=float, default=1.0)
    ap.add_argument("--ramp", type=float, default=0.0, help="seconds over which users arrive")
    ap.add_argument("--mode", default="lab")
    ap.add_argument("--static", action="store_true")
    ap.add_argument("--sid", action="store_true", help="give each user ?sid= (progress store path)")
    ap.add_argument("--out")
    a = ap.parse_args()
    rec = {"lat": {}, "exceptions": [], "timeouts": 0, "missing": [], "dl_bytes": {}}
    users = [User(i, a.url, a.think,
                  f"sid=student{i:03d}" if a.sid else "", rec) for i in range(a.users)]

    async def run(u, delay):
        await asyncio.sleep(delay)
        try:
            await lab_walk(u, a.static, a.mode)
        except Exception as ex:   # count, don't crash the run
            u.errors += 1; rec["exceptions"].append(f"client:{type(ex).__name__}:{ex}"[:200])

    t = time.perf_counter()
    await asyncio.gather(*(run(u, a.ramp * i / max(1, a.users)) for i, u in enumerate(users)))
    wall = time.perf_counter() - t
    summ = {"users": a.users, "mode": a.mode, "think": a.think, "wall_s": round(wall, 1),
            "errors": sum(u.errors for u in users), "timeouts": rec["timeouts"],
            "missing": sorted(set(rec["missing"]))[:10], "exceptions": rec["exceptions"][:5],
            "dl_bytes": rec["dl_bytes"], "actions": {}}
    alll = []
    for k, v in rec["lat"].items():
        v = sorted(v); alll += v
        summ["actions"][k] = {"n": len(v), "p50_ms": round(1000 * statistics.median(v)),
                              "p95_ms": round(1000 * v[min(len(v) - 1, int(0.95 * len(v)))]),
                              "max_ms": round(1000 * v[-1])}
    alll.sort()
    if alll:
        summ["all_p50_ms"] = round(1000 * statistics.median(alll))
        summ["all_p95_ms"] = round(1000 * alll[min(len(alll) - 1, int(0.95 * len(alll)))])
        summ["all_mean_ms"] = round(1000 * statistics.mean(alll))
    print(json.dumps(summ, ensure_ascii=False))
    if a.out:
        json.dump(summ, open(a.out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    asyncio.run(main())
