# sections/onboarding.py
# Shown once between "Get started" and the Outreach/Inbound choice screen.
# Exists because "apping" is IITB-specific slang, and even for people who
# know the word, the actual strategy behind outreach vs. inbound isn't
# obvious. This teaches the strategy, not just the vocabulary, since the
# strategy is where the app's tools (tracker, JD Match, research) plug in.
#
# Built as a step wizard, not one long scroll, so each idea gets room to
# land. Reuses the multi-step-screen pattern already established by
# app.py's page state machine, just scoped to a local "onboarding_step"
# counter instead of a page name.

import streamlit as st
from style import get_theme
from backend import analytics

TOTAL_STEPS = 5


def _progress_dots(current: int):
    t = get_theme()
    dots = "".join(
        f'<span style="display:inline-block;width:7px;height:7px;border-radius:50%;'
        f'margin:0 4px;background:{t["accent"] if i == current else t["hairline_strong"]};"></span>'
        for i in range(TOTAL_STEPS)
    )
    st.markdown(f'<div style="text-align:center;margin-bottom:1.75rem;">{dots}</div>', unsafe_allow_html=True)


def _detail(short: str, more: str):
    """Renders inside an st.expander: a short line always visible, plus a
    'Read more' toggle for the granular how-to underneath. Streamlit doesn't
    support nesting one st.expander inside another, so this uses a plain
    HTML <details>/<summary> instead -- same expand/collapse behavior,
    just markup rather than a second Streamlit widget."""
    t = get_theme()
    st.markdown(
        f'<div style="color:{t["ink"]};font-size:0.95rem;line-height:1.6;">{short}</div>'
        f'<details style="margin-top:0.6rem;">'
        f'<summary style="cursor:pointer;color:{t["accent"]};font-size:0.85rem;'
        f'font-weight:600;">Read more</summary>'
        f'<div style="margin-top:0.6rem;color:{t["muted"]};font-size:0.9rem;'
        f'line-height:1.65;">{more}</div>'
        f'</details>',
        unsafe_allow_html=True,
    )


def _nav(step: int, go_fn, on_choice_target: str = "choice"):
    """Back / Skip / Next row: back pinned left, skip centered, next/let's-go
    pinned right, all sized to match the small back_nav/theme_toggle pill
    buttons in the header rather than the big uppercase CTA style .stButton
    gets by default (see style.py's .st-key-onb_*_wrap rules). Back is
    hidden on step 0 since the page-level header's back link already
    returns to landing there. Uses go_fn (the same page-transition function
    app.py's other screens use) for anything that leaves onboarding
    entirely, so page transitions stay consistent app-wide; the step
    counter is local state that go_fn doesn't need to know about.

    Container keys are step-independent ("onb_back_wrap" etc.) since only
    one step's nav row renders per script run, but the *button* keys still
    carry the step number, which Streamlit requires for uniqueness across
    reruns where the same widget position is reused with new state."""
    col_back, col_skip, col_next = st.columns([1, 1, 1])
    with col_back:
        with st.container(key="onb_back_wrap"):
            if step > 0:
                if st.button("← Back", key=f"onb_back_{step}"):
                    st.session_state.onboarding_step = step - 1
                    st.rerun()
    with col_skip:
        with st.container(key="onb_skip_wrap"):
            if step < TOTAL_STEPS - 1:
                if st.button("Skip intro", key=f"onb_skip_{step}"):
                    analytics.log_event("funnel", "onboarding_skipped", details=f"step={step}")
                    go_fn(on_choice_target)
    with col_next:
        with st.container(key="onb_next_wrap"):
            label = "Let's go →" if step == TOTAL_STEPS - 1 else "Next →"
            if st.button(label, key=f"onb_next_{step}"):
                if step == TOTAL_STEPS - 1:
                    analytics.log_event("funnel", "onboarding_completed")
                    go_fn(on_choice_target)
                else:
                    st.session_state.onboarding_step = step + 1
                    st.rerun()


def _step_0():
    st.markdown(
        '<div class="ah-narrow" style="margin-top:2vh;">'
        '<div class="ah-eyebrow">Before you start</div>'
        '<div class="ah-title-mid">Apping is IITB slang for applying to jobs '
        'outside campus placement.</div>'
        '<div class="ah-body">If your resume isn\'t landing anywhere, it\'s usually '
        'not a skills problem, it\'s a visibility one. Most companies run every '
        'resume through an ATS before a person even looks at it, and your "match" '
        'score changes with every JD. A strong generic resume can lose to a '
        'weaker one that\'s tailored properly. That\'s what JD Match, later in '
        'this app, fixes for you.</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def _step_1():
    st.markdown(
        '<div class="ah-narrow" style="margin-top:2vh;">'
        '<div class="ah-title-mid">Every job you land comes through one of two doors.</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    col_pad_l, col1, col2, col_pad_r = st.columns([0.6, 1, 1, 0.6])
    with col1:
        st.markdown(
            '<div class="ah-card" style="pointer-events:auto;">'
            '<div class="ah-card-title">Outreach</div>'
            '<div class="ah-card-sub">You reach out first, cold. To companies, '
            'recruiters, or people already working there, before there\'s even a '
            'posting.</div></div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            '<div class="ah-card" style="pointer-events:auto;">'
            '<div class="ah-card-title">Inbound</div>'
            '<div class="ah-card-sub">You apply to something that\'s already '
            'posted, a job board or a careers page, and then try to get an actual '
            'person to see it.</div></div>',
            unsafe_allow_html=True,
        )


def _step_2():
    st.markdown(
        '<div class="ah-narrow" style="margin-top:2vh;">'
        '<div class="ah-title-mid">Not every company is worth the same approach.</div>'
        '<div class="ah-body-muted">Startups and big companies need different playbooks.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.expander("1. Build your target list"):
        _detail(
            "Pick 2-3 industries, then aim for 15-25 companies, enough shots "
            "without losing the ability to personalize each one.",
            "For startups: use Tracxn or Crunchbase, filter by industry and "
            "funding stage (Seed/Series A), sort by most recent raise. On the "
            "YC directory, filter by batch (recent ones) and industry tag. "
            "For big companies: track specific divisions, not the whole "
            "company. Read their latest earnings call transcript (search "
            "\"[Company] Q[X] earnings call transcript\", or check their "
            "Investor Relations page) for lines like \"doubling down on [X]\", "
            "that's a hiring signal. Also check the company's LinkedIn page "
            "→ Insights tab (needs Premium) for headcount growth by department."
        )
    with st.expander("2. Find the right person"):
        _detail(
            "At a startup, it barely matters who you pick, a founder or a "
            "recruiter replies about the same. At a big company, be specific.",
            "Company name alone won't get you there. Go to the company's "
            "LinkedIn page → \"People\" tab → filter using the search box "
            "inside it (try \"Recruiter\", \"Manager\", or a team name). For "
            "more precision, use LinkedIn's main search bar with quotes and "
            "AND, e.g. \"Director\" AND \"Cloud Security\" AND \"AWS\". At a "
            "big company, aim for Senior Manager or Director on the exact "
            "team, a VP or higher usually won't read a cold message. Also "
            "worth finding that team's internal recruiter separately from "
            "the hiring manager."
        )
    with st.expander("3. Get their contact info"):
        _detail(
            "LinkedIn first, always. For email, a few free tools will guess "
            "it for you.",
            "Hunter, Apollo, or RocketReach. On Hunter, you give it the "
            "company's domain (like company.com), not a name, it returns the "
            "email pattern it's found (e.g. first.last@company.com) and "
            "sometimes specific people. Apollo works more like a people "
            "search, look up the person by name and company directly. Always "
            "verify before sending, a bounce can hurt your ability to reach "
            "that domain again. One thing specific to big companies: skip "
            "attachments and heavy formatting, their spam filters are "
            "aggressive and can quarantine anything that looks too polished."
        )
    with st.expander("4. Ask for a referral, properly"):
        _detail(
            "An alum, an old colleague, a mutual connection, this is the "
            "warmest version of a cold ask.",
            "LinkedIn's alumni search tool is built exactly for this, filter "
            "by employer, function, location. At a big company, a referral "
            "is often your real goal, not a guaranteed interview, so ask "
            "directly for that instead of pitching yourself for the role "
            "outright."
        )


def _step_3():
    st.markdown(
        '<div class="ah-narrow" style="margin-top:2vh;">'
        '<div class="ah-title-mid">The job\'s already posted.</div>'
        '<div class="ah-body-muted">Applying isn\'t the same as being seen.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.expander("1. Get past the ATS first"):
        _detail(
            "Since matching depends on the specific job, tailor your resume "
            "each time instead of sending the same one everywhere.",
            "Tailoring doesn't mean you have to make new resumes every time. "
            "Reorder and reword your bullets so the keywords match the JD's "
            "language, e.g. if the JD says \"cross-functional stakeholder "
            "management\" and your resume says \"worked with multiple "
            "teams\", change the wording to match. This is literally what "
            "JD Match does: it scores your resume against a real JD and "
            "tells you what's missing before you apply."
        )
    with st.expander("2. Actually get seen"):
        _detail(
            "Applying alone rarely works. Find the person behind the "
            "posting and send a short message referencing your application.",
            "Job boards and a company's own careers page are both fair "
            "game, a lot of roles get posted there before they ever show up "
            "on LinkedIn or Wellfound. Wellfound specifically is good for "
            "finding open startup roles. Once you've applied, do the "
            "outreach steps from the last page: find the recruiter or "
            "hiring manager for that role on LinkedIn and send a short note "
            "mentioning you applied."
        )
    with st.expander("3. If no recruiter is listed"):
        _detail(
            "Search the company's LinkedIn page filtered by recruiting or "
            "talent titles.",
            "Use the \"People\" tab and search \"Recruiter\" or \"Talent\" "
            "inside it, or search directly: \"[Company] recruiter\" "
            "\"[team or role]\" in Google or LinkedIn. Worst case, ask "
            "anyone at the company who the right person is."
        )
    with st.expander("4. Referrals still help, even here"):
        _detail(
            "A referral can push an already-applied resume in front of a "
            "person faster than sitting in the ATS queue.",
            "Worth doing after you've applied too, not just before. Same "
            "alumni search approach as outreach: filter by employer, "
            "function, location."
        )


def _step_4():
    st.markdown(
        '<div class="ah-narrow" style="margin-top:2vh;">'
        '<div class="ah-eyebrow">You\'re set</div>'
        '<div class="ah-title-mid">The hard part was never writing the message.</div>'
        '<div class="ah-body">It\'s doing this every week without losing track '
        'of who you messaged, who replied, and who you still owe a follow up. '
        'That\'s what the tracker, JD Match, and message generator here are '
        'actually for.</div>'
        '</div>',
        unsafe_allow_html=True,
    )


_STEPS = [_step_0, _step_1, _step_2, _step_3, _step_4]


def render(go_fn):
    if "onboarding_step" not in st.session_state:
        st.session_state.onboarding_step = 0

    step = st.session_state.onboarding_step
    step = max(0, min(step, TOTAL_STEPS - 1))

    _progress_dots(step)
    _STEPS[step]()
    st.write("")
    st.write("")
    _nav(step, go_fn)