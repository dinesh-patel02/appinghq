# utils.py
# Small helper functions used across the app


def get_score_color(score: int) -> str:
    """Return a color hex code based on match score for UI display."""
    if score >= 80:
        return "#2c2c2a"   # dark neutral (grayscale phase)
    elif score >= 60:
        return "#5f5e5a"
    elif score >= 40:
        return "#888780"
    else:
        return "#b4b2a9"


def truncate_text(text: str, max_chars: int = 200) -> str:
    """Truncate long text for display."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(' ', 1)[0] + "..."


def validate_inputs(resume_text: str, job_description: str) -> tuple[bool, str]:
    """Validate that inputs are usable before running analysis."""
    if not resume_text or len(resume_text.strip()) < 100:
        return False, "Resume text is too short or empty. Please upload a valid PDF resume."
    if not job_description or len(job_description.strip()) < 50:
        return False, "Job description is too short. Please paste the full job description."
    if len(job_description) > 10000:
        return False, "Job description is too long. Please paste a shorter version (under 10,000 characters)."
    return True, ""
