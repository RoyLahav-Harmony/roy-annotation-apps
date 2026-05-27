# ══════════════════════════════════════════════════════════════════════════════
# analysis_tool_explained.py
# Annotated version of analysis_tool.py for documentation purposes.
# ══════════════════════════════════════════════════════════════════════════════

# Standard library and third-party imports.
import math
import random
import streamlit as st   # The web app framework — every 'st.' call renders something in the browser.
import json
import re
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone

# Set the browser tab title and use the full screen width.
st.set_page_config(page_title="Analysis Tool", layout="wide")
st.title("Extracted Call Conversations")

# ── Global CSS tweak ──────────────────────────────────────────────────────────
# Makes the small label text above metric cards larger so they're easier to read.
st.markdown("""
<style>
[data-testid="stMetricLabel"] p,
[data-testid="stMetricLabel"] label,
[data-testid="stMetricLabel"] div {
    font-size: 1.8rem !important;
    font-weight: 500 !important;
}
</style>
""", unsafe_allow_html=True)


# ── Bar chart helper ──────────────────────────────────────────────────────────
# Builds a Plotly bar chart where each bar also shows its count and % of total.
# Used throughout the Statistics tab for all distributions.
def pct_bar(labels, values, y_title="Calls", height=350):
    total = sum(values)
    # Format each bar label as "count  (X.X%)"
    text = [f"{v}  ({v / total * 100:.1f}%)" if total else str(v) for v in values]
    fig = go.Figure(go.Bar(
        x=labels, y=values,
        text=text, textposition="inside",
        textfont={"color": "black", "size": 26},
    ))
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        height=height,
        yaxis_title=y_title,
    )
    return fig


# ── Intent confidence regex ───────────────────────────────────────────────────
# Matches log lines like:
#   "(~0.01) detected intent "%sorry_what%" as "Sorry, what?" 0.93%"
# Captures: group(1) = intent slug, group(2) = confidence value (e.g. "0.93")
INTENT_RE = re.compile(
    r'detected (?:hard-coded )?intent "([^"]+)" as "[^"]+" ([\d.]+)%'
)

# Regex to extract a datetime string from the first line of the voice_debug_log.
_LOG_DT_RE = re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')


def extract_call_datetime(history: dict, items: list) -> datetime | None:
    """
    Try to find the actual start time of the call.
    First choice: the first line of the voice_debug_log, which contains a timestamp.
    Fallback: the earliest last_user_message_timestamp across all chat items.
    """
    log = history.get("voice_debug_log") or []
    if log:
        m = _LOG_DT_RE.search(log[0])
        if m:
            return datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
    # Walk all items to find the earliest timestamp if the log didn't have one.
    ts = None
    for item in items:
        ds = item.get("director_state") or {}
        t = ds.get("last_user_message_timestamp")
        if t and (ts is None or t < ts):
            ts = t
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


def parse_intent(log_lines):
    """
    Scan the log lines for a user turn and return (intent, confidence).
    Stops at the FIRST matching line — usually the most recent detection.
    Returns (None, None) if no matching line is found.
    """
    for line in (log_lines or []):
        m = INTENT_RE.search(line)
        if m:
            return m.group(1), float(m.group(2))
    return None, None


# ── Outcome classifier — goal path constants ──────────────────────────────────
# These sets contain the goal_path values that identify each outcome.
# A "goal_path" is a string path in the agent's script tree that shows
# which script node the agent was executing at any given moment.

# Any of these paths appearing anywhere in the call = meeting was booked.
_CONFIRMED_SCHEDULING_PATHS = {
    "voice goals end of call/scheduling-via-voice/confirm meeting time",
    "voice goals end of call/scheduling-via-voice/perform scheduling",
    "post scheduling help",
}
# The caller agreed to receive a callback instead of scheduling now.
_CALLBACK_PATHS = {
    "base_agents/voice_agents/schedule-callback/callback slot",
}
# The call was transferred to a human agent.
_TRANSFERRED_PATHS = {
    "base_agents/outbound agents/transfer to customer",
}
# Any goal_path starting with this prefix = agent left a voicemail.
_VOICEMAIL_PREFIXES = (
    "base_agents/outbound agents/voicemail",
)
# These are polite hang-up paths — excluded when finding the last meaningful goal.
_HANGUP_PATHS = {
    "base_agents/voice_agents/hang up",
    "base_agents/voice_agents/hang up - bad number",
}

# Emoji displayed next to each outcome label in the UI.
OUTCOME_EMOJI = {
    "Converted": "✅",
    "Callback Scheduled": "📅",
    "Transferred": "🔀",
    "Voicemail": "📬",
    "Rejection": "🚫",
}


def extract_outcome(items: list) -> tuple[str, str | None]:
    """
    Determine the final outcome of a call by scanning all goal_paths.
    Returns (outcome_label, disconnect_stage).

    - outcome_label: one of the five outcomes above.
    - disconnect_stage: for Rejections only — the last meaningful goal reached
      before the call ended (used in the Statistics tab disconnect chart).
    """
    # Collect every goal_path seen across all turns in this conversation.
    all_goal_paths = []
    for item in items:
        ds = item.get("director_state") or {}
        lb = ds.get("last_behavior") or {}
        gp = lb.get("goal_path")
        if gp:
            all_goal_paths.append(gp)

    # Check for conversion first — it wins even if a hang-up happened afterwards.
    if any(gp in _CONFIRMED_SCHEDULING_PATHS for gp in all_goal_paths):
        return "Converted", None

    if any(gp in _CALLBACK_PATHS for gp in all_goal_paths):
        return "Callback Scheduled", None

    # For the remaining outcomes, only the LAST goal_path matters.
    last_goal_path = all_goal_paths[-1] if all_goal_paths else None

    if last_goal_path in _TRANSFERRED_PATHS:
        return "Transferred", None
    if last_goal_path and last_goal_path.startswith(_VOICEMAIL_PREFIXES):
        return "Voicemail", None

    # Everything else is a Rejection.
    # Find the last meaningful goal (ignoring hang-up paths) for the disconnect chart.
    stage = next(
        (gp for gp in reversed(all_goal_paths) if gp not in _HANGUP_PATHS),
        None,
    )
    return "Rejection", stage


# ── Data loading ──────────────────────────────────────────────────────────────
# @st.cache_data means this function only runs once per unique file upload.
# If the same file is uploaded again, Streamlit returns the cached result.
@st.cache_data
def load_conversations(content: bytes):
    """
    Parse the uploaded JSON file and return a list of conversation dicts.

    Input JSON structure:
      { "agent_name": [ { "chat_id": "...", "history": { "chat_items": [...] } }, ... ] }

    Each chat_item has:
      - "speaker": "user" or "assistant"
      - "content": the utterance text
      - "director_state": internal agent state, including last_behavior → log (for confidence)
    """
    raw = json.loads(content)
    conversations = []

    # Top level is a dict keyed by agent name, each value is a list of chats.
    for agent_name, chats in raw.items():
        for chat in chats:
            chat_id = chat.get("chat_id", "unknown")
            history = chat.get("history", {})
            items = history.get("chat_items", [])

            # Build a flat list of turns, skipping any item with empty content.
            turns = []
            for item in items:
                speaker = item.get("speaker", "")
                content = item.get("content", "").strip()
                if not content:
                    continue  # Skip silent turns (e.g. immediate hangups)

                intent, confidence, goal = None, None, None
                if speaker == "user":
                    # Only user turns carry intent/confidence data.
                    # director_state → last_behavior → log contains the detection lines.
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

            # If a call had no audible speech at all, skip it entirely.
            if not turns:
                continue

            outcome, disconnect_stage = extract_outcome(items)

            # Build "pairs": each pair = one user turn + the agent turn that follows it.
            # Also track the previous agent turn so it can be shown in the review dataset.
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
                    # Peek ahead: if the next turn is the agent responding, grab it.
                    if i + 1 < len(turns) and turns[i + 1]["speaker"] == "assistant":
                        agent_text = turns[i + 1]["content"]
                        i += 2  # Consumed both the user and agent turn.
                    else:
                        i += 1
                    pairs.append({
                        "#": len(pairs) + 1,        # Turn number within this conversation.
                        "Prev Agent": prev_agent or "—",
                        "User": user_text,
                        "Agent": agent_text,
                        "Goal": goal or "—",
                        "Intent": intent or "—",
                        "Confidence": confidence if confidence is not None else "—",
                    })
                    prev_agent = agent_text
                else:
                    # Agent-only turn (no preceding user message) — just track it as prev.
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


# ── File upload ───────────────────────────────────────────────────────────────
# st.stop() halts execution below this point until the user provides a file.
uploaded = st.file_uploader("Upload a calls JSON file", type=["json"])
if uploaded is None:
    st.info("Upload a calls export JSON file to begin.")
    st.stop()

# Parse the file. If it's malformed JSON, show an error and stop.
try:
    conversations = load_conversations(uploaded.read())
except Exception as e:
    st.error(f"Could not parse file: {e}")
    st.stop()

# ── Summary counts for the header metrics ─────────────────────────────────────
total = len(conversations)
with_pairs = sum(1 for c in conversations if c["pairs"])
n_converted  = sum(1 for c in conversations if c["outcome"] == "Converted")
n_callback   = sum(1 for c in conversations if c["outcome"] == "Callback Scheduled")
n_transferred= sum(1 for c in conversations if c["outcome"] == "Transferred")
n_voicemail  = sum(1 for c in conversations if c["outcome"] == "Voicemail")
n_rejection  = sum(1 for c in conversations if c["outcome"] == "Rejection")
# Contact Discovery = calls where the agent attempted to find out the contact name.
n_cd_calls = sum(
    1 for c in conversations
    if any(p["Goal"] == "base_agents/contact discovery" for p in c["pairs"])
)

# Display the metrics in a row across the top.
col1, = st.columns(1)
col1.metric("Total conversations", total)

col4, col5, col6, col7, col8 = st.columns(5)
col4.metric("✅ Converted",           n_converted)
col5.metric("📅 Callback Scheduled",  n_callback)
col6.metric("🔀 Transferred",         n_transferred)
col7.metric("📬 Voicemail",           n_voicemail)
col8.metric("🚫 Rejection",           n_rejection)

col9, = st.columns(1)
col9.metric("🔍 Calls with contact discovery", f"{n_cd_calls} ({n_cd_calls / total * 100:.1f}%)" if total else "0")

st.markdown("---")

# ── Pre-compute confidence buckets ────────────────────────────────────────────
# Split all pairs across all conversations into low-confidence (< 1.0)
# and high-confidence (exactly 1.0). Used in both the Low Confidence tab
# and the Review Dataset tab.
low_conf_pairs  = []
high_conf_pairs = []
for conv in conversations:
    for pair in conv["pairs"]:
        conf = pair["Confidence"]
        if isinstance(conf, float):
            tagged = {"chat_id": conv["chat_id"], **pair}
            if conf < 1.0:
                low_conf_pairs.append(tagged)
            elif conf == 1.0:
                high_conf_pairs.append(tagged)

# ── Session state initialisation ──────────────────────────────────────────────
# Pre-populate all review keys so that switching tabs doesn't reset them.
# setdefault only writes if the key doesn't already exist.
for idx in range(len(low_conf_pairs)):
    st.session_state.setdefault(f"review_{idx}", None)
st.session_state.setdefault("review_seed", 42)

# ── Tab navigation ────────────────────────────────────────────────────────────
# Streamlit's native st.tabs resets on first interaction, so we use a radio
# button as a manual tab bar instead. The selected value is stored in
# session_state under "active_tab".
TAB_NAMES = [
    "All Conversations",
    f"Low Confidence Pairs ({len(low_conf_pairs)})",
    "Statistics",
    "Review Dataset",
]
st.session_state.setdefault("active_tab", TAB_NAMES[0])

active_tab = st.radio(
    "nav", TAB_NAMES,
    horizontal=True,
    label_visibility="collapsed",
    key="active_tab",
)
st.markdown("---")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — All Conversations
# Shows every conversation in a searchable, filterable list.
# Each conversation is collapsed by default; click to expand and see the table.
# ══════════════════════════════════════════════════════════════════════════════
if active_tab == TAB_NAMES[0]:
    search_col, filter_col = st.columns([3, 1])
    search = search_col.text_input("Search by call ID or utterance content")
    outcome_options = ["All"] + list(OUTCOME_EMOJI.keys()) + ["🔍 Contact Discovery"]
    outcome_filter = filter_col.selectbox("Filter by outcome", outcome_options)

    filtered = conversations
    # Apply outcome filter first.
    if outcome_filter == "🔍 Contact Discovery":
        filtered = [c for c in filtered if any(p["Goal"] == "base_agents/contact discovery" for p in c["pairs"])]
    elif outcome_filter != "All":
        filtered = [c for c in filtered if c["outcome"] == outcome_filter]
    # Then apply text search across chat_id and all user/agent utterances.
    if search:
        q = search.lower()
        filtered = [
            c for c in filtered
            if q in c["chat_id"].lower()
            or any(q in p["User"].lower() or q in p["Agent"].lower() for p in c["pairs"])
        ]
    if search or outcome_filter != "All":
        st.caption(f"{len(filtered)} matching conversation(s)")

    # Each conversation is a collapsible expander showing outcome, timestamp, and pairs table.
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


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Low Confidence Pairs
# Lists every user–agent exchange where the intent confidence was below 1.0.
# Reviewers can mark each pair as Correct, Partial, or Incorrect.
# These marks are stored in session_state but NOT exported from this tab.
# ══════════════════════════════════════════════════════════════════════════════
if active_tab == TAB_NAMES[1]:
    if not low_conf_pairs:
        st.info("No pairs with confidence below 1.0 found.")
    else:
        st.caption(
            f"{len(low_conf_pairs)} pair(s) with intent confidence < 1.0 across all conversations."
        )

        # Render a manual header row to label the columns.
        h0, h1, h2, h3, h4, h5, h6, h7, h8 = st.columns([2, 2, 2, 2, 1.5, 1, 0.8, 1, 1])
        for col, label in zip(
            [h0, h1, h2, h3, h4, h5, h6, h7, h8],
            ["Call ID", "Prev Agent", "User", "Agent", "Goal", "Intent", "Conf.", "", ""],
        ):
            col.markdown(f"**{label}**")
        st.divider()

        for idx, pair in enumerate(low_conf_pairs):
            key = f"review_{idx}"
            # Each pair gets 10 columns: data fields + 3 action buttons.
            c0, c1, c2, c3, c4, c5, c6, c7, c8, c9 = st.columns([2, 2, 2, 2, 1.5, 1, 0.8, 1, 1.2, 1.1])
            c0.write(pair["chat_id"])
            c1.write(pair["Prev Agent"])
            c2.write(pair["User"])
            c3.write(pair["Agent"])
            c4.write(pair["Goal"])
            c5.write(pair["Intent"])
            c6.write(f'{pair["Confidence"]:.2f}')

            # Buttons store the verdict in session_state using a unique key per row.
            if c7.button("✔ Correct",   key=f"{key}_ok",      type="primary"):
                st.session_state[key] = "correct"
            if c8.button("± Partial",   key=f"{key}_partial", type="secondary"):
                st.session_state[key] = "partial"
            if c9.button("✘ Incorrect", key=f"{key}_bad",     type="secondary"):
                st.session_state[key] = "incorrect"

            # Show a coloured confirmation below the row based on the stored verdict.
            verdict = st.session_state[key]
            if verdict == "correct":
                st.success("Marked: Correct", icon="✔")
            elif verdict == "partial":
                st.warning("Marked: Partially correct", icon="⚠️")
            elif verdict == "incorrect":
                st.error("Marked: Incorrect", icon="🚫")

            st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Statistics
# All charts on this tab respect the outcome filter at the top.
# ══════════════════════════════════════════════════════════════════════════════
if active_tab == TAB_NAMES[2]:
    selected_outcomes = st.multiselect(
        "Filter by outcome",
        options=list(OUTCOME_EMOJI.keys()),
        default=list(OUTCOME_EMOJI.keys()),
        format_func=lambda o: f"{OUTCOME_EMOJI[o]} {o}",
    )

    # sc = "selected conversations" — the filtered subset for all charts below.
    sc = [c for c in conversations if c["outcome"] in selected_outcomes]

    if not sc:
        st.info("No conversations match the selected outcomes.")
    else:
        # Build two DataFrames: one per-conversation, one per-pair.
        conv_df = pd.DataFrame([
            {"outcome": c["outcome"], "n_turns": c["n_turns"], "n_pairs": len(c["pairs"])}
            for c in sc
        ])

        pair_rows = []
        for c in sc:
            for p in c["pairs"]:
                pair_rows.append({
                    "outcome": c["outcome"],
                    # Only include numeric confidence values; skip "—" strings.
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
        m1.metric("Calls (filtered)",     len(sc))
        m2.metric("Avg turns / call",     f"{conv_df['n_turns'].mean():.1f}")
        m3.metric("Avg exchanges / call", f"{conv_df['n_pairs'].mean():.1f}")
        m4.metric("Conversion rate",      f"{conv_rate:.1f}%")

        m5, m6 = st.columns(2)
        m5.metric("🔍 Calls with contact discovery",    f"{cd_calls} ({cd_calls / len(sc) * 100:.1f}%)")
        m6.metric("🔍 Contact discovery utterances",    cd_utterances)

        st.markdown("---")

        # ── Goal Funnel ────────────────────────────────────────────────────────
        # Shows how many calls reached each progressive stage of the sales flow.
        st.markdown("**Goal Funnel Drop-off**")

        _DM_REACHED_GOALS = {
            "base_agents/outbound agents/speaker verification",
            "base_agents/inbound agents/inbound contact name",
        }
        _DISCOVERY_GOALS = {
            "base_agents/contact discovery",
            "contact_last_name",
        }
        _SCHEDULING_GOALS = {
            "voice goals end of call/scheduling-via-voice/meeting slot",
            "voice goals end of call/scheduling-via-voice/scheduling email",
            "voice goals end of call/scheduling-via-voice/timezone_name",
            "voice goals end of call/scheduling-via-voice/pre-scheduling-goals/confirm last name",
        }

        # Each stage is a (label, lambda) pair — the lambda checks if a call reached that stage.
        funnel_stages = [
            ("Connected",              lambda _: True),
            ("Reached Decision Maker", lambda goals: bool(goals & _DM_REACHED_GOALS)),
            ("Contact Discovery",      lambda goals: bool(goals & _DISCOVERY_GOALS)),
            ("Scheduling Initiated",   lambda goals: bool(goals & _SCHEDULING_GOALS)),
            ("Meeting Confirmed",      lambda goals: bool(goals & _CONFIRMED_SCHEDULING_PATHS)),
        ]

        funnel_counts = []
        for label, check in funnel_stages:
            n = sum(
                1 for c in sc
                if check({p["Goal"] for p in c["pairs"] if p["Goal"] != "—"})
            )
            funnel_counts.append((label, n))

        fig = go.Figure(go.Funnel(
            y=[label for label, _ in funnel_counts],
            x=[count for _, count in funnel_counts],
            textinfo="value+percent initial",
            marker={"color": ["#4C9BE8", "#5DADE2", "#48C9B0", "#F4D03F", "#2ECC71"]},
        ))
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=10), height=350)
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")

        # ── Outcome distribution ───────────────────────────────────────────────
        st.markdown("**Outcome distribution**")
        oc = conv_df["outcome"].value_counts()
        st.plotly_chart(pct_bar(oc.index.tolist(), oc.values.tolist()), use_container_width=True)

        st.markdown("---")

        # ── Call length distribution ───────────────────────────────────────────
        # Bins calls by number of turns, then plots as a line chart.
        st.markdown("**Call length distribution (turns)**")
        min_t = int(conv_df["n_turns"].min())
        max_t = int(conv_df["n_turns"].max())
        n_bins = min(10, max_t - min_t + 1)
        step = max(1, math.ceil((max_t - min_t + 1) / n_bins))
        bin_edges = list(range(min_t, max_t + step + 1, step))
        cut_bins = pd.cut(conv_df["n_turns"], bins=bin_edges, include_lowest=True)
        bc = cut_bins.value_counts().sort_index()
        turn_labels = [f"{int(math.ceil(i.left))}–{int(i.right)}" for i in bc.index]
        fig_tl = go.Figure(go.Scatter(
            x=turn_labels, y=bc.values.tolist(),
            mode="lines+markers",
            line={"width": 3},
            marker={"size": 8},
        ))
        fig_tl.update_layout(
            margin=dict(l=0, r=0, t=10, b=0), height=350,
            xaxis_title="Turns", yaxis_title="Calls",
        )
        st.plotly_chart(fig_tl, use_container_width=True)

        st.markdown("---")

        # ── Confidence score distribution ──────────────────────────────────────
        # Bins all user-turn confidence scores into five fixed ranges.
        st.markdown("**Confidence score distribution**")
        conf_series = pairs_df["confidence"].dropna()
        if conf_series.empty:
            st.info("No confidence data for the selected outcomes.")
        else:
            conf_labels = ["0–0.5", "0.5–0.7", "0.7–0.85", "0.85–0.95", "0.95–1.0"]
            conf_bins = pd.cut(conf_series, bins=[0, 0.5, 0.7, 0.85, 0.95, 1.0], labels=conf_labels)
            cc = conf_bins.value_counts().reindex(conf_labels).fillna(0).astype(int)
            st.plotly_chart(pct_bar(cc.index.tolist(), cc.values.tolist(), y_title="Pairs"), use_container_width=True)

        st.markdown("---")

        # ── Avg turns by outcome ───────────────────────────────────────────────
        # Only shown when more than one outcome type is selected (otherwise meaningless).
        if len(selected_outcomes) > 1:
            st.markdown("**Average turns by outcome**")
            avg = conv_df.groupby("outcome")["n_turns"].mean().round(1)
            fig_avg = go.Figure(go.Bar(
                x=avg.index.tolist(), y=avg.values.tolist(),
                text=[str(v) for v in avg.values.tolist()],
                textposition="inside",
                textfont={"color": "black", "size": 26},
            ))
            fig_avg.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=350, yaxis_title="Avg Turns")
            st.plotly_chart(fig_avg, use_container_width=True)

            st.markdown("---")

        # ── Rejection disconnect stage ─────────────────────────────────────────
        # Shows at which script node the caller typically dropped off.
        st.markdown("**🚫 Where in the call did rejections happen?**")
        rejection_calls = [c for c in sc if c["outcome"] == "Rejection"]
        if not rejection_calls:
            st.info("No rejection calls in the selected outcomes.")
        else:
            st.markdown("**Last goal reached before rejection**")
            sc_series = pd.Series(
                [c["disconnect_stage"] or "No goal recorded" for c in rejection_calls]
            ).value_counts()
            st.plotly_chart(pct_bar(sc_series.index.tolist(), sc_series.values.tolist()), use_container_width=True)

            st.markdown("**Number of exchanges before rejection**")
            rej_pairs = [len(c["pairs"]) for c in rejection_calls]
            n_bins_r = max(1, min(10, len(rejection_calls) // 2))
            min_r, max_r = min(rej_pairs), max(rej_pairs)
            step_r = max(1, math.ceil((max_r - min_r + 1) / n_bins_r))
            edges_r = list(range(min_r, max_r + step_r + 1, step_r))
            cut_r = pd.cut(pd.Series(rej_pairs), bins=edges_r, include_lowest=True)
            br = cut_r.value_counts().sort_index()
            exch_labels = [f"{int(math.ceil(i.left))}–{int(i.right)}" for i in br.index]
            st.plotly_chart(pct_bar(exch_labels, br.values.tolist()), use_container_width=True)

        st.markdown("---")

        # ── User engagement depth ──────────────────────────────────────────────
        # Buckets calls by how many exchanges happened — a proxy for how engaged the caller was.
        st.markdown("**User Engagement Depth**")

        def engagement_bucket(n):
            if n <= 2:  return "Dropped after greeting (1–2)"
            if n <= 5:  return "Short (3–5)"
            if n <= 10: return "Medium (6–10)"
            return "Deep (11+)"

        bucket_order = ["Dropped after greeting (1–2)", "Short (3–5)", "Medium (6–10)", "Deep (11+)"]
        buckets = pd.Series([engagement_bucket(len(c["pairs"])) for c in sc])
        bucket_counts = buckets.value_counts().reindex(bucket_order).fillna(0).astype(int)
        st.plotly_chart(pct_bar(bucket_counts.index.tolist(), bucket_counts.values.tolist()), use_container_width=True)

        st.markdown("---")

        # ── User confusion rate ────────────────────────────────────────────────
        # Detects calls where the user showed signs of not understanding the agent.
        # Each signal is a named regex pattern; "Repeated utterance" is a special case.
        st.markdown("**User Confusion Rate**")

        CONFUSION_SIGNALS = {
            "What? / Huh? / Come again?": re.compile(
                r'\b(what\s*\?+|huh\s*\??|come again|what was that|what did you say|say what)\b', re.I),
            "Repeat request": re.compile(
                r'\b(can you repeat|could you repeat|say that again|repeat that|repeat yourself|one more time|again please|repeat please)\b', re.I),
            "Didn't understand": re.compile(
                r"\b(i don'?t understand|i didn'?t understand|i'?m confused|what do you mean|what are you (saying|talking about)|i'?m lost|didn'?t catch (that|you)|didn'?t get that|didn'?t hear (that|you)|i'?m not following)\b", re.I),
            "Hearing issues": re.compile(
                r"\b(can'?t hear (you)?|couldn'?t hear|hard to hear|you'?re breaking up|bad connection|speak up|can you speak up|louder please|i can'?t hear)\b", re.I),
            "Pardon / Excuse me / Sorry?": re.compile(
                r'\b(pardon\s*\??|excuse me\s*\??|sorry\s*\?+|i beg your pardon|beg your pardon)\b', re.I),
            "Clarification request": re.compile(
                r"\b(what do you mean by|can you (clarify|explain)|could you (clarify|explain)|not sure (what|i understand)|what exactly|what specifically)\b", re.I),
            # Special case: detected by comparing all user utterances for duplicates,
            # not by a regex match.
            "Repeated utterance": None,
        }

        def repeated_utterance(pairs):
            # Returns True if any user message was said more than once in the call.
            msgs = [p["User"].strip().lower() for p in pairs if p["User"].strip()]
            return len(msgs) != len(set(msgs))

        conf_signal_counts = {sig: 0 for sig in CONFUSION_SIGNALS}
        conf_calls = 0
        for c in sc:
            triggered = False
            for sig, pattern in CONFUSION_SIGNALS.items():
                if sig == "Repeated utterance":
                    if repeated_utterance(c["pairs"]):
                        conf_signal_counts[sig] += 1
                        triggered = True
                else:
                    if any(pattern.search(p["User"]) for p in c["pairs"]):
                        conf_signal_counts[sig] += 1
                        triggered = True
            if triggered:
                conf_calls += 1

        conf_pct = conf_calls / len(sc) * 100 if sc else 0
        st.metric("Calls with confusion signals", f"{conf_calls} ({conf_pct:.1f}%)")
        conf_active = {k: v for k, v in conf_signal_counts.items() if v > 0}
        if conf_active:
            st.plotly_chart(pct_bar(list(conf_active.keys()), list(conf_active.values())), use_container_width=True)
        else:
            st.info("No confusion signals detected in the selected calls.")

        st.markdown("---")

        # ── User frustration rate ──────────────────────────────────────────────
        # Similar to confusion, but detects hostility, refusals, and hang-up threats.
        st.markdown("**User Frustration Rate**")

        FRUSTRATION_SIGNALS = {
            "Human / Agent request": re.compile(
                r"\b(human( please)?|real person|live (person|agent)|speak to (a |an )?(human|agent|person|representative|rep|operator)|talk to (a |an )?(human|agent|person|representative|rep)|transfer me|connect me to|agent please|representative please|operator please|get me (a |an )?(human|agent|person))\b", re.I),
            "Stop / Remove me": re.compile(
                r"\b(stop( calling( me)?)?|stop it|leave me alone|don'?t (call|contact) me|do not call|remove me( from)?|take me off|unsubscribe|block (this number|you)|put me on (the )?(do not call|dnc))\b", re.I),
            "Not interested": re.compile(
                r"\b(not interested|i'?m not interested|no thank you|no thanks|not at this time|not right now|we'?re not (looking|interested)|don'?t need (this|that|it)|don'?t want (this|that|it))\b", re.I),
            "Scam / Spam": re.compile(
                r'\b(scam|spam|fraud(ulent)?|illegal|harassment|harassing|report (you|this)|stop calling me|robocall|robo call|soliciting)\b', re.I),
            "Not listening / Understanding": re.compile(
                r"\b(not listening|you'?re not listening|not understanding|you'?re not understanding|stop wasting my time|waste of time|this is (ridiculous|stupid|annoying)|you'?re (not|repeating)|said (no|stop) already)\b", re.I),
            "Already refused": re.compile(
                r"\b(i (already |just )?(said|told you|answered|said no)|already told you|i said no|told you (already|before)|said it (already|before))\b", re.I),
            "Hang up threat": re.compile(
                r"\b(i'?m (going to |gonna )?(hang up|hang|end this|end the call)|hanging up|i'?ll hang up|just hang up|going to hang)\b", re.I),
            "Anger / Profanity": re.compile(
                r"\b(damn|hell|crap|ridiculous|stupid (call|bot|machine|system)|this is (bull|bs)|what (the hell|on earth))\b", re.I),
        }

        frust_signal_counts = {sig: 0 for sig in FRUSTRATION_SIGNALS}
        frust_calls = 0
        for c in sc:
            triggered = False
            for sig, pattern in FRUSTRATION_SIGNALS.items():
                if any(pattern.search(p["User"]) for p in c["pairs"]):
                    frust_signal_counts[sig] += 1
                    triggered = True
            if triggered:
                frust_calls += 1

        frust_pct = frust_calls / len(sc) * 100 if sc else 0
        st.metric("Calls with frustration signals", f"{frust_calls} ({frust_pct:.1f}%)")
        frust_active = {k: v for k, v in frust_signal_counts.items() if v > 0}
        if frust_active:
            st.plotly_chart(pct_bar(list(frust_active.keys()), list(frust_active.values())), use_container_width=True)
        else:
            st.info("No frustration signals detected in the selected calls.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Review Dataset
# Builds a curated dataset for human annotation.
# Always includes all low-confidence pairs; optionally mixes in high-confidence
# pairs at a chosen ratio so annotators don't know which is which (blind review).
# ══════════════════════════════════════════════════════════════════════════════
if active_tab == TAB_NAMES[3]:
    n_low = len(low_conf_pairs)
    n_high_available = len(high_conf_pairs)

    st.markdown(
        f"**{n_low}** pairs with confidence < 1  ·  "
        f"**{n_high_available}** pairs with confidence = 1 available"
    )

    # The user picks what fraction of high-confidence pairs to mix in.
    ratio = st.radio(
        "Ratio of confidence = 1 pairs to add",
        options=["0% (low-confidence only)", "50%", "100%", "150%"],
        horizontal=True,
    )

    ratio_map = {
        "0% (low-confidence only)": 0.0,
        "50%": 0.5,
        "100%": 1.0,
        "150%": 1.5,
    }
    # Cap at however many high-conf pairs are actually available.
    n_to_add = min(int(n_low * ratio_map[ratio]), n_high_available)

    # The Reshuffle button changes the random seed, which changes which high-conf
    # pairs are sampled and how the final list is ordered — without changing
    # the low-conf pairs (they're always all included).
    if st.button("🔀 Reshuffle"):
        st.session_state["review_seed"] = random.randint(0, 999999)
    seed = st.session_state.get("review_seed", 42)

    # Use a seeded random so the shuffle is reproducible until Reshuffle is pressed.
    rng = random.Random(seed)
    sampled_high = rng.sample(high_conf_pairs, n_to_add) if n_to_add > 0 else []
    combined = low_conf_pairs + sampled_high
    rng.shuffle(combined)  # Interleave so high/low pairs aren't grouped together.

    st.caption(
        f"Showing {len(low_conf_pairs)} low-confidence + {n_to_add} high-confidence pairs "
        f"({len(combined)} total), shuffled."
    )

    if not combined:
        st.info("No pairs to display.")
    else:
        # Show the table WITHOUT the Confidence column — hidden to avoid annotator bias.
        display_cols = ["chat_id", "#", "Prev Agent", "User", "Agent", "Goal", "Intent", "Confidence"]
        st.dataframe(
            pd.DataFrame(combined)[display_cols],
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("---")
        # Download button exports the full combined list as JSON (Confidence IS included).
        st.download_button(
            label="⬇️ Download as JSON",
            data=json.dumps(combined, ensure_ascii=False, indent=2),
            file_name="review_dataset.json",
            mime="application/json",
        )
