# sections/inbound_tracker.py
# Inbound = jobs you applied to through job boards. Tracker + hiring-manager
# LinkedIn message generator.

import streamlit as st
import pandas as pd
import os
import re
from datetime import date
from openai import OpenAI
from backend.profile_presets import render_profile_field
from backend.research_engine import research_company
from backend.api_keys import require_groq_key, require_tavily_key
from backend.auth import current_user_email, prompt_login
from backend import analytics, db

COLUMNS = ["Company Name", "Role", "Platform", "Date Applied", "Status", "Hiring Manager / Recruiter", "LinkedIn Message", "Notes"]

# Maps this file's DataFrame column names to Supabase's inbound_entries
# table (snake_case). See backend/db.py and outreach.py's _COLUMN_MAP for
# the same pattern.
_TABLE = "inbound_entries"
_COLUMN_MAP = {
    "Company Name": "company_name",
    "Role": "role",
    "Platform": "platform",
    "Date Applied": "date_applied",
    "Status": "status",
    "Hiring Manager / Recruiter": "hiring_manager_recruiter",
    "LinkedIn Message": "linkedin_message",
    "Notes": "notes",
}
# "Ghosted" and "In Review" dropped -- Ghosted overlapped with "No Response"
# (which matches outreach.py's wording for the same idea) and In Review
# isn't something you can actually verify from outside. Added "Followed Up"
# so the application's own progress can reflect a follow-up.
STATUS_OPTIONS = ["Applied", "Followed Up", "Interviewing", "Offer", "Rejected", "No Response"]
# Reduced to the three that actually matter as *choices* -- Naukri,
# Instahyre, Wellfound etc. all used to sit here as separate options, but
# that meant anything not on this exact list had nowhere to go. Now they
# fall under "Other Job Listing Platform", and the actual name gets typed
# into a free-text field below so it's still searchable later instead of
# every uncommon platform being lumped under a generic "Other".
PLATFORM_OPTIONS = ["LinkedIn", "Career Page", "Other Job Listing Platform"]


def load_data(user_email: str) -> pd.DataFrame:
    """Only this user's rows -- see backend/db.py."""
    return db.load_table(_TABLE, _COLUMN_MAP, user_email)


def save_data(user_email: str, df: pd.DataFrame) -> None:
    """Persists this user's rows only, leaving every other user's rows
    untouched -- see backend/db.py."""
    db.save_table(_TABLE, _COLUMN_MAP, user_email, df)


BANNED_PHRASE_PATTERNS = [
    r"align\w*\s+with",
    r"cross[\s-]functional",
    r"\bsecured?\s+alignment\b|\balignment\b",
    r"explore\s+(potential\s+)?opportunit",
    r"synerg\w*",
    r"resonat\w*",
    r"(great|good|perfect)\s+fit",
    r"hardworking\s+individual",
    r"contribute\s+to\s+(\w+'?s\s+|your\s+|their\s+|its\s+)?(continued\s+)?(growth|success|innovation)",
    # Code-level net for self-applied occupational-status labels ("I'm a
    # product management professional", "I'm an IIT Bombay lead", "I'm a
    # growth pro") -- added after this exact pattern regressed on a later
    # generation despite a prompt instruction banning it. Prompt compliance
    # is probabilistic and can't be trusted alone for a recurring failure;
    # this catches it regardless of what the model does that generation.
    r"i'?m\s+(?:a|an)\s+(?:[\w-]+\s+){0,3}(?:professional|pro|leader|lead|manager|expert|specialist|guru)\b",
    # Hedged connections -- see outreach.py for the full explanation. A
    # hedge like "could be relevant" wasn't caught by either this regex
    # or the judge, despite the prompt banning hedging in plain English.
    r"could\s+be\s+relevant",
    r"could\s+apply",
    r"similar\s+principles",
    r"may\s+resonate",
    r"might\s+be\s+relevant",
    r"i\s+think\b[^.]{0,80}\bsimilar\s+(problem|issue|challenge)\b",
    r"\bseems?\s+(like|comparable|similar|relevant)\b",
    r"similar\s+understanding",
]


def _find_banned_phrases(text: str) -> list[str]:
    lowered = text.lower()
    hits = []
    for pattern in BANNED_PHRASE_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            hits.append(match.group())
    return hits


def _generate_with_retry(client, system_prompt: str, user_prompt: str, temperature: float = 0.4):
    """
    Same simplification as outreach.py -- see there for the full
    explanation. The LLM judge is removed: it kept missing the exact
    connection-quality failures it existed to catch, while costing a full
    extra LLM call per attempt (up to 6 total per message with the old
    2-retry loop). A human reviews every draft before sending, so that's
    where nuanced judgment lives now. This does ONE cheap mechanical check
    (banned phrases/hedges) with one retry if it hits.

    Returns (output, still_flagged, reason).
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile", messages=messages, temperature=temperature,
    )
    output = response.choices[0].message.content.strip()

    found = _find_banned_phrases(output)
    if not found:
        return output, False, ""

    messages.append({"role": "assistant", "content": output})
    messages.append({
        "role": "user",
        "content": (
            f"Your draft used the exact banned filler phrase(s) {found}, which the "
            "instructions explicitly forbid. Rewrite the full message with the same "
            "content and structure, but fix this."
        ),
    })
    retry_response = client.chat.completions.create(
        model="llama-3.3-70b-versatile", messages=messages, temperature=temperature,
    )
    output = retry_response.choices[0].message.content.strip()
    found = _find_banned_phrases(output)
    return output, bool(found), (f"banned phrase(s) {found}" if found else "")


def _strip_trailing_placeholder(text: str) -> str:
    """
    Same safety net as outreach.py -- this generator was missing it entirely,
    so a stray bracket placeholder (e.g. around a detail the model wasn't
    given) had nothing catching it before it reached the user. See
    outreach.py for the full explanation.
    """
    lines = text.rstrip().split("\n")
    while lines and re.fullmatch(r"\s*\[[^\]]*\]\s*", lines[-1]):
        lines.pop()
    return "\n".join(lines).rstrip()


def render():
    user_email = current_user_email()
    if "inbound_df" not in st.session_state:
        st.session_state.inbound_df = load_data(user_email) if user_email else pd.DataFrame(columns=COLUMNS)

    st.markdown('<div class="ah-title">Tracker</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ah-page-desc">Track every job you\'ve applied to, and message '
        'the hiring manager to stand out.</div>',
        unsafe_allow_html=True,
    )

    tab_add, tab_table, tab_generate = st.tabs(["Add entry", "Tracker", "LinkedIn message generator"])

    with tab_add:
        with st.form("add_inbound_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                company_name = st.text_input("Company name")
                role = st.text_input("Role", placeholder="e.g. Associate PM")
                platform_choice = st.selectbox("Platform", PLATFORM_OPTIONS)
                # Always visible rather than conditionally rendered -- widgets
                # inside st.form don't rerun the script on interaction (only
                # on submit), so a field that only appears when platform_choice
                # == "Other..." would show up one submit too late. Simpler to
                # keep it always present with a help note on when it's used.
                platform_other = st.text_input(
                    "If \"Other\", name it",
                    placeholder="e.g. Naukri, Instahyre, Wellfound",
                    help="Only used if you picked \"Other Job Listing Platform\" "
                         "above -- the name you type here is what gets saved, "
                         "so you can search/filter by it later.",
                )
                date_applied = st.date_input("Date applied", value=date.today())
            with col2:
                status = st.selectbox("Status", STATUS_OPTIONS)
                hiring_manager = st.text_input(
                    "Hiring manager / recruiter",
                    placeholder="e.g. Priya Sharma",
                    help="Whoever you're messaging or planning to message about this application.",
                )
                linkedin_message = st.selectbox(
                    "LinkedIn message", ["Not Sent", "Sent", "Replied"],
                    help="Have you messaged the hiring manager yet?",
                )
                notes = st.text_area("Notes (optional)", height=95)

            submitted = st.form_submit_button("Add to tracker", use_container_width=True)

            if submitted:
                if not company_name:
                    st.error("Company name is required.")
                else:
                    platform = (
                        platform_other.strip()
                        if platform_choice == "Other Job Listing Platform" and platform_other.strip()
                        else platform_choice
                    )
                    new_row = pd.DataFrame([{
                        "Company Name": company_name,
                        "Role": role,
                        "Platform": platform,
                        "Date Applied": date_applied,
                        "Status": status,
                        "Hiring Manager / Recruiter": hiring_manager,
                        "LinkedIn Message": linkedin_message,
                        "Notes": notes,
                    }])
                    st.session_state.inbound_df = pd.concat(
                        [st.session_state.inbound_df, new_row], ignore_index=True
                    )
                    if user_email:
                        save_data(user_email, st.session_state.inbound_df)
                        st.success(f"Added {company_name}.")
                        st.session_state.show_add_entry_nudge_inbound = False
                    else:
                        st.success(f"Added {company_name} for this session.")
                        st.session_state.show_add_entry_nudge_inbound = True
                    analytics.log_event("funnel", "inbound_entry_added", details=f"company={company_name}")

        if st.session_state.get("show_add_entry_nudge_inbound"):
            prompt_login("keep this saved for next time", key="signin_add_entry_inbound")

    with tab_table:
        if "inbound_editor_version" not in st.session_state:
            st.session_state.inbound_editor_version = 0
        df = st.session_state.inbound_df
        if df.empty:
            st.info("No entries yet. Add your first one in 'Add entry'.")
        else:
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                status_filter = st.multiselect("Filter by status", STATUS_OPTIONS)
            with col_f2:
                platform_options_present = sorted(df["Platform"].dropna().unique().tolist())
                platform_filter = st.multiselect("Filter by platform", platform_options_present)
            with col_f3:
                search = st.text_input("Search company or role")

            filtered = df.copy()
            if status_filter:
                filtered = filtered[filtered["Status"].isin(status_filter)]
            if platform_filter:
                filtered = filtered[filtered["Platform"].isin(platform_filter)]
            if search:
                filtered = filtered[
                    filtered["Company Name"].str.contains(search, case=False, na=False)
                    | filtered["Role"].str.contains(search, case=False, na=False)
                ]

            edited_df = st.data_editor(
                filtered,
                use_container_width=True,
                num_rows="dynamic",
                column_config={
                    "Status": st.column_config.SelectboxColumn(options=STATUS_OPTIONS),
                    # Platform is intentionally left as a free-text column now
                    # (no SelectboxColumn) -- values can be a custom platform
                    # name typed in via "Other Job Listing Platform", and a
                    # SelectboxColumn would only accept values from a fixed
                    # options list, breaking display/editing for those.
                    "LinkedIn Message": st.column_config.SelectboxColumn(options=["Not Sent", "Sent", "Replied"]),
                },
                key=f"inbound_editor_{st.session_state.inbound_editor_version}",
            )

            def _rows_differ(a, b) -> bool:
                try:
                    return not a.reset_index(drop=True).equals(b.reset_index(drop=True))
                except Exception:
                    return True

            def _persist(bump_version: bool = True):
                if status_filter or search:
                    # see outreach.py for the full explanation -- df.update()
                    # can't remove rows, so a deletion made via
                    # num_rows="dynamic" while filtered/searched would
                    # silently survive a save. Reconstructing instead of
                    # patching handles edits, additions, and deletions.
                    remaining = df.drop(index=filtered.index, errors="ignore")
                    st.session_state.inbound_df = pd.concat(
                        [remaining, edited_df], ignore_index=True
                    )
                else:
                    st.session_state.inbound_df = edited_df
                if user_email:
                    save_data(user_email, st.session_state.inbound_df)
                if bump_version:
                    st.session_state.inbound_editor_version += 1

            # Auto-persist on detected change -- see outreach.py for the
            # full explanation. Without this, an unsaved delete could get
            # discarded the moment the user interacted with any widget on
            # another tab, since that triggers a full rerun that rebuilds
            # this tracker from the still-unchanged saved data.
            #
            # bump_version only fires on a row-count change (add/delete) --
            # see outreach.py for why a plain cell edit shouldn't force a
            # widget remount.
            if _rows_differ(edited_df, filtered):
                _persist(bump_version=(len(edited_df) != len(filtered)))

            col_save, col_stats = st.columns([1, 3])
            with col_save:
                if st.button("Save changes", use_container_width=True):
                    _persist()
                    if user_email:
                        st.success("Saved.")
                    else:
                        st.success("Saved for this session.")
                    st.rerun()
            if not user_email and not df.empty:
                prompt_login("keep your tracker saved across visits", key="signin_tracker_tab_inbound")
            with col_stats:
                total = len(df)
                interviewing = len(df[df["Status"] == "Interviewing"])
                offers = len(df[df["Status"] == "Offer"])
                li_sent = len(df[df["LinkedIn Message"].isin(["Sent", "Replied"])])
                st.caption(
                    f"{total} total - {interviewing} interviewing - {offers} offers - "
                    f"{li_sent} hiring managers messaged"
                )

    with tab_generate:
        st.caption(
            "Use this right after applying. Pick the company from your tracker (or type "
            "one), optionally research it, then paste the JD and the hiring manager's name "
            "to get a short, specific LinkedIn message."
        )
        # Moved out of st.form -- the company picker and research button
        # both need to programmatically fill other fields on the same run,
        # which st.form can't do (only reruns on submit).
        company_key = "inbound_gen_company"
        context_key = "inbound_gen_context"
        if company_key not in st.session_state:
            st.session_state[company_key] = ""
        if context_key not in st.session_state:
            st.session_state[context_key] = ""

        known_companies = (
            sorted(st.session_state.inbound_df["Company Name"].dropna().unique().tolist())
            if not st.session_state.inbound_df.empty else []
        )
        picker_options = ["Type manually"] + known_companies
        picked_company = st.selectbox("Select company", picker_options, key="inbound_company_picker")
        last_picked_key = "inbound_company_last_picked"
        hm_key = "inbound_gen_hiring_manager"
        role_picker_key = "inbound_role_picker"
        last_picked_role_key = "inbound_role_last_picked"
        if hm_key not in st.session_state:
            st.session_state[hm_key] = ""
        if picked_company != "Type manually" and st.session_state.get(last_picked_key) != picked_company:
            st.session_state[company_key] = picked_company
            st.session_state[last_picked_key] = picked_company
            # See outreach.py for the full explanation -- switching
            # companies without clearing the old research/context/message
            # lets stale data from the previous company leak into the new
            # one's generation.
            st.session_state[context_key] = ""
            st.session_state.pop("inbound_research_sources", None)
            st.session_state.pop("last_inbound_message", None)
            st.session_state.pop(last_picked_role_key, None)
            st.session_state[hm_key] = ""

        # If this company has more than one tracker row (e.g. applied to two
        # different roles there), the hiring manager can genuinely differ
        # between them -- so a role picker disambiguates instead of just
        # grabbing whichever row happens to be first. Only shown when it's
        # actually ambiguous; a single-row company skips straight to
        # auto-filling from that one row.
        if picked_company != "Type manually":
            matches = st.session_state.inbound_df[
                st.session_state.inbound_df["Company Name"] == picked_company
            ]
            if len(matches) > 1:
                role_options = matches["Role"].fillna("(no role listed)").tolist()
                picked_role = st.selectbox(
                    f"Which role at {picked_company}?", role_options, key=role_picker_key
                )
                if st.session_state.get(last_picked_role_key) != picked_role:
                    st.session_state[last_picked_role_key] = picked_role
                    row = matches[matches["Role"].fillna("(no role listed)") == picked_role].iloc[0]
                    hm_val = row.get("Hiring Manager / Recruiter", "")
                    st.session_state[hm_key] = "" if pd.isna(hm_val) else str(hm_val).strip()
            elif len(matches) == 1 and st.session_state.get(last_picked_role_key) is None:
                st.session_state[last_picked_role_key] = "__single__"
                hm_val = matches.iloc[0].get("Hiring Manager / Recruiter", "")
                st.session_state[hm_key] = "" if pd.isna(hm_val) else str(hm_val).strip()

        gen_company = st.text_input("Company name", key=company_key)

        if st.button("🔎 Research this company", disabled=not gen_company.strip()):
            if not require_tavily_key():
                st.stop()
            with st.spinner(f"Researching {gen_company}..."):
                try:
                    result = research_company(gen_company)
                    if result["found"]:
                        combined = " ".join(filter(None, [result["overview"], result["recent_news"]]))
                        st.session_state[context_key] = combined
                        st.session_state["inbound_research_sources"] = result["sources"]
                        st.success("Filled in below — review and edit before generating.")
                        analytics.log_event("funnel", "inbound_research_run", details=f"company={gen_company}")
                    else:
                        st.warning("Couldn't find much on this company. That's fine — the JD is the main input here.")
                except ValueError as e:
                    st.error(str(e))
                    analytics.log_error("inbound_research", str(e))
        st.caption(
            "Don't have a Tavily key? Skip this — the job description is the "
            "main source for this message anyway."
        )

        company_context = st.text_area(
            "Company context (optional — what they do / recent news)",
            placeholder="e.g. Raised a Series B last month, building AI tools for creative teams.",
            key=context_key,
        )
        if st.session_state.get("inbound_research_sources"):
            with st.expander("Sources used for research"):
                for s in st.session_state["inbound_research_sources"]:
                    st.caption(f"[{s['title']}]({s['url']})" if s["title"] else s["url"])
                st.caption(
                    "AI-generated summary — worth a skim before you send, in case "
                    "anything's out of date or slightly off."
                )

        your_profile = render_profile_field(
            key_prefix="inbound",
            placeholder="e.g. Final-year student pivoting to PM, applied because of the 0-to-1 focus.",
        )

        hiring_manager_name = st.text_input(
            "Hiring manager's name",
            key=hm_key,
            placeholder="e.g. Priya Sharma",
            help="Auto-filled from the tracker if this company/role has a hiring manager on file. "
            "Edit or clear as needed.",
        )
        job_description = st.text_area(
            "Paste the job description", height=180,
            placeholder="Paste the full job description you applied to.",
        )
        generate_clicked = st.button("Generate LinkedIn message", use_container_width=True)

        if generate_clicked:
            if not gen_company or not hiring_manager_name or not job_description:
                st.error("Company name, hiring manager name, and job description are all required.")
            elif not require_groq_key():
                st.stop()
            else:
                with st.spinner("Drafting your message..."):
                    try:
                        client = OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1")
                        system_prompt = (
                            "Write a short LinkedIn message to a hiring manager, sent right after applying "
                            "to their job posting, in the exact style, tone, and length as the example below "
                            "-- not more formal, not longer. Match it. No subject line. Hard limit: under 300 "
                            "characters, no exceptions.\n\n"
                            "EXAMPLE OF THE STYLE AND LENGTH TO MATCH (this one is an outreach DM, not an "
                            "inbound one, but the voice and compression level are exactly what you should "
                            "match):\n"
                            "---\n"
                            "Hi Ritesh, just sent you a mail but wanted to reach out here too. IIT Bombay "
                            "grad (2026) trying to break into product. Spent the last year doing actual PM "
                            "work at a D2C startup and running ops for 15k students at IITB. Curious if "
                            "there's any room for a PM at Innov8. Would love a quick chat if you're open to "
                            "it.\n"
                            "---\n\n"
                            "What that example does, that yours should too:\n"
                            "- Greeting with the hiring manager's first name, casual ('Hi <name>,').\n"
                            "- Never describe yourself using ANY occupational-status word or phrase (a noun or "
                            "adjective that labels what kind of professional you are -- 'leader', 'lead', "
                            "'professional', 'pro', 'manager', 'expert', 'specialist', 'guru', or any other "
                            "synonym in that same category, in any form: alone, paired, prefixed, or "
                            "shortened/informal), UNLESS that exact word appears in the profile below. This is "
                            "a category ban, not a specific word list -- if you're tempted to reach for any "
                            "word that answers 'what kind of professional am I', don't use it. Describe the "
                            "person by what they DID instead.\n"
                            "- Early in the message (right after the greeting), states plainly that you've "
                            "just applied for this exact role -- this message is sent AFTER the application, "
                            "not instead of it, so it must acknowledge that (e.g. 'just applied for the <role> "
                            "role and wanted to reach out directly' or 'saw the <role> posting and just "
                            "submitted my application'). Keep it brief -- this is not the main point of the "
                            "message.\n"
                            "- The profile below is a dense, multi-fact source document, not a script to "
                            "recite. Pick the ONE fact most relevant to this JD/company and reframe it in "
                            "plain spoken language (not resume phrasing) -- do not string together multiple "
                            "profile facts with 'and'/'also' just because they're all true and specific.\n"
                            "- One specific candidate-to-JD connection, stated as an observation grounded in "
                            "something real from the job description -- not a generic shared label ('AI', "
                            "'execution', 'cross-functional') and not bare admiration ('I'm excited by...') "
                            "without saying why in concrete terms. Exactly one connection -- don't chain a "
                            "second one in with 'as'/'and'/'while'. If the JD or company context mentions "
                            "several distinct facts, pick ONLY ONE to build the connection around -- don't "
                            "reference a second company/JD fact anywhere else, even in passing.\n"
                            "- State the connection as a direct fact, never as a belief or guess -- no 'I "
                            "think X is similar', 'this seems comparable', or similar hedging.\n"
                            "- A soft, open-ended close if space allows ('would love a quick chat if you're "
                            "open to it') -- never a direct ask for the job, an interview, or a referral, and "
                            "never restates a skill in that closing line.\n"
                            "- Count the characters yourself before finishing -- shorter than 300 is fine, "
                            "over 300 is not.\n"
                            "- Before finalizing, run the connection through this check: would it still work, "
                            "almost unchanged, for a different company in the same broad category (e.g. any "
                            "other food-delivery company, any other fintech)? If yes, it's too generic -- find "
                            "a sharper angle from the profile/JD, or state the connection in plain honest "
                            "terms instead of forcing a hollow specific-sounding link.\n\n"
                            "Do not invent facts about the company or role beyond what's given below."
                        )
                        user_prompt = f"""
Company: {gen_company}
Company context (optional, may be empty): {company_context or "Not provided"}
Hiring Manager: {hiring_manager_name}
Job Description: {job_description}
My profile: {your_profile or "Not provided -- write a generic but still specific-to-the-JD message."}

Write the LinkedIn message now. Address the hiring manager by first name only. Prefer
referencing something specific from the job description over the company context, unless
the company context adds something the JD doesn't already say.
"""
                        output, still_flagged, flag_reason = _generate_with_retry(
                            client, system_prompt, user_prompt
                        )
                        if still_flagged:
                            st.warning(
                                "Heads up: this draft still had a flagged phrase after a "
                                f"retry -- {flag_reason}. Give the connection a read before "
                                "sending."
                            )

                        # Separate length check -- the 300-char instruction in
                        # the prompt is a soft target the model can drift
                        # past, so verify it here and ask for a trim if over,
                        # same pattern as outreach.py.
                        if len(output.strip()) > 300:
                            trim_messages = [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                                {"role": "assistant", "content": output},
                                {"role": "user", "content": (
                                    f"That message is {len(output.strip())} characters, over the 300-character "
                                    "limit. Rewrite it shorter, comfortably under 300 characters, while keeping "
                                    "the greeting, self-introduction, and the one connection -- cut words, not "
                                    "required elements."
                                )},
                            ]
                            trim_response = client.chat.completions.create(
                                model="llama-3.3-70b-versatile", messages=trim_messages, temperature=0.4,
                            )
                            output = trim_response.choices[0].message.content.strip()

                            # The trim call is a second, unchecked rewrite of the
                            # same text for the same reason (fewer characters) --
                            # it can reintroduce a banned filler phrase even when
                            # the pre-trim draft passed clean (e.g. squeezing a
                            # specific connection down into "aligns with" to save
                            # room). This shipped unchecked before; re-check here,
                            # same as the equivalent step in outreach.py.
                            trim_found = _find_banned_phrases(output)
                            if trim_found:
                                still_flagged = True
                                flag_reason = (
                                    f"{flag_reason}; also, the length-trim step introduced "
                                    f"banned phrase(s) {trim_found}" if flag_reason
                                    else f"the length-trim step introduced banned phrase(s) {trim_found}"
                                )
                                st.warning(
                                    "Heads up: the length-trim step introduced a flagged "
                                    f"phrase -- {trim_found}. Review it by hand before sending."
                                )

                        st.session_state.last_inbound_message = _strip_trailing_placeholder(output)
                        analytics.log_event("funnel", "inbound_message_generated", details=f"company={gen_company}")
                    except Exception as e:
                        st.error(f"Message generation failed: {e}")
                        analytics.log_error("inbound_message_generation", str(e))

        if st.session_state.get("last_inbound_message"):
            st.markdown("---")
            st.markdown("**LinkedIn message**")
            st.text_area(
                "Editable message", value=st.session_state.last_inbound_message,
                height=150, key="inbound_message_edit_box",
            )
            char_count = len(st.session_state.last_inbound_message)
            st.caption(f"{char_count} characters (LinkedIn's connection note limit is around 300)")
            st.caption("Personalise further before sending. This is a starting draft.")
            st.caption("⚠️ This draft is AI-generated and not perfect -- please review it carefully before sending.")