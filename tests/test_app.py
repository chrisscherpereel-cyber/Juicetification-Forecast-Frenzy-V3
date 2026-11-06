"""End-to-end checks with Streamlit's AppTest (headless; run:  python -m pytest tests -q).

Walks every screen, exercises a checked answer, an exploration slider, the model-selection
table, Run Juicetification and the final report, and verifies that two sessions running
at the same time keep separate scenarios and separate answers.
"""
import os

import pytest

APP = os.path.join(os.path.dirname(__file__), "..", "forecast_frenzy.py")

st_testing = pytest.importorskip("streamlit.testing.v1")


def _new(seed=None, sid=None):
    at = st_testing.AppTest.from_file(APP, default_timeout=120)
    if seed is not None:
        at.query_params["seed"] = str(seed)
    if sid is not None:
        at.query_params["sid"] = sid
    at.run()
    assert not at.exception, at.exception
    return at


def _goto(at, label):
    at.selectbox(key="nav").set_value(label)
    at.run()
    assert not at.exception, at.exception


def test_every_screen_renders():
    at = _new(seed=4242)
    for label in at.selectbox(key="nav").options:
        _goto(at, label)


def test_checked_answer_slider_model_selection_and_report():
    at = _new(seed=4242)
    screens = at.selectbox(key="nav").options

    _goto(at, screens[3])                                  # Module 3 — Naïve
    at.number_input(key="ni_in_r3_sat").set_value(300.0)
    at.button(key="btn_r3_sat").click().run()
    assert "r3_sat" in at.session_state["responses"]

    _goto(at, screens[5])                                  # Module 5 — slider exploration
    at.slider(key="sl_r5a").set_value(0.6).run()
    assert not at.exception
    assert "r5_explore" in at.session_state["responses"]

    _goto(at, screens[11])                                 # Module 11 — hold-out table
    assert len(at.dataframe) == 1
    table = at.dataframe[0].value
    assert list(table["method"]) == ["naïve", "MA3", "exp. smoothing", "linear trend",
                                     "seasonal", "seasonal + trend", "regression"]
    at.selectbox(key="sb_r9pick").set_value("seasonal + trend").run()
    assert at.session_state["chosen_method"] == "seasonal + trend"

    _goto(at, screens[12])                                 # Run Juicetification
    [b for b in at.button if "Lock in" in b.label][0].click().run()
    [b for b in at.button if "Open" in b.label][0].click().run()
    assert not at.exception
    assert len(at.session_state["runs"]) == 1

    _goto(at, screens[14])                                 # Final report
    labels = [d.label for d in at.get("download_button")]
    assert any("submission PDF" in lab for lab in labels)


def test_concurrent_sessions_are_isolated():
    a = _new(seed=1111)
    b = _new(seed=2222)
    assert a.session_state["seed"] == 1111 and b.session_state["seed"] == 2222
    screens = a.selectbox(key="nav").options
    _goto(a, screens[3]); _goto(b, screens[3])
    a.number_input(key="ni_in_r3_sat").set_value(123.0)
    a.button(key="btn_r3_sat").click().run()
    b.run()
    assert "r3_sat" in a.session_state["responses"]
    assert "r3_sat" not in b.session_state["responses"]
    # the two scenarios are different data
    grid_a = [m.value for m in a.markdown if "<table" in m.value]
    grid_b = [m.value for m in b.markdown if "<table" in m.value]
    assert grid_a and grid_b and grid_a != grid_b


def test_in_memory_progress_restores_for_same_student_only():
    a = _new(sid="student-aaa")
    screens = a.selectbox(key="nav").options
    _goto(a, screens[1])
    a.number_input(key="ni_r1g").set_value(310.0).run()
    assert "r1_guess" in a.session_state["responses"]

    again = _new(sid="student-aaa")            # same student returns (new session)
    assert "r1_guess" in again.session_state["responses"]
    other = _new(sid="student-bbb")            # a different student sees nothing of it
    assert "r1_guess" not in other.session_state["responses"]


def test_durable_store_saves_in_background_and_restores(monkeypatch):
    """With (fake, slow) durable storage enabled: answers are uploaded by the background
    writer, the newest snapshot wins, and a returning student gets everything back."""
    import json
    import threading
    import time

    import student_store as store
    from ff_progress import WRITER

    db, lock, calls = {}, threading.Lock(), []

    def fake_save(game, sid, state, **kw):
        time.sleep(0.05)                                   # network latency
        with lock:
            db[(game, sid)] = json.dumps(state); calls.append(sid)
        return True

    def fake_load(game, sid):
        with lock:
            raw = db.get((game, sid))
        return json.loads(raw) if raw else {}

    monkeypatch.setattr(store, "enabled", lambda: True)
    monkeypatch.setattr(store, "save", fake_save)
    monkeypatch.setattr(store, "load", fake_load)

    at = _new(sid="durable-1")
    screens = at.selectbox(key="nav").options
    _goto(at, screens[1])
    at.number_input(key="ni_r1g").set_value(305.0).run()
    _goto(at, screens[3])
    at.number_input(key="ni_in_r3_sat").set_value(300.0)
    at.button(key="btn_r3_sat").click().run()
    assert WRITER.flush((None, "durable-1"), timeout=10)
    saved = json.loads(db[(None, "durable-1")])
    assert {"r1_guess", "r3_sat"} <= set(saved["responses"])

    back = _new(sid="durable-1")                           # returning student
    assert {"r1_guess", "r3_sat"} <= set(back.session_state["responses"])
    assert back.session_state["seed"] == at.session_state["seed"]
