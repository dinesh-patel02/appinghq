# backend/auth.py
# Thin wrapper around st.login() (Google OIDC) for the "sign in only when
# you actually try to save something" flow. Nobody is forced to log in
# just to browse and try the tools -- see prompt_login()'s call sites in
# outreach.py / inbound_tracker.py, which only fire at the "Add to
# tracker" / "Save changes" actions, not on page load.
from __future__ import annotations
import streamlit as st


def current_user_email() -> str | None:
    """None if nobody's logged in. st.user raises if [auth] isn't
    configured in secrets at all, so this fails safe to "not logged in"
    rather than crashing the page during local dev without auth set up."""
    try:
        if st.user.is_logged_in:
            return st.user.email
    except Exception:
        pass
    return None


def prompt_login(reason: str, key: str) -> None:
    """Shows a sign-in prompt inline (not a full-page block). reason is
    the tail end of 'Sign in with Google to ___', e.g. 'save this to your
    tracker'."""
    st.info(f"Sign in with Google to {reason} — otherwise it'll only stick around for this session.")
    if st.button("Sign in with Google", key=key, use_container_width=True):
        st.login("google")
