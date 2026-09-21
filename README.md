# 🥤 Juicetification: Forecast Frenzy

**A guided, hands-on forecasting lab for introductory Operations Management — Version 3.0**

Students step into the role of manager of *Juicetification*, the campus juice bar in the
student union. Over about 75 minutes they learn and **apply** every core demand-forecasting
method — computing each one by hand, writing the matching Excel formula, and then using their
best forecast to staff and stock the bar for a day of business. The lab closes with a
structured debrief and a submittable PDF report.

Each student receives a **unique scenario** (a random Session ID), so no two students work the
same numbers, yet every answer is auto-checked.

---

## Learning objectives

By the end of the lab a student can:

1. Explain what forecasting is and why service-sector demand is *perishable*.
2. Use qualitative signals (manager judgment, customer comments, known events).
3. Compute **naïve**, **moving-average**, and **exponential-smoothing** forecasts.
4. Fit a **linear trend** by least squares (slope, intercept), project it forward, and use
   **R²** to judge whether a trend exists at all.
5. Build and apply day-of-week **seasonal indices** (computing the day and grand averages).
6. Combine **seasonality with trend** by the cycle-average method, with one cycle = one week
   and the seven seasons = Mon–Sun: weekly averages → trend projection → day indices →
   recombined forecast.
7. Forecast from drivers with a **regression** equation.
8. Measure accuracy with **MAD** and **MAPE**.
9. Read hold-out errors, identify the best model, and defend the selection.
10. Write the **Excel formula** for every method using proper cell references.
11. Turn a forecast into an operating plan and feel the dollar cost of forecast error.

---

## What's in the box

| File | Purpose |
|---|---|
| `forecast_frenzy.py` | The complete single-file Streamlit application. |
| `manifest.py` | The app's parameter schema for the Juicetification Director. |
| `juice_director.py` | Shared Director config loader (identical across every simulation repo). |
| `student_store.py` | Shared per-student progress store (identical across every simulation repo). |
| `README.md` | This file. |
| `Juicetification_Forecast_Frenzy_Quickstart.pdf` | One-page printable student quick-start sheet. |
| `Juicetification_Forecast_Frenzy_Quickstart.html` | Editable source of the quick-start sheet. |
| `Juicetification_Forecast_Frenzy_Development_Paper.docx` | Academic paper on the design and theory of the simulation. |
| `requirements.txt` | Python dependencies. |

The **Excel practice workbook** and the **submission PDF** are generated *inside* the app and
downloaded by the student — nothing to distribute separately.

---

## Requirements

- Python 3.9+
- `streamlit`, `pandas`, `numpy`, `openpyxl`

The PDF export uses a built-in, dependency-free writer — no extra packages required.

---

## Quick start

```bash
pip install streamlit pandas numpy openpyxl
streamlit run forecast_frenzy.py
```

The app opens in your browser. Students work left-to-right through the tabs; everything they
enter is saved automatically for the session.

---

## Instructor configuration (Juicetification Director)

Run without any URL parameters, the app uses its built-in defaults and behaves exactly as
described here. It also plugs into the Juicetification Director so an instructor can vary the
economics and demand without editing code. This is handled by two files, `manifest.py` (this
app's parameter schema) and `juice_director.py` (a loader that is identical in every simulation
repo, so it never needs editing).

Supported URL parameters:

- `?manifest=1` returns this app's parameter schema as JSON, so the Director can discover it.
- `?cfg=<base64 json>` applies a self-contained configuration (for example a different price or
  base demand). Values are type-checked and clamped to the limits in `manifest.py`.
- `?game=<code>` looks up a stored configuration through an optional shared endpoint.
- `?seed=<int>` fixes the scenario. A fixed seed gives an entire class the same data, while the
  default (no seed) gives each student a unique Session ID.

Configurable parameters include price, variable cost, fruit and bottle costs, wage, shift hours,
service rate, promotion cost and lift, the stockout penalty, base daily demand, and — new in v3 —
**demand growth per day**, the size of the trend in the generated term. Base daily demand and the
growth rate both shape the generated demand series, so both are included in the caching key to
keep different class configurations independent. Setting `growth_per_day` to 0 restores a flat,
trendless term (Modules 6 and 8 keep their own teaching data either way, so they still work).

---

## Progress persistence and resume (optional)

When the storage secrets are configured, `student_store.py` persists each student's progress so
they can leave and resume, and each student receives a stable, unique scenario derived from their
student id. With a student id present in the URL (`?sid=`), a refresh automatically restores
state, and a completion record is written when the lab is finished. When the secrets are not set,
every storage call is a safe no-op and the app behaves exactly as it does by default.

Configuration lives in Streamlit secrets or environment variables: `DB_ENCRYPTION_KEY` plus
either `DROPBOX_REFRESH_TOKEN` with `DROPBOX_APP_KEY` and `DROPBOX_APP_SECRET`, or
`DROPBOX_ACCESS_TOKEN`. The `dropbox` and `cryptography` packages in `requirements.txt` are
required once durable storage is enabled.

If those secrets are **not** configured but a student id is present in the URL (`?sid=`), the app
falls back to an in-memory, per-student store so progress still survives an exit and refresh for
the life of the running server process (it is cleared only if the server restarts). Durable,
cross-restart persistence still requires the Dropbox secrets above.

---

## How the lab flows

The lab is organized as a set of tabs. Every learning module follows the same rhythm:

> **Objective → Formula → *You apply it* → *Write the Excel formula* → Feedback → Guiding question → Apply it again**

**Tabs, in order:**

1. **📖 Start Here** — the business, the "perishable capacity" idea, and a warm-up.
2. **Modules 1–2** — what forecasting is; qualitative forecasting from a given briefing.
3. **Modules 3–5** — naïve, moving average, and exponential smoothing (with guided
   exploration of window width and the smoothing constant α).
4. **Module 6 — Linear trend projection** *(new in v3)* — students compute the least-squares
   **slope** and **intercept**, project two future periods, and compute **R²**. A side-by-side
   stable series shows why a low R² means *do not* project a trend.
5. **Module 7** — seasonality: students compute the **day average** and **overall (grand)
   average** themselves, then form and apply the index.
6. **Module 8 — Seasonality with trend** *(new in v3)* — the cycle-average method on **four
   weeks of daily demand**, the same grid shape as Module 7 but with the weekly level climbing:
   average each week, regress the four weekly averages on week number to project week 5, compute
   the seven day indices, then multiply the two back together. This is the same method the
   *seasonal + trend* row of Module 11 is scored on, so the hand calculation and the hold-out
   table are one and the same.
7. **Module 9** — regression from temperature, promotions, and attendance.
8. **Module 10 — Accuracy** — compute MAD and MAPE (placed *before* model selection on purpose).
9. **Module 11 — Model selection** — read the hold-out error table (now including *linear trend*
   and *seasonal + trend*), identify the lowest error, and select a method to carry forward.
10. **🏪 Run *Juicetification*** — choose a forecast → calculate the staffing/prep plan → implement
   it → open for the day and see the P&L.
11. **🎓 Debrief** — a structured *What? / So what? / Now what?* that surfaces the student's own
   biggest forecast miss, its dollar cost, and one rule to carry into a real operation.
12. **📝 Final Report** — review checklist, scores, and the downloadable submission PDF.

### Applying the formulas

For every calculation the student chooses how hands-on to be — *compute it myself* (checked with
worked solution), *estimate then reveal*, or *show answer and interpret*. They then write the
**Excel formula**, which the app actually evaluates against the on-screen grid. Formulas must use
**cell references**; typing a value that appears in the grid is rejected, so students build real
spreadsheet skills.

---

## How students are scored

Three scores are reported **separately**, so effort never hides a shaky calculation:

- **Completeness /100** — how much of the lab was finished (effort).
- **Mastery /100** — share of calculations and Excel formulas correct on the **first try** (skill).
- **Performance /100** — how well the operating plan matched demand while running *Juicetification*
  (application: 60% profit vs. a perfectly-matched plan, 40% customer satisfaction).

Written reflections use lightweight **self-rubrics** (e.g., *names a cause, names a trade-off,
connects to a decision*) so the qualitative work gets formative structure too.

---

## Submission

On the **Final Report** tab the student reviews a completeness checklist (and can revisit any tab
to edit), then downloads a **submission PDF** containing their name, Session ID, selected method,
all three scores, and every answer, Excel formula, and reflection. Markdown and CSV exports are
also available.

---

## For facilitators

- **Reproducible scenarios.** Each student's data is keyed to their Session ID, shown on the PDF —
  useful for spot-checking or regenerating a student's exact numbers.
- **Grading.** The PDF captures reasoning and marks calculations correct/incorrect; the CSV export
  gives a quick machine-readable record. The three scores separate effort, skill, and application.
- **Time.** Budget about 60 to 90 minutes; the per-module objective boxes carry suggested minutes, and a class that explores every method in depth will trend toward the upper end.
- **Configuration.** Cost and demand assumptions live in clearly labeled constants near the top of
  `forecast_frenzy.py` (price, variable cost, wage, service rate, promo economics, day-of-week
  seasonality). Adjust them to match your course context.

---

## Design notes

- **Unique-but-checkable data.** Scenario numbers are randomized per session yet rounded so hand
  calculations stay clean and answers remain auto-gradable.
- **Feedback after input.** Evaluative feedback appears only after the student acts — no
  answers or verdicts are shown before a response.
- **Experiential arc.** Concrete decision (run the bar) → reflective debrief → an abstract rule the
  student commits to carrying forward, mirroring the experiential-learning cycle.

---

## Version

**V3.0** — adds two modules drawn from the *Class 8 & 9 — Forecasting* lecture deck:

- **Module 6 · Linear trend projection.** Simple linear regression on the period number.
  Students compute slope and intercept themselves (`SLOPE`, `INTERCEPT`), project two periods
  ahead, and compute `RSQ` — then see the same method applied to a deliberately *stable* series,
  where a low R² makes trend projection the wrong choice. Mirrors the deck's "Caution: using
  Excel" slides.
- **Module 8 · Seasonality with trend.** The deck's cycle-average method, with **one cycle = one
  week and the seven seasons = Mon–Sun**. Students get four weeks of daily demand laid out exactly
  like the Module 7 grid — the only difference is that the weekly level now climbs. Weekly averages
  isolate the trend, a regression on week number projects week 5's level, day indices capture the
  repeating shape, and the two are multiplied back together to forecast every day of the next two
  weeks. Because the cycle is the same week used everywhere else in the lab, this is *literally*
  the `seasonal + trend` method scored in Module 11 — the hand calculation and the hold-out row
  are the same arithmetic.

Supporting changes:

- The simulated term now contains **real growth** (`growth_per_day`, instructor-configurable via
  the Director manifest), so trend-aware methods have something genuine to find. Both new methods
  are scored on the same 14-day hold-out in Module 11 and can be carried into *Run
  Juicetification*. Every method is scored as a one-day-ahead forecast using only data from
  before that day, so the comparison is like-for-like.
- The Excel practice workbook gains **LinearTrend** and **SeasonalTrend** tabs with matching cell
  references.
- The formula checker now evaluates `SLOPE`, `INTERCEPT`, `RSQ`, `CORREL`, `TREND`, `FORECAST`
  and `FORECAST.LINEAR`.
- **Two fixes carried over from v2.** Seasonal-index answers were accepted within ±0.6 — which
  accepted essentially any number for an answer near 1.0; numeric tolerances now take a per-item
  floor. And a stray `None` rendered under every calculation block (a trailing comma turned each
  `num_task(...)` call into a tuple, which Streamlit's magic display printed); removed.

**V1.0** — first publication release.

*All figures in the simulation are illustrative and for educational use.*
