# Performance optimization — Forecast Frenzy v3 on Streamlit Community Cloud

Branch `perf/community-cloud-optimization` · November 2026 · tested on Streamlit 1.67 (and 1.50 for compatibility)

## A. Executive summary

The lab was **CPU-bound**. Memory was never close to a limit. Each student click re-runs the
whole page on the server. Before this work, one click cost about 70 ms of server CPU. A class
working at full speed fills one CPU core at around 20 students, and after that every student's
screen slows down together.

Four things caused almost all of that cost:

1. **A full garbage collection after every click.** Streamlit does this by default. It scans
   every object in memory and was about 20% of all CPU.
2. **The Module 11 hold-out table was recalculated on every click.** It refits trend models for
   every day of the term, and that one calculation was about 19% of CPU.
3. **Charts were rebuilt with Altair on every click.** Each one cost about 14 ms, and all
   students' chart conversions wait on one shared lock inside Streamlit.
4. **Deprecated calls logged a warning on every click.** Two of these APIs are also scheduled
   for removal, so a future Streamlit update would have broken the app.

When Dropbox progress saving is turned on, there was a fifth problem: every change waited on a
network upload before the student's screen could update.

**Result:** server CPU per student is down about **65%**. With 40 simulated students working
through the whole lab, median response time fell from 1.7 s to 0.07 s. Module 11 now responds
in about 20–30 ms instead of 0.15–7 s. All features, numbers, charts and downloads are
unchanged, and that was checked: the same results on 1,216 scenarios, and charts that match the
old ones pixel for pixel in Chrome.

## B. Optimization results

All measurements are local. The server was pinned to **one CPU core**, a stand-in for
Community Cloud's small shared CPU. The load came from simulated students using Streamlit's real
WebSocket protocol, so each one is a real session. "Lab" means each student walks all 15
screens and does about 27 actions, with a 1 s pause between actions. That is a stress test,
roughly 30× faster than real students. "Paced" uses 6 s pauses.

| Component | Problem identified | Modification | Measured improvement |
|---|---|---|---|
| Application startup | Altair imported on every cold start; workbook built on first page view | Altair no longer imported; workbook cached per scenario (built once, about 30 ms) | Memory right after the first student: 233 → 205 MB. First open for one student: 890 → 614 ms (server time) |
| Page loading | Full GC plus deprecation logging on every rerun | `runner.postScriptGC=false`; deprecated APIs replaced | Navigation p50 for 1 student: 56 → 25 ms. At 40 students (stress): 1,935 → 52 ms |
| Session management | Session state snapshotted and serialized several times per rerun | One snapshot per rerun | Included in CPU figures below |
| CPU utilization | Module 11 refits on every click; Altair conversion; GC | Cached and vectorized Module 11 (results identical); Vega-Lite specs; GC setting | Total CPU for 40 full lab passes: **76.1 → 26.7 CPU-s (−65%)**. Per action: 70 → 25 ms |
| Memory consumption | (no problem found) | Bounded caches (256 entries each) | Peak at 40 students: 297 → 265 MB. With storage on: 525 → 410 MB |
| File uploads | **The app has no file uploads** | n/a | n/a |
| File downloads | Workbook rebuilt/re-registered on every rerun; each download click re-ran the whole page | Bytes cached per scenario; `on_click="ignore"` | Workbook download p50 at 40 students: 161 → 7 ms. Downloads no longer cause a rerun |
| Caching | `st.cache_data` wrappers rebuilt on every rerun; outputs re-pickled on every call | Process-wide `lru_cache` in `ff_core.py`, keyed only by scenario and instructor parameters; each caller gets a private copy | Module 11 response: 153 → 19 ms (1 student), 7,285 → 29 ms (40 students) |
| Concurrent users | One core saturated at about 20 students | All of the above | See section D |
| Progress saving (Dropbox) | Every change blocked on an upload | Background writer: coalesced, ordered per student, sign-out still synchronous | 40 students with simulated 0.4 s upload latency: p50 3,211 → 1,103 ms; CPU 117 → 50 CPU-s |

## C. Code modifications

| File | Change |
|---|---|
| `ff_core.py` (new) | The pure computations moved here unchanged: scenario data, simulated term, forecasting methods, workbook. A Python module is imported once per process, so its caches persist across reruns and sessions. `cycle_trend_forecast` was rewritten from O(n²) pandas groupbys to running sums, and is bit-for-bit identical. The Module 11 table is now one cached function. |
| `ff_progress.py` (new) | Background, coalescing writer for Dropbox saves. It calls the unchanged `student_store.save()`. |
| `forecast_frenzy.py` | Uses `ff_core`. Charts are fixed Vega-Lite specs instead of Altair. Downloads use `on_click="ignore"`. `use_container_width` → `width="stretch"`. `components.v1.html` → `st.iframe` (falls back on older Streamlit). Saves are submitted to the background writer. `save()` no longer re-snapshots. |
| `.streamlit/config.toml` (new) | `[runner] postScriptGC = false`. This is not one of the settings Community Cloud overrides. |
| `.gitignore` | **Fixed:** it was named `,gitignore`, so git ignored nothing. It now ignores `.streamlit/secrets.toml`, which protects the Dropbox keys, but not `config.toml`. |
| `requirements.txt` | `streamlit>=1.50,<2` (tested on 1.50 with Python 3.9+ and on 1.67). Removed `altair` because Streamlit still installs it as its own dependency. |
| `tests/` (new) | 17 regression tests: identical forecasts versus the original code, copy-on-read caches, writer ordering and coalescing, every screen rendering, session isolation, and durable save/restore. Run with `python -m pytest tests -q`. |
| `perf/` (new) | Load tester (`loadtest.py`), resource monitor, and a one-command bench script. |

`student_store.py`, `juice_director.py` and `manifest.py` are **unchanged**, as their headers
require.

**Compatibility notes**
- Deferred download generation (`data=callable`) was tried and **rejected**. Under load,
  Streamlit 1.67 can delete a just-generated file before the browser fetches it, and the load
  test hit HTTP 404 errors at 20+ users.
- The background writer means a change made in the last second or two before a server crash
  might not reach Dropbox. It is re-saved on the student's next action. "Save & sign out" still
  waits for and confirms its write.

## D. Testing results

**Before vs. after, 1 CPU core, full lab pass per student, 1 s think time (stress)**

| Students | p50 base → opt (ms) | p95 base → opt (ms) | Server CPU base → opt (CPU-s) | Peak RSS base → opt (MB) | Errors |
|---|---|---|---|---|---|
| 1 | 59 → 26 | 879 → 603 | 2.8 → 1.3 | 233 → 205 | 0 / 0 |
| 5 | 69 → 25 | 355 → 147 | 10.6 → 4.3 | 240 → 211 | 0 / 0 |
| 10 | 80 → 26 | 677 → 154 | 18.7 → 7.5 | 247 → 220 | 0 / 0 |
| 20 | 136 → 31 | 2,767 → 843 | 33.6 → 14.0 | 264 → 237 | 0 / 0 |
| 30 | 872 → 42 | 4,043 → 2,305 | 54.4 → 20.5 | 277 → 251 | 0 / 0 |
| 40 | 1,730 → 65 | 6,506 → 3,010 | 76.1 → 26.7 | 297 → 265 | 0 / 0 |

**40 students, 6 s think time (still faster than a real class):** p50 98 → 34 ms, p95 879 →
170 ms, average server CPU 48% → 18% of one core.

**40 students opening the app at the same instant, including downloading the page's
JavaScript and CSS:** time to first render p50 7.6 → 5.3 s. Most of what remains is the
browser bundle transfer on one core, which is a platform cost (section F). Navigation
immediately after: p50 1,236 → 67 ms.

**Real browser (Chrome) checks.** No page errors. Workbook and PDF downloads work. Scroll-to-top
on Continue behaves the same as before. All 5 charts screenshotted (Start, Module 5 ×2, Module 8,
Module 11) are pixel-identical to the original. Time to interactive for a single student is
about 1.7 s in both versions; that is dominated by the browser loading Streamlit's JavaScript.

**Correctness.** Scenario data, the term, every forecast column, the Module 11 score table and
the workbook contents all match the original code exactly for 1,216 scenarios across 4
instructor configurations. The test suite passes on Streamlit 1.67 + pandas 3 and on Streamlit
1.50 + pandas 2.

**Not measured:** actual Community Cloud CPU or throttling behavior, real Dropbox latency (a
0.4 s simulated latency was used), and client-side rendering on slow student laptops.

## E. GitHub

Branch `perf/community-cloud-optimization`, with a pull request into `main`. Nothing is merged.

## F. Remaining constraints (platform)

- **Resources are not guaranteed.** Streamlit documents approximate limits as of February 2024:
  CPU 0.078 cores minimum up to 2 cores maximum, and memory 690 MB minimum up to 2.7 GB maximum.
  It also says they "may change at any time without notice". How much CPU an app actually gets
  at a given moment is unknown.
- **Memory is comfortable.** About 265 MB at 40 students, or about 410 MB with storage on, which
  is under the 690 MB floor.
- **CPU is the binding constraint.** After this work, a real class pace (one click per student
  every 20–60 s) is roughly 1–2 clicks per second at about 25 ms each, or 3–5% of one core. That
  fits even a small allocation. Bursts, such as everyone pressing Continue at once or the
  start-of-class open, depend on how much CPU Cloud grants at that moment. **Supporting 30–40
  concurrent students is realistic for this workload.** The guarantee is limited by the
  platform's unpublished CPU share, not by the app.
- **First load is dominated by Streamlit's browser bundle (several MB) served from the same
  container.** Code cannot change that. Having students open the app a few minutes before class
  helps.
- **Apps sleep after 12 hours without traffic.** Open the app before class so the first student
  doesn't wait for the wake-up.
- **Optional:** Streamlit offers increased resources for educational use; see the Community Cloud
  docs. Setting `server.fileWatcherType = "none"` would save a little more CPU, but Community
  Cloud relies on file watching to apply pushed code, so it was not changed.
