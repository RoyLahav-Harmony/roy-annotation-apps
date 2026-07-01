"""
agreement_tool.py

Loads two annotated JSON files from the contact-discovery annotation platform,
displays each conversation alongside both annotators' labels, and highlights
agreements and disagreements.

Only conversations labeled by BOTH annotators are shown.

Usage:
    streamlit run agreement_tool.py
"""

import json
import html as _html
import pandas as pd
import altair as alt
import streamlit as st
from pymongo import MongoClient

@st.cache_resource
def _get_mongo_client():
    client = MongoClient(st.secrets["mongodb"]["uri"], serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    return client

def _list_annotation_projects():
    try:
        return sorted(_get_mongo_client()["roy's_projects"].list_collection_names())
    except Exception:
        return []

def _load_project_annotations(project_name):
    try:
        return list(_get_mongo_client()["roy's_projects"][project_name].find(
            {"Labels": {"$exists": True, "$ne": None}}, {"_id": 0}
        ))
    except Exception:
        return []

@st.cache_data(ttl=300, show_spinner="Loading rearranged annotations…")
def _load_rearranged(annotator):
    """{chat_id: [utterances]} for one annotator from contact_discovery_rearranged."""
    try:
        docs = _get_mongo_client()["roy's_projects"]["contact_discovery_rearranged"].find(
            {"annotator": annotator}, {"_id": 0}
        )
        return {d["chat_id"]: d.get("utterances", []) for d in docs}
    except Exception:
        return {}

st.set_page_config(page_title="Agreement Tool", layout="wide", page_icon="🤝")

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"], .stApp { font-family: 'Inter', sans-serif !important; }
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
[data-testid="stToolbar"]    { display: none; }
[data-testid="stDecoration"] { display: none; }
.stApp { background-color: #F1F5F9; }
.stApp p, .stApp li, .stApp span, .stApp label,
.stApp div, .stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: #0F172A; }
hr { border-color: #E2E8F0 !important; margin: 0.6rem 0; }

/* ── Buttons ── */
.stApp .stButton > button,
.stApp .stButton > button:hover,
.stApp .stButton > button:disabled,
.stApp .stButton > button:focus {
    background-color: #93C5FD !important;
    color: #1E3A5F !important;
    border: none !important;
    border-radius: 6px !important;
    opacity: 1 !important;
}

/* ── File uploaders ── */
[data-testid="stFileUploader"],
[data-testid="stFileUploaderDropzone"] {
    background-color: #DBEAFE !important;
    border-color: #93C5FD !important;
    border-radius: 8px !important;
}
[data-testid="stFileUploaderDropzone"] * { color: #1E3A5F !important; }
[data-testid="stFileUploaderDropzone"] button,
[data-testid="stFileUploaderDropzone"] button * {
    background-color: #93C5FD !important;
    color: #1E3A5F !important;
}

/* ── Number input (jump-to / chat counter) ── */
.stApp input[type="number"] {
    background-color: #DBEAFE !important;
    border-color: #93C5FD !important;
    color: #1E3A5F !important;
    border-radius: 6px !important;
}

/* ── Selectboxes ── */
[data-baseweb="select"] > div {
    background: #EFF6FF !important;
    border-color: #93C5FD !important;
}
[data-baseweb="select"] * {
    color: #0F172A !important;
    background-color: transparent !important;
}
[data-baseweb="popover"] * {
    color: #0F172A !important;
    background-color: #EFF6FF !important;
}
[data-baseweb="popover"] li:hover {
    background-color: #DBEAFE !important;
}

.turn-reply {
    background: #EFF6FF; border: 1px solid #BFDBFE;
    border-left: 4px solid #2563EB; border-radius: 8px;
    padding: 10px 14px; margin-bottom: 8px;
}
.turn-assistant {
    background: #F8FAFC; border: 1px solid #E2E8F0;
    border-left: 4px solid #94A3B8; border-radius: 8px;
    padding: 10px 14px; margin-bottom: 8px;
}
.turn-label { font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
               letter-spacing: 0.06em; margin-bottom: 5px; }
.reply-label { color: #2563EB; }
.asst-label  { color: #94A3B8; }

.contact-header {
    background: #F1F5F9; border-radius: 6px; padding: 6px 10px;
    margin: 10px 0 6px; font-size: 0.78rem; font-weight: 700;
    color: #334155; text-transform: uppercase; letter-spacing: 0.05em;
}
.badge-agree    { background:#D1FAE5; color:#065F46; border:1px solid #6EE7B7;
                  border-radius:4px; padding:2px 8px; font-size:0.72rem; font-weight:600; }
.badge-disagree { background:#FEE2E2; color:#991B1B; border:1px solid #FCA5A5;
                  border-radius:4px; padding:2px 8px; font-size:0.72rem; font-weight:600; }
.summary-bar {
    background: white; border: 1px solid #E2E8F0; border-radius: 10px;
    padding: 10px 14px; margin-bottom: 12px;
}

/* ── Dataframe / chart element toolbar ── */
[data-testid="stElementToolbar"],
[data-testid="stElementToolbar"] > div,
.stElementToolbar,
.stElementToolbar > div {
    background-color: #BFDBFE !important;
    border: 1px solid #93C5FD !important;
    border-radius: 6px !important;
}
[data-testid="stElementToolbarButton"],
.stElementToolbar button {
    background-color: #BFDBFE !important;
    color: #1E3A5F !important;
}
[data-testid="stElementToolbarButton"] svg,
.stElementToolbar button svg {
    fill: #1E3A5F !important;
    stroke: #1E3A5F !important;
}
</style>
""", unsafe_allow_html=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(val):
    if val is None:
        return "—"
    if val == "N/A":
        return "N/A"
    if isinstance(val, bool):
        return str(val)
    if isinstance(val, list):
        return "[ ]" if not val else f"[{', '.join(str(v) for v in val)}]"
    if isinstance(val, str):
        return val if val.strip() else "—"
    return str(val)

def _eq(a, b):
    def _norm(v):
        if v is None or v == [] or v == "":
            return "__EMPTY__"
        return v
    return _norm(a) == _norm(b)

def _extract_fields(speaker_dict):
    """Return a flat dict of the comparable fields from one speaker annotation."""
    if not speaker_dict or speaker_dict == "N/A":
        return {}

    def _name_str(raw):
        if not raw or raw == "N/A":
            return "N/A"
        if isinstance(raw[0], str):
            return raw[0]
        return " / ".join(e[0] for e in raw if e)

    def _name_turns(raw):
        if not raw or raw == "N/A":
            return "N/A"
        if isinstance(raw[0], str):
            return raw[1] if len(raw) > 1 else []
        turns = []
        for e in raw:
            if len(e) > 1 and isinstance(e[1], list):
                turns.extend(e[1])
        return sorted(set(turns))

    fname_raw = speaker_dict.get("Fname")
    lname_raw = speaker_dict.get("Lname")
    return {
        "First name":          _name_str(fname_raw),
        "First name turns":    _name_turns(fname_raw),
        "Last name":           _name_str(lname_raw),
        "Last name turns":     _name_turns(lname_raw),
        "Speaker is contact":  speaker_dict.get("contact_is_speaker"),
        "Intro includes name": speaker_dict.get("intro_includes_name"),
        "Intro excludes name": speaker_dict.get("intro_doesnt_include_name"),
        "Name known":          speaker_dict.get("contact_name_known"),
    }

# ── Model analysis helpers ─────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Loading model predictions…")
def _load_model_preds(chat_ids_tuple):
    try:
        docs = list(_get_mongo_client()["roy's_projects"]["contact_discovery_rearranged"].find(
            {"chat_id": {"$in": list(chat_ids_tuple)}, "annotator": "model", "_complete": True},
            {"_id": 0},
        ))
        return {
            d["chat_id"]: {
                u["reply_index"]: u
                for u in d.get("utterances", [])
                if u.get("speaker") == "user" and "reply_index" in u
            }
            for d in docs
        }
    except Exception:
        return {}


def _all_name_entries(raw):
    """Return [(name_str, [reply_indices]), ...] from a raw Fname/Lname field."""
    if not raw or raw == "N/A":
        return []
    if isinstance(raw[0], str):
        idxs = sorted([v for v in (raw[1] if len(raw) > 1 and isinstance(raw[1], list) else []) if isinstance(v, int)])
        return [(str(raw[0]).strip(), idxs)]
    out = []
    for e in raw:
        if isinstance(e, list) and e:
            idxs = sorted([v for v in (e[1] if len(e) > 1 and isinstance(e[1], list) else []) if isinstance(v, int)])
            out.append((str(e[0]).strip(), idxs))
    return out


def _build_gt(labels):
    """
    From agreed Labels dict return:
      contact_at   : set of reply indices where any contact is speaking
      fname_at     : {reply_index: name_str}
      lname_at     : {reply_index: name_str}
      name_entries : [(field, entry_num, name, [idxs]), ...]
    """
    contact_at, fname_at, lname_at, name_entries = set(), {}, {}, []
    for sp in labels.values():
        if not sp or sp == "N/A":
            continue
        cis = sp.get("contact_is_speaker", [])
        if cis and cis != "N/A" and isinstance(cis, list):
            contact_at.update(v for v in cis if isinstance(v, int))
        for i, (name, idxs) in enumerate(_all_name_entries(sp.get("Fname"))):
            for ri in idxs:
                fname_at[ri] = name
            name_entries.append(("fname", i, name, idxs))
        for i, (name, idxs) in enumerate(_all_name_entries(sp.get("Lname"))):
            for ri in idxs:
                lname_at[ri] = name
            name_entries.append(("lname", i, name, idxs))
    return contact_at, fname_at, lname_at, name_entries


def _nm(a, b):
    """Case-insensitive name match, returns False if either is falsy."""
    return bool(a and b and str(a).strip().lower() == str(b).strip().lower())


def _style_groups(df, cid_col="chat_id"):
    """Return a pandas Styler with alternating group colors per consecutive chat_id."""
    colors = ["#EFF6FF", "#DBEAFE"]   # blue-50 / blue-100
    group_ids = []
    current, prev = 0, None
    for cid in df[cid_col]:
        if cid != prev and prev is not None:
            current = 1 - current
        prev = cid
        group_ids.append(current)

    def _apply(df):
        return pd.DataFrame(
            [[f"background-color: {colors[group_ids[i]]}; color: #000000"] * len(df.columns)
             for i in range(len(df))],
            index=df.index,
            columns=df.columns,
        )
    return df.style.apply(_apply, axis=None)


def _ordinal(n):
    """Convert 0-indexed entry number to '1st name', '2nd name', etc."""
    i = n + 1
    s = {1: "st", 2: "nd", 3: "rd"}.get(i if i not in (11, 12, 13) else 0, "th")
    s = {1: "st", 2: "nd", 3: "rd"}.get(i % 10 if i % 100 not in (11, 12, 13) else 0, "th")
    return f"{i}{s} name"


def _norm_name_str(raw):
    if not raw or raw == "N/A":
        return None
    if isinstance(raw, list) and raw:
        return raw[0][0] if isinstance(raw[0], list) else raw[0]
    return None

def _norm_turns(raw):
    if raw is None or raw == "N/A":
        return None
    if isinstance(raw, list):
        return sorted([v for v in raw if isinstance(v, int)])
    return None

def _name_turns_field(raw):
    if not raw or raw == "N/A":
        return None
    if isinstance(raw, list) and raw:
        turns = raw[0][1] if isinstance(raw[0], list) and len(raw[0]) > 1 else (raw[1] if len(raw) > 1 else [])
        return _norm_turns(turns)
    return None

def _agreement_pct(labels_a, labels_b):
    total = agrees = 0
    for sp_key in set(list(labels_a.keys()) + list(labels_b.keys())):
        fa = _extract_fields(labels_a.get(sp_key, {}))
        fb = _extract_fields(labels_b.get(sp_key, {}))
        for field in set(list(fa.keys()) + list(fb.keys())):
            total += 1
            if _eq(fa.get(field), fb.get(field)):
                agrees += 1
    return (agrees / total * 100) if total else 100.0

# ── Per-utterance comparison (contact_discovery_rearranged) ────────────────────

UTT_FIELDS = [
    ("is_contact",                "Is contact"),
    ("fname",                     "First name"),
    ("lname",                     "Last name"),
    ("intro_includes_name",       "Intro includes name"),
    ("intro_doesnt_include_name", "Intro excludes name"),
    ("contact_name_known",        "Name known"),
]

def _reply_map(utterances):
    """{reply_index: utterance_dict} for the user turns of one rearranged doc."""
    return {
        u["reply_index"]: u
        for u in utterances
        if u.get("speaker") == "user" and "reply_index" in u
    }

def _utt_nonempty(field, v):
    """Whether an annotator actually gave this field a value on an utterance."""
    if field == "is_contact":
        return bool(v)
    if field in ("intro_includes_name", "intro_doesnt_include_name"):
        return v is True
    if field == "contact_name_known":
        return v is not None
    return v not in (None, "")          # fname / lname

def _utt_eq(field, a, b):
    """Field-level equality between two annotators (names compared exactly)."""
    if field == "is_contact":
        return bool(a) == bool(b)
    na = a if a not in (None, "") else None
    nb = b if b not in (None, "") else None
    return na == nb

def _fmt_utt(field, v):
    if field == "is_contact":
        return "True" if v else "False"
    if v is None or v == "":
        return "—"
    return str(v)

def _utt_agreement_pct(rmap_a, rmap_b):
    """% agreement over every field on every user utterance.

    All six fields are counted on each utterance, including ones both
    annotators left blank (a blank/blank match counts as agreement).
    """
    total = agree = 0
    for ri in set(rmap_a) | set(rmap_b):
        ua = rmap_a.get(ri, {})
        ub = rmap_b.get(ri, {})
        for f, _ in UTT_FIELDS:
            total += 1
            if _utt_eq(f, ua.get(f), ub.get(f)):
                agree += 1
    return (agree / total * 100) if total else 100.0

# ── Data source ───────────────────────────────────────────────────────────────

st.markdown("## 🤝 Agreement Tool")

source_mode = st.radio(
    "Load from:", ["📂 Upload a file", "☁️ MongoDB project"],
    horizontal=True, label_visibility="collapsed",
)

data = None

if source_mode == "📂 Upload a file":
    uploaded = st.file_uploader(
        "Upload combined annotated JSON", type="json",
        label_visibility="collapsed",
    )
    if uploaded and st.session_state.get("_ag_file") != uploaded.name:
        data = json.load(uploaded)
        st.session_state["_ag_file"] = uploaded.name
        st.session_state.pop("_ag_by_annotator", None)
    elif not uploaded:
        st.info("Upload a combined annotated JSON file to begin.")
        st.stop()

else:
    projects = _list_annotation_projects()
    if not projects:
        st.warning("No annotation projects found in MongoDB.")
        st.stop()
    selected_project = st.selectbox("Select project", options=projects)
    if st.button("⬇️ Load from MongoDB", type="primary"):
        with st.spinner(f"Loading '{selected_project}' from MongoDB…"):
            data = _load_project_annotations(selected_project)
        if not data:
            st.error(f"No labeled annotations found in '{selected_project}'.")
            st.stop()
        st.session_state["_ag_file"] = f"mongodb:{selected_project}"
        st.session_state.pop("_ag_by_annotator", None)
    elif "_ag_by_annotator" not in st.session_state:
        st.info("Select a project and click Load to begin.")
        st.stop()

# ── Load & split by annotator ─────────────────────────────────────────────────

if data is not None:
    by_annotator = {}
    for conv in data:
        ann = conv.get("annotator", "unknown")
        cid = conv.get("chat_id")
        if cid:
            by_annotator.setdefault(ann, {})[cid] = conv
    st.session_state["_ag_by_annotator"] = by_annotator
    st.session_state["_ag_idx"]          = 0

by_annotator = st.session_state["_ag_by_annotator"]
annotators   = sorted(by_annotator.keys())

if len(annotators) < 2:
    st.warning(f"Only one annotator found ({annotators[0] if annotators else '—'}). Need at least two to compare.")
    st.stop()

# ── Annotator selection ───────────────────────────────────────────────────────

sc1, sc2 = st.columns(2)
name_a = sc1.selectbox("Annotator 1", annotators, index=0, key="sel_a")
name_b = sc2.selectbox("Annotator 2", [a for a in annotators if a != name_a],
                        index=0, key="sel_b")

map_a = by_annotator[name_a]
map_b = by_annotator[name_b]

both = sorted([
    cid for cid in map_a
    if cid in map_b
    and "Labels" in map_a[cid]
    and "Labels" in map_b[cid]
])
n_total = len(both)

# Old per-contact joint set, version-filtered — used by the Dataset Health and
# Model Analysis tabs, which still read the contact_discovery collection.
skipped_cids = {cid for cid in both if map_a[cid].get("turns") != map_b[cid].get("turns")}
stats_both   = [cid for cid in both if cid not in skipped_cids]

# Per-utterance annotations from contact_discovery_rearranged — used by the
# Review and Statistics tabs (compare each utterance's labels, not contacts).
rutt_a   = _load_rearranged(name_a)
rutt_b   = _load_rearranged(name_b)
both_utt = sorted(set(rutt_a) & set(rutt_b))

total_a = sum(1 for c in map_a.values() if "Labels" in c)
total_b = sum(1 for c in map_b.values() if "Labels" in c)
st.caption(
    f"{name_a}: {total_a} labeled  ·  "
    f"{name_b}: {total_b} labeled  ·  "
    f"Both (per-utterance set): **{len(both_utt)}**"
)

if not both and not both_utt:
    st.warning(f"No conversations are labeled by both {name_a} and {name_b}.")
    st.stop()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_review, tab_stats, tab_health, tab_model = st.tabs(["📋 Review", "📊 Statistics", "🏥 Dataset Health", "🤖 Model Analysis"])

# ── TAB 1: Review ─────────────────────────────────────────────────────────────

with tab_review:

    if not both_utt:
        st.warning("No conversations labeled by both annotators were found in "
                   "contact_discovery_rearranged.")
        st.stop()

    only_disagree = st.checkbox("Show only conversations with disagreements", value=False)

    def _conv_agree(cid):
        return _utt_agreement_pct(_reply_map(rutt_a[cid]), _reply_map(rutt_b[cid]))

    review_list = [cid for cid in both_utt
                   if not only_disagree or _conv_agree(cid) < 100]
    if not review_list:
        st.info("No conversations match the current filter.")
        st.stop()
    review_total = len(review_list)

    idx = max(0, min(st.session_state.get("_ag_idx", 0), review_total - 1))

    nc1, nc2, nc3, nc4 = st.columns([1, 2, 2, 1])
    if nc1.button("← Prev", disabled=(idx == 0), use_container_width=True):
        st.session_state["_ag_idx"] = idx - 1
        st.rerun()
    nc2.markdown(
        f"<div style='text-align:center;padding-top:6px'>"
        f"Conversation <b>{idx + 1}</b> / <b>{review_total}</b></div>",
        unsafe_allow_html=True,
    )
    jump = nc3.number_input(
        "Jump to", min_value=1, max_value=review_total,
        value=idx + 1, step=1, label_visibility="collapsed",
    )
    if int(jump) - 1 != idx:
        st.session_state["_ag_idx"] = int(jump) - 1
        st.rerun()
    if nc4.button("Next →", disabled=(idx == review_total - 1), use_container_width=True):
        st.session_state["_ag_idx"] = idx + 1
        st.rerun()

    cid    = review_list[idx]
    utts_a = rutt_a[cid]
    utts_b = rutt_b[cid]
    rmap_a = _reply_map(utts_a)
    rmap_b = _reply_map(utts_b)

    texts_a = [u.get("text", "") for u in utts_a]
    texts_b = [u.get("text", "") for u in utts_b]
    versions_differ = texts_a != texts_b
    _version = st.radio(
        "Conversation version:",
        [f"📄 {name_a}'s version", f"📄 {name_b}'s version"],
        horizontal=True,
        key=f"_version_{cid}",
        label_visibility="collapsed",
        captions=["", "⚠️ Text differs" if versions_differ else ""],
    )
    disp_utts = utts_a if _version.startswith(f"📄 {name_a}") else utts_b

    pct       = _utt_agreement_pct(rmap_a, rmap_b)
    badge_cls = "badge-agree" if pct >= 80 else "badge-disagree"

    st.markdown(
        f'<div class="summary-bar">'
        f'<code style="font-size:0.75rem">{cid}</code>'
        f'&emsp;<span class="{badge_cls}">{pct:.0f}% agreement</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.2, 1], gap="large")

    with left:
        st.markdown("**Conversation**")
        with st.container(height=680):
            for u in sorted(disp_utts, key=lambda x: x.get("turn_index", 0)):
                text     = u.get("text", "")
                is_reply = u.get("speaker") == "user"
                if is_reply:
                    label_tag, css, lbl_cls = f"Reply {u.get('reply_index')}", "turn-reply", "reply-label"
                else:
                    label_tag, css, lbl_cls = "Agent", "turn-assistant", "asst-label"
                st.markdown(
                    f'<div class="{css}">'
                    f'<div class="turn-label {lbl_cls}">{label_tag}</div>'
                    f'{_html.escape(str(text))}</div>',
                    unsafe_allow_html=True,
                )

    with right:
        st.markdown("**Per-utterance label comparison**")

        all_ri = sorted(set(rmap_a) | set(rmap_b))
        if not all_ri:
            st.info("No user utterances in this conversation.")
        else:
            with st.container(height=680):
                for ri in all_ri:
                    ua = rmap_a.get(ri, {})
                    ub = rmap_b.get(ri, {})

                    st.markdown(
                        f'<div class="contact-header">Reply {ri}</div>',
                        unsafe_allow_html=True,
                    )

                    hc1, hc2, hc3, hc4 = st.columns([2, 3, 3, 0.7])
                    hc1.markdown("<small><b>Label</b></small>", unsafe_allow_html=True)
                    hc2.markdown(f"<small><b>{name_a}</b></small>", unsafe_allow_html=True)
                    hc3.markdown(f"<small><b>{name_b}</b></small>", unsafe_allow_html=True)
                    hc4.markdown("<small><b>✓</b></small>", unsafe_allow_html=True)

                    st.markdown("<hr/>", unsafe_allow_html=True)

                    for f, lbl in UTT_FIELDS:
                        a = ua.get(f)
                        b = ub.get(f)
                        agreed = _utt_eq(f, a, b)
                        colour = "#065F46" if agreed else "#991B1B"
                        icon   = "✅" if agreed else "❌"

                        rc1, rc2, rc3, rc4 = st.columns([2, 3, 3, 0.7])
                        rc1.markdown(
                            f"<small style='color:#475569'><b>{lbl}</b></small>",
                            unsafe_allow_html=True,
                        )
                        rc2.markdown(
                            f"<small style='color:{colour}'>{_html.escape(_fmt_utt(f, a))}</small>",
                            unsafe_allow_html=True,
                        )
                        rc3.markdown(
                            f"<small style='color:{colour}'>{_html.escape(_fmt_utt(f, b))}</small>",
                            unsafe_allow_html=True,
                        )
                        rc4.markdown(icon)

                    st.markdown("---")

# ── TAB 2: Statistics ─────────────────────────────────────────────────────────

with tab_stats:

    if not both_utt:
        st.warning("No conversations labeled by both annotators were found in "
                   "contact_discovery_rearranged.")
        st.stop()

    # Exclude conversations where the two annotators saw different utterance text
    utt_skipped = {
        cid for cid in both_utt
        if [u.get("text") for u in rutt_a[cid]] != [u.get("text") for u in rutt_b[cid]]
    }
    stats_list = [cid for cid in both_utt if cid not in utt_skipped]

    if utt_skipped:
        st.info(
            f"ℹ️ {len(utt_skipped)} conversation(s) excluded because the two "
            f"annotators saw different versions of the text."
        )

    field_total    = {f: 0 for f, _ in UTT_FIELDS}
    field_disagree = {f: 0 for f, _ in UTT_FIELDS}
    breakdown = {f: {"agree": 0, "differ": 0,
                     f"{name_a}_only": 0, f"{name_b}_only": 0}
                 for f, _ in UTT_FIELDS}
    n_utts = n_utts_disagree = 0

    for cid in stats_list:
        rmap_a = _reply_map(rutt_a[cid])
        rmap_b = _reply_map(rutt_b[cid])
        for ri in sorted(set(rmap_a) | set(rmap_b)):
            ua = rmap_a.get(ri, {})
            ub = rmap_b.get(ri, {})
            n_utts += 1
            utt_has_disagree = False
            for f, _ in UTT_FIELDS:
                a = ua.get(f)
                b = ub.get(f)
                field_total[f] += 1
                if _utt_eq(f, a, b):
                    breakdown[f]["agree"] += 1
                else:
                    field_disagree[f] += 1
                    utt_has_disagree = True
                    na = _utt_nonempty(f, a)
                    nb = _utt_nonempty(f, b)
                    if na and not nb:
                        breakdown[f][f"{name_a}_only"] += 1
                    elif nb and not na:
                        breakdown[f][f"{name_b}_only"] += 1
                    else:
                        breakdown[f]["differ"] += 1
            if utt_has_disagree:
                n_utts_disagree += 1

    if n_utts == 0:
        st.info("No user utterances to compare.")
        st.stop()

    total_points = sum(field_total.values())
    total_dis    = sum(field_disagree.values())

    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("User utterances compared", n_utts)
    mc2.metric("Utterances with a disagreement", n_utts_disagree,
               help=f"{n_utts_disagree}/{n_utts} = {n_utts_disagree / n_utts * 100:.1f}%")
    mc3.metric("Overall label disagreement",
               f"{(total_dis / total_points * 100) if total_points else 0:.1f}%",
               help=f"{total_dis}/{total_points} field comparisons")

    st.caption(
        f"Across {len(stats_list)} jointly-labeled conversations"
        + (f" ({len(utt_skipped)} excluded due to differing text)" if utt_skipped else "")
        + ". Every one of the six labels is compared on every user utterance, "
        "including ones both annotators left blank (a blank/blank match counts "
        "as agreement)."
    )

    st.markdown("### Disagreement rate per label")
    rows = []
    for f, lbl in UTT_FIELDS:
        tot = field_total[f]
        dis = field_disagree[f]
        rows.append({
            "Label":                 lbl,
            "Disagreement rate (%)": round(dis / tot * 100, 1) if tot else 0.0,
            "Disagreements":         dis,
            "Comparison points":     tot,
        })
    rows.sort(key=lambda r: r["Disagreement rate (%)"], reverse=True)
    df = pd.DataFrame(rows)

    chart = (
        alt.Chart(df)
        .mark_bar(color="#3B82F6")
        .encode(
            x=alt.X("Disagreement rate (%):Q", scale=alt.Scale(domain=[0, 100]),
                    axis=alt.Axis(labelColor="#1E3A5F", titleColor="#1E3A5F",
                                  gridColor="#BFDBFE")),
            y=alt.Y("Label:N", sort="-x",
                    axis=alt.Axis(labelColor="#1E3A5F", titleColor="#1E3A5F")),
            tooltip=["Label:N",
                     alt.Tooltip("Disagreement rate (%):Q", format=".1f"),
                     "Disagreements:Q", "Comparison points:Q"],
        )
        .properties(height=300, background="#EFF6FF")
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(chart, use_container_width=True)

    st.markdown("---")
    st.markdown("### Breakdown per label")
    st.caption(
        f"'Agree' and 'Differ' are cases where both annotators labeled the field. "
        f"'Only {name_a}' / 'Only {name_b}' = one labeled it, the other left it empty."
    )
    brows = []
    for f, lbl in UTT_FIELDS:
        b = breakdown[f]
        brows.append({
            "Label":             lbl,
            "Comparison points": field_total[f],
            "Agree":             b["agree"],
            "Differ":            b["differ"],
            f"Only {name_a}":    b[f"{name_a}_only"],
            f"Only {name_b}":    b[f"{name_b}_only"],
        })
    st.dataframe(pd.DataFrame(brows), hide_index=True, use_container_width=True)

# ── TAB 3: Dataset Health ──────────────────────────────────────────────────────

with tab_health:

    health_convs = list(map_a.values())
    total = len(health_convs)
    st.caption(f"Based on {total} conversations annotated by {name_a}")

    if total == 0:
        st.warning("No annotated conversations found.")
        st.stop()

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _h_name_first_turn(raw):
        if not raw or raw == "N/A":
            return None
        turns = []
        if isinstance(raw[0], str):
            turns = raw[1] if len(raw) > 1 and isinstance(raw[1], list) else []
        else:
            for e in raw:
                if len(e) > 1 and isinstance(e[1], list):
                    turns.extend(e[1])
        ints = [v for v in turns if isinstance(v, int)]
        return min(ints) if ints else None

    def _h_field_first_turn(val):
        if not val or val == "N/A" or not isinstance(val, list):
            return None
        ints = [v for v in val if isinstance(v, int)]
        return min(ints) if ints else None

    # ── Accumulate ────────────────────────────────────────────────────────────
    contact_count_dist = {}
    name_completeness  = {"Both": 0, "Fname only": 0, "Lname only": 0, "Neither": 0}
    first_turn_rows    = []
    fname_lname_order  = {"Fname first": 0, "Lname first": 0, "Same turn": 0}
    distances          = []
    multi_name_counts  = {"2 Fnames": 0, "3+ Fnames": 0, "2 Lnames": 0, "3+ Lnames": 0}

    def _name_entry_count(raw):
        """Return number of name entries (1 for old format, len for new)."""
        if not raw or raw == "N/A":
            return 0
        if isinstance(raw[0], str):
            return 1
        return len(raw)

    for conv in health_convs:
        labels  = conv.get("Labels", {}) or {}
        sp_keys = [k for k in labels if k.startswith("speaker ")]
        n = len(sp_keys)

        # Check if every speaker has both Fname and Lname as N/A
        all_na = n > 0 and all(
            (labels.get(k) or {}).get("Fname") == "N/A" and
            (labels.get(k) or {}).get("Lname") == "N/A"
            for k in sp_keys
        )
        contact_count_dist["no_contact" if all_na else n] = (
            contact_count_dist.get("no_contact" if all_na else n, 0) + 1
        )

        for sp_key in sp_keys:
            sp   = labels.get(sp_key) or {}
            fn_c = _name_entry_count(sp.get("Fname"))
            ln_c = _name_entry_count(sp.get("Lname"))
            if fn_c == 2:   multi_name_counts["2 Fnames"]  += 1
            elif fn_c >= 3: multi_name_counts["3+ Fnames"] += 1
            if ln_c == 2:   multi_name_counts["2 Lnames"]  += 1
            elif ln_c >= 3: multi_name_counts["3+ Lnames"] += 1
            ft   = _h_name_first_turn(sp.get("Fname"))
            lt   = _h_name_first_turn(sp.get("Lname"))
            st_t = _h_field_first_turn(sp.get("contact_is_speaker"))

            has_f = ft is not None
            has_l = lt is not None

            # Q2
            if has_f and has_l:
                name_completeness["Both"] += 1
            elif has_f:
                name_completeness["Fname only"] += 1
            elif has_l:
                name_completeness["Lname only"] += 1
            else:
                name_completeness["Neither"] += 1

            # Q3
            if ft  is not None: first_turn_rows.append({"Field": "Fname",             "Turn": ft})
            if lt  is not None: first_turn_rows.append({"Field": "Lname",             "Turn": lt})
            if st_t is not None: first_turn_rows.append({"Field": "Speaker is contact", "Turn": st_t})

            # Q4 & Q5
            if has_f and has_l:
                if ft < lt:
                    fname_lname_order["Fname first"] += 1
                    distances.append(lt - ft)
                elif lt < ft:
                    fname_lname_order["Lname first"] += 1
                    distances.append(ft - lt)
                else:
                    fname_lname_order["Same turn"] += 1

    # ── Q1: Contact count ─────────────────────────────────────────────────────
    st.markdown("### Contact count per conversation")
    def _contact_label(k):
        if k == "no_contact": return "No meaningful contact (all N/A)"
        return f"{k} contact{'s' if k != 1 else ''}"
    def _contact_sort(k):
        return -1 if k == "no_contact" else k
    q1_df = pd.DataFrame([
        {"Contacts": _contact_label(k), "Count": v, "n": _contact_sort(k)}
        for k, v in contact_count_dist.items()
    ]).sort_values("n")
    st.altair_chart(
        alt.Chart(q1_df).mark_bar(color="#3B82F6").encode(
            x=alt.X("Contacts:N", sort=alt.EncodingSortField("n"),
                    axis=alt.Axis(labelColor="#1E3A5F", titleColor="#1E3A5F")),
            y=alt.Y("Count:Q", axis=alt.Axis(labelColor="#1E3A5F", titleColor="#1E3A5F")),
            tooltip=["Contacts:N", "Count:Q"],
        ).properties(height=240, background="#EFF6FF").configure_view(strokeWidth=0),
        use_container_width=True,
    )

    st.markdown("---")

    # ── Q2: Name completeness ─────────────────────────────────────────────────
    st.markdown("### Name completeness per contact")
    q2_df = pd.DataFrame([{"Category": k, "Count": v} for k, v in name_completeness.items()])
    st.altair_chart(
        alt.Chart(q2_df).mark_bar(color="#10B981").encode(
            x=alt.X("Category:N", sort=["Both", "Fname only", "Lname only", "Neither"],
                    axis=alt.Axis(labelColor="#1E3A5F", titleColor="#1E3A5F")),
            y=alt.Y("Count:Q", axis=alt.Axis(labelColor="#1E3A5F", titleColor="#1E3A5F")),
            tooltip=["Category:N", "Count:Q"],
        ).properties(height=240, background="#EFF6FF").configure_view(strokeWidth=0),
        use_container_width=True,
    )

    st.markdown("---")

    # ── Q2b: Multi-name instances ─────────────────────────────────────────────
    st.markdown("### Multiple names per contact")
    st.caption("Contacts where an annotator added more than one Fname or Lname entry")
    mn_df = pd.DataFrame([
        {"Case": k, "Count": v}
        for k, v in multi_name_counts.items() if v > 0
    ])
    if mn_df.empty:
        st.info("No contacts with multiple name entries found.")
    else:
        st.altair_chart(
            alt.Chart(mn_df).mark_bar(color="#8B5CF6").encode(
                x=alt.X("Case:N", sort=list(multi_name_counts.keys()),
                        axis=alt.Axis(labelColor="#1E3A5F", titleColor="#1E3A5F")),
                y=alt.Y("Count:Q", axis=alt.Axis(labelColor="#1E3A5F", titleColor="#1E3A5F")),
                tooltip=["Case:N", "Count:Q"],
            ).properties(height=220, background="#EFF6FF").configure_view(strokeWidth=0),
            use_container_width=True,
        )

    st.markdown("---")

    # ── Q3: First-appearance turn distribution ────────────────────────────────
    st.markdown("### First-appearance turn distribution")
    st.caption("3 bars per turn — one for each field. Click a category to highlight it.")
    if first_turn_rows:
        q3_df = pd.DataFrame(first_turn_rows)
        field_color = alt.Scale(
            domain=["Fname", "Lname", "Speaker is contact"],
            range=["#3B82F6", "#F59E0B", "#10B981"],
        )
        # Pre-aggregate so xOffset grouping works correctly
        q3_agg = q3_df.groupby(["Turn", "Field"]).size().reset_index(name="Count")
        _sel = alt.selection_point(fields=["Field"], name="q3_sel")
        grouped_chart = (
            alt.Chart(q3_agg)
            .mark_bar()
            .encode(
                x=alt.X("Turn:O", axis=alt.Axis(
                    labelColor="#1E3A5F", titleColor="#1E3A5F", title="Turn number")),
                xOffset=alt.XOffset("Field:N",
                                    sort=["Fname", "Lname", "Speaker is contact"]),
                y=alt.Y("Count:Q", axis=alt.Axis(
                    labelColor="#1E3A5F", titleColor="#1E3A5F", title="Count")),
                color=alt.condition(
                    _sel,
                    alt.Color("Field:N", scale=field_color,
                              legend=alt.Legend(labelColor="#1E3A5F", titleColor="#1E3A5F")),
                    alt.value("#CBD5E1"),
                ),
                tooltip=["Field:N", "Turn:O", "Count:Q"],
            )
            .add_params(_sel)
            .properties(height=280, background="#EFF6FF")
            .configure_view(strokeWidth=0)
        )
        # Single compound Altair chart — no Streamlit rerun needed
        _ax = dict(labelColor="#1E3A5F", titleColor="#1E3A5F", gridColor="#BFDBFE")
        _fs = ["Fname", "Lname", "Speaker is contact"]
        _sel = alt.selection_point(fields=["Field"], name="q3_sel", empty=True)

        _grouped = (
            alt.Chart(q3_agg)
            .mark_bar()
            .encode(
                x=alt.X("Turn:O", axis=alt.Axis(**_ax, title="Turn")),
                xOffset=alt.XOffset("Field:N", sort=_fs),
                y=alt.Y("Count:Q", axis=alt.Axis(**_ax, title="Count")),
                color=alt.condition(
                    _sel,
                    alt.Color("Field:N", scale=field_color, sort=_fs,
                              legend=alt.Legend(labelColor="#1E3A5F", titleColor="#1E3A5F")),
                    alt.value("#CBD5E1"),
                ),
                tooltip=["Field:N", "Turn:O", "Count:Q"],
            )
            .add_params(_sel)
            .properties(height=220)
        )

        _hist = (
            alt.Chart(q3_agg)
            .mark_bar()
            .encode(
                x=alt.X("Turn:O", axis=alt.Axis(**_ax, title="Turn number")),
                y=alt.Y("Count:Q", axis=alt.Axis(**_ax, title="Count")),
                color=alt.Color("Field:N", scale=field_color, sort=_fs, legend=None),
                tooltip=["Field:N", "Turn:O", "Count:Q"],
            )
            .transform_filter(_sel)
            .properties(
                height=180,
                title=alt.TitleParams(
                    text="Click a bar above to filter by field",
                    color="#64748B", fontSize=11,
                ),
            )
        )

        st.altair_chart(
            alt.vconcat(_grouped, _hist)
            .properties(background="#EFF6FF")
            .configure_view(strokeWidth=0),
            use_container_width=True,
        )

    st.markdown("---")

    # ── Q4: Fname vs Lname turn order ─────────────────────────────────────────
    st.markdown("### Fname vs Lname — which appears first")
    st.caption("Only contacts where both Fname and Lname are annotated")
    q4_df = pd.DataFrame([{"Order": k, "Count": v} for k, v in fname_lname_order.items() if v > 0])
    if not q4_df.empty:
        st.altair_chart(
            alt.Chart(q4_df).mark_bar(color="#8B5CF6").encode(
                x=alt.X("Order:N", sort=["Fname first", "Same turn", "Lname first"],
                        axis=alt.Axis(labelColor="#1E3A5F", titleColor="#1E3A5F")),
                y=alt.Y("Count:Q", axis=alt.Axis(labelColor="#1E3A5F", titleColor="#1E3A5F")),
                tooltip=["Order:N", "Count:Q"],
            ).properties(height=240, background="#EFF6FF").configure_view(strokeWidth=0),
            use_container_width=True,
        )

    st.markdown("---")

    # ── Q5: Distance between Fname and Lname first turns ─────────────────────
    st.markdown("### Turn distance between Fname and Lname")
    st.caption("Only contacts where they appear in different turns")
    if distances:
        q5_df = pd.DataFrame({"Distance": distances})
        st.altair_chart(
            alt.Chart(q5_df).mark_bar(color="#F59E0B").encode(
                x=alt.X("Distance:Q", bin=alt.Bin(step=1),
                        axis=alt.Axis(labelColor="#1E3A5F", titleColor="#1E3A5F", title="Turns apart")),
                y=alt.Y("count():Q", axis=alt.Axis(labelColor="#1E3A5F", titleColor="#1E3A5F", title="Count")),
                tooltip=[alt.Tooltip("Distance:Q", bin=True, title="Distance"), "count():Q"],
            ).properties(height=240, background="#EFF6FF").configure_view(strokeWidth=0),
            use_container_width=True,
        )
        avg = sum(distances) / len(distances)
        st.caption(f"Average distance: {avg:.1f} turns · Max: {max(distances)} turns · Cases: {len(distances)}")

# ── TAB 4: Model Analysis ──────────────────────────────────────────────────────

with tab_model:
    _ax = {"labelColor": "#1E3A5F", "titleColor": "#1E3A5F", "gridColor": "#BFDBFE"}

    # Filter to 100%-agreed conversations (same text, both annotators)
    perfect = [
        cid for cid in stats_both
        if _agreement_pct(map_a[cid]["Labels"], map_b[cid]["Labels"]) >= 100.0
    ]

    mc1, mc2 = st.columns(2)
    mc1.metric("Conversations with 100% agreement", len(perfect))

    if not perfect:
        st.info("No conversations with 100% annotator agreement found.")
        st.stop()

    model_data = _load_model_preds(tuple(sorted(perfect)))
    qualified  = [cid for cid in perfect if cid in model_data]
    mc2.metric("Of those — with model predictions", len(qualified))

    if not qualified:
        st.info("No model predictions found for these conversations. Run `run_model_predictions.py` first.")
        st.stop()

    st.markdown("---")

    # ── Accumulate across all qualified conversations ──────────────────────────
    m1_tp = m1_tn = m1_fp = m1_fn = 0
    m2_rows         = []
    m3_rows         = []
    m4_contact_gaps = []
    m4_fname_gaps   = []
    m4_lname_gaps   = []

    for cid in qualified:
        labels     = map_a[cid]["Labels"]
        turns      = map_a[cid].get("turns", [])
        model_reps = model_data[cid]   # {reply_index: utterance_dict}

        contact_at, fname_at, lname_at, name_entries = _build_gt(labels)

        all_ri = sorted([
            int(list(t.keys())[0].split(" ")[1])
            for t in turns
            if list(t.keys())[0].startswith("reply ")
        ])
        if not all_ri:
            continue

        # ── Metric 1: per-reply is_contact ────────────────────────────────────
        for ri in all_ri:
            gt   = ri in contact_at
            pred = bool(model_reps.get(ri, {}).get("is_contact"))
            if gt and pred:     m1_tp += 1
            elif gt:            m1_fn += 1
            elif pred:          m1_fp += 1
            else:               m1_tn += 1

        # ── Metric 2: name detection ──────────────────────────────────────────
        n_names = n_correct_names = 0
        fname_seq = lname_seq = 0
        for field, entry_num, gt_name, idxs in name_entries:
            if not idxs:
                continue
            n_names += 1
            if field == "fname":
                seq_num = fname_seq; fname_seq += 1
            else:
                seq_num = lname_seq; lname_seq += 1
            first_ri  = min(idxs)
            utt       = model_reps.get(first_ri, {})
            model_val = utt.get("fname" if field == "fname" else "lname")
            detected  = bool(model_val)
            correct   = _nm(gt_name, model_val)
            if correct:
                n_correct_names += 1
            m2_rows.append({
                "chat_id":     cid,
                "Field":       field,
                "Entry #":     seq_num,
                "Is change":   entry_num > 0,
                "GT name":     gt_name,
                "First reply": first_ri,
                "Model name":  model_val or "—",
                "Detected":    detected,
                "Correct":     correct,
            })

        # ── Metric 3: name count vs accuracy ──────────────────────────────────
        m3_rows.append({
            "chat_id":   cid,
            "n_names":   n_names,
            "n_correct": n_correct_names,
            "accuracy":  n_correct_names / n_names if n_names > 0 else None,
        })

        # ── Metric 4: forgetting gaps ─────────────────────────────────────────
        # is_contact
        last_ok = None
        for ri in all_ri:
            if ri not in contact_at:
                continue
            pred = bool(model_reps.get(ri, {}).get("is_contact"))
            if pred:
                last_ok = ri
            elif last_ok is not None:
                m4_contact_gaps.append(ri - last_ok)
                last_ok = None

        # fname
        last_ok = None
        for ri in all_ri:
            gt_fn = fname_at.get(ri)
            if not gt_fn:
                continue
            pred_fn = model_reps.get(ri, {}).get("fname")
            if _nm(gt_fn, pred_fn):
                last_ok = ri
            elif last_ok is not None:
                m4_fname_gaps.append(ri - last_ok)
                last_ok = None

        # lname
        last_ok = None
        for ri in all_ri:
            gt_ln = lname_at.get(ri)
            if not gt_ln:
                continue
            pred_ln = model_reps.get(ri, {}).get("lname")
            if _nm(gt_ln, pred_ln):
                last_ok = ri
            elif last_ok is not None:
                m4_lname_gaps.append(ri - last_ok)
                last_ok = None

    # ── Display Metric 1 ──────────────────────────────────────────────────────
    st.markdown("### 1 · Contact identification accuracy")
    st.caption("Per-reply: did the model predict `is_contact` correctly on each reply?")

    m1_total = m1_tp + m1_tn + m1_fp + m1_fn
    m1_acc   = (m1_tp + m1_tn) / m1_total * 100 if m1_total else 0
    m1_prec  = m1_tp / (m1_tp + m1_fp) * 100    if (m1_tp + m1_fp) else 0
    m1_rec   = m1_tp / (m1_tp + m1_fn) * 100    if (m1_tp + m1_fn) else 0
    m1_f1    = 2 * m1_prec * m1_rec / (m1_prec + m1_rec) if (m1_prec + m1_rec) else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Accuracy",  f"{m1_acc:.1f}%",  help=f"{m1_tp + m1_tn} / {m1_total} replies")
    c2.metric("Precision", f"{m1_prec:.1f}%", help="Of model True predictions, how many were correct")
    c3.metric("Recall",    f"{m1_rec:.1f}%",  help="Of actual contact replies, how many model caught")
    c4.metric("F1",        f"{m1_f1:.1f}%")

    cm_df = pd.DataFrame({
        "":                    ["GT: Contact", "GT: Not contact"],
        "Model: Contact":      [m1_tp, m1_fp],
        "Model: Not contact":  [m1_fn, m1_tn],
    }).set_index("")
    st.dataframe(cm_df, use_container_width=False)

    st.markdown("---")

    # ── Display Metric 2 ──────────────────────────────────────────────────────
    st.markdown("### 2 · Name detection accuracy")
    st.caption("At the first reply where each name appears, did the model detect it and get it right?")

    if m2_rows:
        m2_df = pd.DataFrame(m2_rows)

        for is_change, label in [(False, "First occurrence"), (True, "Name change")]:
            sub = m2_df[m2_df["Is change"] == is_change]
            if sub.empty:
                continue
            nt = len(sub)
            nd = int(sub["Detected"].sum())
            nc = int(sub["Correct"].sum())
            st.markdown(f"**{label}** — {nt} cases")
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("Detected (any name)",  f"{nd/nt*100:.1f}%", help=f"{nd}/{nt}")
            sc2.metric("Name matched GT",       f"{nc/nt*100:.1f}%", help=f"{nc}/{nt}")
            sc3.metric("Missed entirely",       f"{(nt-nd)/nt*100:.1f}%", help=f"{nt-nd}/{nt}")

        st.markdown("**Breakdown by field**")
        for field_name in ["fname", "lname"]:
            sub = m2_df[m2_df["Field"] == field_name]
            if sub.empty:
                continue
            nt = len(sub)
            nc = int(sub["Correct"].sum())
            nd = int(sub["Detected"].sum())
            st.write(f"**{field_name.capitalize()}** — {nc}/{nt} correct ({nc/nt*100:.1f}%),  {nd}/{nt} detected ({nd/nt*100:.1f}%)")

        with st.expander("View all name detection events"):
            disp = m2_df[["Field", "Entry #", "GT name", "First reply", "Model name", "Detected", "Correct"]].copy()
            disp["Entry #"] = disp["Entry #"].apply(_ordinal).rename("Name #")
            disp = disp.rename(columns={"Entry #": "Name #"})
            st.dataframe(disp, use_container_width=True, hide_index=True)
    else:
        st.info("No name entries found in 100%-agreed conversations.")

    st.markdown("---")

    # ── Display Metric 3 ──────────────────────────────────────────────────────
    st.markdown("### 3 · Name count vs model accuracy")
    st.caption("Does having more names in a conversation reduce model accuracy?")

    m3_df = pd.DataFrame(m3_rows)
    m3_df = m3_df[m3_df["n_names"] > 0].copy()

    if not m3_df.empty:
        m3_df["group"] = m3_df["n_names"].astype(str)
        m3_agg = (
            m3_df.groupby("group")
            .agg(avg_acc=("accuracy", "mean"), n_convs=("accuracy", "count"))
            .reset_index()
        )
        m3_agg["avg_acc_pct"] = (m3_agg["avg_acc"] * 100).round(1)
        sort_order = sorted(m3_agg["group"].unique(), key=lambda x: int(x))

        m3_sel = alt.selection_point(fields=["group"], name="m3_sel")
        m3_chart = (
            alt.Chart(m3_agg)
            .mark_bar()
            .encode(
                x=alt.X("group:N", sort=sort_order, title="Number of name entries",
                         axis=alt.Axis(**_ax)),
                y=alt.Y("avg_acc_pct:Q", scale=alt.Scale(domain=[0, 100]),
                         title="Avg name accuracy (%)", axis=alt.Axis(**_ax)),
                color=alt.condition(m3_sel, alt.value("#8B5CF6"), alt.value("#C4B5FD")),
                tooltip=[
                    alt.Tooltip("group:N",       title="Name entries"),
                    alt.Tooltip("avg_acc_pct:Q", title="Avg accuracy %", format=".1f"),
                    alt.Tooltip("n_convs:Q",     title="Conversations"),
                ],
            )
            .add_params(m3_sel)
            .properties(height=280, background="#EFF6FF")
            .configure_view(strokeWidth=0)
        )

        m3_event = st.altair_chart(m3_chart, use_container_width=True, on_select="rerun")
        st.caption("Click a bar to see per-conversation name breakdown for that group.")

        st.dataframe(
            m3_agg.rename(columns={"group": "Name entries", "avg_acc_pct": "Avg accuracy (%)", "n_convs": "Conversations"})[
                ["Name entries", "Conversations", "Avg accuracy (%)"]
            ],
            hide_index=True, use_container_width=False,
        )

        # ── Detail view on bar click ───────────────────────────────────────────
        selected_group = None
        if m3_event and m3_event.get("selection"):
            sel_vals = [v for v in m3_event["selection"].values() if v]
            if sel_vals and sel_vals[0]:
                selected_group = sel_vals[0][0].get("group")

        if selected_group and m2_rows:
            m2_full = pd.DataFrame(m2_rows)
            m2_full["group"] = m2_full["chat_id"].map(
                lambda c: m3_df.set_index("chat_id")["n_names"].get(c, 0)
            ).apply(lambda n: str(n))

            detail = m2_full[m2_full["group"] == selected_group].copy()
            mistakes = detail[detail["Correct"] == False]

            st.markdown(f"**Detail — {selected_group} name(s) per conversation**")
            if mistakes.empty:
                st.success("No mistakes in this group — model got all names right.")
            else:
                # One row per name entry: show chat_id, field, GT, model prediction, correct
                disp = mistakes[["chat_id", "Field", "Is change", "GT name", "Model name", "Detected"]].copy()
                disp["Is change"] = disp["Is change"].map({True: "Name change", False: "First"})
                disp["chat_id"]   = disp["chat_id"].str[:20] + "…"

                # Also show the correct ones in the same group for context
                all_detail = detail[["chat_id", "Field", "Entry #", "First reply", "GT name", "Model name", "Correct"]].copy()
                all_detail["Entry #"]   = all_detail["Entry #"].apply(_ordinal)
                all_detail = all_detail.rename(columns={"Entry #": "Name #"})
                all_detail["chat_id"]   = all_detail["chat_id"].str[:20] + "…"
                all_detail["✓"] = all_detail["Correct"].map({True: "✅", False: "❌"})
                all_detail = all_detail.drop(columns=["Correct"])

                st.dataframe(
                    _style_groups(all_detail, cid_col="chat_id"),
                    use_container_width=True,
                    hide_index=True,
                )
    else:
        st.info("Not enough data for name count analysis.")

    st.markdown("---")

    # ── Display Metric 4 ──────────────────────────────────────────────────────
    st.markdown("### 4 · Forgetting — how long until the model loses context")
    st.caption(
        "A forgetting event occurs when the model was previously correct on a reply "
        "but gives a wrong answer on a later reply where GT still expects the same answer. "
        "Gap = number of replies between last correct and first wrong."
    )

    m4_fields = [
        ("is_contact", m4_contact_gaps),
        ("fname",      m4_fname_gaps),
        ("lname",      m4_lname_gaps),
    ]
    m4_color_scale = alt.Scale(
        domain=["is_contact", "fname", "lname"],
        range=["#3B82F6", "#10B981", "#F59E0B"],
    )

    # Summary table
    m4_summary_rows = []
    for m4_field, m4_gaps in m4_fields:
        if m4_gaps:
            avg_gap = round(sum(m4_gaps) / len(m4_gaps), 1)
            med_gap = sorted(m4_gaps)[len(m4_gaps) // 2]
        else:
            avg_gap = med_gap = "—"
        m4_summary_rows.append({
            "Field":            m4_field,
            "Events":           len(m4_gaps),
            "Avg gap (replies)": avg_gap,
            "Median gap":       med_gap,
        })
    st.dataframe(pd.DataFrame(m4_summary_rows), hide_index=True, use_container_width=False)

    # Combined chart — all 3 fields in one grouped histogram
    m4_all_rows = []
    for m4_field, m4_gaps in m4_fields:
        for g in m4_gaps:
            m4_all_rows.append({"Field": m4_field, "Gap": g})

    if m4_all_rows:
        m4_df = pd.DataFrame(m4_all_rows)
        m4_agg = m4_df.groupby(["Gap", "Field"]).size().reset_index(name="Count")
        st.altair_chart(
            alt.Chart(m4_agg)
            .mark_bar()
            .encode(
                x=alt.X("Gap:O", title="Replies until forgotten", axis=alt.Axis(**_ax)),
                xOffset=alt.XOffset("Field:N", sort=["is_contact", "fname", "lname"]),
                y=alt.Y("Count:Q", title="Events", axis=alt.Axis(**_ax)),
                color=alt.Color("Field:N", scale=m4_color_scale,
                                sort=["is_contact", "fname", "lname"],
                                legend=alt.Legend(labelColor="#1E3A5F", titleColor="#1E3A5F")),
                tooltip=["Field:N", alt.Tooltip("Gap:O", title="Gap"), "Count:Q"],
            )
            .properties(height=260, background="#EFF6FF")
            .configure_view(strokeWidth=0),
            use_container_width=True,
        )
    else:
        st.info("No forgetting events detected across any field.")
