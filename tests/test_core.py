"""Regression tests for the performance work (run:  python -m pytest tests -q).

1. The rewritten Module 8 / Module 11 'seasonal + trend' method gives bit-for-bit the
   same forecasts as the original O(n^2) pandas implementation (kept below verbatim).
2. Shared caches hand out private copies, so one session can never alter another's data.
3. The background progress writer coalesces, keeps per-student order, and flushes.
"""
import io
import os
import sys
import threading
import time
import zipfile

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ff_core as core  # noqa: E402
from ff_progress import ProgressWriter  # noqa: E402


# --- the ORIGINAL implementation from forecast_frenzy.py v3, unchanged ----------------
def cycle_trend_forecast_original(frame, min_cycles=3):
    out = np.full(len(frame), np.nan)
    weeks = frame["week"].values
    dows = frame["dow"].values
    for i in range(len(frame)):
        prior = frame.iloc[:i]
        if prior.empty:
            continue
        grp = prior.groupby("week")["demand"]
        counts, avgs = grp.count(), grp.mean()
        full = avgs[counts == 7]
        if len(full) < min_cycles:
            continue
        b, a, _r2 = core.ls_fit(full.index.values, full.values)
        grand = prior["demand"].mean()
        day_means = prior.groupby("dow")["demand"].mean()
        if not grand or dows[i] not in day_means.index:
            continue
        out[i] = (a + b * float(weeks[i])) * (day_means[dows[i]] / grand)
    return pd.Series(out, index=frame.index)


CONFIGS = [(320, 0.004), (320, 0.0), (500, 0.012), (150, 0.02)]


@pytest.mark.parametrize("base,growth", CONFIGS)
def test_cycle_trend_identical_to_original(base, growth):
    for seed in range(1000, 1060):
        df = core.simulate_semester(seed, 84, base, growth)
        new = core.cycle_trend_forecast(df)
        old = cycle_trend_forecast_original(df)
        # exact equality, NaNs in the same places
        assert np.array_equal(new.to_numpy(), old.to_numpy(), equal_nan=True), seed


def test_model_selection_table_shape_and_winner_is_stable():
    d, score = core.model_selection(4242, 84, 320, 0.004)
    assert list(score["method"]) == core.METHODS
    assert set(core.METHODS) <= set(d.columns)
    d2, score2 = core.model_selection(4242, 84, 320, 0.004)
    pd.testing.assert_frame_equal(score, score2)


def test_cached_results_are_private_copies():
    d, score = core.model_selection(1111, 84, 320, 0.004)
    d.loc[:, "demand"] = -1
    score.loc[:, "MAD"] = -1
    d2, score2 = core.model_selection(1111, 84, 320, 0.004)
    assert (d2["demand"] >= 0).all() and (score2["MAD"] >= 0).all()

    df = core.simulate_semester(1111, 84, 320, 0.004)
    df["demand"] = 0
    assert core.simulate_semester(1111, 84, 320, 0.004)["demand"].sum() > 0


def test_different_configs_never_share_cache_entries():
    a = core.simulate_semester(2000, 84, 320, 0.004)
    b = core.simulate_semester(2000, 84, 500, 0.004)
    c = core.simulate_semester(2000, 84, 320, 0.0)
    assert not a["demand"].equals(b["demand"]) and not a["demand"].equals(c["demand"])


def test_workbook_is_valid_and_deterministic():
    b1 = core.workbook_bytes(3000, 320)
    b2 = core.workbook_bytes(3000, 320)
    assert b1 is b2                                    # served from cache
    names = zipfile.ZipFile(io.BytesIO(b1)).namelist()
    assert "xl/workbook.xml" in names
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(b1))
    assert wb.sheetnames == ["README", "Naive", "MovingAvg", "ExpSmoothing", "LinearTrend",
                             "Seasonality", "SeasonalTrend", "Regression", "Accuracy"]
    L = core.lab_data(3000, 320)
    assert wb["LinearTrend"]["B5"].value == L["lt_y"][0]


# --- background progress writer -----------------------------------------------------
def test_writer_coalesces_and_keeps_latest():
    w = ProgressWriter(workers=1)
    seen, gate = [], threading.Event()

    def slow_save(key, val):
        gate.wait(5); seen.append((key, val))

    w.submit("s1", slow_save, "s1", 1)          # starts, blocks on gate
    time.sleep(0.05)
    for v in (2, 3, 4):                          # queued while 1 is in flight: coalesce
        w.submit("s1", slow_save, "s1", v)
    gate.set()
    assert w.flush("s1", timeout=5)
    assert seen == [("s1", 1), ("s1", 4)]


def test_writer_never_runs_one_students_saves_concurrently():
    w = ProgressWriter(workers=4)
    active, overlap, done = {"n": 0}, [], []
    lock = threading.Lock()

    def save(v):
        with lock:
            active["n"] += 1
            overlap.append(active["n"])
        time.sleep(0.02)
        with lock:
            active["n"] -= 1
        done.append(v)

    for v in range(10):
        w.submit("same-student", save, v)
        time.sleep(0.005)
    assert w.flush("same-student", timeout=5)
    assert max(overlap) == 1                      # strictly one at a time
    assert done[-1] == 9                          # the newest snapshot always lands last


def test_writer_survives_failures_and_flush_times_out_cleanly():
    w = ProgressWriter(workers=1)

    def boom():
        raise RuntimeError("network down")
    w.submit("k", boom)
    assert w.flush("k", timeout=5)
    assert w.failed == 1
    ok = []
    w.submit("k", lambda: ok.append(1))
    assert w.flush("k", timeout=5) and ok == [1]


def test_writer_discard_drops_queued_job():
    w = ProgressWriter(workers=1)
    gate, ran = threading.Event(), []
    w.submit("a", lambda: gate.wait(5))
    time.sleep(0.05)
    w.submit("a", lambda: ran.append("queued"))
    w.discard("a")
    gate.set()
    assert w.flush("a", timeout=5)
    assert ran == []
