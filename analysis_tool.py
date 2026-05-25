import math
import streamlit as st
import json
import re
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone

st.set_page_config(page_title="Calls Extracted", layout="wide")
st.title("Extracted Call Conversations")

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

# ── Plotly bar chart helper ────────────────────────────────────────────────────
def pct_bar(labels, values, y_title="Calls", height=350):
    total = sum(values)
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

# ── Collect low- and high-confidence pairs once ────────────────────────────────
low_conf_pairs = []
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

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "All Conversations",
    f"Low Confidence Pairs ({len(low_conf_pairs)})",
    "Statistics",
    "Review Dataset",
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

        # ── Goal funnel ────────────────────────────────────────────────────────
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

        funnel_stages = [
            ("Connected",             lambda _: True),
            ("Reached Decision Maker",lambda goals: bool(goals & _DM_REACHED_GOALS)),
            ("Contact Discovery",     lambda goals: bool(goals & _DISCOVERY_GOALS)),
            ("Scheduling Initiated",  lambda goals: bool(goals & _SCHEDULING_GOALS)),
            ("Meeting Confirmed",     lambda goals: bool(goals & _CONFIRMED_SCHEDULING_PATHS)),
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

        # ── Disconnect stage distribution (rejection calls only) ───────────────
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
            "Repeated utterance": None,
        }

        def repeated_utterance(pairs):
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

# ── Tab 4: review dataset ──────────────────────────────────────────────────────
with tab4:
    import random

    n_low = len(low_conf_pairs)
    n_high_available = len(high_conf_pairs)

    st.markdown(
        f"**{n_low}** pairs with confidence < 1  ·  "
        f"**{n_high_available}** pairs with confidence = 1 available"
    )

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
    n_to_add = min(int(n_low * ratio_map[ratio]), n_high_available)

    if st.button("🔀 Reshuffle"):
        st.session_state["review_seed"] = random.randint(0, 999999)
    seed = st.session_state.get("review_seed", 42)

    rng = random.Random(seed)
    sampled_high = rng.sample(high_conf_pairs, n_to_add) if n_to_add > 0 else []
    combined = low_conf_pairs + sampled_high
    rng.shuffle(combined)

    st.caption(
        f"Showing {len(low_conf_pairs)} low-confidence + {n_to_add} high-confidence pairs "
        f"({len(combined)} total), shuffled."
    )

    if not combined:
        st.info("No pairs to display.")
    else:
        display_cols = ["chat_id", "#", "User", "Agent", "Goal", "Intent", "Confidence"]
        st.dataframe(
            pd.DataFrame(combined)[display_cols],
            use_container_width=True,
            hide_index=True,
        )
