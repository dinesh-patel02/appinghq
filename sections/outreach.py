# sections/outreach.py
# Outreach = cold outreach you start yourself. Tracker + message generator.

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

COLUMNS = [
    "Company Name", "POC Name", "POC Designation", "Date Contacted",
    "Followed Up", "Status", "LinkedIn Status", "Notes",
]
STATUS_OPTIONS = ["Sent", "Replied", "Interviewing", "Rejected", "No Response"]

# Maps this file's DataFrame column names (spaced, human-readable) to the
# Postgres columns in Supabase's outreach_entries table (snake_case). See
# backend/db.py -- storage moved off local CSV since free hosting tiers
# (Streamlit Community Cloud, Hugging Face Spaces) don't guarantee the
# local filesystem survives a restart/redeploy.
_TABLE = "outreach_entries"
_COLUMN_MAP = {
    "Company Name": "company_name",
    "POC Name": "poc_name",
    "POC Designation": "poc_designation",
    "Date Contacted": "date_contacted",
    "Followed Up": "followed_up",
    "Status": "status",
    "LinkedIn Status": "linkedin_status",
    "Notes": "notes",
}


def load_data(user_email: str) -> pd.DataFrame:
    """Only this user's rows -- see backend/db.py."""
    return db.load_table(_TABLE, _COLUMN_MAP, user_email)


def save_data(user_email: str, df: pd.DataFrame) -> None:
    """Persists this user's rows only, leaving every other user's rows
    untouched -- see backend/db.py."""
    db.save_table(_TABLE, _COLUMN_MAP, user_email, df)


# Literal, mechanical tone-filler phrases and hedges -- things a random
# candidate could say about any company, or ways of softening a connection
# into a guess instead of a fact. Deliberately NOT trying to catch "is this
# connection specific enough" here -- that's a judgment call that used to
# be handled by a separate LLM judge, which was removed (see
# _generate_with_retry) because it kept missing the exact failures it
# existed to catch while costing extra LLM calls on every message. A human
# reviews every draft before sending; that's where connection-quality
# judgment lives now. Keep this list to true mechanical phrases/hedges
# only -- don't turn it back into a chase of every specific bad connection.
BANNED_PHRASE_PATTERNS = [
    r"align\w*\s+with",                    # align/aligns/aligning/alignment with
    r"cross[\s-]functional",               # standalone, not just "align with" -- catches
                                            # noun-phrase forms like "cross-functional alignment"
    r"\bsecured?\s+alignment\b|\balignment\b",  # bare "alignment" too -- same filler word
                                            # kept slipping through when "with"/"cross-functional"
                                            # wasn't adjacent (e.g. "secured alignment")
    r"explore\s+(potential\s+)?opportunit",  # explore opportunities / potential opportunities
    r"synerg\w*",                          # synergy/synergies/synergistic
    r"resonat\w*",                         # resonate/resonates/resonated -- same soft-connector
                                            # tic as "aligns with"/"synergy"; recurred across
                                            # multiple drafts as the exact word signaling a vague
                                            # connection instead of a stated fact
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
    # Hedged connections -- the prompt explicitly bans stating the
    # connection as anything less than one plain fact ("never hedged"),
    # but that instruction wasn't backed by a code-level check, so hedges
    # like "could be relevant" or "similar principles could apply" kept
    # slipping through both this regex pass and the judge (the judge only
    # checks specificity, not confidence of phrasing). A hedge is a
    # reliable literal-text signal the same way a filler phrase is --
    # worth catching mechanically rather than leaving to the judge.
    r"could\s+be\s+relevant",
    r"could\s+apply",
    r"similar\s+principles",
    r"may\s+resonate",
    r"might\s+be\s+relevant",
    # Broader hedge catch -- "I think X is a similar problem/issue/challenge"
    # slipped through last round because it doesn't contain any of the
    # narrower phrases above. "I think" framing a comparison as a personal
    # guess, rather than stating it as fact, is the actual pattern to catch.
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
    Runs the generation call and does ONE cheap mechanical check: banned
    tone-filler phrases and hedges (BANNED_PHRASE_PATTERNS above). If any
    hit, one retry with the flagged phrase(s) named explicitly; otherwise
    ships as-is.

    There USED to be a second LLM call here -- a judge that checked
    connection quality/specificity (generic category matches, chained
    connections, company-only observations) -- with up to 2 retries on
    top, so up to 6 total LLM calls per message. Removed deliberately: across
    this whole debugging history, the judge kept missing exactly the
    failures it existed to catch (e.g. "friction points" <-> "understanding
    member needs" generic process-language matching slipped straight
    through it), while every retry it triggered cost a full extra
    generation + judge call. That's not a check earning its token cost --
    every draft gets reviewed and edited by a human before sending anyway,
    so nuanced connection-quality judgment now lives there instead. This
    function only auto-corrects the mechanical, literal-text problems a
    regex can reliably and cheaply catch.

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
            "instructions explicitly forbid. Rewrite the full email with the same "
            "content and structure, but fix this."
        ),
    })
    retry_response = client.chat.completions.create(
        model="llama-3.3-70b-versatile", messages=messages, temperature=temperature,
    )
    output = retry_response.choices[0].message.content.strip()
    found = _find_banned_phrases(output)
    return output, bool(found), (f"banned phrase(s) {found}" if found else "")


def _compress_to_linkedin(client, email_text: str, poc_first_name: str) -> tuple[str, bool, str]:
    """
    Turns an already-approved email into a LinkedIn DM by compressing it,
    rather than generating the LinkedIn version from scratch in parallel.

    Why: generating LinkedIn independently meant it was a second, separate
    roll of the dice -- its own connection could fail the judge even when
    the email's didn't, and it had its own recurring bugs (character
    limit, CTA-smuggling). Deriving it from the email that already passed
    review means it inherits a connection that's already been checked,
    instead of risking a fresh one. This call is deliberately simple --
    "shrink this, don't add anything" -- rather than another rule-heavy
    prompt, per the decision to lean on review/warnings over stacking more
    instructions.

    IMPORTANT: compression can still reintroduce a banned filler phrase even
    when the source email didn't have one -- e.g. squeezing "resonated with
    my work on X" down to "aligns with X" to save characters. That was
    shipping unchecked. This now runs the same banned-phrase check as the
    email (one retry, not the full judge -- the connection itself was
    already judged on the email; this only re-checks for filler the
    compression step itself might introduce).

    Returns (text, still_flagged, reason).
    """
    system_prompt = (
        "You compress an already-written cold outreach email into a short LinkedIn DM. "
        "This is a compression task, not a rewriting task: do not add any new facts, "
        "connections, claims, or reasoning that isn't already in the email. Do not "
        "soften or rephrase the connection into something different -- keep the exact "
        "same one already stated in the email, just shorter. In particular, do not "
        "compress toward generic filler words (e.g. 'aligns with', 'cross-functional', "
        "'synergy') even if they'd save characters -- keep the specific wording, just "
        "shorter.\n\n"
        "Keep, in this order: (1) a greeting -- 'Hi <name>,' if a first name is given "
        "below, otherwise 'Hi,'; (2) a short mention that you already sent them an "
        "email (this DM is sent AFTER the email, not instead of it -- e.g. 'just sent "
        "you a mail, wanted to reach out here too' or 'sent you a mail a moment ago, "
        "following up here as well' -- keep it brief, this is not the main point of "
        "the message); (3) a one-line self-introduction; (4) the same "
        "candidate-to-company connection from the email, compressed to one clause. If "
        "space allows after those, a brief low-pressure call to action (e.g. "
        "'happy to share more' or 'would love to connect') -- never a direct ask for a "
        "job, interview, or referral, and never one that reintroduces any candidate "
        "skill or detail. No sign-off, no subject line -- this is a DM, not an email.\n\n"
        "Hard limit: under 300 characters total, including the greeting. Shorter than "
        "the ceiling is fine as long as the three required elements are present.\n\n"
        "Respond with ONLY the LinkedIn DM text -- no preamble, no labels."
    )
    user_prompt = f"""EMAIL TO COMPRESS:
{email_text}

Point of contact's first name (use in greeting if present): {poc_first_name or "Not given"}

This LinkedIn DM will be sent AFTER the email above has already gone out, so it must
briefly acknowledge that (see the system instructions). Write the LinkedIn DM now."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile", messages=messages, temperature=0.3,
    )
    output = response.choices[0].message.content.strip()

    found = _find_banned_phrases(output)
    if not found:
        return output, False, ""

    messages.append({"role": "assistant", "content": output})
    messages.append({
        "role": "user",
        "content": (
            f"Your compressed version used the banned filler phrase(s) {found}, which "
            "the instructions explicitly forbid. Rewrite it, same length and structure, "
            "keeping the same specific wording from the email instead of compressing "
            "into that filler phrase."
        ),
    })
    retry_response = client.chat.completions.create(
        model="llama-3.3-70b-versatile", messages=messages, temperature=0.3,
    )
    output = retry_response.choices[0].message.content.strip()
    found = _find_banned_phrases(output)
    return output, bool(found), (f"banned phrase(s) {found}" if found else "")


def _strip_trailing_placeholder(text: str) -> str:
    """
    Safety net for when the model ignores the "never emit a name
    placeholder" prompt instruction -- which happens intermittently at
    temperature 0.4 (seen emitting both invented names like '[Your Name]'
    and meta-commentary like '[No name provided, so none will be
    included]'). Prompt wording alone isn't reliable enough here, so this
    strips any trailing line that's ENTIRELY wrapped in brackets,
    regardless of what it says inside them -- catches both failure modes
    without needing to enumerate every phrasing the model might use.
    """
    lines = text.rstrip().split("\n")
    while lines and re.fullmatch(r"\s*\[[^\]]*\]\s*", lines[-1]):
        lines.pop()
    return "\n".join(lines).rstrip()


def render():
    user_email = current_user_email()
    if "outreach_df" not in st.session_state:
        st.session_state.outreach_df = load_data(user_email) if user_email else pd.DataFrame(columns=COLUMNS)

    st.markdown('<div class="ah-title">Outreach</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ah-page-desc">Cold outreach you start yourself. Track the companies '
        'you\'re reaching out to directly, and generate personalised emails and LinkedIn messages.</div>',
        unsafe_allow_html=True,
    )

    tab_add, tab_table, tab_generate = st.tabs(["Add entry", "Tracker", "Message generator"])

    with tab_add:
        with st.form("add_outreach_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                company_name = st.text_input("Company name")
                poc_name = st.text_input("Point of contact")
                poc_designation = st.text_input("Designation", placeholder="e.g. Head of Product")
                date_contacted = st.date_input("Date contacted", value=date.today())
            with col2:
                follow_up = st.selectbox("Followed up?", ["Yes", "No"])
                status = st.selectbox("Status", STATUS_OPTIONS)
                linkedin_status = st.selectbox("Messaged on LinkedIn?", ["Yes", "No"])
                notes = st.text_area("Notes (optional)", height=95)

            submitted = st.form_submit_button("Add to tracker", use_container_width=True)

            if submitted:
                if not company_name:
                    st.error("Company name is required.")
                else:
                    new_row = pd.DataFrame([{
                        "Company Name": company_name,
                        "POC Name": poc_name,
                        "POC Designation": poc_designation,
                        "Date Contacted": date_contacted,
                        "Followed Up": follow_up,
                        "Status": status,
                        "LinkedIn Status": linkedin_status,
                        "Notes": notes,
                    }])
                    st.session_state.outreach_df = pd.concat(
                        [st.session_state.outreach_df, new_row], ignore_index=True
                    )
                    if user_email:
                        save_data(user_email, st.session_state.outreach_df)
                        st.success(f"Added {company_name}.")
                        st.session_state.show_add_entry_nudge = False
                    else:
                        st.success(f"Added {company_name} for this session.")
                        st.session_state.show_add_entry_nudge = True
                    analytics.log_event("funnel", "outreach_entry_added", details=f"company={company_name}")

        if st.session_state.get("show_add_entry_nudge"):
            prompt_login("keep this saved for next time", key="signin_add_entry")

    with tab_table:
        if "outreach_editor_version" not in st.session_state:
            st.session_state.outreach_editor_version = 0
        df = st.session_state.outreach_df
        if df.empty:
            st.info("No entries yet. Add your first one in 'Add entry'.")
        else:
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                status_filter = st.multiselect("Filter by status", STATUS_OPTIONS)
            with col_f2:
                search = st.text_input("Search company name")

            filtered = df.copy()
            if status_filter:
                filtered = filtered[filtered["Status"].isin(status_filter)]
            if search:
                filtered = filtered[filtered["Company Name"].str.contains(search, case=False, na=False)]

            edited_df = st.data_editor(
                filtered,
                use_container_width=True,
                num_rows="dynamic",
                column_config={
                    "Status": st.column_config.SelectboxColumn(options=STATUS_OPTIONS),
                    "Followed Up": st.column_config.SelectboxColumn(options=["Yes", "No"]),
                    "LinkedIn Status": st.column_config.SelectboxColumn(options=["Yes", "No"]),
                },
                key=f"outreach_editor_{st.session_state.outreach_editor_version}",
            )

            def _rows_differ(a, b) -> bool:
                try:
                    return not a.reset_index(drop=True).equals(b.reset_index(drop=True))
                except Exception:
                    # any comparison hiccup (dtype mismatch etc.) errs toward
                    # "treat as changed" rather than silently skipping a save
                    return True

            def _persist(bump_version: bool = True):
                if status_filter or search:
                    # df.update() only overwrites rows at matching indices --
                    # it can't remove anything, so deleting a row via
                    # num_rows="dynamic" while a filter/search was active
                    # would silently survive a save. Fix: drop the ORIGINAL
                    # filtered rows (by their index in the full df) and
                    # re-append whatever edited_df ended up with. edited_df
                    # already correctly reflects any edits, additions, AND
                    # deletions made in the filtered view, so reconstructing
                    # the full df this way (rather than patching it) handles
                    # all three cases instead of just edits.
                    remaining = df.drop(index=filtered.index, errors="ignore")
                    st.session_state.outreach_df = pd.concat(
                        [remaining, edited_df], ignore_index=True
                    )
                else:
                    st.session_state.outreach_df = edited_df
                if user_email:
                    save_data(user_email, st.session_state.outreach_df)
                if bump_version:
                    # Bump the editor's key so the NEXT render creates a
                    # brand-new data_editor widget instead of reusing this
                    # one. Streamlit stores each edit (add/edit/delete) made
                    # in a data_editor under its key, and replays that diff
                    # BY ROW POSITION against whatever data gets passed in on
                    # the following rerun -- without this, the editor would
                    # try to replay a stale "delete row at position N"
                    # against data where position N means something else
                    # (or no longer exists).
                    st.session_state.outreach_editor_version += 1

            # Auto-persist the moment a change is detected, rather than only
            # on a manual "Save changes" click. The editor's edits (an
            # add/edit/delete) only live in this widget's own return value
            # until something writes them into session_state -- if the user
            # switches to another tab and interacts with ANY other widget
            # there, that triggers a full script rerun which rebuilds this
            # tracker from the still-unchanged saved data, discarding
            # whatever hadn't been saved yet. That's what made deletions
            # look like they silently reverted after switching tabs. Saving
            # immediately on detected change closes that gap entirely.
            #
            # bump_version is passed separately from the save itself and
            # only set True when the ROW COUNT changed -- i.e. an actual
            # add or delete, which is the only case that produces a stale
            # positional diff worth guarding against. A plain cell edit
            # (e.g. renaming a company) doesn't shift row positions, so
            # forcing a full widget remount for it was overkill -- and
            # actively harmful, since remounting the widget right after
            # the user's own edit could visually fight with what they were
            # typing, making it look like edits weren't taking.
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
                prompt_login("keep your tracker saved across visits", key="signin_tracker_tab")
            with col_stats:
                total = len(df)
                replied = len(df[df["Status"] == "Replied"])
                interviewing = len(df[df["Status"] == "Interviewing"])
                st.caption(f"{total} total - {replied} replied - {interviewing} interviewing")

    with tab_generate:
        st.caption(
            "Pick a company from your tracker (or type one) and research it automatically, "
            "or paste in the context yourself. This, plus your profile, drafts a message you "
            "can edit before sending."
        )
        # Moved out of st.form -- both the company picker and the research
        # button need to programmatically fill other fields on the same
        # run, which forms can't do (they only rerun on submit).
        company_key = "outreach_gen_company"
        context_key = "outreach_gen_context"
        news_key = "outreach_gen_news"
        for k in (company_key, context_key, news_key):
            if k not in st.session_state:
                st.session_state[k] = ""

        known_companies = (
            sorted(st.session_state.outreach_df["Company Name"].dropna().unique().tolist())
            if not st.session_state.outreach_df.empty else []
        )
        picker_options = ["Type manually"] + known_companies
        picked_company = st.selectbox("Select company", picker_options, key="outreach_company_picker")
        last_picked_key = "outreach_company_last_picked"
        poc_key = "outreach_gen_poc"
        if poc_key not in st.session_state:
            st.session_state[poc_key] = ""
        if picked_company != "Type manually" and st.session_state.get(last_picked_key) != picked_company:
            st.session_state[company_key] = picked_company
            st.session_state[last_picked_key] = picked_company
            # Switching to a different company must not carry over the
            # PREVIOUS company's research/context/generated messages --
            # otherwise clicking Generate again after switching (without
            # re-researching) sends the new company's name alongside the
            # old company's context, and the model can end up writing
            # about the old company almost verbatim. Clearing all of this
            # forces a clean slate: either re-research, or knowingly type
            # fresh context for the new company.
            st.session_state[context_key] = ""
            st.session_state[news_key] = ""
            st.session_state.pop("outreach_research_sources", None)
            st.session_state.pop("last_email", None)
            st.session_state.pop("last_linkedin", None)
            st.session_state.pop("outreach_poc_row_choice", None)

        # POC auto-fill -- a company can have MULTIPLE tracker rows (e.g. two
        # different positions with two different hiring managers), so this
        # can't just grab the first match. If there's more than one row for
        # the picked company, show a picker so the user chooses which
        # position/POC to pull from, instead of silently guessing the first
        # one. Recomputed every render (not just on company change) so the
        # picker below always reflects the current selection.
        if picked_company != "Type manually":
            matches = st.session_state.outreach_df[
                st.session_state.outreach_df["Company Name"] == picked_company
            ]
            if len(matches) > 1:
                def _row_label(row) -> str:
                    poc = str(row.get("POC Name", "")).strip()
                    desig = str(row.get("POC Designation", "")).strip()
                    poc = poc if poc and poc.lower() != "nan" else "No POC on file"
                    desig = f" ({desig})" if desig and desig.lower() != "nan" else ""
                    return f"{poc}{desig}"

                row_options = [_row_label(row) for _, row in matches.iterrows()]
                chosen_label = st.selectbox(
                    f"Multiple entries found for {picked_company} -- which one?",
                    row_options,
                    key="outreach_poc_row_choice",
                )
                chosen_idx = row_options.index(chosen_label)
                chosen_row = matches.iloc[chosen_idx]
                poc_val = chosen_row.get("POC Name", "")
                st.session_state[poc_key] = "" if pd.isna(poc_val) else str(poc_val).strip()
            elif not matches.empty:
                poc_val = matches.iloc[0].get("POC Name", "")
                st.session_state[poc_key] = "" if pd.isna(poc_val) else str(poc_val).strip()

        name_key = "outreach_your_name"
        if name_key not in st.session_state:
            st.session_state[name_key] = ""
        your_name = st.text_input(
            "Your name",
            key=name_key,
            help="Used for the self-intro and sign-off. This is a fixed personal detail, not "
            "something to bury inside your profile text -- kept separate so it's never missing "
            "or guessed.",
        )

        gen_company = st.text_input("Company name", key=company_key)
        poc_name = st.text_input(
            "Point of contact's name (optional — leave blank for a generic greeting)",
            key=poc_key,
            help="Auto-filled from the tracker if this company has a POC on file. Edit or clear as needed.",
        )

        if st.button("🔎 Research this company", disabled=not gen_company.strip()):
            if not require_tavily_key():
                st.stop()
            with st.spinner(f"Researching {gen_company}..."):
                try:
                    result = research_company(gen_company)
                    if result["found"]:
                        st.session_state[context_key] = result["overview"]
                        st.session_state[news_key] = result["recent_news"]
                        st.session_state["outreach_research_sources"] = result["sources"]
                        st.success("Filled in below — review and edit before generating.")
                        analytics.log_event("funnel", "outreach_research_run", details=f"company={gen_company}")
                    else:
                        st.warning("Couldn't find much on this company. Fill in the fields manually.")
                except ValueError as e:
                    st.error(str(e))
                    analytics.log_error("outreach_research", str(e))
        st.caption("Don't have a Tavily key? Skip this and fill in the fields below manually.")

        company_context = st.text_area(
            "What does this company do? (1-2 sentences)",
            placeholder="e.g. Early-stage fintech building a UPI-based lending product for gig workers.",
            key=context_key,
        )
        recent_news = st.text_area(
            "Any recent news? (optional, improves personalisation)",
            placeholder="e.g. Raised a seed round last month, launched a new app.",
            key=news_key,
        )
        if st.session_state.get("outreach_research_sources"):
            with st.expander("Sources used for research"):
                for s in st.session_state["outreach_research_sources"]:
                    st.caption(f"[{s['title']}]({s['url']})" if s["title"] else s["url"])
                st.caption(
                    "AI-generated summary — worth a skim before you send, in case "
                    "anything's out of date or slightly off."
                )

        your_profile = render_profile_field(
            key_prefix="outreach",
            placeholder="e.g. Final-year engineering student, looking for APM/PM roles.",
        )

        generate_clicked = st.button("Generate messages", use_container_width=True)

        if generate_clicked:
            if not your_name or not gen_company or not company_context or not your_profile:
                st.error("Your name, company name, company context, and your profile are all required.")
            elif not require_groq_key():
                st.stop()
            else:
                with st.spinner("Drafting your messages..."):
                    try:
                        client = OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1")
                        poc_first_name = poc_name.strip().split(" ")[0] if poc_name.strip() else ""
                        system_prompt = (
                            "Write a cold outreach EMAIL (with subject line) in the exact style, tone, and "
                            "level of specificity as the example below -- not more formal, not longer, not "
                            "more polished. Match it. Write only the email -- the LinkedIn version is handled "
                            "separately, by compressing whatever email you write here.\n\n"
                            "EXAMPLE OF THE STYLE AND SPECIFICITY TO MATCH:\n"
                            "---\n"
                            "Subject: Quick one from an IIT Bombay grad\n\n"
                            "Hi Ritesh,\n\n"
                            "I'm Dinesh, just graduated from IIT Bombay (Chemistry, 2026). I know this is a "
                            "cold mail so I'll keep it short.\n\n"
                            "I've been trying to break into product and have spent the last year actually "
                            "doing the work rather than just reading about it. Interned at an early-stage D2C "
                            "startup doing user research, PRDs, and GTM work. Before that, spent two years "
                            "running cultural operations for IIT Bombay as Institute Cultural Nominee, which "
                            "at 15,000 students and 14 clubs was basically a product and ops problem the "
                            "whole time.\n\n"
                            "I came across Innov8 and the way you've thought about workspace as a community "
                            "problem rather than a square footage problem stuck with me. Curious if there's "
                            "any room for a PM on the team.\n\n"
                            "Would you be open to a quick 15-minute call? Happy to send my resume if that "
                            "helps.\n\n"
                            "Dinesh\n"
                            "+91-7977500778\n"
                            "---\n\n"
                            "What that example does, that yours should too:\n"
                            "- Greeting uses a first name casually ('Hi <name>,') if one is given, otherwise "
                            "'Hi,' -- never a formal 'Dear <name>,' and never invent a name you weren't given.\n"
                            "- The candidate's own name is given below. ALWAYS use it in the self-intro (\"I'm "
                            "<name>, ...\") and ALWAYS sign off with it -- never omit the self-intro or the "
                            "sign-off, and never leave the email without a name in it.\n"
                            "- Opens by naming the cold-mail reality plainly, not with a compliment or 'I've "
                            "been following your journey.'\n"
                            "- Describes the candidate's background in PAST TENSE, what they actually did, "
                            "using the candidate's own words/framing from their profile below -- not resume "
                            "language, not aspirational ('I want to...').\n"
                            "- CRITICAL: the profile below is a dense, multi-fact source document, not a "
                            "script to recite in full. Pick only the ONE OR TWO facts most relevant to THIS "
                            "specific company/recipient and build the background paragraph around just those "
                            "-- drop everything else in the profile, even if it's impressive. Then reframe "
                            "the chosen fact(s) the way a person would say it out loud, not as a resume line: "
                            "'managed 14 clubs and 15,000 students as Institute Cultural Nominee' becomes "
                            "'ran ops for 15k students at IITB, which was basically a product problem the "
                            "whole time' -- same fact, spoken framing. A background paragraph that strings "
                            "together three or more profile facts with 'and'/'also' reads as a resume dump "
                            "and is wrong even if every fact in it is true and specific.\n"
                            "- The one candidate-to-company connection stands alone in its own short paragraph, "
                            "as a specific OBSERVATION about how the company/person thinks about their work -- "
                            "not a compliment, and not built on a generic shared label (e.g. 'AI', "
                            "'cross-functional', 'data-driven'). Pick exactly one; don't chain a second one in "
                            "with 'as'/'and'/'while'. This paragraph MUST explicitly tie something the "
                            "candidate actually did (from their profile) to something specific about the "
                            "company -- a company fact on its own, however impressive or specific (a revenue "
                            "number, a feature, a launch), is NOT a connection by itself. If you can't find a "
                            "genuine link to something the candidate did, say so honestly in plain terms "
                            "rather than writing a company-only observation that just sounds like a "
                            "connection.\n"
                            "- If the company research below mentions several distinct facts (e.g. their "
                            "product philosophy AND an expansion plan AND a metric), pick ONLY ONE of them to "
                            "build the connection around -- do not reference a second company fact anywhere "
                            "else in the email, even as a passing compliment with no candidate tie attached. "
                            "One company fact, one candidate fact, one sentence tying them together. Nothing "
                            "else about the company belongs in the email.\n"
                            "- State the connection as a direct fact, never as a belief or guess -- no 'I "
                            "think X is similar', 'I think this is comparable', 'this seems like', or any "
                            "other phrasing that frames it as your opinion rather than a stated fact.\n"
                            "- The ask is one sentence, the smallest possible next step (a short call) -- "
                            "nothing else in that sentence, no restating skills.\n"
                            "- Sign-off is a first name only, no 'Best,'/'Regards,' formality, no full contact "
                            "block -- just the name (and phone number below it, only if given).\n"
                            "- Subject line names something specific about identity (school, grad year, the "
                            "role transition) -- never describe yourself using ANY occupational-status word or "
                            "phrase (a noun or adjective that labels what kind of professional you are -- "
                            "'leader', 'lead', 'professional', 'pro', 'manager', 'expert', 'specialist', 'guru', "
                            "or any other synonym in that same category, in any form: alone, paired, prefixed, "
                            "or shortened/informal), anywhere in the subject or body, UNLESS that exact word "
                            "appears in the profile below. This is a category ban, not a specific word list -- "
                            "if you're tempted to reach for any word that answers 'what kind of professional am "
                            "I', don't use it. Describe the person by what they DID (shipped, managed, built, "
                            "negotiated) instead of a role name they weren't given.\n"
                            "- The connection is stated as ONE plain fact, never hedged ('could apply to...', "
                            "'similar principles could...') and never chained to a second one with a connector "
                            "word ('as', 'and', 'while') -- e.g. 'X resonated with my work on Y, as I think "
                            "about how similar principles could apply to Z' is TWO connections wearing one "
                            "sentence; cut everything from 'as' onward.\n"
                            "- Don't reuse the same phrase from the background paragraph inside the connection "
                            "paragraph -- if a fact already appeared once, refer to it differently or drop it.\n"
                            "- Before finalizing, run the connection paragraph through this check: would this "
                            "exact sentence still work, almost unchanged, for a different company in the same "
                            "broad category (e.g. any other food-delivery company, any other fintech, any "
                            "other D2C brand)? If yes, it's too generic -- go back into the profile and company "
                            "context and find a sharper, more specific angle (a concrete number, a named "
                            "system, a specific mechanism), or if nothing sharper exists, write the connection "
                            "in plain honest terms about the company's actual mission/space instead of forcing "
                            "a specific-sounding but hollow link.\n\n"
                            "Do not invent facts about the company or the point of contact beyond what's given."
                        )
                        user_prompt = f"""
Company: {gen_company}
Candidate's name (use for self-intro and sign-off, always): {your_name}
Point of contact's first name (use for greeting if present, otherwise use the generic greeting): {poc_first_name or "Not given"}
What the company does: {company_context}
Recent news: {recent_news or "None provided"}
My profile: {your_profile}

Write the cold email now, following the exact sentence structure given.
"""
                        email_output, still_flagged, flag_reason = _generate_with_retry(
                            client, system_prompt, user_prompt
                        )
                        if still_flagged:
                            st.warning(
                                "Heads up: this draft still had a flagged phrase after a "
                                f"retry -- {flag_reason}. Give the connection sentence a read "
                                "before sending."
                            )
                        email_final = _strip_trailing_placeholder(email_output.strip())

                        # LinkedIn is derived by compressing the email above, not
                        # generated independently -- see _compress_to_linkedin.
                        # This means it inherits whatever connection the email
                        # already has instead of risking a second, separately-generated one.
                        # It now also re-checks for banned filler phrases the
                        # compression step itself might introduce (e.g. squeezing
                        # a specific connection down into "aligns with") -- that
                        # gap previously shipped unchecked.
                        linkedin_output, li_still_flagged, li_flag_reason = _compress_to_linkedin(
                            client, email_final, poc_first_name
                        )

                        # Separate length check -- the 300-char instruction lives
                        # in the compression prompt, but that's a soft target the
                        # model can drift past (as seen with a 290+ char draft),
                        # so verify it here and ask for a further trim if it's
                        # over, rather than trusting the prompt alone.
                        if len(linkedin_output.strip()) > 300:
                            trim_response = client.chat.completions.create(
                                model="llama-3.3-70b-versatile",
                                messages=[
                                    {"role": "user", "content": (
                                        f"This LinkedIn DM is {len(linkedin_output.strip())} characters, over "
                                        "the 300-character limit:\n\n"
                                        f"{linkedin_output.strip()}\n\n"
                                        "Shorten it to comfortably under 300 characters. Do not add any new "
                                        "content -- keep the same greeting, self-introduction, and connection, "
                                        "just cut words, not required elements. Do not compress toward filler "
                                        "words like 'aligns with', 'cross-functional', or 'synergy' to save "
                                        "characters -- keep the specific wording, just shorter."
                                    )},
                                ],
                                temperature=0.3,
                            )
                            linkedin_output = trim_response.choices[0].message.content.strip()
                            # The trim call can reintroduce the same filler-word
                            # problem the compression step just fixed -- it's
                            # rewriting the same text for the same reason
                            # (fewer characters). Re-check rather than trusting
                            # this second unchecked rewrite.
                            trim_found = _find_banned_phrases(linkedin_output)
                            if trim_found:
                                li_still_flagged = True
                                li_flag_reason = (
                                    f"{li_flag_reason}; also, the length-trim step introduced "
                                    f"banned phrase(s) {trim_found}" if li_flag_reason
                                    else f"the length-trim step introduced banned phrase(s) {trim_found}"
                                )

                        if li_still_flagged:
                            st.warning(
                                "Heads up: the LinkedIn DM still had a flagged issue after "
                                f"compression -- {li_flag_reason}. Review it by hand before "
                                "sending."
                            )

                        st.session_state.last_email = email_final
                        st.session_state.last_linkedin = _strip_trailing_placeholder(linkedin_output.strip())
                        analytics.log_event("funnel", "outreach_message_generated", details=f"company={gen_company}")
                    except Exception as e:
                        st.error(f"Message generation failed: {e}")
                        analytics.log_error("outreach_message_generation", str(e))

        if st.session_state.get("last_email"):
            st.markdown("---")
            col_email, col_li = st.columns(2)
            with col_email:
                st.markdown("**Cold email**")
                st.text_area("Editable email draft", value=st.session_state.last_email, height=300, key="email_edit_box")
            with col_li:
                st.markdown("**LinkedIn DM**")
                st.text_area("Editable LinkedIn draft", value=st.session_state.last_linkedin, height=300, key="li_edit_box")
            st.caption("Edit either draft before sending. Always personalise further if you can.")
            st.caption("⚠️ These drafts are AI-generated and not perfect -- please review both carefully before sending.")