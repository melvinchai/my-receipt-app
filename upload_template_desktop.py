import streamlit as st
import pandas as pd
from PIL import Image, ImageOps, ImageDraw

st.set_page_config(page_title="Grouped Document Uploader", layout="wide")
st.title("📄 Grouped Document Uploader")

# ✅ Initialize session state
if "groups" not in st.session_state:
    st.session_state.groups = [{
        "claimant_id": "Donald Trump",
        "images": [None]*4,
        "doc_types": ["receipt", "proof of payment", "", ""]
    }]
if "submitted_groups" not in st.session_state:
    st.session_state.submitted_groups = []
if "confirm_triggered" not in st.session_state:
    st.session_state.confirm_triggered = False
if "submit_triggered" not in st.session_state:
    st.session_state.submit_triggered = False

# --- Simulated entity extraction ---
def extract_entities(image):
    return pd.DataFrame({
        "Field": ["brand_name", "payment_type", "category", "tax_code"],
        "Value": ["MockBrand", "Credit Card", "Meals", "TX123"]
    })

# --- Generate stitched preview image ---
def generate_group_preview(group):
    images = [img for img in group["images"] if img]
    if not images:
        return None

    pil_images = []
    for img in images:
        image = Image.open(img)
        image = ImageOps.exif_transpose(image)
        image = image.resize((300, 300))
        pil_images.append(image)

    total_width = 310 * len(pil_images)
    preview = Image.new("RGB", (total_width, 320), color="white")

    for idx, img in enumerate(pil_images):
        preview.paste(img, (idx * 310, 10))

    draw = ImageDraw.Draw(preview)
    draw.text((10, 290), f"Claimant: {group['claimant_id']}", fill="black")

    return preview

# --- Confirm logic ---
def confirm_group():
    st.session_state.confirm_triggered = True

# --- Submit logic ---
def submit_group():
    group = st.session_state.groups.pop(0)
    st.session_state.submitted_groups.append(group)
    st.session_state.submit_triggered = True
    st.session_state.confirm_triggered = False

# ✅ Sidebar controls
with st.sidebar:
    st.header("🧭 Controls")
    if st.session_state.groups:
        st.button("🖼️ Confirm Current Group", on_click=confirm_group)
        if st.session_state.confirm_triggered:
            st.button("✅ Submit Current Group", on_click=submit_group)

# ✅ Display success message
if st.session_state.submit_triggered:
    submitted_idx = len(st.session_state.submitted_groups)
    st.success(f"✅ Submitted successfully for Group {submitted_idx}")
    st.session_state.submit_triggered = False

# --- Render current group only ---
if st.session_state.groups:
    group = st.session_state.groups[0]
    st.markdown(f"---\n### Claim Group {len(st.session_state.submitted_groups) + 1}")
    group["claimant_id"] = st.selectbox(
        "Claimant ID",
        ["Donald Trump", "Joe Biden"],
        index=0 if group["claimant_id"] == "Donald Trump" else 1,
        key="claimant_id"
    )

    cols = st.columns(4)
    for img_idx in range(4):
        uploader_key = f"img_{img_idx}"
        type_key = f"type_{img_idx}"

        uploaded = cols[img_idx].file_uploader(
            f"Document {img_idx + 1}",
            type=["jpg", "jpeg", "png"],
            key=uploader_key
        )
        group["images"][img_idx] = uploaded

        group["doc_types"][img_idx] = cols[img_idx].selectbox(
            "Type",
            ["receipt", "proof of payment", "other"],
            index=0 if img_idx == 0 else 1,
            key=type_key
        )

        if uploaded:
            image = Image.open(uploaded)
            image = ImageOps.exif_transpose(image)
            st.image(image, caption=f"Document {img_idx + 1} — {group['doc_types'][img_idx]}", use_container_width=True)

# --- Show preview after confirmation ---
if st.session_state.confirm_triggered and st.session_state.groups:
    preview_image = generate_group_preview(st.session_state.groups[0])
    if preview_image:
        st.markdown("### Confirmation Group 1")
        st.image(preview_image, caption="🖼️ Group 1 Preview Before Submission", use_container_width=True)

# --- Optional: Display entity tables for submitted groups ---
for idx, group in enumerate(st.session_state.submitted_groups):
    st.markdown(f"---\n### 📑 Entity Tables for Submitted Group {idx + 1}")
    st.write(f"**Claimant ID:** {group['claimant_id']}")
    for img_idx, image in enumerate(group["images"]):
        if image:
            doc_type = group["doc_types"][img_idx]
            st.markdown(f"**Document {img_idx + 1} ({doc_type})**")
            entity_df = extract_entities(image)
            st.dataframe(entity_df)
