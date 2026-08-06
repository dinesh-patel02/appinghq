# backend/db.py
# Supabase connection + generic per-user load/save helpers, replacing the
# local-CSV storage outreach.py and inbound_tracker.py used to use.
#
# Why this exists: outreach_data.csv / inbound_data.csv worked fine
# locally, but Streamlit-hosting free tiers (Streamlit Community Cloud,
# Hugging Face Spaces) don't guarantee filesystem persistence -- a
# redeploy, restart, or sleep/wake cycle can silently wipe local files.
# Supabase (Postgres) gives real persistence, plus much faster
# read/write than the Google-Sheets alternative would (no per-call API
# round trip the way analytics.py's append_row has).
#
# Connects with the SECRET / service_role key, not the publishable/anon
# key -- this is a server-side app (Streamlit runs on the server, not in
# the user's browser), so the secret key is the correct one, and it
# bypasses Row Level Security by design. RLS is still enabled on both
# tables with no policies, so the publishable/anon key -- if ever used
# anywhere by mistake -- gets zero access.
#
# Mirrors the existing per-user CSV pattern exactly: load_data reads only
# this user's rows, save_data deletes this user's existing rows and
# re-inserts the current set, leaving every other user's rows untouched.
# Callers keep using their existing pandas DataFrames with spaced column
# names (e.g. "Company Name") -- this module handles the mapping to/from
# Postgres's snake_case columns, so outreach.py/inbound_tracker.py's
# render() logic doesn't need to change at all.

import pandas as pd
import streamlit as st

_CLIENT = None
_INIT_FAILED = False


def get_client():
    """Lazily connect to Supabase. Cached for the process lifetime, same
    pattern as analytics.py's _get_sheet()."""
    global _CLIENT, _INIT_FAILED

    if _CLIENT is not None:
        return _CLIENT
    if _INIT_FAILED:
        return None

    try:
        from supabase import create_client

        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        _CLIENT = create_client(url, key)
        return _CLIENT
    except Exception as e:
        _INIT_FAILED = True
        print(f"[db] failed to connect to Supabase: {e}")
        return None


def load_table(table: str, column_map: dict, user_email: str) -> pd.DataFrame:
    """
    Returns only this user's rows as a DataFrame with the app's existing
    (spaced) column names -- e.g. "Company Name", not "company_name".

    column_map: {app_column_name: db_column_name}, e.g.
        {"Company Name": "company_name", "POC Name": "poc_name", ...}

    Returns an empty DataFrame (with the right columns) if Supabase isn't
    reachable or the user has no rows yet -- callers already handle an
    empty DataFrame as "no entries yet", same as with the CSV.
    """
    app_columns = list(column_map.keys())
    client = get_client()
    if client is None or not user_email:
        return pd.DataFrame(columns=app_columns)

    try:
        db_columns = list(column_map.values())
        resp = (
            client.table(table)
            .select(",".join(db_columns))
            .eq("user_email", user_email)
            .order("id")
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return pd.DataFrame(columns=app_columns)

        df = pd.DataFrame(rows)
        # rename db columns -> app columns, in the app's expected order
        df = df.rename(columns={v: k for k, v in column_map.items()})
        return df.reindex(columns=app_columns).reset_index(drop=True)
    except Exception as e:
        print(f"[db] failed to load {table} for {user_email}: {e}")
        return pd.DataFrame(columns=app_columns)


def save_table(table: str, column_map: dict, user_email: str, df: pd.DataFrame) -> None:
    """
    Persists this user's rows only -- deletes their existing rows in
    `table`, then re-inserts the current set. Every other user's rows are
    untouched (the delete is scoped with .eq("user_email", ...)), same
    guarantee the old CSV read-filter-rewrite pattern gave.

    Silently no-ops if Supabase isn't reachable or user_email is empty,
    same fail-soft behavior as analytics.py -- a save failure here
    shouldn't crash the page the user is actively working in.
    """
    client = get_client()
    if client is None or not user_email:
        return

    try:
        client.table(table).delete().eq("user_email", user_email).execute()

        if df.empty:
            return

        records = []
        for _, row in df.iterrows():
            record = {"user_email": user_email}
            for app_col, db_col in column_map.items():
                value = row.get(app_col, "")
                # Postgres wants plain JSON-serialisable values -- dates /
                # NaN need coercing to str/"" the same way to_csv() used
                # to handle them for free.
                if pd.isna(value):
                    value = ""
                else:
                    value = str(value)
                record[db_col] = value
            records.append(record)

        client.table(table).insert(records).execute()
    except Exception as e:
        print(f"[db] failed to save {table} for {user_email}: {e}")
