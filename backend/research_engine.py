# backend/research_engine.py
# Company research via Tavily (https://tavily.com), used to auto-fill the
# "what does this company do" / "recent news" fields in the message
# generators instead of the user typing them in by hand every time.
#
# Chosen over Serper/Brave/Exa/SerpAPI because Tavily is the only option
# with a free tier that actually renews monthly (1,000 requests) rather
# than a one-time bucket, and it returns pre-summarized, LLM-ready content
# instead of raw SERP HTML that would need its own parsing/summarization
# step. See the pricing comparison worked through in chat for the full
# reasoning -- Brave dropped its free tier in Feb 2026, Serper's free
# quota is one-time not recurring, and Exa is built for semantic/academic
# search, not "what does this startup do."

import os
import requests
import logging

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"


def _get_tavily_key() -> str:
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        raise ValueError(
            "Tavily API key not found. Get a free key at tavily.com "
            "(1,000 free searches/month, no card needed) and set "
            "TAVILY_API_KEY in your .env file."
        )
    return key


def research_company(company_name: str) -> dict:
    """
    Fetches a short overview and recent news for a company, grounded in
    real search results rather than the LLM's own (possibly stale or
    invented) knowledge of the company.

    Returns:
        {
            "overview": str,       # what the company does, 1-3 sentences
            "recent_news": str,    # recent developments, 1-3 sentences
            "sources": [{"title": str, "url": str}, ...],
            "found": bool,         # False if Tavily returned nothing useful
        }

    Raises ValueError if TAVILY_API_KEY isn't set. Network/API errors are
    caught and returned as found=False with an empty result rather than
    raised, since a research failure shouldn't block the user from writing
    a message manually -- it's a convenience layer, not a hard dependency.
    """
    api_key = _get_tavily_key()

    payload = {
        "api_key": api_key,
        "query": f"{company_name} company what they do recent news",
        "search_depth": "basic",
        "include_answer": "advanced",
        "max_results": 5,
    }

    try:
        response = requests.post(TAVILY_URL, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        logger.warning("Tavily research failed for %s: %s", company_name, e)
        return {"overview": "", "recent_news": "", "sources": [], "found": False}

    overview = data.get("answer", "") or ""

    results = data.get("results", [])
    sources = [
        {"title": r.get("title", ""), "url": r.get("url", "")}
        for r in results[:4]
        if r.get("url")
    ]

    # Build a short "recent news" line from the top couple of result
    # snippets -- the "answer" field tends to read as a general overview,
    # so this pulls specific recent-sounding content separately rather
    # than duplicating the same summary in both fields.
    news_snippets = []
    for r in results[:3]:
        content = (r.get("content") or "").strip()
        if content:
            news_snippets.append(content[:220].rsplit(" ", 1)[0] + "...")
    recent_news = " ".join(news_snippets[:2])

    return {
        "overview": overview.strip(),
        "recent_news": recent_news.strip(),
        "sources": sources,
        "found": bool(overview or news_snippets),
    }
