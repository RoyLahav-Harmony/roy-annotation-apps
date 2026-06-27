"""
contact_discovery_annotator.py

Annotation tool for contact-discovery simplified JSON files.
Upload the simplified JSON exported from live_dashboard.py, annotate each
conversation, then download the result as an annotated JSON.

Usage:
    streamlit run contact_discovery_annotator.py
"""

import json
import re
import html as _html
import requests
import streamlit as st
import bcrypt
from datetime import datetime, timezone
from pymongo import MongoClient

# ── MongoDB connection ─────────────────────────────────────────────────────────

@st.cache_resource
def _get_mongo_client():
    # Raise on failure — @st.cache_resource only caches successful connections.
    client = MongoClient(st.secrets["mongodb"]["uri"], serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    return client

def _get_mongo_collection():
    try:
        return _get_mongo_client()["roy's_projects"]["contact_discovery"]
    except Exception:
        return None

def _get_source_collection(project_name="contact_discovery"):
    try:
        return _get_mongo_client()["Roy_source_files"][project_name]
    except Exception:
        return None

def _list_source_projects():
    try:
        return sorted(_get_mongo_client()["Roy_source_files"].list_collection_names())
    except Exception:
        return []

def _load_source_project(project_name):
    try:
        return list(_get_mongo_client()["Roy_source_files"][project_name].find({}, {"_id": 0}))
    except Exception:
        return []

def _list_annotation_projects():
    try:
        return sorted(_get_mongo_client()["roy's_projects"].list_collection_names())
    except Exception:
        return []

def _load_my_annotations(project_name, annotator):
    try:
        return list(_get_mongo_client()["roy's_projects"][project_name].find(
            {"annotator": annotator}, {"_id": 0}
        ))
    except Exception:
        return []

# ── Spellcheck ────────────────────────────────────────────────────────────────

try:
    from spellchecker import SpellChecker as _SpellChecker
    _spell = _SpellChecker()
    SPELLCHECK = True
except ImportError:
    SPELLCHECK = False

st.set_page_config(page_title="Contact Discovery Annotator", layout="wide", page_icon="🔍")

# ── CSS ────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"], .stApp {
    font-family: 'Inter', sans-serif !important;
}

#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
[data-testid="stToolbar"]    { display: none; }
[data-testid="stDecoration"] { display: none; }

.stApp { background-color: #F1F5F9; }

.stApp p, .stApp li, .stApp span, .stApp label,
.stApp div, .stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: #0F172A; }

.stApp [data-testid="stCaptionContainer"] p,
.stApp small { color: #64748B !important; }

.stApp .stButton > button[kind="primary"],
.stApp .stButton > button[kind="primary"] *,
.stApp .stDownloadButton > button,
.stApp .stDownloadButton > button * { color: #FFFFFF !important; }

.stApp .stButton > button[kind="secondary"] {
    background-color: #FFFFFF !important;
    border: 1px solid #CBD5E1 !important;
    color: #0F172A !important;
}
.stApp .stButton > button[kind="secondary"] * { color: #0F172A !important; }

/* Light-blue background for all secondary buttons */
[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-secondaryFormSubmit"] {
    background-color: #EFF6FF !important;
    border-color: #93C5FD !important;
    color: #1E3A5F !important;
}

hr { border-color: #E2E8F0 !important; margin: 1rem 0; }

[data-testid="stInfo"]    { border-radius: 8px; }
[data-testid="stWarning"] { border-radius: 8px; }
[data-testid="stSuccess"] { border-radius: 8px; }

/* ── Selectboxes — bright background, dark text ── */
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

/* ── Text inputs — bright background, dark text ── */
.stMain input[type="text"],
.stMain textarea {
    background: #EFF6FF !important;
    color: #0F172A !important;
    border-color: #93C5FD !important;
}
.stMain input[type="text"]::placeholder,
.stMain textarea::placeholder {
    color: #94A3B8 !important;
    opacity: 1 !important;
}
/* Disabled textareas (e.g. "exact text sent to model") keep the same bright style */
.stMain textarea:disabled,
.stMain textarea[disabled] {
    background: #EFF6FF !important;
    color: #0F172A !important;
    -webkit-text-fill-color: #0F172A !important;
    opacity: 1 !important;
}
/* Expander header — bright background, dark text */
[data-testid="stExpander"] details summary {
    background: #DBEAFE !important;
    color: #0F172A !important;
    border-radius: 6px;
}
[data-testid="stExpander"] details summary * {
    color: #0F172A !important;
}

/* ── Field captions/labels — larger, bold, black ── */
.stMain [data-testid="stCaptionContainer"] p {
    font-size: 0.92rem !important;
    font-weight: 700 !important;
    color: #0F172A !important;
}
.stMain label {
    font-size: 0.92rem !important;
    font-weight: 700 !important;
    color: #0F172A !important;
}

/* ── File uploader ── */
[data-testid="stFileUploader"] {
    background: white;
    border-radius: 10px;
    padding: 4px;
}
[data-testid="stFileUploaderDropzone"] {
    background: white !important;
}
[data-testid="stFileUploaderDropzone"] * {
    color: #0F172A !important;
}
[data-testid="stFileUploaderDropzone"] small,
[data-testid="stFileUploaderDropzone"] span {
    color: #64748B !important;
}
[data-testid="stFileUploaderDropzone"] button {
    background-color: #2563EB !important;
    color: #FFFFFF !important;
}
[data-testid="stFileUploaderDropzone"] button * {
    color: #FFFFFF !important;
}

/* ── Download button — always readable ── */
.stApp .stDownloadButton > button {
    background-color: #2563EB !important;
    color: #FFFFFF !important;
}
.stApp .stDownloadButton > button * {
    color: #FFFFFF !important;
}

/* ── Two-column layout ── */

[data-testid="stHorizontalBlock"] {
    align-items: flex-start !important;
}

/* Scrollable st.container(border=True, height=X) — overflow is a direct HTML attribute */
[data-testid="stVerticalBlock"][overflow="auto"] {
    border: 2px solid #3B82F6 !important;
    border-radius: 10px !important;
    box-shadow: 0 0 0 2px #3B82F6 !important;
}
/* Plain st.container(border=True) — handled via JS below for precision */
[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stVerticalBlockBorderWrapper"] > div {
    border: 2px solid #3B82F6 !important;
    border-radius: 10px !important;
    box-shadow: 0 0 0 2px #3B82F6 !important;
}



/* ── Left: scrollable conversation ── */
.conv-id {
    font-size: 0.72rem;
    color: #64748B;
    font-family: monospace;
    margin-bottom: 8px;
}

/* edited turn gets an amber left border */
.turn-edited {
    border-left-color: #F59E0B !important;
    background: #FFFBEB !important;
}
.edited-badge {
    font-size: 0.68rem;
    color: #B45309;
    margin-top: 2px;
}
.turn-active-edit {
    border-left-color: #7C3AED !important;
    background: #F5F3FF !important;
}
.turn-inserting-after {
    border-left-color: #A78BFA !important;
    background: #EDE9FE !important;
}
.turn-pending-delete {
    border-left-color: #DC2626 !important;
    background: #FEF2F2 !important;
}

.turn-reply {
    background: #EFF6FF;
    border: 1px solid #BFDBFE;
    border-left: 4px solid #2563EB;
    border-radius: 8px;
    padding: 10px 14px;
    margin-bottom: 8px;
}
.turn-assistant {
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-left: 4px solid #94A3B8;
    border-radius: 8px;
    padding: 10px 14px;
    margin-bottom: 8px;
}
.turn-label {
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 5px;
}
.reply-label { color: #2563EB; }
.asst-label  { color: #94A3B8; }

/* ── Right: annotation panel ── */
.panel-header {
    background: white;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 14px;
}
.panel-header h3 {
    margin: 0 0 2px 0;
    font-size: 1rem;
    font-weight: 700;
    color: #0F172A;
}
.panel-header p {
    margin: 0;
    font-size: 0.78rem;
    color: #64748B;
}

.annotated-badge {
    display: inline-block;
    background: #D1FAE5;
    color: #065F46;
    border: 1px solid #6EE7B7;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.72rem;
    font-weight: 600;
    margin-left: 8px;
}
</style>
""", unsafe_allow_html=True)

# ── JS: keyboard shortcut block + inner section borders ───────────────────────
import streamlit.components.v1 as _components
_components.html("""
<script>
(function() {
    // Block Cmd+C / Ctrl+C from triggering Streamlit's clear-cache shortcut
    window.parent.addEventListener('keydown', function(e) {
        if (e.metaKey || e.ctrlKey || e.altKey) {
            e.stopImmediatePropagation();
        }
    }, true);

    // Add borders to section-level stLayoutWrapper in the right pane only.
    // Uses JS so we can check actual parent chains rather than guessing CSS selectors.
    function applyBorders() {
        var doc = window.parent.document;
        var panes = doc.querySelectorAll('[data-testid="stVerticalBlock"][overflow="auto"]');
        if (panes.length < 2) return;

        var rightPane = panes[panes.length - 1];

        // Clear any previously injected styles on all stLayoutWrapper in both panes
        doc.querySelectorAll('[data-testid="stLayoutWrapper"]').forEach(function(el) {
            el.style.removeProperty('border');
            el.style.removeProperty('border-radius');
            el.style.removeProperty('box-shadow');
        });

        // Add borders only to section-level wrappers in the right pane:
        // those whose closest stLayoutWrapper ancestor is the right pane boundary.
        rightPane.querySelectorAll('[data-testid="stLayoutWrapper"]').forEach(function(el) {
            var p = el.parentElement;
            var nested = false;
            while (p && p !== rightPane) {
                if (p.getAttribute('data-testid') === 'stLayoutWrapper') {
                    nested = true;
                    break;
                }
                p = p.parentElement;
            }
            if (!nested) {
                el.style.setProperty('border',        '1px solid #93C5FD', 'important');
                el.style.setProperty('border-radius', '10px',              'important');
                el.style.setProperty('box-shadow',    'none',              'important');
            }
        });
    }

    // Re-run after every Streamlit re-render (debounced)
    var _t;
    new MutationObserver(function() {
        clearTimeout(_t);
        _t = setTimeout(applyBorders, 120);
    }).observe(window.parent.document.body, { childList: true, subtree: true });

    applyBorders();
})();
</script>
""", height=0)

# ── Login ─────────────────────────────────────────────────────────────────────

def _check_login(username, password):
    try:
        users = st.secrets["users"]
        key = username.strip().lower()
        if key not in users:
            return False, None
        stored_hash = users[key]["password_hash"].encode()
        if bcrypt.checkpw(password.encode(), stored_hash):
            return True, users[key]["name"]
        return False, None
    except Exception:
        return False, None

if not st.session_state.get("authenticated"):
    st.markdown("## 🔍 Contact Discovery Annotator")
    st.markdown("Please log in to continue.")
    username_input = st.text_input("Username", placeholder="e.g. roy")
    password_input = st.text_input("Password", type="password")
    if st.button("Log in", type="primary", disabled=not (username_input.strip() and password_input)):
        ok, display_name = _check_login(username_input, password_input)
        if ok:
            st.session_state["authenticated"]  = True
            st.session_state["annotator_name"] = display_name
            st.rerun()
        else:
            st.error("Incorrect username or password.")
    st.stop()

annotator_name = st.session_state["annotator_name"]
_cap_col, _logout_col = st.columns([6, 1])
_cap_col.caption(f"Logged in as **{annotator_name}**")
if _logout_col.button("Log out", use_container_width=True):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# ── Data source ────────────────────────────────────────────────────────────────

def _ingest_conversations(data, label):
    """Shared logic for loading conversations into session state from any source."""
    import time
    for conv in data:
        if conv.get("turns") and "assistant" in conv["turns"][-1]:
            conv["turns"] = conv["turns"][:-1]
    st.session_state["conversations"] = data
    st.session_state["annotations"]   = {}
    st.session_state["conv_index"]    = 0
    st.session_state["_loaded_file"]  = label
    st.session_state["_load_id"]      = str(int(time.time() * 1000))
    source_words = set()
    for conv in data:
        for turn in conv.get("turns", []):
            text = list(turn.values())[0] if turn else ""
            source_words.update(re.findall(r"\b[a-zA-Z']{2,}\b", str(text).lower()))
    st.session_state["_source_words"] = source_words

source_mode = st.radio(
    "Load conversations from:",
    ["📂 Upload a file", "☁️ MongoDB project"],
    horizontal=True,
    label_visibility="collapsed",
)

if source_mode == "📂 Upload a file":
    uploaded = st.file_uploader("Upload simplified JSON", type="json", label_visibility="collapsed")
    if uploaded is not None and st.session_state.get("_loaded_file") != uploaded.name:
        _ingest_conversations(json.load(uploaded), uploaded.name)

else:
    try:
        _get_mongo_client()
        _mongo_ok = True
    except Exception as _mongo_err:
        _mongo_ok = False
        st.error(f"MongoDB connection failed: {_mongo_err}")

    projects = _list_source_projects() if _mongo_ok else []
    if _mongo_ok and not projects:
        st.warning("No projects found in MongoDB. Upload source files to the Roy_source_files database via Compass.")
    else:
        selected_project = st.selectbox("Select project", options=projects)
        skip_annotated = st.checkbox(
            "Skip conversations I've already annotated",
            value=True,
        )
        if st.button("⬇️ Load from MongoDB", type="primary"):
            with st.spinner(f"Loading '{selected_project}' from MongoDB…"):
                data = _load_source_project(selected_project)
            if not data:
                st.error(f"No conversations found in '{selected_project}'.")
            else:
                if skip_annotated:
                    col = _get_mongo_collection()
                    if col is not None:
                        done_ids = {
                            d["chat_id"] for d in
                            col.find({"annotator": annotator_name}, {"chat_id": 1})
                        }
                        original_count = len(data)
                        data = [c for c in data if c.get("chat_id") not in done_ids]
                        skipped = original_count - len(data)
                        if skipped:
                            st.info(f"Skipping {skipped} already annotated conversation(s).")
                if not data:
                    st.warning("All conversations in this project have already been annotated by you.")
                else:
                    _ingest_conversations(data, f"mongodb:{selected_project}")
                    st.success(f"Loaded {len(data)} conversation(s) from '{selected_project}'.")
                    st.rerun()

if "conversations" not in st.session_state:
    st.info("Load a project from MongoDB or upload a JSON file above to begin.")
    st.stop()

# ── Load previous annotations (optional) ──────────────────────────────────────

def _restore_annotations(ann_data, label):
    """Shared logic for restoring annotations from any source (file or MongoDB)."""
    loaded_n  = 0
    orig_by_id = {c["chat_id"]: c["turns"] for c in st.session_state["conversations"]}

    for item in ann_data:
        cid    = item.get("chat_id")
        labels = item.get("Labels", {})
        if not cid or cid not in orig_by_id:
            continue

        # ── Restore labels ────────────────────────────────────────────────
        if labels:
            st.session_state["annotations"][cid] = labels
            n_speakers = sum(1 for k in labels if k.startswith("speaker "))
            st.session_state.pop(f"contacts__{cid}", None)
            for sp_i in range(max(n_speakers, 5)):
                for field in ["fname_na", "fname_n",
                              "lname_na", "lname_n",
                              "speaker_start", "speaker_end", "speaker_na",
                              "intro_inc_start", "intro_inc_end", "intro_inc_na",
                              "intro_exc_start", "intro_exc_end", "intro_exc_na",
                              "name_known"]:
                    st.session_state.pop(f"{field}__{cid}__{sp_i}", None)
                for _j in range(10):
                    for _fld in ["fname", "fname_start", "fname_end", "fname_turns_na",
                                 "lname", "lname_start", "lname_end", "lname_turns_na"]:
                        st.session_state.pop(f"{_fld}__{cid}__{sp_i}__{_j}", None)

        # ── Restore edited / inserted turns ───────────────────────────────
        ann_turns  = item.get("turns", [])
        orig_turns = orig_by_id[cid]
        if ann_turns and ann_turns != orig_turns:
            st.session_state[f"working_turns__{cid}"] = [dict(t) for t in ann_turns]
            edited, new = set(), set()
            for i, t in enumerate(ann_turns):
                fk = list(t.keys())[0]
                if i >= len(orig_turns):
                    new.add(i)
                else:
                    ok = list(orig_turns[i].keys())[0]
                    if fk != ok:
                        new.add(i)
                    elif t[fk] != orig_turns[i][ok]:
                        edited.add(i)
            st.session_state[f"edited_indices__{cid}"] = edited
            st.session_state[f"new_indices__{cid}"]    = new

        loaded_n += 1

    st.session_state["_loaded_ann_file"] = label
    return loaded_n

with st.expander("↩ Load previous annotations"):
    ann_mode = st.radio(
        "Load from:",
        ["📂 Upload a file", "☁️ MongoDB"],
        horizontal=True,
        key="ann_mode_radio",
        label_visibility="collapsed",
    )

    if ann_mode == "📂 Upload a file":
        ann_upload = st.file_uploader(
            "Upload a previously exported annotated JSON",
            type="json",
            key="ann_uploader",
            label_visibility="collapsed",
        )
        if ann_upload is not None and st.session_state.get("_loaded_ann_file") != ann_upload.name:
            n = _restore_annotations(json.load(ann_upload), ann_upload.name)
            st.success(f"Loaded {n} conversation(s) — labels and turn edits restored.")

    else:
        ann_projects = _list_annotation_projects()
        if not ann_projects:
            st.warning("No annotation projects found in MongoDB.")
        else:
            ann_project = st.selectbox("Select project", options=ann_projects, key="ann_project_select")
            if st.button("↩ Load my annotations from MongoDB", use_container_width=True):
                with st.spinner("Loading your annotations from MongoDB…"):
                    ann_data = _load_my_annotations(ann_project, annotator_name)
                if not ann_data:
                    st.warning(f"No annotations found for '{annotator_name}' in '{ann_project}'.")
                else:
                    n = _restore_annotations(ann_data, f"mongodb:{ann_project}:{annotator_name}")
                    st.success(f"Restored {n} annotation(s) from MongoDB.")
                    st.rerun()


_all_conversations = st.session_state["conversations"]
annotations        = st.session_state["annotations"]

def _get_source(conv):
    """Return the source label for a conversation, falling back to 'agent' field."""
    return conv.get("source") or conv.get("agent")

# ── Source filter ──────────────────────────────────────────────────────────────
_all_sources = sorted({_get_source(c) for c in _all_conversations if _get_source(c)})
if _all_sources:
    # Tie the widget key to the load ID so it resets (uses default) on every new load.
    _load_id = st.session_state.get("_load_id", "0")
    _selected_sources = st.multiselect(
        "Filter by source",
        options=_all_sources,
        default=_all_sources,
        key=f"_source_filter_{_load_id}",
        placeholder="Showing all sources",
    )
    conversations = (
        [c for c in _all_conversations if _get_source(c) in _selected_sources]
        if _selected_sources else _all_conversations
    )
else:
    conversations = _all_conversations

n_total     = len(conversations)
n_annotated = sum(1 for c in conversations if c["chat_id"] in annotations)

if not conversations:
    st.warning("No conversations match the selected source filter.")
    st.stop()

idx     = max(0, min(st.session_state.get("conv_index", 0), n_total - 1))
conv    = conversations[idx]
chat_id = conv["chat_id"]
turns   = conv["turns"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_changes(orig_turns, working_turns, edited_indices, new_indices):
    """Return a list of change records, or None if nothing changed."""
    if (not edited_indices and not new_indices
            and len(orig_turns) == len(working_turns)):
        return None

    def _text(turn):
        return turn[list(turn.keys())[0]]

    changes = []

    # Non-new working turns correspond positionally to original turns
    non_new = [(i, working_turns[i]) for i in range(len(working_turns))
               if i not in new_indices]

    for j, (wi, wt) in enumerate(non_new):
        if j >= len(orig_turns):
            break
        orig_text = _text(orig_turns[j])
        work_text = _text(wt)
        if orig_text != work_text:
            changes.append({
                "type":    "edited",
                "was":     orig_text,
                "is now":  work_text,
            })

    # Original turns beyond non_new length were deleted
    for j in range(len(non_new), len(orig_turns)):
        changes.append({
            "type": "deleted",
            "was":  _text(orig_turns[j]),
        })

    # Newly inserted turns
    for wi in sorted(new_indices):
        changes.append({
            "type": "added",
            "text": _text(working_turns[wi]),
        })

    return changes if changes else None

def _renumber_turns(turn_list):
    """Re-sequence all 'reply N' keys in order after any insertion/deletion."""
    result, n = [], 0
    for t in turn_list:
        key = list(t.keys())[0]
        if key.startswith("reply "):
            result.append({f"reply {n}": t[key]})
            n += 1
        else:
            result.append(dict(t))
    return result

def _spell_check(text):
    if not SPELLCHECK or not text:
        return []
    source_words = st.session_state.get("_source_words", set())
    words = re.findall(r"\b[a-zA-Z']{2,}\b", text)
    # Exclude words already present in the source file (proper nouns, domain terms)
    novel_words = [w for w in words if w.lower() not in source_words]
    misspelled = _spell.unknown(novel_words)
    results = []
    for w in misspelled:
        candidates = list((_spell.candidates(w) or set()) - {w})[:3]
        results.append((w, candidates))
    return results

def _render_spell_errors(issues, key_prefix):
    """Render each spelling error with a 'Mark as name' button.
    Returns True if blocking errors still remain."""
    if not issues:
        return False
    st.error("Spelling errors must be fixed or marked as a name before saving:")
    for word, candidates in issues:
        wcol, scol, bcol = st.columns([1, 2, 1])
        wcol.markdown(f"**{word}**")
        scol.caption("→ " + (", ".join(candidates) if candidates else "no suggestions"))
        if bcol.button("Mark as name", key=f"mark_name__{key_prefix}__{word}",
                       use_container_width=True):
            st.session_state.setdefault("_source_words", set()).add(word.lower())
            st.rerun()
    return True

def _grammar_check(text):
    """Call LanguageTool public API and return grammar issues (spelling excluded)."""
    if not text or not text.strip():
        return []
    try:
        resp = requests.post(
            "https://api.languagetool.org/v2/check",
            data={"text": text, "language": "en-US"},
            timeout=10,
        )
        resp.raise_for_status()
        matches = resp.json().get("matches", [])
        return [
            (m["offset"], m["length"], m["message"],
             [r["value"] for r in m.get("replacements", [])[:3]])
            for m in matches
            if m.get("rule", {}).get("issueType") != "misspelling"
        ]
    except Exception:
        return []

def _render_grammar_preview(text, issues):
    """Render text with blue wavy underlines under grammar issues."""
    if not issues:
        st.info("✅ No grammar issues found.")
        return
    html_parts = []
    prev_end = 0
    for offset, length, message, replacements in sorted(issues, key=lambda x: x[0]):
        html_parts.append(_html.escape(text[prev_end:offset]).replace("\n", "<br>"))
        word = _html.escape(text[offset:offset + length])
        tip  = _html.escape(message)
        if replacements:
            tip += " → " + ", ".join(_html.escape(r) for r in replacements)
        html_parts.append(
            f'<span style="text-decoration:underline wavy #2563EB;cursor:help;" title="{tip}">{word}</span>'
        )
        prev_end = offset + length
    html_parts.append(_html.escape(text[prev_end:]).replace("\n", "<br>"))
    st.markdown(
        f'<div style="background:#EFF6FF;border:1px solid #93C5FD;border-radius:6px;'
        f'padding:10px 14px;font-size:0.9rem;line-height:1.6;font-family:inherit;">'
        f'{"".join(html_parts)}</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"ℹ️ {len(issues)} grammar suggestion(s) — won't block saving")

# ── Working turns (mutable copy — edits & insertions applied here) ────────────

wt_key      = f"working_turns__{chat_id}"
edited_key  = f"edited_indices__{chat_id}"
new_key     = f"new_indices__{chat_id}"
if wt_key not in st.session_state:
    st.session_state[wt_key]     = [dict(t) for t in turns]
    st.session_state[edited_key] = set()
    st.session_state[new_key]    = set()
working_turns  = st.session_state[wt_key]
edited_indices = st.session_state[edited_key]
new_indices    = st.session_state[new_key]

# reply_numbers comes from working_turns (may include inserted turns)
reply_numbers = [
    int(key.split(" ", 1)[1])
    for t in working_turns
    for key in [list(t.keys())[0]]
    if key.startswith("reply ")
]

# Flag: last turn must not be an agent turn
_last_turn_is_agent = (
    bool(working_turns) and "assistant" in working_turns[-1]
)

# ── Contact helpers (needed by both columns) ──────────────────────────────────

def _make_range(start, end):
    if start is None or end is None:
        return []
    return list(range(start, end + 1))

def _norm_name_entries(data):
    """Normalize Fname/Lname data to a list of [name, turns] pairs.
    Handles both old format ["name", [turns]] and new format [["name", [turns]], ...].
    Returns [] if data is "N/A" or empty."""
    if not data or data == "N/A":
        return []
    if isinstance(data[0], str):
        return [data]  # old single-name format → wrap
    return data

def _read_contacts_from_widgets(cid, n):
    contacts = []
    for i in range(n):
        fname_na     = st.session_state.get(f"fname_na__{cid}__{i}", False)
        lname_na     = st.session_state.get(f"lname_na__{cid}__{i}", False)
        speaker_na   = st.session_state.get(f"speaker_na__{cid}__{i}", False)
        intro_inc_na = st.session_state.get(f"intro_inc_na__{cid}__{i}", False)
        intro_exc_na = st.session_state.get(f"intro_exc_na__{cid}__{i}", False)

        # ── First names (multiple entries) ────────────────────────────────
        if fname_na:
            fname_val = "N/A"
        else:
            fn_count = st.session_state.get(f"fname_n__{cid}__{i}", 1)
            fname_entries = []
            for j in range(fn_count):
                ftn_na = st.session_state.get(f"fname_turns_na__{cid}__{i}__{j}", False)
                fname_entries.append([
                    st.session_state.get(f"fname__{cid}__{i}__{j}", "").strip().title(),
                    "N/A" if ftn_na else _make_range(
                        st.session_state.get(f"fname_start__{cid}__{i}__{j}"),
                        st.session_state.get(f"fname_end__{cid}__{i}__{j}"),
                    ),
                ])
            fname_val = fname_entries

        # ── Last names (multiple entries) ─────────────────────────────────
        if lname_na:
            lname_val = "N/A"
        else:
            ln_count = st.session_state.get(f"lname_n__{cid}__{i}", 1)
            lname_entries = []
            for j in range(ln_count):
                ltn_na = st.session_state.get(f"lname_turns_na__{cid}__{i}__{j}", False)
                lname_entries.append([
                    st.session_state.get(f"lname__{cid}__{i}__{j}", "").strip().title(),
                    "N/A" if ltn_na else _make_range(
                        st.session_state.get(f"lname_start__{cid}__{i}__{j}"),
                        st.session_state.get(f"lname_end__{cid}__{i}__{j}"),
                    ),
                ])
            lname_val = lname_entries

        contacts.append({
            "Fname": fname_val,
            "Lname": lname_val,
            "contact_is_speaker": "N/A" if speaker_na else _make_range(
                st.session_state.get(f"speaker_start__{cid}__{i}"),
                st.session_state.get(f"speaker_end__{cid}__{i}"),
            ),
            "intro_includes_name": "N/A" if intro_inc_na else _make_range(
                st.session_state.get(f"intro_inc_start__{cid}__{i}"),
                st.session_state.get(f"intro_inc_end__{cid}__{i}"),
            ),
            "intro_doesnt_include_name": "N/A" if intro_exc_na else _make_range(
                st.session_state.get(f"intro_exc_start__{cid}__{i}"),
                st.session_state.get(f"intro_exc_end__{cid}__{i}"),
            ),
            "contact_name_known": st.session_state.get(f"name_known__{cid}__{i}"),
        })
    return contacts

# ── Two-column layout ──────────────────────────────────────────────────────────

# ── Navigation rows ────────────────────────────────────────────────────────────

# Row 1 — jump controls
_r1a, _r1b, _r1c, _r1d = st.columns([1.5, 2.5, 0.6, 1.8])

if _r1a.button("⏮ Jump to start", disabled=(idx == 0), use_container_width=True):
    st.session_state["conv_index"] = 0
    st.rerun()

_chat_id_jump = _r1b.text_input("chat_id", placeholder="enter chat_id",
                                  label_visibility="collapsed")
if _r1c.button("Go", use_container_width=True):
    _all_ids = [c["chat_id"] for c in conversations]
    if _chat_id_jump.strip() in _all_ids:
        st.session_state["conv_index"] = _all_ids.index(_chat_id_jump.strip())
        st.rerun()
    else:
        st.error(f"Chat ID not found: {_chat_id_jump.strip()}")

_annotated_ids = set(annotations.keys())
_last_ann_idx  = max(
    (i for i, c in enumerate(conversations) if c["chat_id"] in _annotated_ids),
    default=None,
)
if _last_ann_idx is not None:
    _next_ann = min(_last_ann_idx + 1, n_total - 1)
    if _r1d.button(f"⏭ Last annotated (→ {_next_ann + 1})", use_container_width=True):
        st.session_state["conv_index"] = _next_ann
        st.rerun()

# Row 2 — per-conversation navigation
_r2a, _r2c = st.columns(2)

if _r2a.button("← Back", disabled=(idx == 0), use_container_width=True):
    st.session_state["conv_index"] = idx - 1
    st.rerun()

if _r2c.button("Next →", disabled=(idx >= n_total - 1), use_container_width=True):
    st.session_state["conv_index"] = idx + 1
    st.rerun()

st.markdown("---")

left, right = st.columns([1.3, 1], gap="large")

# ── LEFT: scrollable conversation ─────────────────────────────────────────────

with left:
    st.markdown(f'<div class="conv-id">{_html.escape(chat_id)}</div>', unsafe_allow_html=True)

    active_edit    = st.session_state.get(f"active_edit__{chat_id}")
    inserting_after = st.session_state.get(f"inserting_after__{chat_id}")
    panel_open     = active_edit is not None or inserting_after is not None

    # ── Height control ────────────────────────────────────────────────────────
    if "left_h" not in st.session_state:
        st.session_state["left_h"] = 820
    _lc1, _lc2, _lc3 = st.columns([3, 1, 1])
    _lc1.caption(f"Height: {st.session_state['left_h']}px")
    if _lc2.button("▼", key="left_h_up",   use_container_width=True):
        st.session_state["left_h"] = min(1400, st.session_state["left_h"] + 100)
        st.rerun()
    if _lc3.button("▲", key="left_h_down", use_container_width=True):
        st.session_state["left_h"] = max(300,  st.session_state["left_h"] - 100)
        st.rerun()

    # ── Scrollable turn list ───────────────────────────────────────────────────
    with st.container(height=st.session_state["left_h"], border=True):
        for turn_idx, turn in enumerate(working_turns):
            key          = list(turn.keys())[0]
            current_text = turn[key]
            is_reply     = key.startswith("reply ")
            label_tag    = f"Reply {key.split(' ', 1)[1]}" if is_reply else "Agent"
            css_class    = "turn-reply" if is_reply else "turn-assistant"
            lbl_class    = "reply-label" if is_reply else "asst-label"
            is_new       = turn_idx in new_indices
            is_edited    = turn_idx in edited_indices
            is_active    = active_edit == turn_idx

            safe       = _html.escape(str(current_text)).replace("\n", "<br>")
            edited_cls  = " turn-edited" if is_edited else ""
            new_cls     = " turn-edited" if is_new else ""
            active_cls  = " turn-active-edit" if is_active else ""
            insert_cls  = " turn-inserting-after" if inserting_after == turn_idx else ""
            _pending_del = st.session_state.get(f"deleting_turn__{chat_id}") == turn_idx
            delete_cls  = " turn-pending-delete" if _pending_del else ""

            chk_col, bubble_col, up_col, dn_col, edit_col, ins_col, del_col = st.columns([0.05, 0.67, 0.05, 0.05, 0.06, 0.06, 0.06])
            with chk_col:
                if is_reply:
                    _key = f"model_turn__{chat_id}__{turn_idx}"
                    if _key not in st.session_state:
                        st.session_state[_key] = False
                    st.checkbox("", key=_key, label_visibility="collapsed",
                                help="Run model on conversation up to and including this reply")
            with bubble_col:
                badge = ""
                if is_new:
                    badge = "<div class='edited-badge'>✨ new</div>"
                elif is_edited:
                    badge = "<div class='edited-badge'>✏️ edited</div>"
                st.markdown(
                    f'<div class="{css_class}{edited_cls}{new_cls}{active_cls}{insert_cls}{delete_cls}">'
                    f'<div class="turn-label {lbl_class}">{label_tag}</div>'
                    f'{safe}{badge}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            def _swap(idx_a, idx_b):
                """Swap two turns and update tracking indices."""
                working_turns[idx_a], working_turns[idx_b] = working_turns[idx_b], working_turns[idx_a]
                def _remap(s):
                    return {(idx_b if i == idx_a else idx_a if i == idx_b else i) for i in s}
                st.session_state[edited_key] = _remap(edited_indices)
                st.session_state[new_key]    = _remap(new_indices)
                st.session_state[wt_key]     = _renumber_turns(working_turns)

            with up_col:
                if st.button("▲", key=f"up_btn__{chat_id}__{turn_idx}",
                             disabled=(turn_idx == 0), help="Move up"):
                    _swap(turn_idx, turn_idx - 1)
                    st.rerun()
            with dn_col:
                if st.button("▼", key=f"dn_btn__{chat_id}__{turn_idx}",
                             disabled=(turn_idx == len(working_turns) - 1), help="Move down"):
                    _swap(turn_idx, turn_idx + 1)
                    st.rerun()

            with edit_col:
                edit_icon = "✕" if is_active else "✏️"
                edit_tip  = "Cancel edit" if is_active else "Edit"
                if st.button(edit_icon, key=f"edit_btn__{chat_id}__{turn_idx}", help=edit_tip):
                    st.session_state[f"active_edit__{chat_id}"]     = None if is_active else turn_idx
                    st.session_state[f"inserting_after__{chat_id}"] = None
                    st.session_state.pop(f"ta__{chat_id}__{turn_idx}", None)
                    st.rerun()
            with ins_col:
                ins_icon = "✕" if inserting_after == turn_idx else "➕"
                ins_tip  = "Cancel insert" if inserting_after == turn_idx else "Insert a turn after this one"
                if st.button(ins_icon, key=f"ins_btn__{chat_id}__{turn_idx}", help=ins_tip):
                    st.session_state[f"inserting_after__{chat_id}"] = (
                        None if inserting_after == turn_idx else turn_idx
                    )
                    st.session_state[f"active_edit__{chat_id}"] = None
                    st.rerun()
            with del_col:
                _is_pending = st.session_state.get(f"deleting_turn__{chat_id}") == turn_idx
                _del_icon = "✕" if _is_pending else "🗑"
                _del_tip  = "Cancel delete" if _is_pending else "Delete this turn"
                if st.button(_del_icon, key=f"del_btn__{chat_id}__{turn_idx}", help=_del_tip):
                    if _is_pending:
                        st.session_state[f"deleting_turn__{chat_id}"] = None
                    else:
                        st.session_state[f"deleting_turn__{chat_id}"] = turn_idx
                        st.session_state[f"active_edit__{chat_id}"] = None
                        st.session_state[f"inserting_after__{chat_id}"] = None
                    st.rerun()

    # ── Edit panel ────────────────────────────────────────────────────────────
    if active_edit is not None and active_edit < len(working_turns):
        edit_turn    = working_turns[active_edit]
        edit_key     = list(edit_turn.keys())[0]
        is_reply     = edit_key.startswith("reply ")
        label_tag    = f"Reply {edit_key.split(' ', 1)[1]}" if is_reply else "Agent"
        current_text = edit_turn[edit_key]

        st.markdown(f"**Editing: {label_tag}**")
        new_text = st.text_area(
            label_tag,
            value=current_text,
            key=f"ta__{chat_id}__{active_edit}",
            label_visibility="collapsed",
            height=100,
        )
        spell_issues = _spell_check(new_text)
        has_spell_errors = _render_spell_errors(spell_issues, f"{chat_id}__{active_edit}")
        if not has_spell_errors and SPELLCHECK and new_text.strip():
            st.caption("✓ No spelling issues")

        # ── Grammar check (non-blocking) ──────────────────────────────────────
        _gc_key = f"grammar_result__{chat_id}__{active_edit}"
        if st.button("🔵 Check grammar", key=f"grammar_btn__{chat_id}__{active_edit}",
                     use_container_width=True, disabled=not new_text.strip()):
            with st.spinner("Checking grammar…"):
                _gc_issues = _grammar_check(new_text)
            st.session_state[_gc_key] = (new_text, _gc_issues)
            st.rerun()
        _gc_state = st.session_state.get(_gc_key)
        if _gc_state and _gc_state[0] == new_text:
            _render_grammar_preview(new_text, _gc_state[1])

        sc1, sc2 = st.columns(2)
        if sc1.button("✓ Save edit", key=f"save_t__{chat_id}__{active_edit}",
                      type="primary", use_container_width=True,
                      disabled=has_spell_errors):
            # Re-check at save time to catch the race where the button fires
            # before the disabled state has been re-rendered. Don't render a
            # second error box — the one above the button is already visible.
            if _spell_check(new_text):
                st.stop()
            else:
                _nc = len(st.session_state.get(f"contacts__{chat_id}", [{}]))
                if _nc:
                    st.session_state[f"contacts__{chat_id}"] = _read_contacts_from_widgets(chat_id, _nc)
                working_turns[active_edit] = {edit_key: new_text}
                st.session_state[wt_key] = working_turns
                edited_indices.add(active_edit)
                st.session_state[edited_key] = edited_indices
                st.session_state[f"active_edit__{chat_id}"] = None
                st.session_state.pop(f"ta__{chat_id}__{active_edit}", None)
                st.rerun()
        if sc2.button("✗ Cancel", key=f"cancel_t__{chat_id}__{active_edit}",
                      use_container_width=True):
            st.session_state[f"active_edit__{chat_id}"] = None
            st.session_state.pop(f"ta__{chat_id}__{active_edit}", None)
            st.rerun()

    # ── Insert panel ──────────────────────────────────────────────────────────
    elif inserting_after is not None:
        n_replies_before = sum(
            1 for t in working_turns[:inserting_after + 1]
            if list(t.keys())[0].startswith("reply ")
        )
        new_reply_n = n_replies_before

        turn_type = st.radio(
            "Turn type", ["User", "Agent"], horizontal=True,
            key=f"ins_type__{chat_id}",
        )
        placeholder = (f"Reply {new_reply_n} — user utterance"
                       if turn_type == "User" else "Agent response")
        st.markdown(f"**Insert {turn_type} turn after turn {inserting_after}**")
        new_turn_text = st.text_area(
            "New turn text",
            key=f"new_turn_text__{chat_id}",
            height=80,
            placeholder=placeholder,
        )
        ins_spell_issues = _spell_check(new_turn_text)
        has_ins_errors   = _render_spell_errors(ins_spell_issues, f"{chat_id}__ins")

        # ── Grammar check (non-blocking) ──────────────────────────────────────
        _igc_key = f"grammar_result__{chat_id}__ins"
        if st.button("🔵 Check grammar", key=f"grammar_btn__{chat_id}__ins",
                     use_container_width=True, disabled=not new_turn_text.strip()):
            with st.spinner("Checking grammar…"):
                _igc_issues = _grammar_check(new_turn_text)
            st.session_state[_igc_key] = (new_turn_text, _igc_issues)
            st.rerun()
        _igc_state = st.session_state.get(_igc_key)
        if _igc_state and _igc_state[0] == new_turn_text:
            _render_grammar_preview(new_turn_text, _igc_state[1])

        ip1, ip2 = st.columns(2)
        if ip1.button("✓ Insert", key=f"confirm_ins__{chat_id}",
                      type="primary", use_container_width=True,
                      disabled=has_ins_errors):
            if _spell_check(new_turn_text):
                st.stop()
            _nc = len(st.session_state.get(f"contacts__{chat_id}", [{}]))
            if _nc:
                st.session_state[f"contacts__{chat_id}"] = _read_contacts_from_widgets(chat_id, _nc)
            new_turn = (
                {f"reply {new_reply_n}": new_turn_text or ""}
                if turn_type == "User"
                else {"assistant": new_turn_text or ""}
            )
            working_turns.insert(inserting_after + 1, new_turn)
            st.session_state[edited_key] = {
                i + 1 if i > inserting_after else i for i in edited_indices
            }
            st.session_state[new_key] = (
                {i + 1 if i > inserting_after else i for i in new_indices}
                | {inserting_after + 1}
            )
            st.session_state[wt_key] = _renumber_turns(working_turns)
            st.session_state[f"inserting_after__{chat_id}"] = None
            st.session_state.pop(f"new_turn_text__{chat_id}", None)
            st.rerun()
        if ip2.button("✗ Cancel", key=f"cancel_ins__{chat_id}",
                      use_container_width=True):
            st.session_state[f"inserting_after__{chat_id}"] = None
            st.session_state.pop(f"new_turn_text__{chat_id}", None)
            st.rerun()

    # ── Delete confirmation panel ─────────────────────────────────────────────
    elif st.session_state.get(f"deleting_turn__{chat_id}") is not None:
        del_idx = st.session_state[f"deleting_turn__{chat_id}"]
        if del_idx < len(working_turns):
            del_turn  = working_turns[del_idx]
            del_key   = list(del_turn.keys())[0]
            is_reply  = del_key.startswith("reply ")
            label_tag = f"Reply {del_key.split(' ', 1)[1]}" if is_reply else "Agent"
            preview   = str(del_turn[del_key])[:80] + ("…" if len(str(del_turn[del_key])) > 80 else "")

            st.markdown(f"**🗑 Delete: {label_tag}**")
            st.markdown(f"> *{preview}*")
            st.warning("Are you sure you want to delete this turn?")

            dc1, dc2 = st.columns(2)
            if dc1.button("✓ Yes, delete", key=f"confirm_del__{chat_id}",
                          type="primary", use_container_width=True):
                _nc = len(st.session_state.get(f"contacts__{chat_id}", [{}]))
                if _nc:
                    st.session_state[f"contacts__{chat_id}"] = _read_contacts_from_widgets(chat_id, _nc)
                working_turns.pop(del_idx)
                st.session_state[edited_key] = {
                    (i - 1 if i > del_idx else i) for i in edited_indices if i != del_idx
                }
                st.session_state[new_key] = {
                    (i - 1 if i > del_idx else i) for i in new_indices if i != del_idx
                }
                st.session_state[wt_key] = _renumber_turns(working_turns)
                st.session_state[f"deleting_turn__{chat_id}"] = None
                # Clear all turn-range selectbox values — reply numbers have
                # changed so stale values would crash the selectbox widget.
                _simple_range_fields = ["speaker_start", "speaker_end",
                                        "intro_inc_start", "intro_inc_end",
                                        "intro_exc_start", "intro_exc_end"]
                _nc = len(st.session_state.get(f"contacts__{chat_id}", [{}]))
                for _ci in range(_nc):
                    for _rf in _simple_range_fields:
                        st.session_state.pop(f"{_rf}__{chat_id}__{_ci}", None)
                    _fn_cnt = st.session_state.get(f"fname_n__{chat_id}__{_ci}", 1)
                    for _j in range(_fn_cnt):
                        for _rf in ["fname_start", "fname_end"]:
                            st.session_state.pop(f"{_rf}__{chat_id}__{_ci}__{_j}", None)
                    _ln_cnt = st.session_state.get(f"lname_n__{chat_id}__{_ci}", 1)
                    for _j in range(_ln_cnt):
                        for _rf in ["lname_start", "lname_end"]:
                            st.session_state.pop(f"{_rf}__{chat_id}__{_ci}__{_j}", None)
                st.rerun()
            if dc2.button("✗ Cancel", key=f"cancel_del__{chat_id}",
                          use_container_width=True):
                st.session_state[f"deleting_turn__{chat_id}"] = None
                st.rerun()

    if _last_turn_is_agent:
        st.warning(
            "⚠️ The last turn is an Agent turn. "
            "A conversation must end with a User (reply) turn. "
            "Move or delete the final Agent turn before saving."
        )

    # ── Model test ────────────────────────────────────────────────────────────
    st.markdown("---")
    with st.expander("🤖 Model Test"):
        st.caption("Use the checkboxes next to each turn above to select which turns to send.")

        n_turns = len(working_turns)
        # Derive n_contacts without depending on the right panel's variables
        _mt_contacts = st.session_state.get(f"contacts__{chat_id}", [{}])
        n_contacts_mt = len(_mt_contacts)

        # Indices of reply turns only
        reply_turn_indices = [
            j for j, t in enumerate(working_turns)
            if list(t.keys())[0].startswith("reply ")
        ]

        # ── Select All / Clear All ─────────────────────────────────────────
        def _select_all_turns():
            for j in reply_turn_indices:
                st.session_state[f"model_turn__{chat_id}__{j}"] = True

        def _clear_all_turns():
            for j in reply_turn_indices:
                st.session_state[f"model_turn__{chat_id}__{j}"] = False

        sa_col, ca_col = st.columns(2)
        sa_col.button("☑ Select All", key=f"sel_all__{chat_id}",
                      on_click=_select_all_turns, use_container_width=True)
        ca_col.button("☐ Clear All",  key=f"clear_all__{chat_id}",
                      on_click=_clear_all_turns, use_container_width=True)

        checked_reply_indices = sorted([
            j for j in reply_turn_indices
            if st.session_state.get(f"model_turn__{chat_id}__{j}", False)
        ])
        any_selected = bool(checked_reply_indices)

        # ── Run button ────────────────────────────────────────────────────
        def _turns_to_conv(turns, selected_indices):
            lines = []
            for j, t in enumerate(turns):
                if j not in selected_indices:
                    continue
                k      = list(t.keys())[0]
                prefix = "user" if k.startswith("reply ") else "assistant"
                text   = t[k]
                text   = text.replace("\n", " ")
                text   = re.sub(r'\[SPEED=[^\]]*\]', '', text)
                text   = re.sub(r' {2,}', ' ', text).strip()
                lines.append(f"{prefix}: {text}")
            return "\n".join(lines)

        if st.button("▶ Run Model", key=f"run_model__{chat_id}",
                     type="primary", use_container_width=True,
                     disabled=not any_selected):
            # One separate model call per checked reply, each sending
            # everything from turn 0 up to and including that reply.
            runs = []
            for reply_idx in checked_reply_indices:
                reply_key = list(working_turns[reply_idx].keys())[0]
                reply_num = int(reply_key.split(" ", 1)[1])
                selected  = set(range(reply_idx + 1))
                conv_text = _turns_to_conv(working_turns, selected)
                try:
                    resp = requests.get(
                        "http://3.236.82.208:443/",
                        params={"conv": conv_text, "debug_mode": True, "to_print": True},
                        headers={"x-api-key": "9c406cbae26316c3f2673bfffc0cb78c5e5a1cdaff0211365e870eb54e30e126"},
                        timeout=30,
                    )
                    resp.raise_for_status()
                    runs.append({
                        "reply_num":    reply_num,
                        "reply_idx":    reply_idx,
                        "sent_indices": sorted(selected),
                        "sent_text":    conv_text,
                        "result":       resp.json(),
                    })
                except Exception as e:
                    st.error(f"Model call failed at reply {reply_num}: {e}")
            st.session_state[f"model_results__{chat_id}"] = runs
            st.rerun()

        # ── Results ───────────────────────────────────────────────────────
        def _get_model_name(d):
            for _k in ("contact_name", "name", "full_name"):
                if d.get(_k): return str(d[_k])
            f, l = d.get("first_name",""), d.get("last_name","")
            return f"{f} {l}".strip() if (f or l) else None

        def _get_model_fname(d):
            if d.get("first_name"): return str(d["first_name"])
            # Fall back to first word of full name
            full = _get_model_name(d)
            return full.split()[0] if full else None

        def _get_model_lname(d):
            if d.get("last_name"): return str(d["last_name"])
            # Fall back to everything after the first word
            full = _get_model_name(d)
            parts = full.split() if full else []
            return " ".join(parts[1:]) if len(parts) > 1 else None

        def _get_model_speaker(d):
            for _k in ("speaker_is_contact","is_speaker","contact_is_speaker"):
                if _k in d: return bool(d[_k])
            return None

        def _render_run(run):
            reply_num    = run["reply_num"]
            sent_indices = run["sent_indices"]
            sent_text    = run["sent_text"]
            model_result = run["result"]

            st.markdown(f"**── Up to Reply {reply_num} ──**")
            with st.expander("📋 Exact text sent to model"):
                st.text_area("", value=sent_text, height=120,
                             disabled=True, label_visibility="collapsed")

            if not annotations.get(chat_id):
                st.info("Save annotations first to enable comparison.")
                return

            # Reply numbers present in this run's sent turns
            srn = set()
            for _j in sent_indices:
                if _j < len(working_turns):
                    _k2 = list(working_turns[_j].keys())[0]
                    if _k2.startswith("reply "):
                        srn.add(int(_k2.split(" ", 1)[1]))

            mr = model_result
            if isinstance(mr, list):
                mc_list = mr
            elif isinstance(mr, dict):
                mc_list = mr.get("contacts", [mr]) if "contacts" in mr else [mr]
            else:
                mc_list = []

            sc_mt = st.session_state.get(f"contacts__{chat_id}", [])
            st.markdown("**Comparison:**")
            for i in range(n_contacts_mt):
                sp  = sc_mt[i] if i < len(sc_mt) else {}
                fd  = sp.get("Fname", [["", []]])
                ld  = sp.get("Lname", [["", []]])
                spd = sp.get("contact_is_speaker", [])
                fna = fd == "N/A"
                lna = ld == "N/A"
                sna = spd == "N/A"

                fn_entries = _norm_name_entries(fd) if not fna else []
                ln_entries = _norm_name_entries(ld) if not lna else []
                fn = fn_entries[0][0] if fn_entries else ""
                ln = ln_entries[0][0] if ln_entries else ""
                full = "N/A" if (fna and lna) else f"{fn} {ln}".strip()

                ann_spk = None if sna else (any(r in srn for r in spd) if isinstance(spd, list) else False)

                st.markdown(f"**Contact {i+1} — {full}**")
                mc = next((c for c in mc_list if (mn:=_get_model_name(c)) and
                           (full.lower() in mn.lower() or mn.lower() in full.lower())), None)
                if mc is None and i < len(mc_list): mc = mc_list[i]
                mc = mc or {}

                # ── First name ────────────────────────────────────────────
                if not fna:
                    all_fn_turns = []
                    for fe in fn_entries:
                        ft = fe[1] if len(fe) > 1 else []
                        if isinstance(ft, list):
                            all_fn_turns.extend(ft)
                    fvis = (not all_fn_turns or any(r in srn for r in all_fn_turns))
                    mfn  = _get_model_fname(mc)
                    if not fvis:
                        if mfn:
                            st.markdown(f"⚠️ **First name** — not introduced yet, but model returned `{mfn}`")
                        else:
                            st.markdown("❓ **First name** — not introduced yet")
                    elif mfn is None:
                        ann_fn_display = " / ".join(fe[0] for fe in fn_entries if fe) if len(fn_entries) > 1 else fn
                        st.markdown(f"❓ **First name** — model returned nothing · annotated `{ann_fn_display}`")
                    else:
                        all_fn_names = [fe[0] for fe in fn_entries if fe]
                        ok = any(n.lower() == mfn.lower() for n in all_fn_names)
                        ann_fn_display = " / ".join(all_fn_names) if len(all_fn_names) > 1 else fn
                        c1, c2 = st.columns(2)
                        c1.markdown(f"{'✅' if ok else '❌'} **First name**")
                        c2.markdown(f"annotated `{ann_fn_display}` · model `{mfn}`")

                # ── Last name ─────────────────────────────────────────────
                if not lna:
                    all_ln_turns = []
                    for le in ln_entries:
                        lt = le[1] if len(le) > 1 else []
                        if isinstance(lt, list):
                            all_ln_turns.extend(lt)
                    lvis = (not all_ln_turns or any(r in srn for r in all_ln_turns))
                    mln  = _get_model_lname(mc)
                    if not lvis:
                        if mln:
                            st.markdown(f"⚠️ **Last name** — not introduced yet, but model returned `{mln}`")
                        else:
                            st.markdown("❓ **Last name** — not introduced yet")
                    elif mln is None:
                        ann_ln_display = " / ".join(le[0] for le in ln_entries if le) if len(ln_entries) > 1 else ln
                        st.markdown(f"❓ **Last name** — model returned nothing · annotated `{ann_ln_display}`")
                    else:
                        all_ln_names = [le[0] for le in ln_entries if le]
                        ok = any(n.lower() == mln.lower() for n in all_ln_names)
                        ann_ln_display = " / ".join(all_ln_names) if len(all_ln_names) > 1 else ln
                        c1, c2 = st.columns(2)
                        c1.markdown(f"{'✅' if ok else '❌'} **Last name**")
                        c2.markdown(f"annotated `{ann_ln_display}` · model `{mln}`")

                if not sna:
                    ms = _get_model_speaker(mc)
                    if ms is None:
                        st.markdown("❓ **Speaker is contact** — no value returned")
                    else:
                        ok = ms == ann_spk
                        c1, c2 = st.columns(2)
                        c1.markdown(f"{'✅' if ok else '❌'} **Speaker is contact**")
                        c2.markdown(f"annotated `{ann_spk}` · model `{ms}`")

                if i < n_contacts_mt - 1:
                    st.markdown("---")

        model_runs = st.session_state.get(f"model_results__{chat_id}", [])
        for ri, run in enumerate(model_runs):
            _render_run(run)
            if ri < len(model_runs) - 1:
                st.markdown("═══════════════")

# ── RIGHT: annotation panel ───────────────────────────────────────────────────

with right:
  if "right_h" not in st.session_state:
      st.session_state["right_h"] = 820
  _rc1, _rc2, _rc3 = st.columns([3, 1, 1])
  _rc1.caption(f"Height: {st.session_state['right_h']}px")
  if _rc2.button("▼", key="right_h_up",   use_container_width=True):
      st.session_state["right_h"] = min(1400, st.session_state["right_h"] + 100)
      st.rerun()
  if _rc3.button("▲", key="right_h_down", use_container_width=True):
      st.session_state["right_h"] = max(300,  st.session_state["right_h"] - 100)
      st.rerun()

  with st.container(height=st.session_state["right_h"], border=True):
    already_done = chat_id in annotations
    badge = '<span class="annotated-badge">✅ annotated</span>' if already_done else ""

    st.markdown(
        f'<div class="panel-header">'
        f'<h3>🔍 Annotations{badge}</h3>'
        f'<p>Conversation {idx + 1} of {n_total}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Progress
    st.progress(
        n_annotated / n_total if n_total else 0,
        text=f"{n_annotated} / {n_total} annotated",
    )

    # Progress shown in header only — navigation moved above panels

    st.markdown("---")

    last_reply = reply_numbers[-1] if reply_numbers else None

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _init(key, default):
        if key not in st.session_state:
            st.session_state[key] = default

    def _start_from(turns_list):
        return min(turns_list) if turns_list else None

    def _end_from(turns_list):
        return max(turns_list) if turns_list else None

    # Per-contact fields (not per-name-entry)
    WIDGET_FIELDS = ["fname_na", "fname_n",
                     "lname_na", "lname_n",
                     "speaker_start", "speaker_end", "speaker_na",
                     "intro_inc_start", "intro_inc_end", "intro_inc_na",
                     "intro_exc_start", "intro_exc_end", "intro_exc_na",
                     "name_known"]

    def _clear_name_entry_keys(cid, i):
        """Clear all per-name-entry widget keys for contact i (up to 10 entries)."""
        for j in range(10):
            for fld in ["fname", "fname_start", "fname_end", "fname_turns_na",
                        "lname", "lname_start", "lname_end", "lname_turns_na"]:
                st.session_state.pop(f"{fld}__{cid}__{i}__{j}", None)

    def _clear_widget_keys(cid, n):
        for i in range(n):
            for f in WIDGET_FIELDS:
                st.session_state.pop(f"{f}__{cid}__{i}", None)
            _clear_name_entry_keys(cid, i)

    def _check_all_filled(cid, n):
        """Return list of human-readable missing field descriptions."""
        missing = []
        for i in range(n):
            label        = f"Contact {i + 1}"
            fname_na     = st.session_state.get(f"fname_na__{cid}__{i}", False)
            lname_na     = st.session_state.get(f"lname_na__{cid}__{i}", False)
            speaker_na   = st.session_state.get(f"speaker_na__{cid}__{i}", False)
            intro_inc_na = st.session_state.get(f"intro_inc_na__{cid}__{i}", False)
            intro_exc_na = st.session_state.get(f"intro_exc_na__{cid}__{i}", False)
            name_known   = st.session_state.get(f"name_known__{cid}__{i}")

            if not fname_na:
                fn_count = st.session_state.get(f"fname_n__{cid}__{i}", 1)
                for j in range(fn_count):
                    ftn_na = st.session_state.get(f"fname_turns_na__{cid}__{i}__{j}", False)
                    suffix = f" #{j+1}" if fn_count > 1 else ""
                    if not st.session_state.get(f"fname__{cid}__{i}__{j}", "").strip():
                        missing.append(f"{label}: First name{suffix} (or mark N/A)")
                    if not ftn_na:
                        if st.session_state.get(f"fname_start__{cid}__{i}__{j}") is None:
                            missing.append(f"{label}: Fname{suffix} turns — start (or mark N/A)")
                        if st.session_state.get(f"fname_end__{cid}__{i}__{j}") is None:
                            missing.append(f"{label}: Fname{suffix} turns — end (or mark N/A)")

            if not lname_na:
                ln_count = st.session_state.get(f"lname_n__{cid}__{i}", 1)
                for j in range(ln_count):
                    ltn_na = st.session_state.get(f"lname_turns_na__{cid}__{i}__{j}", False)
                    suffix = f" #{j+1}" if ln_count > 1 else ""
                    if not st.session_state.get(f"lname__{cid}__{i}__{j}", "").strip():
                        missing.append(f"{label}: Last name{suffix} (or mark N/A)")
                    if not ltn_na:
                        if st.session_state.get(f"lname_start__{cid}__{i}__{j}") is None:
                            missing.append(f"{label}: Lname{suffix} turns — start (or mark N/A)")
                        if st.session_state.get(f"lname_end__{cid}__{i}__{j}") is None:
                            missing.append(f"{label}: Lname{suffix} turns — end (or mark N/A)")

            if not speaker_na:
                if st.session_state.get(f"speaker_start__{cid}__{i}") is None:
                    missing.append(f"{label}: Contact is speaker — start (or mark N/A)")
                if st.session_state.get(f"speaker_end__{cid}__{i}") is None:
                    missing.append(f"{label}: Contact is speaker — end (or mark N/A)")
            if not intro_inc_na:
                if st.session_state.get(f"intro_inc_start__{cid}__{i}") is None:
                    missing.append(f"{label}: Intro includes name — start (or mark N/A)")
                if st.session_state.get(f"intro_inc_end__{cid}__{i}") is None:
                    missing.append(f"{label}: Intro includes name — end (or mark N/A)")
            if not intro_exc_na:
                if st.session_state.get(f"intro_exc_start__{cid}__{i}") is None:
                    missing.append(f"{label}: Intro doesn't include name — start (or mark N/A)")
                if st.session_state.get(f"intro_exc_end__{cid}__{i}") is None:
                    missing.append(f"{label}: Intro doesn't include name — end (or mark N/A)")
            if name_known is None:
                missing.append(f"{label}: Contact name known (True / False / N/A)")
        return missing

    # ── Contact list init ──────────────────────────────────────────────────────

    contacts_key = f"contacts__{chat_id}"
    if contacts_key not in st.session_state:
        existing = annotations.get(chat_id, {})
        speaker_keys = sorted([k for k in existing if k.startswith("speaker ")],
                               key=lambda k: int(k.split(" ")[1]))
        if speaker_keys:
            seed_contacts = [existing[k] for k in speaker_keys]
        elif "contacts" in existing:  # old list format
            seed_contacts = existing["contacts"]
        elif existing:  # old flat single-contact format
            seed_contacts = [existing]
        else:
            seed_contacts = [{}]
        st.session_state[contacts_key] = seed_contacts

    contacts = st.session_state[contacts_key]
    n_contacts = len(contacts)

    # Keep contacts in sync with live widget state on every render.
    # This ensures _init always has up-to-date defaults to restore from,
    # even if a left-panel button rerun resets widget keys.
    # Skip when an "add name" button just fired — the snapshot in contacts_key
    # is already correct, and re-reading widgets would overwrite it with cleared values.
    _skip_sync = st.session_state.pop(f"_skip_sync__{chat_id}", False)
    if not _skip_sync and f"fname__{chat_id}__0__0" in st.session_state:
        contacts = _read_contacts_from_widgets(chat_id, n_contacts)
        st.session_state[contacts_key] = contacts

    # ── Init widget keys from contact list ────────────────────────────────────

    for i, c in enumerate(contacts):
        # ── First names ───────────────────────────────────────────────────────
        fname_data  = c.get("Fname", [["", []]])
        fname_is_na = fname_data == "N/A"
        _init(f"fname_na__{chat_id}__{i}", fname_is_na)
        if not fname_is_na:
            fn_entries = _norm_name_entries(fname_data) if fname_data else [["", []]]
            if not fn_entries:
                fn_entries = [["", []]]
            _init(f"fname_n__{chat_id}__{i}", len(fn_entries))
            for j, fe in enumerate(fn_entries):
                fn_str   = fe[0] if len(fe) > 0 else ""
                fn_turns = fe[1] if len(fe) > 1 else []
                ftn_is_na = fn_turns == "N/A"
                _init(f"fname_turns_na__{chat_id}__{i}__{j}", ftn_is_na)
                _init(f"fname__{chat_id}__{i}__{j}",          fn_str)
                _init(f"fname_start__{chat_id}__{i}__{j}",    None if ftn_is_na else _start_from(fn_turns if isinstance(fn_turns, list) else []))
                _init(f"fname_end__{chat_id}__{i}__{j}",      None if ftn_is_na else _end_from(fn_turns if isinstance(fn_turns, list) else []))
        else:
            _init(f"fname_n__{chat_id}__{i}", 1)
            _init(f"fname_turns_na__{chat_id}__{i}__0", False)
            _init(f"fname__{chat_id}__{i}__0",          "")
            _init(f"fname_start__{chat_id}__{i}__0",    None)
            _init(f"fname_end__{chat_id}__{i}__0",      None)

        # ── Last names ────────────────────────────────────────────────────────
        lname_data  = c.get("Lname", [["", []]])
        lname_is_na = lname_data == "N/A"
        _init(f"lname_na__{chat_id}__{i}", lname_is_na)
        if not lname_is_na:
            ln_entries = _norm_name_entries(lname_data) if lname_data else [["", []]]
            if not ln_entries:
                ln_entries = [["", []]]
            _init(f"lname_n__{chat_id}__{i}", len(ln_entries))
            for j, le in enumerate(ln_entries):
                ln_str   = le[0] if len(le) > 0 else ""
                ln_turns = le[1] if len(le) > 1 else []
                ltn_is_na = ln_turns == "N/A"
                _init(f"lname_turns_na__{chat_id}__{i}__{j}", ltn_is_na)
                _init(f"lname__{chat_id}__{i}__{j}",          ln_str)
                _init(f"lname_start__{chat_id}__{i}__{j}",    None if ltn_is_na else _start_from(ln_turns if isinstance(ln_turns, list) else []))
                _init(f"lname_end__{chat_id}__{i}__{j}",      None if ltn_is_na else _end_from(ln_turns if isinstance(ln_turns, list) else []))
        else:
            _init(f"lname_n__{chat_id}__{i}", 1)
            _init(f"lname_turns_na__{chat_id}__{i}__0", False)
            _init(f"lname__{chat_id}__{i}__0",          "")
            _init(f"lname_start__{chat_id}__{i}__0",    None)
            _init(f"lname_end__{chat_id}__{i}__0",      None)

        speaker_val = c.get("contact_is_speaker", [])
        _init(f"speaker_na__{chat_id}__{i}",       speaker_val == "N/A")
        _init(f"speaker_start__{chat_id}__{i}",    None if speaker_val == "N/A" else _start_from(speaker_val))
        _init(f"speaker_end__{chat_id}__{i}",      None if speaker_val == "N/A" else _end_from(speaker_val))

        intro_inc_val = c.get("intro_includes_name", [])
        _init(f"intro_inc_na__{chat_id}__{i}",     intro_inc_val == "N/A")
        _init(f"intro_inc_start__{chat_id}__{i}",  None if intro_inc_val == "N/A" else _start_from(intro_inc_val))
        _init(f"intro_inc_end__{chat_id}__{i}",    None if intro_inc_val == "N/A" else _end_from(intro_inc_val))

        intro_exc_val = c.get("intro_doesnt_include_name", [])
        _init(f"intro_exc_na__{chat_id}__{i}",     intro_exc_val == "N/A")
        _init(f"intro_exc_start__{chat_id}__{i}",  None if intro_exc_val == "N/A" else _start_from(intro_exc_val))
        _init(f"intro_exc_end__{chat_id}__{i}",    None if intro_exc_val == "N/A" else _end_from(intro_exc_val))

        _init(f"name_known__{chat_id}__{i}",       c.get("contact_name_known", None))

    # ── All N/A ───────────────────────────────────────────────────────────────

    def _set_all_na():
        for _i in range(n_contacts):
            st.session_state[f"fname_na__{chat_id}__{_i}"]     = True
            st.session_state[f"lname_na__{chat_id}__{_i}"]     = True
            st.session_state[f"speaker_na__{chat_id}__{_i}"]   = True
            st.session_state[f"intro_inc_na__{chat_id}__{_i}"] = True
            st.session_state[f"intro_exc_na__{chat_id}__{_i}"] = True
            st.session_state[f"name_known__{chat_id}__{_i}"]   = "N/A"

    st.button("⬜ Mark all fields N/A", key=f"all_na__{chat_id}",
              on_click=_set_all_na, use_container_width=True)

    st.markdown("---")

    # ── Sanitize stale turn-range values before rendering ─────────────────────
    # After turn deletions reply_numbers shrinks; any saved value no longer in
    # the list would crash the selectbox — reset those to None.
    _simple_range_keys = ["speaker_start", "speaker_end",
                          "intro_inc_start", "intro_inc_end",
                          "intro_exc_start", "intro_exc_end"]
    for _ci in range(n_contacts):
        for _rk in _simple_range_keys:
            _sk = f"{_rk}__{chat_id}__{_ci}"
            if st.session_state.get(_sk) not in [None] + reply_numbers:
                st.session_state[_sk] = None
        _fn_cnt = st.session_state.get(f"fname_n__{chat_id}__{_ci}", 1)
        for _j in range(_fn_cnt):
            for _rk in ["fname_start", "fname_end"]:
                _sk = f"{_rk}__{chat_id}__{_ci}__{_j}"
                if st.session_state.get(_sk) not in [None] + reply_numbers:
                    st.session_state[_sk] = None
        _ln_cnt = st.session_state.get(f"lname_n__{chat_id}__{_ci}", 1)
        for _j in range(_ln_cnt):
            for _rk in ["lname_start", "lname_end"]:
                _sk = f"{_rk}__{chat_id}__{_ci}__{_j}"
                if st.session_state.get(_sk) not in [None] + reply_numbers:
                    st.session_state[_sk] = None

    # ── Render each contact ────────────────────────────────────────────────────

    opts      = [None] + reply_numbers
    fmt_end   = lambda x: "— select —" if x is None else str(x)
    fmt_start = lambda x: "— clear —" if x is None else str(x)

    for i in range(n_contacts):
        label_col, remove_col = st.columns([3, 1])
        label_col.markdown(f"**Contact {i + 1}**")
        if remove_col.button("✕ Remove", key=f"remove__{chat_id}__{i}",
                             disabled=(n_contacts == 1), use_container_width=True):
            # Shift contact slots i+1 → i
            for _j in range(i, n_contacts - 1):
                # Per-contact (non-name-entry) fields
                for _f in WIDGET_FIELDS:
                    _src = f"{_f}__{chat_id}__{_j + 1}"
                    _dst = f"{_f}__{chat_id}__{_j}"
                    if _src in st.session_state:
                        st.session_state[_dst] = st.session_state[_src]
                    else:
                        st.session_state.pop(_dst, None)
                # Per-name-entry fields
                for _pfx in ["fname", "lname"]:
                    _cnt_src = f"{_pfx}_n__{chat_id}__{_j + 1}"
                    _cnt_dst = f"{_pfx}_n__{chat_id}__{_j}"
                    _cnt     = st.session_state.get(_cnt_src, 1)
                    st.session_state[_cnt_dst] = _cnt
                    for _k in range(max(_cnt, 10)):
                        for _fld in [_pfx, f"{_pfx}_start", f"{_pfx}_end", f"{_pfx}_turns_na"]:
                            _src2 = f"{_fld}__{chat_id}__{_j + 1}__{_k}"
                            _dst2 = f"{_fld}__{chat_id}__{_j}__{_k}"
                            if _src2 in st.session_state:
                                st.session_state[_dst2] = st.session_state[_src2]
                            else:
                                st.session_state.pop(_dst2, None)
            # Clear the now-unused last slot
            _last = n_contacts - 1
            for _f in WIDGET_FIELDS:
                st.session_state.pop(f"{_f}__{chat_id}__{_last}", None)
            for _pfx in ["fname", "lname"]:
                st.session_state.pop(f"{_pfx}_n__{chat_id}__{_last}", None)
                for _k in range(10):
                    for _fld in [_pfx, f"{_pfx}_start", f"{_pfx}_end", f"{_pfx}_turns_na"]:
                        st.session_state.pop(f"{_fld}__{chat_id}__{_last}__{_k}", None)
            updated = list(contacts)
            updated.pop(i)
            st.session_state[contacts_key] = updated
            st.rerun()

        # ── First names ────────────────────────────────────────────────────────
        with st.container(border=True):
            fn_na = st.session_state.get(f"fname_na__{chat_id}__{i}", False)
            fn_hdr_col, fn_na_col = st.columns([3, 1])
            fn_hdr_col.markdown("**First name**")
            fn_na_col.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            fn_na_col.checkbox("N/A", key=f"fname_na__{chat_id}__{i}")

            fn_count = st.session_state.get(f"fname_n__{chat_id}__{i}", 1)
            for j in range(fn_count):
                if j > 0:
                    _alias_col, _rm_fn_col = st.columns([3, 1])
                    _alias_col.markdown(f"*Other name {j + 1}*")
                    if _rm_fn_col.button("✕", key=f"rm_fname__{chat_id}__{i}__{j}",
                                         use_container_width=True, help="Remove this name"):
                        for _jj in range(j, fn_count - 1):
                            for _fld in ["fname", "fname_start", "fname_end", "fname_turns_na"]:
                                _src = f"{_fld}__{chat_id}__{i}__{_jj + 1}"
                                _dst = f"{_fld}__{chat_id}__{i}__{_jj}"
                                if _src in st.session_state:
                                    st.session_state[_dst] = st.session_state[_src]
                                else:
                                    st.session_state.pop(_dst, None)
                        for _fld in ["fname", "fname_start", "fname_end", "fname_turns_na"]:
                            st.session_state.pop(f"{_fld}__{chat_id}__{i}__{fn_count - 1}", None)
                        st.session_state[f"fname_n__{chat_id}__{i}"] = fn_count - 1
                        st.rerun()
                _fn_input_label = f"First name {j + 1}" if fn_count > 1 else "Contact first name"
                st.text_input(_fn_input_label, key=f"fname__{chat_id}__{i}__{j}", disabled=fn_na)
                ftn_na = st.session_state.get(f"fname_turns_na__{chat_id}__{i}__{j}", False)
                _fc_caption = f"Fname turns {j + 1}" if fn_count > 1 else "Fname turns"
                st.caption(_fc_caption)
                fc1, fc2, fc_na = st.columns([2, 2, 1])
                fc1.selectbox("Start", options=opts, format_func=fmt_start,
                              key=f"fname_start__{chat_id}__{i}__{j}", disabled=fn_na or ftn_na)
                fc2.selectbox("End",   options=opts, format_func=fmt_end,
                              key=f"fname_end__{chat_id}__{i}__{j}",   disabled=fn_na or ftn_na)
                fc_na.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                fc_na.checkbox("N/A", key=f"fname_turns_na__{chat_id}__{i}__{j}", disabled=fn_na)

            if not fn_na:
                if st.button("＋ Add first name", key=f"add_fname__{chat_id}__{i}",
                             use_container_width=True):
                    st.session_state[contacts_key] = _read_contacts_from_widgets(chat_id, n_contacts)
                    st.session_state[f"_skip_sync__{chat_id}"] = True
                    new_j = fn_count
                    st.session_state[f"fname__{chat_id}__{i}__{new_j}"]          = ""
                    st.session_state[f"fname_turns_na__{chat_id}__{i}__{new_j}"] = False
                    st.session_state[f"fname_start__{chat_id}__{i}__{new_j}"]    = None
                    st.session_state[f"fname_end__{chat_id}__{i}__{new_j}"]      = None
                    st.session_state[f"fname_n__{chat_id}__{i}"]                 = fn_count + 1
                    st.rerun()

        # ── Last names ─────────────────────────────────────────────────────────
        with st.container(border=True):
            ln_na = st.session_state.get(f"lname_na__{chat_id}__{i}", False)
            ln_hdr_col, ln_na_col = st.columns([3, 1])
            ln_hdr_col.markdown("**Last name**")
            ln_na_col.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            ln_na_col.checkbox("N/A", key=f"lname_na__{chat_id}__{i}")

            ln_count = st.session_state.get(f"lname_n__{chat_id}__{i}", 1)
            for j in range(ln_count):
                if j > 0:
                    _alias_col2, _rm_ln_col = st.columns([3, 1])
                    _alias_col2.markdown(f"*Other name {j + 1}*")
                    if _rm_ln_col.button("✕", key=f"rm_lname__{chat_id}__{i}__{j}",
                                         use_container_width=True, help="Remove this name"):
                        for _jj in range(j, ln_count - 1):
                            for _fld in ["lname", "lname_start", "lname_end", "lname_turns_na"]:
                                _src = f"{_fld}__{chat_id}__{i}__{_jj + 1}"
                                _dst = f"{_fld}__{chat_id}__{i}__{_jj}"
                                if _src in st.session_state:
                                    st.session_state[_dst] = st.session_state[_src]
                                else:
                                    st.session_state.pop(_dst, None)
                        for _fld in ["lname", "lname_start", "lname_end", "lname_turns_na"]:
                            st.session_state.pop(f"{_fld}__{chat_id}__{i}__{ln_count - 1}", None)
                        st.session_state[f"lname_n__{chat_id}__{i}"] = ln_count - 1
                        st.rerun()
                _ln_input_label = f"Last name {j + 1}" if ln_count > 1 else "Contact last name"
                st.text_input(_ln_input_label, key=f"lname__{chat_id}__{i}__{j}", disabled=ln_na)
                ltn_na = st.session_state.get(f"lname_turns_na__{chat_id}__{i}__{j}", False)
                _lc_caption = f"Lname turns {j + 1}" if ln_count > 1 else "Lname turns"
                st.caption(_lc_caption)
                lc1, lc2, lc_na = st.columns([2, 2, 1])
                lc1.selectbox("Start", options=opts, format_func=fmt_start,
                              key=f"lname_start__{chat_id}__{i}__{j}", disabled=ln_na or ltn_na)
                lc2.selectbox("End",   options=opts, format_func=fmt_end,
                              key=f"lname_end__{chat_id}__{i}__{j}",   disabled=ln_na or ltn_na)
                lc_na.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                lc_na.checkbox("N/A", key=f"lname_turns_na__{chat_id}__{i}__{j}", disabled=ln_na)

            if not ln_na:
                if st.button("＋ Add last name", key=f"add_lname__{chat_id}__{i}",
                             use_container_width=True):
                    st.session_state[contacts_key] = _read_contacts_from_widgets(chat_id, n_contacts)
                    st.session_state[f"_skip_sync__{chat_id}"] = True
                    new_j = ln_count
                    st.session_state[f"lname__{chat_id}__{i}__{new_j}"]          = ""
                    st.session_state[f"lname_turns_na__{chat_id}__{i}__{new_j}"] = False
                    st.session_state[f"lname_start__{chat_id}__{i}__{new_j}"]    = None
                    st.session_state[f"lname_end__{chat_id}__{i}__{new_j}"]      = None
                    st.session_state[f"lname_n__{chat_id}__{i}"]                 = ln_count + 1
                    st.rerun()

        # ── Contact is speaker ────────────────────────────────────────────────
        with st.container(border=True):
            sp_na = st.session_state.get(f"speaker_na__{chat_id}__{i}", False)
            st.caption("Contact is speaker")
            sc1, sc2, sc_na = st.columns([2, 2, 1])
            sc1.selectbox("Start", options=opts, format_func=fmt_start,
                          key=f"speaker_start__{chat_id}__{i}", disabled=sp_na)
            sc2.selectbox("End",   options=opts, format_func=fmt_end,
                          key=f"speaker_end__{chat_id}__{i}",   disabled=sp_na)
            sc_na.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            sc_na.checkbox("N/A", key=f"speaker_na__{chat_id}__{i}")

        # ── Intro / name known ────────────────────────────────────────────────
        with st.container(border=True):
            # ── Intro includes name ───────────────────────────────────────────
            ii_na = st.session_state.get(f"intro_inc_na__{chat_id}__{i}", False)
            st.caption("Intro includes name")
            ii1, ii2, ii_na_col = st.columns([2, 2, 1])
            ii1.selectbox("Start", options=opts, format_func=fmt_start,
                          key=f"intro_inc_start__{chat_id}__{i}", disabled=ii_na)
            ii2.selectbox("End",   options=opts, format_func=fmt_end,
                          key=f"intro_inc_end__{chat_id}__{i}",   disabled=ii_na)
            ii_na_col.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            ii_na_col.checkbox("N/A", key=f"intro_inc_na__{chat_id}__{i}")

            # ── Intro doesn't include name ────────────────────────────────────
            ie_na = st.session_state.get(f"intro_exc_na__{chat_id}__{i}", False)
            st.caption("Intro doesn't include name")
            ie1, ie2, ie_na_col = st.columns([2, 2, 1])
            ie1.selectbox("Start", options=opts, format_func=fmt_start,
                          key=f"intro_exc_start__{chat_id}__{i}", disabled=ie_na)
            ie2.selectbox("End",   options=opts, format_func=fmt_end,
                          key=f"intro_exc_end__{chat_id}__{i}",   disabled=ie_na)
            ie_na_col.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            ie_na_col.checkbox("N/A", key=f"intro_exc_na__{chat_id}__{i}")

            # ── Contact name known ────────────────────────────────────────────
            st.caption("Contact name known")
            name_known_val = st.session_state.get(f"name_known__{chat_id}__{i}")
            nk1, nk2, nk3 = st.columns(3)
            if nk1.button(
                "True",
                key=f"name_known_true__{chat_id}__{i}",
                type="primary" if name_known_val is True else "secondary",
                use_container_width=True,
            ):
                st.session_state[f"name_known__{chat_id}__{i}"] = (
                    None if name_known_val is True else True
                )
                st.rerun()
            if nk2.button(
                "False",
                key=f"name_known_false__{chat_id}__{i}",
                type="primary" if name_known_val is False else "secondary",
                use_container_width=True,
            ):
                st.session_state[f"name_known__{chat_id}__{i}"] = (
                    None if name_known_val is False else False
                )
                st.rerun()
            if nk3.button(
                "N/A",
                key=f"name_known_na__{chat_id}__{i}",
                type="primary" if name_known_val == "N/A" else "secondary",
                use_container_width=True,
            ):
                st.session_state[f"name_known__{chat_id}__{i}"] = (
                    None if name_known_val == "N/A" else "N/A"
                )
                st.rerun()

        if i < n_contacts - 1:
            st.markdown("---")

    if st.button("➕ Add contact", use_container_width=True):
        # Don't clear existing widget keys — existing contacts' values stay live.
        # Just clear the new slot so _init populates it with empty defaults.
        for _f in WIDGET_FIELDS:
            st.session_state.pop(f"{_f}__{chat_id}__{n_contacts}", None)
        _clear_name_entry_keys(chat_id, n_contacts)
        updated = list(contacts)
        updated.append({})
        st.session_state[contacts_key] = updated
        st.rerun()

  # ── Save & Export — outside the scrollable container ─────────────────────

  if st.button("💾 Save & next", type="primary",
               use_container_width=True, key="save_and_next_btn",
               disabled=_last_turn_is_agent):
      missing = _check_all_filled(chat_id, n_contacts)
      if missing:
          st.error("**Please fill in all fields before saving:**\n\n" +
                   "\n".join(f"- {m}" for m in missing))
      else:
          # Prefer the contacts already synced from widget state during this
          # render pass — avoids selectbox resets that can occur when Save &
          # Next triggers a rerun and options are re-evaluated before the
          # button handler reads them.
          saved_contacts = st.session_state.get(contacts_key) or _read_contacts_from_widgets(chat_id, n_contacts)
          saved_labels = {
              f"speaker {i}": c
              for i, c in enumerate(saved_contacts)
          }
          annotations[chat_id] = saved_labels
          st.session_state["annotations"] = annotations
          st.session_state[contacts_key] = saved_contacts
          _clear_widget_keys(chat_id, n_contacts)

          # ── Upsert to MongoDB ─────────────────────────────────────────────
          _mongo_col = _get_mongo_collection()
          if _mongo_col is not None:
              try:
                  _working   = st.session_state.get(f"working_turns__{chat_id}", conv["turns"])
                  _edited    = st.session_state.get(f"edited_indices__{chat_id}", set())
                  _new       = st.session_state.get(f"new_indices__{chat_id}", set())
                  _changes   = _build_changes(conv["turns"], _working, _edited, _new)
                  _doc = {
                      "chat_id":      chat_id,
                      "annotator":    annotator_name,
                      "Labels":       saved_labels,
                      "turns":        _working,
                      "source":       conv.get("source"),
                      "last_updated": datetime.now(timezone.utc).isoformat(),
                  }
                  if _changes:
                      _doc["changes"] = _changes
                  _mongo_col.update_one(
                      {"chat_id": chat_id, "annotator": annotator_name},
                      {"$set": _doc},
                      upsert=True,
                  )
              except Exception as _e:
                  st.warning(f"⚠️ Saved locally but MongoDB sync failed: {_e}")
          else:
              st.warning("⚠️ MongoDB unavailable — annotation saved locally only.")

          # ── Sync turns back to source file if Roy edited them ─────────────
          if annotator_name == "Roy" and _mongo_col is not None:
              try:
                  _source_col = _get_source_collection()
                  if _source_col is not None:
                      _src_doc = _source_col.find_one({"chat_id": chat_id}, {"turns": 1})
                      if _src_doc and _src_doc.get("turns") != _working:
                          _source_col.update_one(
                              {"chat_id": chat_id},
                              {"$set": {"turns": _working}},
                          )
              except Exception as _se:
                  st.warning(f"⚠️ Annotation saved but source file sync failed: {_se}")

          if idx < n_total - 1:
              st.session_state["conv_index"] = idx + 1
          st.rerun()

  def _apply_edits(c):
      wt = st.session_state.get(f"working_turns__{c['chat_id']}")
      turns = wt if (wt is not None and wt != c["turns"]) else c["turns"]
      if turns and "assistant" in turns[-1]:
          turns = turns[:-1]
      return {**c, "turns": turns}

  _annotator = st.session_state.get("annotator_name", "unknown")

  annotated_export = [
      {**_apply_edits(c), "annotator": _annotator, "Labels": annotations[c["chat_id"]]}
      if c["chat_id"] in annotations else _apply_edits(c)
      for c in conversations
  ]

  json_str   = json.dumps(annotated_export, ensure_ascii=False, indent=2)
  json_bytes = json_str.encode("utf-8")
  st.session_state["_last_export_json"] = json_str

  def _on_download_click():
      st.session_state["_run_verify"] = True

  file_stem = st.session_state.get("_loaded_file", "export").replace(".json", "")
  safe_name = _annotator.replace(" ", "_")
  st.download_button(
      label=f"⬇️ Download annotated JSON  ({n_annotated} / {n_total})",
      data=json_bytes,
      file_name=f"{file_stem}_{safe_name}_annotated.json",
      mime="application/json",
      use_container_width=True,
      on_click=_on_download_click,
  )

  # ── Post-download verification ─────────────────────────────────────────────
  if st.session_state.get("_run_verify"):
      st.session_state["_run_verify"] = False
      stored = st.session_state.get("_last_export_json", "")
      issues = []
      try:
          parsed = json.loads(stored)
      except json.JSONDecodeError as e:
          issues.append(f"JSON parse error: {e}")
          parsed = []

      parsed_by_id = {item["chat_id"]: item for item in parsed if "chat_id" in item}

      for conv in conversations:
          cid   = conv["chat_id"]
          short = cid[:13] + "…"
          item  = parsed_by_id.get(cid)
          if item is None:
              issues.append(f"{short}: missing from output file")
              continue
          if cid in annotations:
              if (json.dumps(item.get("Labels"), sort_keys=True) !=
                      json.dumps(annotations[cid], sort_keys=True)):
                  issues.append(f"{short}: Labels in file differ from session state")
          if item.get("turns") and "assistant" in item["turns"][-1]:
              issues.append(f"{short}: output still ends with an assistant turn")

      if issues:
          st.error(f"⚠️ Verification failed — {len(issues)} issue(s):\n\n" +
                   "\n".join(f"- {iss}" for iss in issues))
      else:
          st.success(f"✅ Verified — all {n_annotated} annotated conversation(s) "
                     f"match session state and no trailing assistant turns found")
