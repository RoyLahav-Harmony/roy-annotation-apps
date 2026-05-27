# ══════════════════════════════════════════════════════════════════════════════
# annotation_tool_explained.py
# Annotated version of annotation_tool.py for documentation purposes.
# ══════════════════════════════════════════════════════════════════════════════

import json
import hashlib                           # Used to detect when a new file is uploaded.
import streamlit as st
import streamlit.components.v1 as components  # Allows injecting raw HTML/JS into the page.
from datetime import datetime, timezone

st.set_page_config(page_title="Annotation Tool", layout="wide")
st.title("Annotation Tool")


# ── Annotator name gate ────────────────────────────────────────────────────────
# The first thing the app does is ask for the reviewer's name.
# This name is stored in session_state and stamped onto the exported JSON.
# The app will not proceed past this block until a name is entered.

if "annotator_name" not in st.session_state:
    st.session_state.annotator_name = ""

if not st.session_state.annotator_name:
    st.subheader("Welcome")
    st.markdown("Please enter your name before starting.")
    name_input = st.text_input("Your name", placeholder="e.g. Jane Smith")
    if st.button("Start", type="primary") and name_input.strip():
        st.session_state.annotator_name = name_input.strip()
        st.rerun()  # Reload the page to show the main UI.
    st.stop()       # Nothing below this line runs until a name is saved.


# ── File upload ────────────────────────────────────────────────────────────────
# The user uploads the review_dataset.json produced by analysis_tool.py.
# st.stop() means the rest of the app won't render until a file is provided.

uploaded = st.file_uploader("Upload a review dataset JSON file", type=["json"])
if uploaded is None:
    st.info("Upload a review dataset JSON file to begin annotating.")
    st.stop()


# ── Load pairs from file ───────────────────────────────────────────────────────
# @st.cache_data caches the result so the file is only parsed once,
# even as the user clicks through pairs and the page re-renders.

@st.cache_data
def load_pairs(content: bytes) -> list[dict]:
    data = json.loads(content)
    pairs = []
    for item in data:
        chat_id  = item.get("chat_id", "unknown")
        turn_num = item.get("#", "?")
        pairs.append({
            # Combine chat_id and turn number into a unique identifier for this exchange.
            "turn_id":     f"{chat_id}_t{turn_num}",
            "chat_id":     chat_id,
            "Prev Agent":  item.get("Prev Agent", "—"),
            "User":        item.get("User", ""),
            "Agent":       item.get("Agent", ""),
            "Goal":        item.get("Goal", "—"),
            "Intent":      item.get("Intent", "—"),
            # Stored with a leading underscore to signal it's internal/hidden from display.
            "_confidence": item.get("Confidence"),
        })
    return pairs


pairs = load_pairs(uploaded.read())
total = len(pairs)

# ── Reset state when a new file is uploaded ────────────────────────────────────
# Compute an MD5 hash of the file contents.
# If it differs from the last loaded file, reset all annotation state so the
# user starts fresh with a clean slate on the new file.

file_hash = hashlib.md5(uploaded.getvalue()).hexdigest()
if st.session_state.get("_file_hash") != file_hash:
    st.session_state["_file_hash"]  = file_hash
    st.session_state["annotations"] = [None] * total  # None = not yet annotated.
    st.session_state["current_idx"] = 0               # Start at the first pair.

# Convenience alias — session_state["annotations"] is a list where each element
# is either None (unannotated) or a score string like "Correct".
annotations: list = st.session_state["annotations"]


# ── Progress header ────────────────────────────────────────────────────────────
# Shows the annotator's name and how many pairs have been scored so far.

annotated = sum(1 for a in annotations if a is not None)
st.caption(
    f"Annotator: **{st.session_state.annotator_name}**  ·  "
    f"Progress: **{annotated} / {total}** pairs annotated"
)
# Visual progress bar from 0.0 to 1.0.
st.progress(annotated / total if total else 0)
st.markdown("---")


# ── Current pair display ───────────────────────────────────────────────────────
# Show one pair at a time based on current_idx.

idx  = st.session_state["current_idx"]
pair = pairs[idx]

st.markdown(f"#### Pair {idx + 1} of {total}")
st.caption(f"Turn ID: `{pair['turn_id']}`  ·  Chat: `{pair['chat_id']}`")
st.markdown(" ")

# ── Inline styles for the turn display boxes ──────────────────────────────────
# These are defined as plain CSS strings and injected directly into the HTML.
# Inline styles are used instead of CSS classes because Streamlit's CSS
# pipeline can override or drop class-based styles unpredictably.

BOX_STYLE = (
    "background-color:#000000;"   # Black background so white text is readable.
    "border:1px solid #444;"
    "border-radius:6px;"
    "padding:14px 16px;"
    "font-size:1.8rem;"           # 2× the default font size for easy reading.
    "min-height:110px;"
    "line-height:1.4;"
    "color:#ffffff;"              # White text on black background.
)
LABEL_STYLE = (
    "font-size:0.95rem;"
    "font-weight:600;"
    "color:#444;"
    "margin-bottom:6px;"
)

# Three equal-width columns: previous agent turn | user turn | agent turn.
col_prev, col_user, col_agent = st.columns(3)

with col_prev:
    st.markdown(
        f'<div style="{LABEL_STYLE}">Previous Agent Turn</div>'
        f'<div style="{BOX_STYLE}">{pair["Prev Agent"] or "<em>none</em>"}</div>',
        unsafe_allow_html=True,  # Required to render raw HTML in Streamlit.
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

# Show the Goal and Intent metadata below the turn boxes.
st.markdown(" ")
meta_col1, meta_col2 = st.columns(2)
meta_col1.markdown(f"**Goal:** `{pair['Goal']}`")
meta_col2.markdown(f"**Intent:** `{pair['Intent']}`")

st.markdown("---")


# ── Scoring buttons ────────────────────────────────────────────────────────────
# Four buttons — one per possible score. The currently selected score is shown
# with a checkmark prefix so the annotator can see their choice at a glance.
# Clicking a button saves the score and advances to the next unannotated pair.

st.markdown("**Was the agent's response correct?**")

SCORES = ["Correct", "Partially Correct", "Incorrect", "Not Sure"]
current_score = annotations[idx]  # The score already saved for this pair (or None).

score_cols = st.columns(len(SCORES))
for score, col in zip(SCORES, score_cols):
    # Add a checkmark to the label if this button matches the saved score.
    label = f"✓ {score}" if current_score == score else score
    if col.button(label, key=f"btn_{idx}_{score}", use_container_width=True):
        # Save the score for the current pair.
        st.session_state["annotations"][idx] = score
        # Auto-advance: find the next pair that hasn't been annotated yet.
        next_unannotated = next(
            (i for i in range(idx + 1, total) if annotations[i] is None), None
        )
        if next_unannotated is not None:
            st.session_state["current_idx"] = next_unannotated
        st.rerun()  # Re-render the page to show the next pair.


# ── Button colour injection via JavaScript ─────────────────────────────────────
# Streamlit doesn't support custom CSS on individual buttons reliably.
# Instead, we inject a small JavaScript snippet inside a hidden iframe
# (via components.html). The script reaches into the parent page's DOM
# and colours each button based on its text content.
# A MutationObserver re-runs the colouring whenever the DOM changes
# (e.g. when the page re-renders after a button click).

components.html("""
<script>
(function () {
    // Map each score label to its background colour.
    var COLORS = {
        "Correct":           { bg: "#27ae60", fg: "white" },  // Green
        "Partially Correct": { bg: "#e6ac00", fg: "white" },  // Yellow
        "Incorrect":         { bg: "#e74c3c", fg: "white" },  // Red
        "Not Sure":          { bg: "#2980b9", fg: "white" }   // Blue
    };

    function applyColors() {
        try {
            var doc = window.parent.document;  // Access the parent Streamlit page.
            doc.querySelectorAll("button").forEach(function (btn) {
                var pEl  = btn.querySelector("p");
                var raw  = pEl ? pEl.innerText : btn.innerText;
                // Strip the "✓ " prefix if present to get the plain score name.
                var text = raw.replace(/^✓\\s*/, "").trim();
                var c    = COLORS[text];
                if (c) {
                    // Use !important to override Streamlit's own button styles.
                    btn.style.setProperty("background-color", c.bg, "important");
                    btn.style.setProperty("border-color",     c.bg, "important");
                    btn.style.setProperty("color",            c.fg, "important");
                }
            });
        } catch (e) {}
    }

    applyColors();  // Run once on load.

    // Watch for DOM changes and re-apply colours after each page re-render.
    try {
        new MutationObserver(applyColors).observe(
            window.parent.document.body,
            { childList: true, subtree: true }
        );
    } catch (e) {}
})();
</script>
""", height=0)  # height=0 hides the iframe — we only need the script to run.

st.markdown("---")


# ── Navigation controls ────────────────────────────────────────────────────────
# Three controls in a row: Previous | status/jump | Next.

nav_prev, nav_info, nav_next = st.columns([1, 3, 1])

# Previous button — disabled on the first pair.
if nav_prev.button("← Previous", disabled=idx == 0, use_container_width=True):
    st.session_state["current_idx"] -= 1
    st.rerun()

# Next button — disabled on the last pair.
if nav_next.button("Next →", disabled=idx == total - 1, use_container_width=True):
    st.session_state["current_idx"] += 1
    st.rerun()

# Middle section: shows how many pairs remain, with a shortcut to jump to the first one.
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
# Builds the output JSON in memory and offers it as a file download.
# The confidence score (_confidence) is included here even though it was
# hidden from the annotator during scoring.

st.markdown("### Export Annotations")

output = {
    "annotator":       st.session_state.annotator_name,  # Who did the annotation.
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
            "confidence": pairs[i]["_confidence"],  # Hidden during annotation, included in export.
            "score":      annotations[i],           # The annotator's verdict (or None if skipped).
        }
        for i in range(total)
    ],
}

# Build a filename that includes the annotator's name and today's date.
safe_name = st.session_state.annotator_name.replace(" ", "_").lower()
filename  = f"annotations_{safe_name}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"

st.download_button(
    label="⬇️ Download Annotations JSON",
    data=json.dumps(output, ensure_ascii=False, indent=2),
    file_name=filename,
    mime="application/json",
    use_container_width=True,
)
