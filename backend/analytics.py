# backend/analytics.py
# Lightweight event logger for AppingHQ, writing rows to a Google Sheet via a
# service account. Designed to NEVER break the app -- every failure is caught
# and swallowed (optionally printed to the terminal for debugging), since
# analytics going down should never take the product down with it.
#
# Sheet columns (row 1 headers), in order:
#   timestamp | user_email | event_type | event_name | details | session_id
#
# event_type is one of: "usage", "funnel", "error"
# user_email is the signed-in user's email, or "anonymous" if logged out.

import uuid
from datetime import datetime, timezone

import streamlit as st

_CLIENT = None
_SHEET = None
_INIT_FAILED = False


def _get_sheet():
    """Lazily connect to the Google Sheet. Cached for the process lifetime."""
    global _CLIENT, _SHEET, _INIT_FAILED

    if _SHEET is not None:
        return _SHEET
    if _INIT_FAILED:
        return None

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
        ]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)

        sheet_id = st.secrets["analytics"]["sheet_id"]
        sheet = client.open_by_key(sheet_id).worksheet("Events")

        _CLIENT = client
        _SHEET = sheet
        return _SHEET
    except Exception as e:
        # Don't crash the app if analytics can't connect -- just stop trying
        # for the rest of this process and move on silently.
        _INIT_FAILED = True
        print(f"[analytics] failed to connect to Google Sheet: {e}")
        return None


def _get_session_id() -> str:
    """One random ID per browser session, stable across reruns."""
    if "analytics_session_id" not in st.session_state:
        st.session_state.analytics_session_id = str(uuid.uuid4())[:8]
    return st.session_state.analytics_session_id


def _get_user_email() -> str:
    """Signed-in user's email, or 'anonymous' if not logged in."""
    try:
        if getattr(st, "user", None) and st.user.is_logged_in:
            return st.user.email
    except Exception:
        pass
    return "anonymous"


def log_event(event_type: str, event_name: str, details: str = ""):
    """
    Log one event. Never raises -- any failure is caught and swallowed so
    analytics can never break the app.

    event_type: "usage" | "funnel" | "error"
    event_name: short identifier, e.g. "page_view", "entry_added", "sign_in"
    details: free-text extra context, e.g. "page=outreach" or an error message
    """
    try:
        sheet = _get_sheet()
        if sheet is None:
            return

        row = [
            datetime.now(timezone.utc).isoformat(),
            _get_user_email(),
            event_type,
            event_name,
            details,
            _get_session_id(),
        ]
        sheet.append_row(row, value_input_option="RAW")
    except Exception as e:
        # Swallow everything -- a broken analytics call should never surface
        # to the user or interrupt whatever they were doing.
        print(f"[analytics] failed to log event ({event_type}/{event_name}): {e}")


def log_page_view(page: str):
    """Convenience wrapper -- only call this when the page actually changes,
    not on every rerun (see track_page_view in app.py for the change check)."""
    log_event("usage", "page_view", details=f"page={page}")


def log_sign_in():
    log_event("usage", "sign_in")


def log_error(context: str, message: str):
    log_event("error", context, details=message)
