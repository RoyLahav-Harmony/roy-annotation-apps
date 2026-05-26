import json
import hashlib
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timezone

st.set_page_config(page_title="Annotation Tool", layout="wide")
st.title("Annotation Tool")

# ── Annotator name gate ────────────────────────────────────────────────────────
if "annotator_name" not in st.session_state:
    st.session_state.annotator_name = ""

if not st.session_state.annotator_name:
    st.subheader("Welcome")
    st.markdown("Please enter your name before starting.")
    name_input = st.text_input("Your name", placeholder="e.g. Jane Smith")
    if st.button("Start", type="primary") and name_input.strip():
        st.session_state.annotator_name = name_input.strip()
        st.rerun()
    st.stop()

# ── File upload ────────────────────────────────────────────────────────────────
uploaded = st.file_uploader("Upload a review dataset JSON file", type=["json"])
if uploaded is None:
    st.info("Upload a review dataset JSON file to begin annotating.")
    st.stop()


@st.cache_data
def load_pairs(content: bytes) -> list[dict]:
    data = json.loads(content)
    pairs = []
    for item in data:
        chat_id = item.get("chat_id", "unknown")
        turn_num = item.get("#", "?")
        pairs.append({
            "turn_id":     f"{chat_id}_t{turn_num}",
            "chat_id":     chat_id,
            "Prev Agent":  item.get("Prev Agent", "—"),
            "User":        item.get("User", ""),
            "Agent":       item.get("Agent", ""),
            "Goal":        item.get("Goal", "—"),
            "Intent":      item.get("Intent", "—"),
            "_confidence": item.get("Confidence"),
        })
    return pairs


pairs = load_pairs(uploaded.read())
total = len(pairs)

# Reset state when a different file is loaded.
file_hash = hashlib.md5(uploaded.getvalue()).hexdigest()
if st.session_state.get("_file_hash") != file_hash:
    st.session_state["_file_hash"]  = file_hash
    st.session_state["annotations"] = [None] * total
    st.session_state["current_idx"] = 0

annotations: list = st.session_state["annotations"]

# ── Header bar ─────────────────────────────────────────────────────────────────
annotated = sum(1 for a in annotations if a is not None)
st.caption(
    f"Annotator: **{st.session_state.annotator_name}**  ·  "
    f"Progress: **{annotated} / {total}** pairs annotated"
)
st.progress(annotated / total if total else 0)
st.markdown("---")

# ── Pair display ───────────────────────────────────────────────────────────────
idx  = st.session_state["current_idx"]
pair = pairs[idx]

st.markdown(f"#### Pair {idx + 1} of {total}")
st.caption(f"Turn ID: `{pair['turn_id']}`  ·  Chat: `{pair['chat_id']}`")
st.markdown(" ")

# Inline styles so rendering is independent of Streamlit's CSS pipeline
BOX_STYLE = (
    "background-color:#000000;"
    "border:1px solid #444;"
    "border-radius:6px;"
    "padding:14px 16px;"
    "font-size:1.8rem;"
    "min-height:110px;"
    "line-height:1.4;"
    "color:#ffffff;"
)
LABEL_STYLE = (
    "font-size:0.95rem;"
    "font-weight:600;"
    "color:#444;"
    "margin-bottom:6px;"
)

col_prev, col_user, col_agent = st.columns(3)

with col_prev:
    st.markdown(
        f'<div style="{LABEL_STYLE}">Previous Agent Turn</div>'
        f'<div style="{BOX_STYLE}">{pair["Prev Agent"] or "<em>none</em>"}</div>',
        unsafe_allow_html=True,
    )

with col_user:
    st.markdown(
        f'<div style="{LABEL_STYLE}">User Turn</div>'
        f'<div style="{BOX_STYLE}">{pair["User"] or "<em>empty</em>"}</div>',
        unsafe_allow_html=True,
    )

with col_agent:
    st.markdown(
        f'<div style="{LABEL_STYLE}">Agent Turn</div>'
        f'<div style="{BOX_STYLE}">{pair["Agent"] or "<em>empty</em>"}</div>',
        unsafe_allow_html=True,
    )

st.markdown(" ")
meta_col1, meta_col2 = st.columns(2)
meta_col1.markdown(f"**Goal:** `{pair['Goal']}`")
meta_col2.markdown(f"**Intent:** `{pair['Intent']}`")

st.markdown("---")

# ── Scoring buttons ────────────────────────────────────────────────────────────
st.markdown("**Was the agent's response correct?**")

SCORES = ["Correct", "Partially Correct", "Incorrect", "Not Sure"]
current_score = annotations[idx]

score_cols = st.columns(len(SCORES))
for score, col in zip(SCORES, score_cols):
    label = f"✓ {score}" if current_score == score else score
    if col.button(label, key=f"btn_{idx}_{score}", use_container_width=True):
        st.session_state["annotations"][idx] = score
        next_unannotated = next(
            (i for i in range(idx + 1, total) if annotations[i] is None), None
        )
        if next_unannotated is not None:
            st.session_state["current_idx"] = next_unannotated
        st.rerun()

# JavaScript injected via components iframe — accesses parent document to
# color the score buttons by their text content, and re-runs on DOM changes.
components.html("""
<script>
(function () {
    var COLORS = {
        "Correct":           { bg: "#27ae60", fg: "white" },
        "Partially Correct": { bg: "#e6ac00", fg: "white" },
        "Incorrect":         { bg: "#e74c3c", fg: "white" },
        "Not Sure":          { bg: "#2980b9", fg: "white" }
    };

    function applyColors() {
        try {
            var doc = window.parent.document;
            doc.querySelectorAll("button").forEach(function (btn) {
                var pEl  = btn.querySelector("p");
                var raw  = pEl ? pEl.innerText : btn.innerText;
                var text = raw.replace(/^✓\s*/, "").trim();
                var c    = COLORS[text];
                if (c) {
                    btn.style.setProperty("background-color", c.bg, "important");
                    btn.style.setProperty("border-color",     c.bg, "important");
                    btn.style.setProperty("color",            c.fg, "important");
                }
            });
        } catch (e) {}
    }

    applyColors();
    try {
        new MutationObserver(applyColors).observe(
            window.parent.document.body,
            { childList: true, subtree: true }
        );
    } catch (e) {}
})();
</script>
""", height=0)

st.markdown("---")

# ── Navigation ─────────────────────────────────────────────────────────────────
nav_prev, nav_info, nav_next = st.columns([1, 3, 1])

if nav_prev.button("← Previous", disabled=idx == 0, use_container_width=True):
    st.session_state["current_idx"] -= 1
    st.rerun()

if nav_next.button("Next →", disabled=idx == total - 1, use_container_width=True):
    st.session_state["current_idx"] += 1
    st.rerun()

unannotated_indices = [i for i, a in enumerate(annotations) if a is None]
if unannotated_indices:
    nav_info.caption(f"{len(unannotated_indices)} pair(s) still need annotation.")
    if nav_info.button("Jump to next unannotated", use_container_width=True):
        st.session_state["current_idx"] = unannotated_indices[0]
        st.rerun()
else:
    nav_info.success("All pairs annotated — ready to export!")

st.markdown("---")

# ── Export ─────────────────────────────────────────────────────────────────────
st.markdown("### Export Annotations")

output = {
    "annotator":       st.session_state.annotator_name,
    "exported_at":     datetime.now(timezone.utc).isoformat(),
    "total_pairs":     total,
    "annotated_pairs": annotated,
    "annotations": [
        {
            "turn_id":    pairs[i]["turn_id"],
            "chat_id":    pairs[i]["chat_id"],
            "Prev Agent": pairs[i]["Prev Agent"],
            "User":       pairs[i]["User"],
            "Agent":      pairs[i]["Agent"],
            "Goal":       pairs[i]["Goal"],
            "Intent":     pairs[i]["Intent"],
            "score":      annotations[i],
        }
        for i in range(total)
    ],
}

safe_name = st.session_state.annotator_name.replace(" ", "_").lower()
filename  = f"annotations_{safe_name}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"

st.download_button(
    label="⬇️ Download Annotations JSON",
    data=json.dumps(output, ensure_ascii=False, indent=2),
    file_name=filename,
    mime="application/json",
    use_container_width=True,
)
