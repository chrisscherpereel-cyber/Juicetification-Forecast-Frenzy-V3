"""Shared sign-in screen for every Juicetification simulation.

Identical copy lives in each app's repo so all games sign students in the same way:
the student makes up an ID they will remember, and signing in again with that same ID
resumes their saved progress. The screen never says WHICH ID to use.

The ID is kept in the URL as ?sid= (via student_store), exactly as before, so saved
progress, per-student scenarios, and instructor links that already carry ?sid= keep working.
"""

import streamlit as st

import student_store as store

GATE_KEY = "_login_id"


def require_login(title, icon="🧃", required=None):
    """Show the sign-in screen and stop the page until the student has signed in.

    Returns the signed-in ID. `required` defaults to store.enabled(): with no shared
    storage configured there is nothing to save or resume, so the screen is skipped and
    None is returned (the app then behaves exactly as before)."""
    sid = store.get_student_id()
    if sid:
        return sid
    if required is None:
        required = store.enabled()
    if not required:
        return None

    st.title(f"{icon} Juicetification: {title}")
    st.subheader("Sign in")
    st.write("Create an ID you will remember and use it every time you return. "
             "Your progress is saved under this ID, so signing in again with the "
             "**same ID** picks up right where you left off.")
    with st.form("login_gate", clear_on_submit=False, border=False):
        entered = st.text_input("Your ID", key=GATE_KEY,
                                autocomplete="off",
                                help="Type it exactly the same way each time — "
                                     "capital letters count.")
        submitted = st.form_submit_button("Sign in ▶", type="primary")
    st.caption("Tip: write your ID down. Please don't use a password.")
    if submitted:
        entered = (entered or "").strip()
        if entered:
            store.set_student_id(entered)
            st.rerun()
        else:
            st.warning("Please enter an ID to sign in.")
    st.stop()
