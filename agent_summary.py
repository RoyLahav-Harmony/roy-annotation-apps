import streamlit as st
import json
import pandas as pd

st.set_page_config(page_title="Agent Script Summary", layout="wide")
st.title("Agent Script Summary")

# ── File upload ────────────────────────────────────────────────────────────────
uploaded = st.file_uploader("Upload an agent script JSON file", type=["json"])
if uploaded is None:
    st.info("Upload an agent script JSON file to begin.")
    st.stop()


# ── Helpers ────────────────────────────────────────────────────────────────────
def extract_messages(field):
    """Return a flat list of non-empty utterance strings from any messages format."""
    if not field:
        return []
    if isinstance(field, str):
        return [field.strip()] if field.strip() else []
    if isinstance(field, list):
        out = []
        for m in field:
            if isinstance(m, str) and m.strip():
                out.append(m.strip())
            elif isinstance(m, dict):
                text = m.get("message", "").strip()
                if text:
                    out.append(text)
        return out
    return []


def walk_goals(goals, parent_path=""):
    """
    Recursively yield (label, [utterances]) for every extractable piece
    of a goal tree, including refusal handling, choice acknowledges,
    copy_from references, and nested sub-goals.
    """
    for goal in (goals or []):
        if goal.get("enabled") is False:
            continue

        name = goal.get("name", "").strip()
        # appended goals belong conceptually to the parent; keep parent path
        path = parent_path if goal.get("appended") and parent_path else (
            f"{parent_path} / {name}" if parent_path else name
        )

        # Primary messages
        utterances = extract_messages(goal.get("messages"))
        # copy_from: no local messages but references an external template
        if not utterances and goal.get("copy_from"):
            utterances = [f"[external template: {goal['copy_from']}]"]
        if utterances:
            yield path, utterances

        # Refusal handling
        refusal = extract_messages(goal.get("refusal_handling"))
        if refusal:
            yield f"{path} (refusal handling)", refusal

        # Sub-goals listed directly under this goal
        yield from walk_goals(goal.get("goals", []), path)

        # Choice branches
        for choice in (goal.get("choices") or []):
            choice_name = choice.get("name", "").strip()

            # Acknowledge message on the choice itself
            ack = choice.get("acknowledge", "").strip()
            if ack:
                yield f"{path} = {choice_name} acknowledge", [ack]

            # Sub-goals inside this choice
            choice_path = f"{path} / {choice_name}" if choice_name else path
            yield from walk_goals(choice.get("goals", []), choice_path)


def walk_experiments(experiments):
    """Yield (label, [utterances]) from experiment test-group goal overrides."""
    for exp in (experiments or []):
        for group in (exp.get("test_groups") or []):
            goals_update = group.get("goals_update") or {}
            for goal_name, overrides in goals_update.items():
                msgs = extract_messages(overrides.get("messages"))
                if msgs:
                    yield f"{goal_name} (experiment: {group.get('name', exp.get('name', 'variant'))})", msgs


def walk_metadata(default_metadata):
    """
    Yield (label, [utterance]) for default_metadata values that look like
    natural-language utterances (strings > 20 chars, not pure variable refs).
    """
    for key, value in (default_metadata or {}).items():
        if not isinstance(value, str):
            continue
        text = value.strip()
        if len(text) < 20:
            continue
        # Skip values that are purely a variable reference or a URL
        if text.startswith("http") or (text.startswith("{%") and text.endswith("%}")):
            continue
        label = key.strip("_%").replace("_", " ")
        yield f"default: {label}", [text]


# ── Main extraction ────────────────────────────────────────────────────────────
@st.cache_data
def build_summary(content: bytes):
    script = json.loads(content)
    rows = []

    def add(label, utterances):
        unique = list(dict.fromkeys(utterances))
        rows.append({
            "Goal": label,
            "Utterances": " | ".join(unique),
            "# Variants": len(unique),
        })

    for label, utts in walk_goals(script.get("goals", [])):
        add(label, utts)

    for label, utts in walk_experiments(script.get("experiments", [])):
        add(label, utts)

    for label, utts in walk_metadata(script.get("default_metadata")):
        add(label, utts)

    return pd.DataFrame(rows, columns=["Goal", "Utterances", "# Variants"])


try:
    df = build_summary(uploaded.read())
except Exception as e:
    st.error(f"Could not parse script: {e}")
    st.stop()

if df.empty:
    st.warning("No goals with utterances found in this file.")
    st.stop()

# ── Metrics ────────────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns(3)
c1.metric("Goals found", len(df))
c2.metric("Total utterance variants", int(df["# Variants"].sum()))
c3.metric("Goals with multiple variants", int((df["# Variants"] > 1).sum()))

st.markdown("---")

# ── Filters ────────────────────────────────────────────────────────────────────
search = st.text_input("Filter by goal name or utterance text")
only_multi = st.checkbox("Show only goals with multiple utterance variants")

filtered = df.copy()
if search:
    q = search.lower()
    filtered = filtered[
        filtered["Goal"].str.lower().str.contains(q, na=False)
        | filtered["Utterances"].str.lower().str.contains(q, na=False)
    ]
if only_multi:
    filtered = filtered[filtered["# Variants"] > 1]

st.caption(f"Showing {len(filtered)} of {len(df)} goals")

# ── Table ──────────────────────────────────────────────────────────────────────
st.dataframe(
    filtered,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Goal":       st.column_config.TextColumn("Goal", width="medium"),
        "Utterances": st.column_config.TextColumn("Utterances (| separated)", width="large"),
        "# Variants": st.column_config.NumberColumn("# Variants", width="small"),
    },
)
