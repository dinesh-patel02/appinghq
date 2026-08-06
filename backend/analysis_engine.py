# analysis_engine.py

from openai import OpenAI, AuthenticationError, BadRequestError, PermissionDeniedError, NotFoundError
from backend.rag_engine import retrieve_relevant_chunks, FAISS
import os
from dotenv import load_dotenv
import json
import re
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

load_dotenv()
logger = logging.getLogger(__name__)


def _get_api_key() -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise ValueError(
            "Groq API key not found. "
            "Set GROQ_API_KEY in your .env file "
            "or as an environment variable."
        )
    return key


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        brace_match = re.search(r'\{.*\}', text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group())
            except json.JSONDecodeError:
                pass
        depth = 0
        start = -1
        for i, ch in enumerate(text):
            if ch == '{':
                if start == -1:
                    start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start != -1:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        start = -1
    return {}


def _is_transient_error(exc: BaseException) -> bool:
    """
    True for errors worth retrying (rate limits, timeouts, 5xx, network
    blips), False for permanent client errors (invalid API key, malformed
    request, etc.) that will fail identically no matter how many times we
    retry -- retrying those just burns ~15+ seconds of backoff before
    showing the user the same error they'd have seen immediately.

    Written as a plain function rather than
    `retry_if_exception_type(Exception) & ~retry_if_exception_type(...)`
    because the `~` (bitwise negation) operator on tenacity predicates
    requires a newer tenacity version than what's installed here -- older
    versions raise `TypeError: bad operand type for unary ~`.

    Must be wrapped in `retry_if_exception(...)` below rather than passed
    directly as `retry=_is_transient_error` -- tenacity calls `retry=`
    callables with the `retry_state` object, not the raw exception. Passed
    bare, `isinstance(retry_state, (AuthenticationError, ...))` is always
    False, so this always returned True -- including after a *successful*
    call, since a bare callable's return value is treated as "should
    retry?" with no automatic success check. That caused retries to
    continue even after the API call succeeded, all the way to
    stop_after_attempt(5), where reraise() found no exception on the final
    (successful) attempt and raised RetryError itself instead of the
    result. `retry_if_exception` correctly short-circuits to "don't retry"
    on success and only calls the predicate when there was an exception.
    """
    return not isinstance(
        exc, (AuthenticationError, BadRequestError, PermissionDeniedError, NotFoundError)
    )


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=15),
    retry=retry_if_exception(_is_transient_error),
    reraise=True,
)
def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """Single Groq generation call wrapped with exponential-backoff retry."""
    client = OpenAI(
        api_key=os.getenv("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1"
    )
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1
    )
    return response.choices[0].message.content.strip()


def analyze_application_bundle(
    vector_store: FAISS,
    job_description: str,
    company_name: str = "",
) -> dict:
    resume_context = retrieve_relevant_chunks(
        vector_store,
        job_description + " skills experience projects achievements leadership",
        k=12,
    )

    system_prompt = (
        "You are a strict, honest technical recruiter with 15+ years of experience. "
        "Your job is to evaluate resumes against job descriptions with brutal accuracy. "
        "You never inflate scores to be encouraging. "
        "A resume missing the core required skills of a role must score below 40. "
        "A resume that is a completely different career track (e.g. PM resume vs SWE role) must score below 35. "
        "You only reference skills, achievements, and metrics that are explicitly present in the resume text provided. "
        "You never invent numbers, percentages, or metrics not found in the resume. "
        "If a bullet has no metric in the resume, rewrite it with a placeholder like [ADD METRIC] instead of inventing one. "
        "You craft interview answers using the STAR format grounded only in the candidate's actual experience. "
        "Respond in valid JSON only. No markdown. No explanation outside the JSON."
    )

    user_prompt = f"""You are evaluating a real candidate's resume against a real job description. Be strict and accurate.

SCORING RULES — follow these exactly:
- Score 80-100: Candidate meets 80%+ of required skills and has directly relevant experience
- Score 60-79: Candidate meets 50-79% of required skills, some gaps but transferable experience
- Score 40-59: Candidate meets 30-49% of required skills, significant gaps
- Score 20-39: Candidate meets fewer than 30% of required skills, wrong career track or level
- Score 0-19: Candidate has almost no relevant skills for this role
- If the JD requires 3+ years experience and the candidate is a fresher, deduct 20 points minimum
- If the JD is a technical/engineering role and the resume has no technical skills, score must be below 35
- If a required years-of-experience threshold is not met (e.g. JD wants 5+ years, candidate has less),
  this is itself a required "skill" — it MUST appear as its own entry in missing_skills or partial_skills
  below, phrased like "5+ years of product management experience" or "3+ years in a technical role".
  Do not let this gap live only in the numeric score or in weaknesses — it must also be named explicitly
  as a skill_gaps entry so it's visible to someone who only reads that tab.

FABRICATION RULES — follow these exactly:
- Only list skills as "present" if they are explicitly named in the resume text below
- Never invent metrics or numbers not present in the resume
- If rewriting a bullet and the original has no metric, write [ADD METRIC: describe what to measure] as a placeholder
- If the ORIGINAL bullet already contains a real number, count, or percentage (e.g. "15+", "116-person",
  "200+ events"), you MUST carry that exact number into the improved version. Never replace an existing
  real metric with an [ADD METRIC: ...] placeholder — placeholders are ONLY for information that is
  genuinely absent from the original bullet. Downgrading a real number into a placeholder is a fabrication
  in reverse: it destroys true information and must never happen.
- Never say a candidate has experience in X if X does not appear in their resume

RESUME CONTENT (most relevant sections — this is the ONLY source of truth about the candidate):
{resume_context}

JOB DESCRIPTION:
{job_description}

{'COMPANY: ' + company_name if company_name else ''}

Respond with ONLY this exact JSON structure — no extra text, no markdown:

{{
  "match_score": {{
    "score": <integer 0-100, follow scoring rules above strictly>,
    "score_label": "<Poor|Below Average|Average|Good|Excellent>",
    "summary": "<2-3 sentence honest assessment naming specific gaps and specific matches>",
    "strengths": ["<specific strength found in resume that matches JD>", "<strength 2>", "<strength 3>"],
    "weaknesses": ["<specific gap — name the exact missing skill or experience>", "<weakness 2>", "<weakness 3>"]
  }},
  "skill_gaps": {{
    "required_skills": ["<exact skill required by JD>", ...],
    "present_skills": ["<skill explicitly found in resume text only>", ...],
    "missing_skills": ["<required skill completely absent from resume>", ...],
    "partial_skills": ["<required skill partially present>", ...],
    "recommendations": [
      {{"skill": "<missing skill name>", "how_to_show": "<specific actionable advice>"}}
    ]
  }},
  "interview_prep": {{
    "questions": [
      {{
        "question": "<likely interview question for this specific role>",
        "type": "<Behavioral|Technical|Strategy|Product Sense>",
        "why_asked": "<why this company asks this>",
        "suggested_answer": "<STAR answer using only experiences explicitly in the resume>",
        "resume_evidence": "<exact bullet or section from resume that supports this>"
      }}
    ]
  }},
  "resume_fixes": {{
    "improvements": [
      {{
        "original": "<copy the exact original bullet from the resume>",
        "improved": "<rewrite using XYZ formula — KEEP any real numbers already in the original bullet exactly as-is; use [ADD METRIC: what to measure] ONLY for details that have no number in the original>",
        "reason": "<why this version is stronger for this specific role>"
      }}
    ],
    "new_bullets": [
      {{
        "bullet": "<suggested new bullet based only on experiences in the resume>",
        "section": "<which resume section>",
        "why": "<why this helps for this specific role>"
      }}
    ],
    "what_to_highlight": ["<specific experience from resume to emphasise for this role>", ...]
  }}
}}

Rules:
- match_score.score must be an integer 0-100, follow scoring rules strictly
- interview_prep.questions must contain exactly 5 questions
- resume_fixes.improvements must contain 3-4 bullet rewrites using only actual bullets from the resume
- resume_fixes.new_bullets must contain 2-3 suggestions
- Every field must be present, use empty arrays if no data
- Never fabricate metrics, skills, or experiences not in the resume"""

    raw_text = _call_llm(system_prompt, user_prompt)
    raw = _parse_json(raw_text)

    match_score = raw.get("match_score", {})
    skill_gaps = raw.get("skill_gaps", {})
    interview_prep = raw.get("interview_prep", {})
    resume_fixes = raw.get("resume_fixes", {})

    return {
        "match_score": {
            "score": match_score.get("score", 0),
            "score_label": match_score.get("score_label", ""),
            "summary": match_score.get("summary", ""),
            "strengths": match_score.get("strengths", []),
            "weaknesses": match_score.get("weaknesses", []),
        },
        "skill_gaps": {
            "required_skills": skill_gaps.get("required_skills", []),
            "present_skills": skill_gaps.get("present_skills", []),
            "missing_skills": skill_gaps.get("missing_skills", []),
            "partial_skills": skill_gaps.get("partial_skills", []),
            "recommendations": skill_gaps.get("recommendations", []),
        },
        "interview_prep": {
            "questions": interview_prep.get("questions", []),
        },
        "resume_fixes": {
            "improvements": resume_fixes.get("improvements", []),
            "new_bullets": resume_fixes.get("new_bullets", []),
            "what_to_highlight": resume_fixes.get("what_to_highlight", []),
        },
    }