"""
fresh_conversions_dashboard.py

Daily "fresh conversions" dashboard — contacts that were called for the first
time AND merged on the same calendar day, for a specific agent.

Usage:
    streamlit run fresh_conversions_dashboard.py
"""

import ast
from datetime import datetime, date, timedelta

import pandas as pd
import streamlit as st
from pymongo import MongoClient

# ── Config ─────────────────────────────────────────────────────────────────────

MONGODB_URL = st.secrets["fresh_conversions"]["uri"]
AGENT_ID = "d6bb22ee-d3d0-4e0a-8e5f-67d58bdc759d"

st.set_page_config(page_title="Fresh Conversions", layout="wide")
st.title("Fresh Conversions Dashboard")

# ── Helpers ────────────────────────────────────────────────────────────────────

def parse_dt(s):
    s = str(s)[:26]
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

def parse_metadata(rm):
    if isinstance(rm, dict):
        return rm
    try:
        return ast.literal_eval(str(rm))
    except Exception:
        return {}

# ── Data fetch ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Fetching contact overview from MongoDB…")
def fetch_tab3_data(start_iso: str, end_iso: str) -> pd.DataFrame:
    """
    One row per contact whose first-ever call happened within the date range.
    Also records whether they had any merge event within the range.
    """
    start_date = datetime.fromisoformat(start_iso)
    end_date   = datetime.fromisoformat(end_iso)

    client     = MongoClient(MONGODB_URL)
    collection = client["call_queue"]["phone_calls"]

    docs = collection.find(
        {"agent_id": AGENT_ID},
        {"contact_id": 1, "call_attempts_log": 1, "_id": 0},
    )

    rows = []
    for doc in docs:
        attempts = doc.get("call_attempts_log", [])

        all_times = [parse_dt(a.get("start_time", "")) for a in attempts]
        all_times = [t for t in all_times if t]
        if not all_times:
            continue
        first_call = min(all_times)

        # Only include contacts whose first-ever call is in the range
        if not (start_date <= first_call <= end_date):
            continue

        # Find the earliest merge event in the range (if any)
        merge_times = [
            parse_dt(a.get("merge_time", ""))
            for a in attempts
            if a.get("merge_time")
        ]
        merge_times = [t for t in merge_times if t and start_date <= t <= end_date]
        first_merge = min(merge_times) if merge_times else None

        rows.append({
            "contact_id":       doc.get("contact_id", ""),
            "first_call_date":  first_call.date(),
            "first_merge_date": first_merge.date() if first_merge else None,
        })

    client.close()

    return pd.DataFrame(rows)

@st.cache_data(ttl=300, show_spinner="Fetching fresh contact totals from MongoDB…")
def fetch_fresh_totals(start_iso: str, end_iso: str) -> dict:
    """Return {date: count} of all contacts whose first-ever call happened on each day."""
    start_date = datetime.fromisoformat(start_iso)
    end_date   = datetime.fromisoformat(end_iso)

    client     = MongoClient(MONGODB_URL)
    collection = client["call_queue"]["phone_calls"]

    docs = collection.find(
        {"agent_id": AGENT_ID},
        {"call_attempts_log": 1, "_id": 0},
    )

    totals: dict = {}
    for doc in docs:
        attempts  = doc.get("call_attempts_log", [])
        all_times = [parse_dt(a.get("start_time", "")) for a in attempts]
        all_times = [t for t in all_times if t]
        if not all_times:
            continue
        first = min(all_times)
        if start_date <= first <= end_date:
            d = first.date()
            totals[d] = totals.get(d, 0) + 1

    client.close()
    return totals


@st.cache_data(ttl=300, show_spinner="Fetching data from MongoDB…")
def fetch_data(start_iso: str, end_iso: str) -> pd.DataFrame:
    start_date = datetime.fromisoformat(start_iso)
    end_date   = datetime.fromisoformat(end_iso)

    client     = MongoClient(MONGODB_URL)
    collection = client["call_queue"]["phone_calls"]

    docs = collection.find(
        {"agent_id": AGENT_ID, "result": "converted"},
        {"contact_id": 1, "call_attempts_log": 1, "_id": 0},
    )

    rows = []
    for doc in docs:
        attempts = doc.get("call_attempts_log", [])
        converted = next((a for a in attempts if a.get("result") == "converted"), None)
        if not converted:
            continue

        conv_time = parse_dt(converted.get("start_time", ""))
        if not conv_time or not (start_date <= conv_time <= end_date):
            continue

        merge_time = converted.get("merge_time")
        metadata   = parse_metadata(converted.get("result_metadata", {}))
        if not merge_time:
            merge_time = metadata.get("%merge_time%", "")
        if not merge_time:
            continue

        all_times = [parse_dt(a.get("start_time", "")) for a in attempts]
        all_times = [t for t in all_times if t]
        if not all_times:
            continue
        first_attempt = min(all_times)

        if first_attempt.date() != conv_time.date():
            continue

        rows.append({
            "contact_full_name":    metadata.get("contact_full_name", ""),
            "contact_id":           doc.get("contact_id", ""),
            "first_call_attempt":   first_attempt,
            "connecting_call_time": conv_time,
            "merge_time":           merge_time,
            "date":                 conv_time.date(),
        })

    client.close()

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("connecting_call_time", ascending=False).reset_index(drop=True)
    return df

# ── Sidebar controls ───────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Filters")
    date_from = st.date_input("From", value=date(2026, 1, 1), max_value=date.today())
    date_to   = st.date_input("To",   value=date.today(),     max_value=date.today())
    pull      = st.button("Pull Data", type="primary", use_container_width=True)

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame()

if pull:
    start_iso = datetime(date_from.year, date_from.month, date_from.day).isoformat()
    end_iso   = datetime(date_to.year,   date_to.month,   date_to.day, 23, 59, 59).isoformat()
    st.session_state.df            = fetch_data(start_iso, end_iso)
    st.session_state.fresh_totals  = fetch_fresh_totals(start_iso, end_iso)
    st.session_state.tab3_data     = fetch_tab3_data(start_iso, end_iso)

df = st.session_state.df

if df.empty:
    st.info("Select a date range and click **Pull Data** to load results.")
    st.stop()

# ── Tabs ───────────────────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs(["Individual Contacts", "Daily Summary", "First-Time Merges"])

with tab1:
    st.subheader(f"Fresh conversions — {len(df)} contacts")
    display = df.drop(columns=["date"]).copy()
    display["first_call_attempt"]   = display["first_call_attempt"].astype(str)
    display["connecting_call_time"] = display["connecting_call_time"].astype(str)
    st.dataframe(display, use_container_width=True, height=600)

with tab2:
    fresh_totals = st.session_state.get("fresh_totals", {})

    daily = (
        df.groupby("date")
          .size()
          .reset_index(name="fresh_conversions")
          .sort_values("date", ascending=False)
    )
    daily["total_fresh_contacts"] = daily["date"].map(
        lambda d: fresh_totals.get(d, 0)
    )
    daily = daily[["date", "total_fresh_contacts", "fresh_conversions"]]
    daily["date"] = daily["date"].astype(str)

    st.subheader("Fresh conversions per day")
    st.dataframe(daily, use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    col1.metric("Total fresh contacts", int(daily["total_fresh_contacts"].sum()))
    col2.metric("Total fresh conversions", int(daily["fresh_conversions"].sum()))

with tab3:
    t3 = st.session_state.get("tab3_data", pd.DataFrame())

    if t3.empty:
        st.info("No data found for the selected range.")
    else:
        total_created    = len(t3)
        total_with_merge = t3["first_merge_date"].notna().sum()

        col1, col2 = st.columns(2)
        col1.metric("Unique contacts created", total_created)
        col2.metric("Of those — had a merge event", int(total_with_merge))

        st.markdown("---")

        # Monthly breakdown grouped by month of first call
        t3["month"] = pd.to_datetime(t3["first_call_date"]).dt.to_period("M")
        monthly = (
            t3.groupby("month")
              .agg(
                  contacts_created  = ("contact_id", "count"),
                  contacts_merged   = ("first_merge_date", lambda x: x.notna().sum()),
              )
              .reset_index()
              .sort_values("month", ascending=False)
        )
        monthly["month"] = monthly["month"].astype(str)

        st.subheader("Monthly breakdown")
        st.dataframe(monthly, use_container_width=True, hide_index=True)
