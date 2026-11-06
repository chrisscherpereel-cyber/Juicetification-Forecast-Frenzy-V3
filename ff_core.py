"""
ff_core.py — the pure, cacheable computation behind Forecast Frenzy.

WHY THIS FILE EXISTS (performance)
Streamlit re-executes forecast_frenzy.py from top to bottom on EVERY click, for EVERY
student. Anything defined in that script is rebuilt on each rerun — including the
@st.cache_data wrappers, which re-read their own source code each time. Code in an
imported module like this one runs ONCE per server process, so its caches are plain,
cheap dictionary lookups.

Everything here is a deterministic function of (scenario seed, instructor parameters).
Nothing here ever sees a student's name, id or answers, so sharing these caches
between sessions cannot leak one student's data to another: two students only ever
share a cached entry if they were already given the identical scenario.

Cached values are shared between sessions, so the public accessors below hand each
caller its OWN copy (DataFrame.copy) — a caller can never mutate the shared original.
The copies cost microseconds; the computations they replace cost milliseconds.
"""

import io
from functools import lru_cache

import numpy as np
import pandas as pd

# Bounded caches. Each entry is a few KB (a 4-week grid, an 84-day frame, a ~14 KB
# workbook), so even a full cache is well under a few MB. A class of 40 with unique
# scenarios needs 40 entries; 256 leaves room for several sections and Director
# configurations before the oldest entries are evicted (and simply recomputed).
CACHE_SIZE = 256

# ----------------------------------------------------------------------------
# Constants shared with the app (moved here unchanged from forecast_frenzy.py)
# ----------------------------------------------------------------------------
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DOW_INDEX = {"Mon": 1.05, "Tue": 1.00, "Wed": 1.10, "Thu": 1.08,
             "Fri": 0.95, "Sat": 0.55, "Sun": 0.60}
REG = {"intercept": 40, "temp": 2.5, "promo": 45, "attend": 1.8}   # given equation

# V3: Module 8 (seasonality WITH trend) uses the SAME cycle as the rest of the lab —
# one cycle = one week, the seven seasons = Mon…Sun — so the method the student works
# by hand is exactly the "seasonal + trend" method scored in Module 11.
ST_CYCLES = 4                      # four weeks of history, as in Module 7
ST_COLS = ["B", "C", "D", "E", "F", "G", "H"]      # one column per day, Mon…Sun


# ----------------------------------------------------------------------------
# Least-squares helper
# ----------------------------------------------------------------------------
def ls_fit(x, y):
    """Simple linear regression by the least-squares formulas taught in class.
    Returns (slope b, intercept a, r_squared)."""
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    xb, yb = x.mean(), y.mean()
    sxx = float(((x - xb) ** 2).sum())
    sxy = float(((x - xb) * (y - yb)).sum())
    b = sxy / sxx if sxx else 0.0
    a = yb - b * xb
    syy = float(((y - yb) ** 2).sum())
    r2 = (sxy ** 2) / (sxx * syy) if sxx and syy else 0.0
    return b, a, r2


# ----------------------------------------------------------------------------
# Per-scenario teaching data (unchanged logic)
# ----------------------------------------------------------------------------
def _make_lab_data(seed, base_demand):
    rng = np.random.default_rng(seed + 7)
    r5 = lambda a, b: int(round(rng.uniform(a, b) / 5) * 5)
    r10 = lambda a, b: int(round(rng.uniform(a, b) / 10) * 10)
    week = {d: r5(280, 335) for d in ["Mon", "Tue", "Wed", "Thu", "Fri"]}
    sat_actual = r5(320, 360)
    es_alpha = float(rng.choice([0.2, 0.3, 0.4]))
    es_F = r5(300, 320)
    es_A = es_F + r10(20, 40)
    es_A2 = es_F - r10(10, 30)
    # Seasonality: 4 weeks of daily demand — students compute the averages.
    seas_grid = []
    for _wk in range(4):
        seas_grid.append([int(round((base_demand * DOW_INDEX[d] + rng.normal(0, 8)) / 5) * 5)
                          for d in DAYS])
    wed_i, sat_i = DAYS.index("Wed"), DAYS.index("Sat")
    wed_col = [seas_grid[w][wed_i] for w in range(4)]
    sat_col = [seas_grid[w][sat_i] for w in range(4)]
    all_vals = [v for row in seas_grid for v in row]
    wed_avg = sum(wed_col) / 4
    sat_avg = sum(sat_col) / 4
    grand = sum(all_vals) / len(all_vals)
    r1 = (r5(75, 90), 1, r5(80, 92))
    r2 = (r5(50, 62), 0, r5(55, 68))
    acts = [r10(180, 260), r10(230, 300), r10(280, 340), r10(360, 430)]
    errs = [int(x) for x in rng.choice([-30, -20, -10, 10, 20, 30], size=4, replace=True)]
    fcs = [int(a + e) for a, e in zip(acts, errs)]

    # ---- V3 | Module 6 data: a genuinely TRENDING series (12 periods) --------
    # "Mango Sunrise" bottles sold per week since launch — a clean upward trend.
    lt_scale = base_demand / 320.0                       # follows the instructor's base demand
    lt_b_true = float(rng.choice([14.0, 16.0, 18.0, 20.0, 22.0])) * lt_scale
    lt_a_true = r5(170, 230) * lt_scale
    lt_t = list(range(1, 13))
    lt_y = [int(round(lt_a_true + lt_b_true * t + rng.normal(0, 9 * lt_scale))) for t in lt_t]
    lt_slope, lt_int, lt_r2 = ls_fit(lt_t, lt_y)
    lt_fc13 = lt_int + lt_slope * 13
    lt_fc14 = lt_int + lt_slope * 14
    # A deliberately FLAT companion series — used for the deck's low-R2 caution.
    # Pure noise over only 12 points can accidentally look like a trend, which would
    # wreck the teaching point, so resample until the fitted line really is flat.
    lt_flat, lt_flat_r2 = None, 1.0
    for _attempt in range(200):
        cand = [int(round(2.4 * base_demand + rng.normal(0, 20 * lt_scale))) for _ in range(12)]
        _fb, _fa, cand_r2 = ls_fit(lt_t, cand)
        if cand_r2 < 0.12:
            lt_flat, lt_flat_r2 = cand, cand_r2
            break
    if lt_flat is None:                      # belt-and-braces fallback (never hit in testing)
        lt_flat = [int(round(2.4 * base_demand + d)) for d in
                   (0, -12, 11, -5, 6, -18, 9, -9, 3, -13, -2, -6)]
        _fb, _fa, lt_flat_r2 = ls_fit(lt_t, lt_flat)

    # ---- V3 | Module 8 data: 4 cycles (weeks) x 7 seasons (days), trending up
    # Same grid SHAPE as Module 7's seasonality data, but the weekly level climbs.
    # That contrast is the point: identical layout, one extra signal to handle.
    # Day indices are the bar's own day-of-week shape, normalised to average 1.0
    # so the grand average is a fair "typical day" benchmark.
    _dow_mean = sum(DOW_INDEX[d] for d in DAYS) / 7.0
    st_idx_true = [DOW_INDEX[d] / _dow_mean for d in DAYS]
    st_lvl1 = r5(270, 300) * lt_scale                 # week-1 average daily demand
    st_growth = r5(25, 35) * lt_scale                 # extra customers per day, per week
    st_cycnums = list(range(1, ST_CYCLES + 1))

    def _build_st_grid(week_noise, day_noise):
        # A week-level shock as well as a day-level one, so the weekly averages don't
        # sit perfectly on a line (an R-squared of exactly 1.000 looks fake).
        g = []
        for wk in range(ST_CYCLES):
            lvl = st_lvl1 + st_growth * wk + rng.normal(0, week_noise * lt_scale)
            g.append([int(round(lvl * ix + rng.normal(0, day_noise * lt_scale)))
                      for ix in st_idx_true])
        return g

    # The module tells the student these weekly averages "climb steadily", and the whole
    # point of the trend step is that they do. Random shocks can flip two adjacent weeks,
    # which would make the teaching text wrong, so resample until the four really do rise
    # and the line through them is convincing. The fallback drops the week-level shock.
    st_grid, st_cycavg = None, None
    for _attempt in range(200):
        cand = _build_st_grid(7, 6)
        cavg = [sum(row) / 7.0 for row in cand]
        _cb, _ca_, cr2 = ls_fit(st_cycnums, cavg)
        if all(cavg[k] < cavg[k + 1] for k in range(ST_CYCLES - 1)) and cr2 >= 0.85:
            st_grid, st_cycavg = cand, cavg
            break
    if st_grid is None:
        st_grid = _build_st_grid(0, 6)
        st_cycavg = [sum(row) / 7.0 for row in st_grid]
    # Every answer below is derived from the GRID the student actually sees.
    st_b, st_a, st_r2 = ls_fit(st_cycnums, st_cycavg)
    st_next = [ST_CYCLES + 1, ST_CYCLES + 2]           # the two weeks being projected
    st_proj = [st_a + st_b * w for w in st_next]
    st_dayavg = [sum(st_grid[c][dd] for c in range(ST_CYCLES)) / float(ST_CYCLES)
                 for dd in range(7)]
    st_all = [v for row in st_grid for v in row]
    st_grand = sum(st_all) / len(st_all)
    st_indices = [da / st_grand for da in st_dayavg]
    st_fc_w5 = [st_proj[0] * ix for ix in st_indices]
    st_fc_w6 = [st_proj[1] * ix for ix in st_indices]

    return {"week": week, "sat_actual": sat_actual,
            "es_alpha": es_alpha, "es_F": es_F, "es_A": es_A, "es_A2": es_A2,
            "seas_grid": seas_grid, "wed_avg": wed_avg, "sat_avg": sat_avg, "grand": grand,
            "base": base_demand, "r1": r1, "r2": r2, "acts": acts, "fcs": fcs,
            # Module 6 — linear trend projection
            "lt_t": lt_t, "lt_y": lt_y, "lt_slope": lt_slope, "lt_int": lt_int,
            "lt_r2": lt_r2, "lt_fc13": lt_fc13, "lt_fc14": lt_fc14,
            "lt_flat": lt_flat, "lt_flat_r2": lt_flat_r2,
            # Module 8 — seasonality with trend (cycle = week, seasons = Mon…Sun)
            "st_grid": st_grid, "st_cycnums": st_cycnums, "st_cycavg": st_cycavg,
            "st_b": st_b, "st_a": st_a, "st_r2": st_r2,
            "st_next": st_next, "st_proj": st_proj,
            "st_dayavg": st_dayavg, "st_grand": st_grand, "st_indices": st_indices,
            "st_fc_w5": st_fc_w5, "st_fc_w6": st_fc_w6}


def _simulate_semester(seed, n_days, base_demand, growth_per_day):
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_days):
        dow = DAYS[d % 7]
        week = d // 7 + 1
        temp = float(np.clip(rng.normal(72 + 0.15 * d, 8), 45, 100))
        weather = 1.0 + 0.010 * (temp - 72)
        exam = 1 if week in (6, 12) else 0
        event = 1 if rng.random() < 0.12 else 0
        attendance = float(np.clip(rng.normal(82, 9) * DOW_INDEX[dow], 20, 100))
        promo = 1 if rng.random() < 0.18 else 0
        growth = 1.0 + growth_per_day * d          # V3: the juice bar is growing
        mean = (base_demand * DOW_INDEX[dow] * weather * growth * (1.18 if exam else 1)
                * (1.35 if event else 1) * (attendance / 82.0) * (1.22 if promo else 1))
        demand = int(max(0, rng.normal(mean, mean * 0.08)))
        rows.append({"day": d + 1, "week": week, "dow": dow, "temp_f": round(temp, 1),
                     "exam": exam, "event": event, "attendance": round(attendance, 1),
                     "promo": promo, "demand": demand})
    return pd.DataFrame(rows)


def naive_forecast(s): return s.shift(1)
def moving_average(s, w): return s.shift(1).rolling(w).mean()


def exp_smoothing(s, alpha):
    v = s.values.astype(float); fc = np.full(len(v), np.nan)
    if len(v):
        level = v[0]
        for t in range(1, len(v)):
            fc[t] = level; level = alpha * v[t] + (1 - alpha) * level
    return pd.Series(fc, index=s.index)


def seasonal_indices(df):
    return (df.groupby("dow")["demand"].mean() / df["demand"].mean()).reindex(DAYS).to_dict()


def seasonal_naive_forecast(df):
    idx = seasonal_indices(df)
    return df["demand"].shift(1).rolling(7).mean() * df["dow"].map(idx)


# ---- V3 | Module 6 method: linear trend projection (simple linear regression)
# NOTE on fairness: naive, moving average, exponential smoothing and the seasonal
# method are all ONE-STEP-AHEAD forecasts that only ever use data before the day
# being forecast. The two new methods are scored exactly the same way — refit on
# everything up to yesterday, then project one day. Fitting them once on the
# training half instead would have scored them against a 14-day-ahead projection
# while every rival got a one-day-ahead one, making the Module 11 table meaningless.
def linear_trend_forecast(frame, min_obs=14):
    """Expanding-window least squares: each day's forecast comes from the line
    fitted to every PRIOR day."""
    y = frame["demand"].values.astype(float)
    t = frame["day"].values.astype(float)
    out = np.full(len(frame), np.nan)
    for i in range(min_obs, len(frame)):
        b, a, _r2 = ls_fit(t[:i], y[:i])
        out[i] = a + b * t[i]
    return pd.Series(out, index=frame.index)


# ---- V3 | Module 8 method: seasonality WITH trend, cycle-average style -------
def cycle_trend_forecast(frame, min_cycles=3):
    """Module 8's method applied to the daily series, with the CYCLE = one week
    and the SEASONS = the seven days of the week. For each day, using only data
    from before it:
        1. average each COMPLETE prior cycle (week)    -> cycle averages
        2. regress cycle average on cycle number       -> project this week
        3. season index = day average / grand average
        4. forecast = projected cycle average x season index

    PERFORMANCE: the original version re-ran three pandas groupbys on every prefix of
    the series (O(n^2) groupby calls, ~85% of this screen's CPU). This version gets the
    same prefix statistics from running sums in one pass. Because demand values are
    integers, every sum is exact in floating point, so each average — and therefore
    every forecast — is bit-for-bit identical to the original (verified by
    tests/test_equivalence.py against the original implementation on hundreds of
    scenarios).
    """
    n = len(frame)
    out = np.full(n, np.nan)
    demand = frame["demand"].to_numpy(dtype=float)
    weeks = frame["week"].to_numpy()
    dows = frame["dow"].to_numpy(dtype=object)

    wk_sum, wk_cnt = {}, {}          # week -> running sum / count of PRIOR days
    day_sum, day_cnt = {}, {}        # day-of-week -> running sum / count of PRIOR days
    tot = 0.0
    for i in range(n):
        if i:
            # fold day i-1 into the prior-data statistics
            w, dname, v = weeks[i - 1], dows[i - 1], demand[i - 1]
            wk_sum[w] = wk_sum.get(w, 0.0) + v; wk_cnt[w] = wk_cnt.get(w, 0) + 1
            day_sum[dname] = day_sum.get(dname, 0.0) + v
            day_cnt[dname] = day_cnt.get(dname, 0) + 1
            tot += v
        else:
            continue                                  # no prior data for day 0
        full_w = sorted(w for w, c in wk_cnt.items() if c == 7)   # complete cycles only
        if len(full_w) < min_cycles:
            continue
        b, a, _r2 = ls_fit(np.asarray(full_w), np.asarray([wk_sum[w] / wk_cnt[w] for w in full_w]))
        grand = tot / i
        if not grand or dows[i] not in day_cnt:
            continue
        out[i] = (a + b * float(weeks[i])) * ((day_sum[dows[i]] / day_cnt[dows[i]]) / grand)
    return pd.Series(out, index=frame.index)


def regression_fit(df):
    X = np.column_stack([np.ones(len(df)), df["temp_f"], df["promo"], df["attendance"],
                         df["exam"], df["event"]])
    y = df["demand"].values.astype(float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta, X @ beta


def mad(a, f):
    a, f = np.asarray(a, float), np.asarray(f, float); m = ~np.isnan(f)
    return float(np.mean(np.abs(a[m] - f[m]))) if m.any() else np.nan


def mape(a, f):
    a, f = np.asarray(a, float), np.asarray(f, float); m = (~np.isnan(f)) & (a != 0)
    return float(np.mean(np.abs((a[m] - f[m]) / a[m])) * 100) if m.any() else np.nan


def rmse(a, f):
    a, f = np.asarray(a, float), np.asarray(f, float); m = ~np.isnan(f)
    return float(np.sqrt(np.mean((a[m] - f[m]) ** 2))) if m.any() else np.nan


# ============================================================================
# Companion Excel workbook — coords match the app (unchanged logic)
# ============================================================================
def _build_workbook(seed, base_demand):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    L = _make_lab_data(seed, base_demand); W = L["week"]
    ARIAL = "Arial"
    tf = Font(name=ARIAL, size=14, bold=True); hf = Font(name=ARIAL, size=11, bold=True)
    nf = Font(name=ARIAL, size=11); note = Font(name=ARIAL, size=10, italic=True, color="555555")
    yel = PatternFill("solid", fgColor="FFF2CC"); blu = PatternFill("solid", fgColor="DDEBF7")
    grey = PatternFill("solid", fgColor="F2F2F2")
    thin = Side(style="thin", color="BBBBBB"); bx = Border(thin, thin, thin, thin)
    ctr = Alignment(horizontal="center")
    wb = Workbook()

    def setup(ws, t, sub):
        ws["A1"] = t; ws["A1"].font = tf; ws["A2"] = sub; ws["A2"].font = note
        ws.column_dimensions["A"].width = 40
        for c in "BCDEFGH": ws.column_dimensions[c].width = 12

    def data(ws, ref, v):
        ws[ref] = v; ws[ref].fill = blu; ws[ref].border = bx; ws[ref].font = nf; ws[ref].alignment = ctr

    def inp(ws, ref):
        ws[ref].fill = yel; ws[ref].border = bx; ws[ref].font = nf; ws[ref].alignment = ctr

    ws = wb.active; ws.title = "README"
    setup(ws, "Juicetification: Forecast Frenzy — Excel Practice Workbook",
          f"Scenario ID {seed}. Type a FORMULA (start with =) in every YELLOW cell. Use CELL "
          "REFERENCES, never typed-in numbers.")
    for i, t in enumerate([
        "", "LEGEND:  Yellow = you fill in (write a formula)   |   Blue = given data",
        "", "Naive:           = the previous day's cell",
        "Moving average:  =AVERAGE(range)",
        "Exp. smoothing:  =Fprev + alpha*(Actual - Fprev)     (reference the alpha cell)",
        "Linear trend:    b =SLOPE(yRange,tRange)   a =INTERCEPT(yRange,tRange)   R2 =RSQ(...)",
        "                 then Forecast = aCell + bCell*periodCell   (or =TREND(y,t,newT))",
        "Seasonal index:  day average and overall average are AVERAGE() formulas you build,",
        "                 then index = dayAvgCell / overallAvgCell ; Forecast = baseCell * indexCell",
        "Seas.+trend:     cycle averages -> =TREND(cycleAvgs,cycleNums,nextCycle) -> projected CA;",
        "                 index = seasonAvgCell / grandAvgCell ; Forecast = projectedCA * indexCell",
        "Regression:      =interceptCell + tempCoefCell*Temp + promoCoefCell*Promo + attCoefCell*Att",
        "MAD:             =AVERAGE(|error| column)    MAPE = AVERAGE(|error|/actual)*100",
        "", "Cell references here MATCH the app. Type your formula, then check it in the app."],
            start=4):
        ws[f"A{i}"] = t; ws[f"A{i}"].font = nf
    ws.column_dimensions["A"].width = 96

    for name, sub in [("Naive", "F(t+1)=A(t)"), ("MovingAvg", "F(t+1)=average of last n days")]:
        ws = wb.create_sheet(name); setup(ws, name, sub)
        dd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        vv = [W["Mon"], W["Tue"], W["Wed"], W["Thu"], W["Fri"], L["sat_actual"]]
        ws["A4"] = "Day"; ws["A4"].font = hf; ws["A5"] = "Actual"; ws["A5"].font = hf
        for j, (d, v) in enumerate(zip(dd, vv)):
            c = get_column_letter(2 + j)
            ws[f"{c}4"] = d; ws[f"{c}4"].font = hf; ws[f"{c}4"].alignment = ctr
            data(ws, f"{c}5", v)
        if name == "Naive":
            ws["A7"] = "Saturday naive forecast (=Fri)"; ws["A7"].font = nf; inp(ws, "B7")
            ws["A8"] = "Thursday abs error =ABS(Thu-Wed)"; ws["A8"].font = nf; inp(ws, "B8")
        else:
            ws["A7"] = "3-day MA forecast for Saturday"; ws["A7"].font = nf; inp(ws, "B7")
            ws["A8"] = "3-day MA forecast for Sunday"; ws["A8"].font = nf; inp(ws, "B8")

    ws = wb.create_sheet("ExpSmoothing"); setup(ws, "Exp. smoothing", "F(t+1)=F(t)+alpha*(A(t)-F(t))")
    ws["A4"] = "alpha"; ws["A4"].font = hf; data(ws, "B4", L["es_alpha"])
    ws["A6"] = "Day"; ws["B6"] = "Prior F"; ws["C6"] = "Actual"; ws["D6"] = "New forecast (next day)"
    for c in "ABCD": ws[f"{c}6"].font = hf
    ws["A7"] = "Day 1"; ws["A7"].font = nf; data(ws, "B7", L["es_F"]); data(ws, "C7", L["es_A"]); inp(ws, "D7")
    ws["A8"] = "Day 2"; ws["A8"].font = nf; data(ws, "C8", L["es_A2"]); inp(ws, "D8")
    ws["A10"] = "Day-2 prior forecast is your Day-1 answer (D7). Hint: =B7+$B$4*(C7-B7)"; ws["A10"].font = note

    # ---- V3: Module 6 — linear trend projection ----------------------------
    ws = wb.create_sheet("LinearTrend")
    setup(ws, "Linear trend projection", "Least squares: y-hat = a + b*t  (t = period number)")
    for c in "IJKLM": ws.column_dimensions[c].width = 12
    ws["A4"] = "Period (t)"; ws["A4"].font = hf
    ws["A5"] = "Bottles sold"; ws["A5"].font = hf
    for j in range(12):
        c = get_column_letter(2 + j)
        data(ws, f"{c}4", L["lt_t"][j]); data(ws, f"{c}5", L["lt_y"][j])
    for lab, ref in [("Slope  b   =SLOPE(B5:M5,B4:M4)", "B8"),
                     ("Intercept  a   =INTERCEPT(B5:M5,B4:M4)", "B9"),
                     ("R-squared   =RSQ(B5:M5,B4:M4)", "B10")]:
        r = int(ref[1:]); ws[f"A{r}"] = lab; ws[f"A{r}"].font = nf; inp(ws, ref)
    ws["A12"] = "Next period to forecast (t)"; ws["A12"].font = nf; data(ws, "B12", 13)
    ws["A13"] = "Forecast for t = 13   =B9+B8*B12"; ws["A13"].font = nf; inp(ws, "B13")
    ws["A14"] = "Period after that (t)"; ws["A14"].font = nf; data(ws, "B14", 14)
    ws["A15"] = "Forecast for t = 14   =B9+B8*B14"; ws["A15"].font = nf; inp(ws, "B15")
    ws["A17"] = ("Shortcuts that give the same answer: =TREND(B5:M5,B4:M4,B12)  or  "
                 "=FORECAST.LINEAR(B12,B5:M5,B4:M4)")
    ws["A17"].font = note
    ws["A18"] = ("CAUTION: a LOW R-squared means the data is random — there is no trend to "
                 "project, so do not use this method.")
    ws["A18"].font = note

    ws = wb.create_sheet("Seasonality"); setup(ws, "Seasonality", "You compute the averages first.")
    ws["A4"] = "Week"; ws["A4"].font = hf
    for j, d in enumerate(DAYS):
        c = get_column_letter(2 + j); ws[f"{c}4"] = d; ws[f"{c}4"].font = hf; ws[f"{c}4"].alignment = ctr
    for wk in range(4):
        ws[f"A{5+wk}"] = f"Wk {wk+1}"; ws[f"A{5+wk}"].font = nf
        for j, v in enumerate(L["seas_grid"][wk]):
            data(ws, f"{get_column_letter(2+j)}{5+wk}", v)
    labels = [("Wed average  =AVERAGE(D5:D8)", "B10"), ("Sat average  =AVERAGE(G5:G8)", "B11"),
              ("Overall (grand) average  =AVERAGE(B5:H8)", "B12"), ("Base level", "B13"),
              ("Wed index  =B10/B12", "B14"), ("Sat index  =B11/B12", "B15"),
              ("Wed forecast  =B13*B14", "B16")]
    for lab, ref in labels:
        r = int(ref[1:]); ws[f"A{r}"] = lab; ws[f"A{r}"].font = nf
        if ref == "B13":
            data(ws, ref, L["base"])
        else:
            inp(ws, ref)

    # ---- V3: Module 8 — seasonality with trend (cycle = week, seasons = days)
    ws = wb.create_sheet("SeasonalTrend")
    setup(ws, "Seasonality with trend", "Weekly averages -> trend -> day indices -> forecast")
    ws["A4"] = "Week"; ws["A4"].font = hf
    for j, dname in enumerate(DAYS):
        c = ST_COLS[j]; ws[f"{c}4"] = dname; ws[f"{c}4"].font = hf; ws[f"{c}4"].alignment = ctr
    for wk in range(ST_CYCLES):
        ws[f"A{5+wk}"] = f"Wk {wk+1}"; ws[f"A{5+wk}"].font = nf
        for j, v in enumerate(L["st_grid"][wk]):
            data(ws, f"{ST_COLS[j]}{5+wk}", v)
    ws["A10"] = "Cycle (week) number"; ws["A10"].font = nf
    for j, v in enumerate(L["st_cycnums"]):
        data(ws, f"{ST_COLS[j]}10", v)
    ws["A11"] = "1. Cycle average  =AVERAGE(B5:H5)"; ws["A11"].font = nf
    for c in ST_COLS[:ST_CYCLES]: inp(ws, f"{c}11")
    ws["A12"] = "Weeks to project"; ws["A12"].font = nf
    data(ws, "B12", L["st_next"][0]); data(ws, "C12", L["st_next"][1])
    ws["A13"] = "2. Projected weekly avg  =TREND($B$11:$E$11,$B$10:$E$10,B12)"; ws["A13"].font = nf
    for c in "BC": inp(ws, f"{c}13")
    ws["A15"] = "3. Day average  =AVERAGE(B5:B8)"; ws["A15"].font = nf
    ws["A16"] = "4. Grand average  =AVERAGE(B5:H8)"; ws["A16"].font = nf
    ws["A17"] = "5. Day index  =B15/$B$16"; ws["A17"].font = nf
    ws["A19"] = "6. Forecast Week 5  =$B$13*B17"; ws["A19"].font = nf
    ws["A20"] = "   Forecast Week 6  =$C$13*B17"; ws["A20"].font = nf
    for c in ST_COLS:
        inp(ws, f"{c}15"); inp(ws, f"{c}17"); inp(ws, f"{c}19"); inp(ws, f"{c}20")
    inp(ws, "B16")
    ws["A22"] = ("The trend lives in the WEEKLY AVERAGES; the seasonality lives in the DAY "
                 "INDICES. Multiply them back together to forecast any day of any future week.")
    ws["A22"].font = note

    ws = wb.create_sheet("Regression"); setup(ws, "Regression", "Demand=40+2.5*Temp+45*Promo+1.8*Att")
    for i, (lab, v) in enumerate([("Intercept", REG["intercept"]), ("Temp coef", REG["temp"]),
                                  ("Promo coef", REG["promo"]), ("Attend coef", REG["attend"])], start=4):
        ws[f"A{i}"] = lab; ws[f"A{i}"].font = nf; data(ws, f"B{i}", v)
    ws["A9"] = "Temp"; ws["B9"] = "Promo"; ws["C9"] = "Attendance"; ws["D9"] = "Predicted"
    for c in "ABCD": ws[f"{c}9"].font = hf
    for i, row in enumerate([L["r1"], L["r2"]], start=10):
        for j, v in enumerate(row): data(ws, f"{get_column_letter(1+j)}{i}", v)
        inp(ws, f"D{i}")
    ws["A13"] = "Hint: =$B$4+$B$5*A10+$B$6*B10+$B$7*C10 (reference the coefficient cells)"
    ws["A13"].font = note

    ws = wb.create_sheet("Accuracy"); setup(ws, "Accuracy", "MAD=avg|err| ; MAPE=avg(|err|/act)*100")
    for j, h in enumerate(["Day", "Actual", "Forecast", "|Error|", "%Error"]):
        c = get_column_letter(1 + j); ws[f"{c}4"] = h; ws[f"{c}4"].font = hf; ws[f"{c}4"].alignment = ctr
    for i in range(4):
        r = 5 + i
        ws[f"A{r}"] = i + 1; ws[f"A{r}"].font = nf; ws[f"A{r}"].alignment = ctr
        data(ws, f"B{r}", L["acts"][i]); data(ws, f"C{r}", L["fcs"][i]); inp(ws, f"D{r}"); inp(ws, f"E{r}")
    ws["A10"] = "MAD (customers)"; ws["A10"].font = hf; inp(ws, "B10")
    ws["A11"] = "MAPE (%)"; ws["A11"].font = hf; inp(ws, "B11")
    ws["A13"] = "Hints: D5 =ABS(B5-C5) ; E5 =D5/B5 ; MAD =AVERAGE(D5:D8) ; MAPE =AVERAGE(E5:E8)*100"
    ws["A13"].font = note

    # No Answer Key sheet in the student workbook — the app checks answers and the
    # yellow-cell hints guide the formulas, so we do not ship the worked solutions.
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()

# ============================================================================
# Cached, copy-on-read accessors used by the app
# ============================================================================
def lab_data(seed, base_demand):
    """Per-scenario teaching data (Modules 3-10). Deliberately NOT cached: it takes
    ~0.6 ms to build, which is less than a defensive deep copy of a cached result
    would cost, so each rerun simply gets a fresh one (exactly as before)."""
    return _make_lab_data(seed, base_demand)


@lru_cache(maxsize=CACHE_SIZE)
def _semester_cached(seed, n_days, base_demand, growth_per_day):
    return _simulate_semester(seed, n_days, base_demand, growth_per_day)


def simulate_semester(seed, n_days, base_demand, growth_per_day):
    """The simulated term. Returns a private copy of the cached frame."""
    return _semester_cached(int(seed), int(n_days), base_demand, growth_per_day).copy()


METHODS = ["naïve", "MA3", "exp. smoothing", "linear trend", "seasonal", "seasonal + trend",
           "regression"]


@lru_cache(maxsize=CACHE_SIZE)
def _model_selection_cached(seed, n_days, base_demand, growth_per_day, holdout):
    df = _semester_cached(seed, n_days, base_demand, growth_per_day)
    train = df.iloc[:-holdout].copy()
    d = df.copy()
    d["naïve"] = naive_forecast(d["demand"]); d["MA3"] = moving_average(d["demand"], 3)
    d["exp. smoothing"] = exp_smoothing(d["demand"], 0.3); d["seasonal"] = seasonal_naive_forecast(d)
    d["linear trend"] = linear_trend_forecast(d)
    d["seasonal + trend"] = cycle_trend_forecast(d)
    beta, _ = regression_fit(train)
    Xte = np.column_stack([np.ones(len(df)), df["temp_f"], df["promo"], df["attendance"],
                           df["exam"], df["event"]])
    d["regression"] = Xte @ beta
    te = d.iloc[-holdout:]
    score = pd.DataFrame([{"method": m, "MAD": round(mad(te["demand"], te[m]), 1),
                           "MAPE %": round(mape(te["demand"], te[m]), 1),
                           "RMSE": round(rmse(te["demand"], te[m]), 1)} for m in METHODS])
    return d, score


def model_selection(seed, n_days, base_demand, growth_per_day, holdout=14):
    """Module 11's hold-out table: (frame with every method's one-step forecasts,
    score table). The expanding-window refits behind it are the most expensive
    computation in the app, so they run once per scenario, not once per click.
    Returns private copies."""
    d, score = _model_selection_cached(int(seed), int(n_days), base_demand, growth_per_day,
                                       int(holdout))
    return d.copy(), score.copy()


@lru_cache(maxsize=CACHE_SIZE)
def workbook_bytes(seed, base_demand):
    """The student's Excel practice workbook (immutable bytes, safe to share)."""
    return _build_workbook(int(seed), base_demand)

