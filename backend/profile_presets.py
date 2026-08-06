# backend/profile_presets.py
# Small JSON-backed store for saved "your profile" blurbs, so the same
# background/pitch text doesn't have to be retyped for every message
# generated in Outreach or Inbound. Shared between both, since it's the
# same person's profile either way (though someone might keep a couple of
# variants, e.g. "APM pivot" vs "generic PM" -- hence a list, not a single
# blob).
#
# Also owns the "generate from resume" flow: instead of hand-typing a
# profile (which tends to come out as a thin, generic summary -- the exact
# thing that kept producing generic candidate-side connections in message
# generation), the person can upload their resume once and have a dense,
# fact-rich profile extracted from it, then save that as a preset like any
# other. Deliberately NOT tied to JD Match's session state -- this needs
# its own upload step so it still works in a fresh session where JD Match
# was never opened.

import json
import os

PRESETS_FILE = "profile_presets.json"


def load_presets() -> dict:
    """Returns {label: profile_text}. Empty dict if no presets saved yet."""
    if not os.path.exists(PRESETS_FILE):
        return {}
    try:
        with open(PRESETS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # corrupted or unreadable file -- fail soft rather than crashing
        # the whole page over a preset-loading issue
        return {}


def save_preset(label: str, profile_text: str) -> None:
    """Saves or overwrites a preset under `label`."""
    label = label.strip()
    if not label:
        return
    presets = load_presets()
    presets[label] = profile_text
    with open(PRESETS_FILE, "w") as f:
        json.dump(presets, f, indent=2)


def delete_preset(label: str) -> None:
    presets = load_presets()
    presets.pop(label, None)
    with open(PRESETS_FILE, "w") as f:
        json.dump(presets, f, indent=2)


GENERATE_OPTION = "Generate from resume"
MANUAL_OPTION = "Write manually"


def _render_generate_from_resume(key_prefix: str, text_key: str) -> None:
    """
    Resume upload + preferences + Generate button. On success, fills the
    profile textarea directly (same as picking a saved preset does) so the
    person reviews/edits it before saving, same as everywhere else in this
    app -- generation never gets to skip the human review step.
    """
    import streamlit as st
    from backend.rag_engine import parse_pdf
    from backend.profile_generator import generate_profile_from_resume
    from backend.api_keys import require_groq_key

    st.caption(
        "Upload your resume once to generate a fact-rich profile -- specific "
        "numbers and projects make for much better connections than a "
        "hand-typed summary. Review and edit before saving."
    )

    resume_file = st.file_uploader(
        "Resume (PDF)", type=["pdf"], key=f"{key_prefix}_gen_resume_upload"
    )
    preferences = st.text_input(
        "What are you looking for? (optional, sharpens the result)",
        placeholder="e.g. APM/PM roles involving product discovery work",
        key=f"{key_prefix}_gen_preferences",
    )

    if st.button("Generate profile", key=f"{key_prefix}_gen_btn", disabled=not resume_file):
        if not require_groq_key():
            return
        with st.spinner("Reading your resume and drafting a profile..."):
            try:
                resume_text = parse_pdf(resume_file)
                result = generate_profile_from_resume(resume_text, preferences)
            except ValueError as e:
                st.error(str(e))
                return
            except Exception as e:
                st.error(f"Couldn't generate a profile: {e}")
                return

        st.session_state[text_key] = result["profile"]
        if result["thin_resume"]:
            st.warning(
                "Your resume parsed as pretty short -- the generated profile "
                "might be light on specifics. Worth a look before saving."
            )
        else:
            st.success("Generated below -- review, edit, and save as a preset if it looks good.")


def render_profile_field(key_prefix: str, placeholder: str = "", height: int = 100) -> str:
    """
    Renders the preset dropdown + profile textarea + save/delete controls,
    and returns the current profile text.

    MUST be called OUTSIDE any st.form -- forms don't rerun until submit,
    so a preset selection couldn't live-update the textarea if this lived
    inside one. This is why the profile field was moved out of the
    Outreach/Inbound message-generator forms; the rest of each form is
    unaffected.

    key_prefix keeps Outreach's and Inbound's widget keys from colliding
    (e.g. "outreach" / "inbound") while both read/write the same shared
    preset file, since it's the same person's profile either way.
    """
    import streamlit as st

    text_key = f"{key_prefix}_profile_text"
    if text_key not in st.session_state:
        st.session_state[text_key] = ""

    presets = load_presets()
    labels = [MANUAL_OPTION, GENERATE_OPTION] + sorted(presets.keys())

    picked = st.selectbox(
        "Use a saved profile",
        labels,
        key=f"{key_prefix}_profile_picker",
    )

    if picked == GENERATE_OPTION:
        _render_generate_from_resume(key_prefix, text_key)
    elif picked != MANUAL_OPTION and picked in presets:
        # only overwrite if the picker actually changed selection, so the
        # user can still freely edit the box afterward without it snapping
        # back on every rerun
        last_picked_key = f"{key_prefix}_last_picked"
        if st.session_state.get(last_picked_key) != picked:
            st.session_state[text_key] = presets[picked]
            st.session_state[last_picked_key] = picked

    st.text_area(
        "Your profile (background, the role you want, one line on why)",
        placeholder=placeholder,
        height=height,
        key=text_key,
    )

    with st.expander("Save or manage presets"):
        col_save, col_del = st.columns(2)
        with col_save:
            new_label = st.text_input(
                "Save current text as", key=f"{key_prefix}_new_preset_label",
                placeholder="e.g. APM pivot",
            )
            if st.button("Save preset", key=f"{key_prefix}_save_preset_btn"):
                if new_label.strip() and st.session_state[text_key].strip():
                    save_preset(new_label, st.session_state[text_key])
                    st.success(f"Saved '{new_label}'.")
                    st.rerun()
                else:
                    st.error("Need both a name and some profile text to save.")
        with col_del:
            if presets:
                to_delete = st.selectbox(
                    "Delete a preset", sorted(presets.keys()),
                    key=f"{key_prefix}_delete_picker",
                )
                if st.button("Delete", key=f"{key_prefix}_delete_preset_btn"):
                    delete_preset(to_delete)
                    st.success(f"Deleted '{to_delete}'.")
                    st.rerun()
            else:
                st.caption("No presets saved yet.")

    return st.session_state[text_key]