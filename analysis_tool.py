import streamlit as st
import json
import re
import pandas as pd
from datetime import datetime, timezone

st.set_page_config(page_title="Calls Extracted", layout="wide")
st.title("Extracted Call Conversations")

# ── Intent + confidence parser ─────────────────────────────────────────────────
INTENT_RE = re.compile(
    r'detected (?:hard-coded )?intent "([^"]+)" as "[^"]+" ([\d.]+)%'
)

# ── Call datetime parser ───────────────────────────────────────────────────────
_LOG_DT_RE = re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')

def extract_call_datetime(history: dict, items: list) -> datetime | None:
    # Prefer the start timestamp from the first debug log line.
    log = history.get("voice_debug_log") or []
    if log:
        m = _LOG_DT_RE.search(log[0])
        if m:
            return datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
    # Fall back to the earliest last_user_message_timestamp in the items.
    ts = None
    for item in items:
        ds = item.get("director_state") or {}
        t = ds.get("last_user_message_timestamp")
        if t and (ts is None or t < ts):
            ts = t
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None

def parse_intent(log_lines):
    for line in (log_lines or []):
        m = INTENT_RE.search(line)
        if m:
            return m.group(1), float(m.group(2))
    return None, None


# ── Outcome classifier ─────────────────────────────────────────────────────────
# These paths confirm a meeting was successfully scheduled — checked across ALL turns.
_CONFIRMED_SCHEDULING_PATHS = {
    "voice goals end of call/scheduling-via-voice/confirm meeting time",
    "voice goals end of call/scheduling-via-voice/perform scheduling",
    "post scheduling help",
}
_CALLBACK_PATHS = {
    "base_agents/voice_agents/schedule-callback/callback slot",
}
_TRANSFERRED_PATHS = {
    "base_agents/outbound agents/transfer to customer",
}
_VOICEMAIL_PREFIXES = (
    "base_agents/outbound agents/voicemail",
)
_HANGUP_PATHS = {
    "base_agents/voice_agents/hang up",
    "base_agents/voice_agents/hang up - bad number",
}

OUTCOME_EMOJI = {
    "Converted": "✅",
    "Callback Scheduled": "📅",
    "Transferred": "🔀",
    "Voicemail": "📬",
    "Rejection": "🚫",
}


def extract_outcome(items: list) -> tuple[str, str | None]:
    """Returns (outcome, disconnect_stage).

    disconnect_stage is the last meaningful goal before a rejection, used for
    disconnect distribution analysis. None for all other outcomes.
    """
    all_goal_paths = []
    for item in items:
        ds = item.get("director_state") or {}
        lb = ds.get("last_behavior") or {}
        gp = lb.get("goal_path")
        if gp:
            all_goal_paths.append(gp)

    # Conversion wins regardless of what happened after (e.g. polite hang-up).
    if any(gp in _CONFIRMED_SCHEDULING_PATHS for gp in all_goal_paths):
        return "Converted", None

    # Callback scheduled — caller agreed to a callback instead of a meeting.
    if any(gp in _CALLBACK_PATHS for gp in all_goal_paths):
        return "Callback Scheduled", None

    last_goal_path = all_goal_paths[-1] if all_goal_paths else None

    if last_goal_path in _TRANSFERRED_PATHS:
        return "Transferred", None
    if last_goal_path and last_goal_path.startswith(_VOICEMAIL_PREFIXES):
        return "Voicemail", None

    # Everything else with any utterance activity is a rejection — caller either
    # disconnected before scheduling or refused to schedule.
    stage = next(
        (gp for gp in reversed(all_goal_paths) if gp not in _HANGUP_PATHS),
        None,
    )
    return "Rejection", stage


# ── Data loading ───────────────────────────────────────────────────────────────
@st.cache_data
def load_conversations(content: bytes):
    raw = json.loads(content)
    conversations = []
    for agent_name, chats in raw.items():
        for chat in chats:
            chat_id = chat.get("chat_id", "unknown")
            history = chat.get("history", {})
            items = history.get("chat_items", [])

            turns = []
            for item in items:
                speaker = item.get("speaker", "")
                content = item.get("content", "").strip()
                if not content:
                    continue

                intent, confidence, goal = None, None, None
                if speaker == "user":
                    ds = item.get("director_state") or {}
                    lb = ds.get("last_behavior") or {}
                    intent, confidence = parse_intent(lb.get("log", []))
                    goal = lb.get("goal_path") or None

                turns.append({
                    "speaker": speaker,
                    "content": content,
                    "intent": intent,
                    "confidence": confidence,
                    "goal": goal,
                })

            # Skip calls with no utterances — nothing useful to show or analyse.
            if not turns:
                continue

            outcome, disconnect_stage = extract_outcome(items)

            pairs = []
            prev_agent = ""
            i = 0
            while i < len(turns):
                t = turns[i]
                if t["speaker"] == "user":
                    user_text = t["content"]
                    intent = t["intent"]
                    confidence = t["confidence"]
                    goal = t["goal"]
                    agent_text = ""
                    if i + 1 < len(turns) and turns[i + 1]["speaker"] == "assistant":
                        agent_text = turns[i + 1]["content"]
                        i += 2
                    else:
                        i += 1
                    pairs.append({
                        "#": len(pairs) + 1,
                        "Prev Agent": prev_agent or "—",
                        "User": user_text,
                        "Agent": agent_text,
                        "Goal": goal or "—",
                        "Intent": intent or "—",
                        "Confidence": confidence if confidence is not None else "—",
                    })
                    prev_agent = agent_text
                else:
                    if t["content"]:
                        prev_agent = t["content"]
                    i += 1

            conversations.append({
                "chat_id": chat_id,
                "agent": agent_name,
                "pairs": pairs,
                "n_turns": len(turns),
                "outcome": outcome,
                "disconnect_stage": disconnect_stage,
                "call_datetime": extract_call_datetime(history, items),
            })
    return conversations


# ── Load ───────────────────────────────────────────────────────────────────────
uploaded = st.file_uploader("Upload a calls JSON file", type=["json"])
if uploaded is None:
    st.info("Upload a calls export JSON file to begin.")
    st.stop()

try:
    conversations = load_conversations(uploaded.read())
except Exception as e:
    st.error(f"Could not parse file: {e}")
    st.stop()

total = len(conversations)
with_pairs = sum(1 for c in conversations if c["pairs"])
n_converted = sum(1 for c in conversations if c["outcome"] == "Converted")
n_callback = sum(1 for c in conversations if c["outcome"] == "Callback Scheduled")
n_transferred = sum(1 for c in conversations if c["outcome"] == "Transferred")
n_voicemail = sum(1 for c in conversations if c["outcome"] == "Voicemail")
n_rejection = sum(1 for c in conversations if c["outcome"] == "Rejection")
n_cd_calls = sum(
    1 for c in conversations
    if any(p["Goal"] == "base_agents/contact discovery" for p in c["pairs"])
)

col1, = st.columns(1)
col1.metric("Total conversations", total)

col4, col5, col6, col7, col8 = st.columns(5)
col4.metric("✅ Converted", n_converted)
col5.metric("📅 Callback Scheduled", n_callback)
col6.metric("🔀 Transferred", n_transferred)
col7.metric("📬 Voicemail", n_voicemail)
col8.metric("🚫 Rejection", n_rejection)

col9, = st.columns(1)
col9.metric("🔍 Calls with contact discovery", f"{n_cd_calls} ({n_cd_calls / total * 100:.1f}%)" if total else "0")

st.markdown("---")

# ── Collect low-confidence pairs once ─────────────────────────────────────────
low_conf_pairs = []
for conv in conversations:
    for pair in conv["pairs"]:
        conf = pair["Confidence"]
        if isinstance(conf, float) and conf < 1.0:
            low_conf_pairs.append({"chat_id": conv["chat_id"], **pair})

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    "All Conversations",
    f"Low Confidence Pairs ({len(low_conf_pairs)})",
    "Statistics",
])

# ── Tab 1: all conversations ───────────────────────────────────────────────────
with tab1:
    search_col, filter_col = st.columns([3, 1])
    search = search_col.text_input("Search by call ID or utterance content")
    outcome_options = ["All"] + list(OUTCOME_EMOJI.keys()) + ["🔍 Contact Discovery"]
    outcome_filter = filter_col.selectbox("Filter by outcome", outcome_options)

    filtered = conversations
    if outcome_filter == "🔍 Contact Discovery":
        filtered = [c for c in filtered if any(p["Goal"] == "base_agents/contact discovery" for p in c["pairs"])]
    elif outcome_filter != "All":
        filtered = [c for c in filtered if c["outcome"] == outcome_filter]
    if search:
        q = search.lower()
        filtered = [
            c for c in filtered
            if q in c["chat_id"].lower()
            or any(q in p["User"].lower() or q in p["Agent"].lower() for p in c["pairs"])
        ]
    if search or outcome_filter != "All":
        st.caption(f"{len(filtered)} matching conversation(s)")

    for conv in filtered:
        chat_id = conv["chat_id"]
        pairs = conv["pairs"]
        outcome = conv["outcome"]
        emoji = OUTCOME_EMOJI.get(outcome, "❓")
        cd_tag = "  |  🔍 contact discovery" if any(
            p["Goal"] == "base_agents/contact discovery" for p in pairs
        ) else ""
        dt = conv["call_datetime"]
        dt_tag = f"  |  🕐 {dt.strftime('%Y-%m-%d %H:%M')} UTC" if dt else ""
        label = f"{emoji} **{chat_id}**  —  {outcome}{cd_tag}{dt_tag}  |  {conv['n_turns']} turns, {len(pairs)} pair(s)"
        with st.expander(label, expanded=False):
            st.caption(f"Agent: {conv['agent']}  |  Outcome: **{outcome}**")
            if not pairs:
                st.info("No user–agent pairs found (conversation may be empty or agent-only).")
                continue
            st.dataframe(pd.DataFrame(pairs), use_container_width=True, hide_index=True)

# ── Tab 2: low-confidence pairs with review buttons ───────────────────────────
with tab2:
    if not low_conf_pairs:
        st.info("No pairs with confidence below 1.0 found.")
    else:
        st.caption(
            f"{len(low_conf_pairs)} pair(s) with intent confidence < 1.0 across all conversations."
        )

        # Header row
        h0, h1, h2, h3, h4, h5, h6, h7, h8 = st.columns([2, 2, 2, 2, 1.5, 1, 0.8, 1, 1])
        for col, label in zip(
            [h0, h1, h2, h3, h4, h5, h6, h7, h8],
            ["Call ID", "Prev Agent", "User", "Agent", "Goal", "Intent", "Conf.", "", ""],
        ):
            col.markdown(f"**{label}**")
        st.divider()

        for idx, pair in enumerate(low_conf_pairs):
            key = f"review_{idx}"
            if key not in st.session_state:
                st.session_state[key] = None

            c0, c1, c2, c3, c4, c5, c6, c7, c8, c9 = st.columns([2, 2, 2, 2, 1.5, 1, 0.8, 1, 1.2, 1.1])
            c0.write(pair["chat_id"])
            c1.write(pair["Prev Agent"])
            c2.write(pair["User"])
            c3.write(pair["Agent"])
            c4.write(pair["Goal"])
            c5.write(pair["Intent"])
            c6.write(f'{pair["Confidence"]:.2f}')

            if c7.button("✔ Correct",  key=f"{key}_ok",      type="primary"):
                st.session_state[key] = "correct"
            if c8.button("± Partial",  key=f"{key}_partial", type="secondary"):
                st.session_state[key] = "partial"
            if c9.button("✘ Incorrect", key=f"{key}_bad",    type="secondary"):
                st.session_state[key] = "incorrect"

            verdict = st.session_state[key]
            if verdict == "correct":
                st.success("Marked: Correct", icon="✔")
            elif verdict == "partial":
                st.warning("Marked: Partially correct", icon="⚠️")
            elif verdict == "incorrect":
                st.error("Marked: Incorrect", icon="🚫")

            st.divider()

# ── Tab 3: statistics ──────────────────────────────────────────────────────────
with tab3:
    selected_outcomes = st.multiselect(
        "Filter by outcome",
        options=list(OUTCOME_EMOJI.keys()),
        default=list(OUTCOME_EMOJI.keys()),
        format_func=lambda o: f"{OUTCOME_EMOJI[o]} {o}",
    )

    sc = [c for c in conversations if c["outcome"] in selected_outcomes]

    if not sc:
        st.info("No conversations match the selected outcomes.")
    else:
        # ── Build DataFrames ───────────────────────────────────────────────────
        conv_df = pd.DataFrame([
            {"outcome": c["outcome"], "n_turns": c["n_turns"], "n_pairs": len(c["pairs"])}
            for c in sc
        ])

        pair_rows = []
        for c in sc:
            for p in c["pairs"]:
                pair_rows.append({
                    "outcome": c["outcome"],
                    "goal": p["Goal"] if p["Goal"] != "—" else None,
                    "intent": p["Intent"] if p["Intent"] != "—" else None,
                    "confidence": p["Confidence"] if isinstance(p["Confidence"], float) else None,
                })
        pairs_df = pd.DataFrame(pair_rows)

        # ── Summary metrics ────────────────────────────────────────────────────
        n_conv = sum(1 for c in sc if c["outcome"] == "Converted")
        conv_rate = n_conv / len(sc) * 100 if sc else 0
        cd_calls = sum(
            1 for c in sc
            if any(p["Goal"] == "base_agents/contact discovery" for p in c["pairs"])
        )
        cd_utterances = sum(
            1 for c in sc
            for p in c["pairs"]
            if p["Goal"] == "base_agents/contact discovery"
        )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Calls (filtered)", len(sc))
        m2.metric("Avg turns / call", f"{conv_df['n_turns'].mean():.1f}")
        m3.metric("Avg exchanges / call", f"{conv_df['n_pairs'].mean():.1f}")
        m4.metric("Conversion rate", f"{conv_rate:.1f}%")

        m5, m6 = st.columns(2)
        m5.metric("🔍 Calls with contact discovery", f"{cd_calls} ({cd_calls / len(sc) * 100:.1f}%)")
        m6.metric("🔍 Contact discovery utterances", cd_utterances)

        st.markdown("---")

        # ── Outcome distribution + call length histogram ───────────────────────
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**Outcome distribution**")
            outcome_counts = (
                conv_df["outcome"]
                .value_counts()
                .rename_axis("Outcome")
                .reset_index(name="Calls")
                .set_index("Outcome")
            )
            st.bar_chart(outcome_counts)

        with col2:
            st.markdown("**Call length distribution (turns)**")
            bins = pd.cut(conv_df["n_turns"], bins=10)
            bin_counts = (
                bins.value_counts()
                .sort_index()
                .rename_axis("Turns")
                .reset_index(name="Calls")
                .assign(Turns=lambda df: df["Turns"].astype(str))
                .set_index("Turns")
            )
            st.bar_chart(bin_counts)

        st.markdown("---")

        # ── Goal path frequency ────────────────────────────────────────────────
        st.markdown("**Top goal paths (across all turns)**")
        goal_counts = (
            pairs_df["goal"]
            .dropna()
            .value_counts()
            .head(15)
            .rename_axis("Goal")
            .reset_index(name="Occurrences")
            .set_index("Goal")
        )
        if goal_counts.empty:
            st.info("No goal data for the selected outcomes.")
        else:
            st.bar_chart(goal_counts)

        st.markdown("---")

        # ── Intent distribution + confidence distribution ──────────────────────
        col3, col4 = st.columns(2)

        with col3:
            st.markdown("**Top intents**")
            intent_counts = (
                pairs_df["intent"]
                .dropna()
                .value_counts()
                .head(15)
                .rename_axis("Intent")
                .reset_index(name="Occurrences")
                .set_index("Intent")
            )
            if intent_counts.empty:
                st.info("No intent data for the selected outcomes.")
            else:
                st.bar_chart(intent_counts)

        with col4:
            st.markdown("**Confidence score distribution**")
            conf_series = pairs_df["confidence"].dropna()
            if conf_series.empty:
                st.info("No confidence data for the selected outcomes.")
            else:
                conf_bins = pd.cut(conf_series, bins=[0, 0.5, 0.7, 0.85, 0.95, 1.0],
                                   labels=["0–0.5", "0.5–0.7", "0.7–0.85", "0.85–0.95", "0.95–1.0"])
                conf_counts = (
                    conf_bins.value_counts()
                    .sort_index()
                    .rename_axis("Confidence")
                    .reset_index(name="Pairs")
                    .set_index("Confidence")
                )
                st.bar_chart(conf_counts)

        st.markdown("---")

        # ── Avg turns by outcome (only useful when multiple outcomes selected) ─
        if len(selected_outcomes) > 1:
            st.markdown("**Average turns by outcome**")
            avg_by_outcome = (
                conv_df.groupby("outcome")["n_turns"]
                .mean()
                .round(1)
                .rename_axis("Outcome")
                .reset_index(name="Avg Turns")
                .set_index("Outcome")
            )
            st.bar_chart(avg_by_outcome)

        st.markdown("---")

        # ── Disconnect stage distribution (rejection calls only) ─────────────
        st.markdown("**🚫 Where in the call did rejections happen?**")
        rejection_calls = [c for c in sc if c["outcome"] == "Rejection"]
        if not rejection_calls:
            st.info("No rejection calls in the selected outcomes.")
        else:
            col5, col6 = st.columns(2)

            with col5:
                st.caption("Last goal reached before rejection")
                stage_counts = (
                    pd.Series(
                        [c["disconnect_stage"] or "No goal recorded" for c in rejection_calls],
                        name="Stage",
                    )
                    .value_counts()
                    .rename_axis("Goal at Rejection")
                    .reset_index(name="Calls")
                    .set_index("Goal at Rejection")
                )
                st.bar_chart(stage_counts)

            with col6:
                st.caption("Number of exchanges before rejection")
                rejection_df = pd.DataFrame(
                    [{"n_pairs": len(c["pairs"])} for c in rejection_calls]
                )
                bins = pd.cut(rejection_df["n_pairs"], bins=max(1, min(10, len(rejection_calls) // 2)))
                bin_counts = (
                    bins.value_counts()
                    .sort_index()
                    .rename_axis("Exchanges")
                    .reset_index(name="Calls")
                    .assign(Exchanges=lambda df: df["Exchanges"].astype(str))
                    .set_index("Exchanges")
                )
                st.bar_chart(bin_counts)
