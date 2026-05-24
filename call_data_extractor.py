import streamlit as st
import pandas as pd
import json
import io

st.set_page_config(page_title="Call Data Extractor", layout="wide")
st.title("Call Data Extractor")

# ── Field name candidates for auto-detection ───────────────────────────────────
CALL_ID_HINTS   = ["call_id", "id", "conversation_id", "session_id", "callSid", "dialogId"]
TURNS_HINTS     = ["turns", "utterances", "messages", "dialogue", "transcript", "interactions"]
SPEAKER_HINTS   = ["speaker", "role", "actor", "from", "sender", "party"]
TEXT_HINTS      = ["text", "utterance", "message", "content", "transcription", "body"]
CONF_HINTS      = ["confidence", "intent_confidence", "score", "confidence_score", "nlu_confidence"]

USER_DEFAULTS   = {"user", "customer", "caller", "human", "client"}
AGENT_DEFAULTS  = {"agent", "assistant", "bot", "system", "representative", "rep"}


def find_key(keys, hints):
    lower_map = {k.lower(): k for k in keys}
    for h in hints:
        if h.lower() in lower_map:
            return lower_map[h.lower()]
    return None


def safe_index(options, value):
    try:
        return options.index(value) if value in options else 0
    except ValueError:
        return 0


@st.cache_data
def load_file(file):
    name = file.name.lower()
    raw = file.read()
    if name.endswith(".jsonl"):
        records = [json.loads(l) for l in raw.decode().splitlines() if l.strip()]
        return records, "json"
    elif name.endswith(".json"):
        data = json.loads(raw)
        if isinstance(data, list):
            return data, "json"
        for v in data.values():
            if isinstance(v, list) and v:
                return v, "json"
        return [data], "json"
    elif name.endswith(".csv"):
        return pd.read_csv(io.BytesIO(raw)), "csv"
    raise ValueError(f"Unsupported file type: {file.name}")


def make_pairs(turns, speaker_key, text_key, conf_key, user_set, agent_set):
    """Pair consecutive user turns with the next agent turn."""
    pairs = []
    i = 0
    while i < len(turns):
        t = turns[i]
        speaker = str(t.get(speaker_key, "")).strip().lower()
        if speaker in user_set:
            user_text = t.get(text_key, "")
            conf = t.get(conf_key, "N/A") if conf_key else "N/A"
            agent_text = ""
            if i + 1 < len(turns):
                next_speaker = str(turns[i + 1].get(speaker_key, "")).strip().lower()
                if next_speaker in agent_set:
                    agent_text = turns[i + 1].get(text_key, "")
                    i += 2
                    pairs.append((len(pairs) + 1, user_text, agent_text, conf))
                    continue
            pairs.append((len(pairs) + 1, user_text, agent_text, conf))
        i += 1
    return pairs


def show_conversation(call_id, turns, speaker_key, text_key, conf_key, user_set, agent_set):
    pairs = make_pairs(turns, speaker_key, text_key, conf_key, user_set, agent_set)
    label = f"Call ID: {call_id}  —  {len(turns)} turns, {len(pairs)} pairs"
    with st.expander(label):
        if not pairs:
            st.warning("No user–agent pairs found. Adjust speaker values in the sidebar.")
            return
        cols = ["#", "User Utterance", "Agent Response"]
        if conf_key:
            cols.append("Intent Confidence")
        rows = []
        for p in pairs:
            row = {"#": p[0], "User Utterance": p[1], "Agent Response": p[2]}
            if conf_key:
                row["Intent Confidence"] = p[3]
            rows.append(row)
        st.dataframe(pd.DataFrame(rows, columns=cols), use_container_width=True, hide_index=True)


# ── File upload ────────────────────────────────────────────────────────────────
uploaded = st.file_uploader("Upload a conversations file", type=["json", "jsonl", "csv"])

if uploaded is None:
    st.info("Upload a JSON, JSONL, or CSV file to begin.")
    st.stop()

try:
    data, fmt = load_file(uploaded)
except Exception as e:
    st.error(f"Could not load file: {e}")
    st.stop()

# ── Sidebar: field mapping ─────────────────────────────────────────────────────
with st.sidebar:
    st.header("Field Mapping")

    if fmt == "json":
        first = data[0] if data else {}
        top_keys = list(first.keys())

        call_id_key = st.selectbox("Call ID field", top_keys,
                                   index=safe_index(top_keys, find_key(top_keys, CALL_ID_HINTS)))
        turns_key = st.selectbox("Turns field", top_keys,
                                 index=safe_index(top_keys, find_key(top_keys, TURNS_HINTS)))

        first_turns = first.get(turns_key, [])
        turn_keys = list(first_turns[0].keys()) if first_turns and isinstance(first_turns[0], dict) else []

        if not turn_keys:
            st.warning("No turns found in the first record. Check the Turns field.")
            st.stop()

        speaker_key = st.selectbox("Speaker field", turn_keys,
                                   index=safe_index(turn_keys, find_key(turn_keys, SPEAKER_HINTS)))
        text_key = st.selectbox("Utterance text field", turn_keys,
                                index=safe_index(turn_keys, find_key(turn_keys, TEXT_HINTS)))
        conf_options = ["(none)"] + turn_keys
        conf_default = find_key(turn_keys, CONF_HINTS) or "(none)"
        conf_key_raw = st.selectbox("Intent confidence field", conf_options,
                                    index=safe_index(conf_options, conf_default))
        conf_key = conf_key_raw if conf_key_raw != "(none)" else None

        all_speakers = set()
        for rec in data[:100]:
            for t in rec.get(turns_key, []):
                v = str(t.get(speaker_key, "")).strip()
                if v:
                    all_speakers.add(v)

    else:  # CSV
        col_list = list(data.columns)

        call_id_key = st.selectbox("Call ID column", col_list,
                                   index=safe_index(col_list, find_key(col_list, CALL_ID_HINTS)))
        turns_key = None
        speaker_key = st.selectbox("Speaker column", col_list,
                                   index=safe_index(col_list, find_key(col_list, SPEAKER_HINTS)))
        text_key = st.selectbox("Utterance text column", col_list,
                                index=safe_index(col_list, find_key(col_list, TEXT_HINTS)))
        conf_options = ["(none)"] + col_list
        conf_default = find_key(col_list, CONF_HINTS) or "(none)"
        conf_key_raw = st.selectbox("Intent confidence column", conf_options,
                                    index=safe_index(conf_options, conf_default))
        conf_key = conf_key_raw if conf_key_raw != "(none)" else None

        all_speakers = set(data[speaker_key].dropna().astype(str).unique())

    st.markdown("---")
    st.markdown("**Speaker identification**")
    user_vals = st.multiselect(
        "User / customer speaker values",
        sorted(all_speakers),
        default=sorted(v for v in all_speakers if v.lower() in USER_DEFAULTS),
    )
    agent_vals = st.multiselect(
        "Agent / bot speaker values",
        sorted(all_speakers),
        default=sorted(v for v in all_speakers if v.lower() in AGENT_DEFAULTS),
    )

# ── Main: render conversations ─────────────────────────────────────────────────
user_set  = {v.lower() for v in user_vals}
agent_set = {v.lower() for v in agent_vals}

st.header("Extracted Conversations")

if not user_set:
    st.warning("Select at least one user/customer speaker value in the sidebar.")
    st.stop()

if fmt == "json":
    for rec in data:
        call_id = rec.get(call_id_key, "Unknown")
        turns   = rec.get(turns_key, [])
        show_conversation(call_id, turns, speaker_key, text_key, conf_key, user_set, agent_set)

else:  # CSV
    for call_id, group in data.groupby(call_id_key, sort=False):
        turns = group.to_dict("records")
        show_conversation(call_id, turns, speaker_key, text_key, conf_key, user_set, agent_set)
