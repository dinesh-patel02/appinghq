# backend/api_keys.py
# Centralized "bring your own key" prompts. Any tool that needs an LLM or
# search call checks for its key right before using it:
#
#     if not require_groq_key():
#         st.stop()
#
# If the key is already set, this is a no-op and execution continues past
# it. If not, it pops a modal asking the user to paste one, saves it to
# os.environ for the rest of the session, and reruns -- so the code below
# the check can just assume os.getenv("GROQ_API_KEY") is populated.

import os
import streamlit as st


@st.dialog("Add your Groq API key")
def _groq_key_dialog():
    st.write(
        "This feature needs an **LLM API key** to run -- it's what actually "
        "generates the analysis. Since this is a personal project, I can't "
        "host everyone on my own key, so you'll need to bring your own. "
        "It's free and takes under a minute."
    )
    st.markdown(
        "**How to get one:**\n"
        "1. Go to [console.groq.com/keys](https://console.groq.com/keys) and sign in (Google/GitHub works).\n"
        "2. Click **Create API Key**, give it any name.\n"
        "3. Copy the key (starts with `gsk_`) and paste it below."
    )
    key = st.text_input("Groq API key", type="password", key="_groq_dialog_input")
    if st.button("Save and continue", use_container_width=True, type="primary"):
        cleaned = key.strip()  # trailing space/newline from copy-paste silently breaks the key
        if not cleaned:
            st.error("Paste a key first.")
        else:
            os.environ["GROQ_API_KEY"] = cleaned
            st.rerun()


@st.dialog("Add your Tavily API key")
def _tavily_key_dialog():
    st.write(
        "Auto-researching a company needs a **web search API key** (Tavily). "
        "Since this is a personal project, I can't host everyone on my own "
        "key, so you'll need to bring your own -- or just close this and "
        "fill in the company context fields manually instead."
    )
    st.markdown(
        "**How to get one:**\n"
        "1. Go to [tavily.com](https://tavily.com) and sign up (free, 1,000 searches/month).\n"
        "2. Your API key is shown on your dashboard right after signup.\n"
        "3. Copy the key (starts with `tvly-`) and paste it below."
    )
    key = st.text_input("Tavily API key", type="password", key="_tavily_dialog_input")
    if st.button("Save and continue", use_container_width=True, type="primary"):
        cleaned = key.strip()
        if not cleaned:
            st.error("Paste a key first.")
        else:
            os.environ["TAVILY_API_KEY"] = cleaned
            st.rerun()


def require_groq_key() -> bool:
    """True if a Groq key is already set. Otherwise opens the prompt
    dialog and returns False -- callers should st.stop() right after,
    since the rest of the page shouldn't render behind the modal."""
    if os.getenv("GROQ_API_KEY"):
        return True
    _groq_key_dialog()
    return False


def require_tavily_key() -> bool:
    """Same pattern as require_groq_key(), for the optional
    Tavily-powered company research step."""
    if os.getenv("TAVILY_API_KEY"):
        return True
    _tavily_key_dialog()
    return False
