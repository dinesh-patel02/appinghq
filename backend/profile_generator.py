# backend/profile_generator.py
# Turns an uploaded resume (+ what the candidate is looking for) into a
# dense, fact-rich "your profile" blurb for the outreach/inbound message
# generators.
#
# Why this exists: a hand-typed profile preset is only as good as what the
# person remembers to include, and message generation kept failing on
# generic candidate-side connections precisely because presets tended to
# be thin summaries ("PM intern, looking for APM roles") rather than the
# specific numbers/projects/systems that actually let a message find a
# real, non-generic tie to a company (see CRED vs Innov8 -- the difference
# between a passing and failing connection was exactly this kind of
# specificity). The resume already has those specifics; this extracts them
# into the same profile-blurb shape the rest of the app already expects,
# instead of asking the person to re-transcribe their own resume by hand.

import os
from openai import OpenAI

# Below this many characters, the parsed resume is almost certainly a
# near-empty PDF or a parsing failure, not a real (if short) resume --
# worth a warning to the caller either way, but not worth blocking on.
MIN_RESUME_CHARS = 400


def _get_groq_client() -> OpenAI:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("Groq API key not found. Set GROQ_API_KEY in your .env file.")
    return OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")


def generate_profile_from_resume(resume_text: str, preferences: str = "") -> dict:
    """
    Generates a dense, fact-rich profile blurb from resume text, for use as
    a saved preset in the outreach/inbound message generators.

    Returns {"profile": str, "thin_resume": bool}. thin_resume=True is a
    signal for the caller to surface a "this might be too sparse" warning
    -- it does NOT block generation. A short resume might still be usable,
    and the human reviews/edits the result before saving it as a preset
    anyway, same as everywhere else in this app.

    Raises ValueError if GROQ_API_KEY isn't set.
    """
    thin_resume = len(resume_text.strip()) < MIN_RESUME_CHARS

    client = _get_groq_client()

    system_prompt = (
        "You extract a candidate's professional profile from their resume, for use by "
        "a downstream tool that writes cold outreach messages to companies. The single "
        "biggest failure mode of that downstream tool is generating connections that are "
        "generic -- built on vague competency labels ('cross-functional', 'leadership', "
        "'data-driven', 'diverse groups') instead of concrete, specific facts. Your job is "
        "to prevent that by writing a profile dense with the SPECIFIC, CONCRETE details "
        "the resume actually contains.\n\n"
        "RULES:\n"
        "- Only include facts explicitly present in the resume text given. Never invent, "
        "estimate, or round up numbers, projects, or skills not stated.\n"
        "- Prioritise concrete specifics over competency labels: exact numbers/metrics, "
        "named systems or projects the candidate actually built or ran, specific tools or "
        "domains worked in, specific problems solved -- not generic descriptors of what "
        "kind of person they are.\n"
        "- Never use generic filler words: 'synergy', 'cross-functional', 'innovative', "
        "'results-driven', 'hardworking', 'passionate', 'dynamic', 'diverse groups'.\n"
        "- Write in first person.\n"
        "- Structure: (1) current status/role in one line, (2) 3-6 specific achievements "
        "or projects, each with its real number or concrete detail attached, (3) one line "
        "at the end on the kind of role/company being targeted, using the preferences "
        "given.\n"
        "- Length: dense but readable, roughly 120-220 words. This will be read by another "
        "AI model looking for connections, not a human skimming for vibes -- specificity "
        "matters more than polish.\n\n"
        "Respond with ONLY the profile text. No headers, no preamble, no markdown."
    )

    user_prompt = f"""RESUME TEXT:
{resume_text}

WHAT THEY'RE LOOKING FOR: {preferences or "Not specified -- infer from resume if possible, otherwise leave general."}

Write the profile now."""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    profile_text = response.choices[0].message.content.strip()

    return {"profile": profile_text, "thin_resume": thin_resume}
