# sections/feedback.py
# In-app feedback widget -- a collapsed expander pinned to the bottom of
# every page (wired once from app.py's routing block, not duplicated per
# section file, since this app has no persistent sidebar to anchor it to).
#
# Purpose isn't feature-request triage, it's validation evidence: does
# AppingHQ actually close the "I don't know what to do" gap it's meant to
# close, not just "is this fast." So the questions lead with pre/post
# clarity before touching time-saved or feature usage. See onboarding.py's
# step 0 for the same thesis in explainer form.
#
# All fields optional -- Send is always enabled, since a single filled-in
# suggestion is worth more than a blocked, abandoned form. Every choice
# widget starts at index=None (no default selection) so a skipped question
# logs as blank rather than silently recording whatever option happened to
# sit first in the list.
#
# Reuses the existing analytics pipeline (backend/analytics.py) rather than
# a separate CSV/Sheet -- log_event already handles the Sheets write, user
# identity, and timestamp the same way every other funnel/error event in
# this app does, so feedback shows up in the same place analysts already
# look.

import streamlit as st
from backend import analytics

_KEYS = [
    "fb_knew_steps",
    "fb_clarity",
    "fb_time_saved",
    "fb_most_useful",
    "fb_would_recommend",
    "fb_suggestions",
]


def _clear_inputs():
    for k in _KEYS:
        if k in st.session_state:
            del st.session_state[k]


def render(page: str = ""):
    with st.expander("💬 Got feedback?"):
        st.caption("Less than a minute — and it directly shapes what gets built next.")

        knew_steps = st.radio(
            "Before using AppingHQ, did you know what steps to take in your job search?",
            ["Not at all", "Had a rough idea", "Knew exactly what to do"],
            index=None,
            key="fb_knew_steps",
        )
        clarity = st.radio(
            "Did AppingHQ make that clearer?",
            ["A lot clearer", "A little clearer", "Not clearer", "Haven't used it enough to say"],
            index=None,
            key="fb_clarity",
        )
        time_saved = st.radio(
            "Did it save you time compared to doing it manually?",
            ["Yes, a lot", "A little", "Not really", "Haven't used it enough to say"],
            index=None,
            key="fb_time_saved",
        )
        most_useful = st.radio(
            "Which part was most useful?",
            ["JD Matching", "Outreach messages", "Inbound tracker", "Company research", "Nothing yet"],
            index=None,
            key="fb_most_useful",
        )
        would_recommend = st.radio(
            "Would you recommend this to another job seeker?",
            ["Yes", "Maybe", "No"],
            index=None,
            key="fb_would_recommend",
        )
        suggestions = st.text_area(
            "What's still confusing or manual, even after using this?",
            key="fb_suggestions",
            placeholder="Optional -- but this is the part that helps most.",
        )

        if st.button("Send", key="fb_submit"):
            answered = any(
                [knew_steps, clarity, time_saved, most_useful, would_recommend, (suggestions or "").strip()]
            )
            if not answered:
                st.warning("Add at least one answer before sending.")
            else:
                details = (
                    f"knew_steps_before={knew_steps or ''} | "
                    f"clarity_gained={clarity or ''} | "
                    f"time_saved={time_saved or ''} | "
                    f"most_useful_feature={most_useful or ''} | "
                    f"would_recommend={would_recommend or ''} | "
                    f"suggestions={(suggestions or '').strip()} | "
                    f"page={page}"
                )
                analytics.log_event("usage", "feedback_submitted", details=details)
                _clear_inputs()
                st.session_state["fb_just_submitted"] = True
                st.rerun()

        if st.session_state.pop("fb_just_submitted", False):
            st.success("Thanks -- this genuinely helps 🙏")