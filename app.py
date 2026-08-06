# app.py
# AppingHQ -- main entry point and custom navigation.
#
# Navigation is a small state machine using st.session_state.page, rather than
# Streamlit's default sidebar multipage nav, since the product needs a landing
# page and a choice screen before the actual tools.
#
# States:
#   "landing"          -> intro + Get started button
#   "onboarding"       -> what is apping / outreach vs inbound explainer (5-step wizard)
#   "choice"           -> Outreach / Inbound cards
#   "outreach"         -> Outreach tracker + message generator
#   "inbound_choice"   -> JD Match / Tracker cards (inside Inbound)
#   "inbound_jd"       -> JD match tool
#   "inbound_tracker"  -> Inbound tracker + LinkedIn message generator
#
# "Get started" on landing routes into "onboarding" rather than straight to
# "choice" -- apping is IITB-specific slang and the outreach/inbound split
# isn't self-explanatory, so first-time users get a short explainer wizard
# before picking a path. onboarding_step (separate from page) tracks
# progress within that wizard; it's reset implicitly by never being read
# outside onboarding.py, so re-entering "onboarding" later just resumes
# wherever the counter was left, which is fine since "Skip intro" is always
# available and the wizard is idempotent to revisit.

import streamlit as st
from style import inject_base_css, clickable_card, render_header
from sections import outreach, inbound_tracker, jd_match, onboarding, feedback
from backend import analytics

st.set_page_config(page_title="AppingHQ", layout="wide", initial_sidebar_state="collapsed")

if "page" not in st.session_state:
    st.session_state.page = "landing"
if "theme" not in st.session_state:
    st.session_state.theme = "light"  # light mode by default

inject_base_css()

# ── ANALYTICS: sign-in (fires once per session, right after login happens) ──
if getattr(st, "user", None) and st.user.is_logged_in and not st.session_state.get(
    "analytics_sign_in_logged"
):
    analytics.log_sign_in()
    st.session_state.analytics_sign_in_logged = True


def go(page: str):
    st.session_state.page = page
    st.rerun()


# ── LANDING ─────────────────────────────────────────────────────────────────
def render_landing():
    render_header(back_target=None, go_fn=go)  # toggle only, no back link
    st.write("")
    st.markdown(
        '<div class="ah-narrow">'
        '<div class="ah-eyebrow">AppingHQ</div>'
        '<div class="ah-title">Looking for a job?</div>'
        '<div class="ah-body">So are we. AppingHQ is how we keep our apping organized.</div>'
        '<div class="ah-body-muted">No more fifteen browser tabs, three spreadsheets, '
        'and a WhatsApp chat with yourself. Apping, in one place.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 0.6, 1])
    with col2:
        if st.button("Get started", key="get_started", use_container_width=True):
            go("onboarding")


# ── CHOICE SCREEN ───────────────────────────────────────────────────────────
def render_choice():
    render_header(back_target="landing", go_fn=go)
    st.markdown(
        '<div class="ah-narrow">'
        '<div class="ah-title-mid">A job\'s a lot like dating. Sometimes you shoot your shot, '
        'sometimes they slide into your DMs first. So what will you do?</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    col_pad_l, col1, col2, col_pad_r = st.columns([0.6, 1, 1, 0.6])
    with col1:
        if clickable_card("outreach", "Outreach", "Shoot your shot."):
            go("outreach")
    with col2:
        if clickable_card("inbound", "Inbound", "They're in your DMs."):
            go("inbound_choice")


# ── INBOUND SUB-CHOICE ──────────────────────────────────────────────────────
def render_inbound_choice():
    render_header(back_target="choice", go_fn=go)
    st.markdown(
        '<div class="ah-narrow">'
        '<div class="ah-title-mid">They texted first. Now what?</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    col_pad_l, col1, col2, col_pad_r = st.columns([0.6, 1, 1, 0.6])
    with col1:
        if clickable_card("jd", "JD Match", "See if you're actually their type."):
            go("inbound_jd")
    with col2:
        if clickable_card("tracker", "Tracker", "Don't leave them on read."):
            go("inbound_tracker")


# ── ROUTING ──────────────────────────────────────────────────────────────────
page = st.session_state.page

# ── ANALYTICS: page view (only log when the page actually changed) ─────────
if st.session_state.get("_analytics_last_page") != page:
    analytics.log_page_view(page)
    st.session_state._analytics_last_page = page

if page == "landing":
    render_landing()
elif page == "onboarding":
    render_header(back_target="landing", go_fn=go)
    onboarding.render(go)
elif page == "choice":
    render_choice()
elif page == "outreach":
    render_header(back_target="choice", go_fn=go)
    outreach.render()
elif page == "inbound_choice":
    render_inbound_choice()
elif page == "inbound_jd":
    render_header(back_target="inbound_choice", go_fn=go)
    jd_match.render()
elif page == "inbound_tracker":
    render_header(back_target="inbound_choice", go_fn=go)
    inbound_tracker.render()
else:
    st.session_state.page = "landing"
    st.rerun()

# ── FEEDBACK: only on pages where the person has actually used a real
# feature (outreach tool, inbound tracker, JD match) -- not on landing,
# onboarding, or the choice screens, where there's nothing yet to have an
# opinion about. See sections/feedback.py for why it lives here rather
# than a sidebar.
_FEEDBACK_PAGES = {"outreach", "inbound_tracker", "inbound_jd"}
if page in _FEEDBACK_PAGES:
    st.write("")
    st.divider()
    feedback.render(page=page)