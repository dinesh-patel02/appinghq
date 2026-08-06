# sections/jd_match.py
# JD Match tool -- lives inside the Inbound flow.
# Analysis logic is unchanged from the original build (already grounded,
# already on Groq). This module only owns rendering.

import streamlit as st
import os
import hashlib
from dotenv import load_dotenv
from openai import AuthenticationError
from backend.rag_engine import parse_pdf, build_vector_store
from backend.analysis_engine import analyze_application_bundle
from backend.utils import validate_inputs
from backend.api_keys import require_groq_key
from backend import analytics

load_dotenv()


@st.cache_resource(show_spinner="Building an index from your resume...")
def _cached_vector_store(resume_text: str):
    return build_vector_store(resume_text)


@st.cache_data(show_spinner="Checking your resume against the job description...")
def _cached_analysis(resume_text: str, job_description: str, company_name: str) -> dict:
    vs = _cached_vector_store(resume_text)
    return analyze_application_bundle(vs, job_description, company_name)


def render():
    if "analysis_results" not in st.session_state:
        st.session_state.analysis_results = None
    if "analysis_inputs_hash" not in st.session_state:
        st.session_state.analysis_inputs_hash = None

    st.markdown('<div class="ah-title">JD Match</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ah-page-desc">Upload your resume and paste a job description '
        'to see exactly where you stand before you apply.</div>',
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2, gap="large")
    with col1:
        st.markdown("**Your resume**")
        uploaded_file = st.file_uploader("Upload PDF resume", type=["pdf"], label_visibility="collapsed")
    with col2:
        st.markdown("**Job description**")
        company_name = st.text_input("Company name (optional)", placeholder="e.g. Razorpay")
        job_description = st.text_area(
            "Paste the full job description",
            height=180,
            placeholder="Paste the complete job description here.",
            label_visibility="collapsed",
        )

    st.write("")
    run_analysis = st.button("Check my fit", use_container_width=False)

    if run_analysis:
        if not require_groq_key():
            st.stop()
        if not uploaded_file:
            st.error("Upload your resume PDF first.")
            st.stop()
        if not job_description:
            st.error("Paste the job description first.")
            st.stop()

        resume_text = parse_pdf(uploaded_file)
        is_valid, error_msg = validate_inputs(resume_text, job_description)
        if not is_valid:
            st.error(error_msg)
            st.stop()

        inputs_hash = hashlib.sha256(
            (resume_text + job_description + company_name).encode()
        ).hexdigest()

        if not (st.session_state.analysis_inputs_hash == inputs_hash and st.session_state.analysis_results):
            try:
                results = _cached_analysis(resume_text, job_description, company_name)
            except AuthenticationError:
                st.error(
                    "Groq rejected your API key. Double-check it's copied exactly "
                    "from console.groq.com (it should start with `gsk_`) with no "
                    "extra spaces, and that it's still active."
                )
                analytics.log_error("jd_match_analysis", "Groq authentication error")
                st.stop()
            st.session_state.analysis_results = results
            st.session_state.analysis_inputs_hash = inputs_hash
            analytics.log_event("funnel", "jd_match_run", details=f"company={company_name}")

        st.success("Done.")

    if st.session_state.analysis_results:
        results = st.session_state.analysis_results
        match_data = results["match_score"]
        gap_data = results["skill_gaps"]
        interview_data = results["interview_prep"]
        improvement_data = results["resume_fixes"]

        tab1, tab2, tab3, tab4 = st.tabs(["Match score", "Skill gaps", "Interview prep", "Resume fixes"])

        with tab1:
            score = match_data.get("score", 0)
            col_score, col_detail = st.columns([1, 2], gap="large")
            with col_score:
                st.markdown(
                    f'<div class="ah-card ah-score-card">'
                    f'<div class="ah-score-label">Overall match</div>'
                    f'<div class="ah-score-value">{score}%</div>'
                    f'<div class="ah-score-caption">{match_data.get("score_label", "")}</div></div>',
                    unsafe_allow_html=True,
                )
            with col_detail:
                st.markdown("**Summary**")
                st.write(match_data.get("summary", ""))
                col_str, col_weak = st.columns(2)
                with col_str:
                    st.markdown("**Strengths**")
                    for s in match_data.get("strengths", []):
                        st.markdown(f"- {s}")
                with col_weak:
                    st.markdown("**Weaknesses**")
                    for w in match_data.get("weaknesses", []):
                        st.markdown(f"- {w}")
            st.progress(score / 100)

        with tab2:
            col_present, col_missing, col_partial = st.columns(3)
            with col_present:
                st.markdown("**Skills you have**")
                for skill in gap_data.get("present_skills", []):
                    st.markdown(f'<span class="ah-tag">{skill}</span>', unsafe_allow_html=True)
            with col_missing:
                st.markdown("**Missing skills**")
                for skill in gap_data.get("missing_skills", []):
                    st.markdown(f'<span class="ah-tag">{skill}</span>', unsafe_allow_html=True)
            with col_partial:
                st.markdown("**Partial match**")
                for skill in gap_data.get("partial_skills", []):
                    st.markdown(f'<span class="ah-tag">{skill}</span>', unsafe_allow_html=True)
            st.markdown("---")
            st.markdown("**How to close the gaps**")
            for rec in gap_data.get("recommendations", []):
                with st.expander(rec.get("skill", "")):
                    st.write(rec.get("how_to_show", ""))

        with tab3:
            company_label = f"at {company_name}" if company_name else "for this role"
            st.markdown(f"**Likely questions {company_label}**")
            st.caption("Generated from the job description and your resume.")
            for i, q in enumerate(interview_data.get("questions", []), 1):
                with st.expander(f"Q{i}: {q.get('question', '')}"):
                    st.caption(q.get("type", ""))
                    st.markdown("**Why they ask this**")
                    st.write(q.get("why_asked", ""))
                    st.markdown("**Suggested answer**")
                    st.info(q.get("suggested_answer", ""))
                    st.markdown("**Resume evidence to reference**")
                    st.caption(q.get("resume_evidence", ""))

        with tab4:
            st.markdown("**What to highlight for this role**")
            for item in improvement_data.get("what_to_highlight", []):
                st.markdown(f"- {item}")
            st.markdown("---")
            st.markdown("**Rewrite these bullets**")
            for imp in improvement_data.get("improvements", []):
                col_orig, col_new = st.columns(2)
                with col_orig:
                    st.markdown("**Original**")
                    st.error(imp.get("original", ""))
                with col_new:
                    st.markdown("**Improved**")
                    st.success(imp.get("improved", ""))
                st.caption(f"Why: {imp.get('reason', '')}")
                st.markdown("---")
            st.markdown("**New bullets to add**")
            for nb in improvement_data.get("new_bullets", []):
                with st.expander(f"Add to: {nb.get('section', 'your resume')}"):
                    st.success(nb.get("bullet", ""))
                    st.caption(f"Why this helps: {nb.get('why', '')}")