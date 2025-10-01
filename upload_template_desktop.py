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
if "upload_triggered" not in st.session_state:
    st.session_state.upload_triggered = False
if "final_confirm_triggered" not in st.session_state:
    st.session_state.final_confirm_triggered = False

# --- Simulated entity extraction ---
def extract_entities(image):
    return {
        "brand_name": "MockBrand",
        "payment_type": "Credit Card",
        "category": "Meals",
        "tax_code": "TX123"
    }

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

# --- Upload to AI logic ---
def upload_group():
    st.session_state.upload_triggered = True

# --- Final confirmation logic ---
def final_confirm():
    group = st.session_state.groups.pop(0)
    st.session_state.submitted_groups.append(group)
    st.session_state.confirm_triggered = False
    st.session_state.upload_triggered = False
    st.session_state.final_confirm_triggered = True

    # Initialize next group
    st.session_state.groups.append({
        "claimant_id": "Donald Trump",
        "images": [None]*4,
        "doc_types": ["receipt", "proof of payment", "", ""]
    })

    st.experimental_rerun()

# ✅ Sidebar controls
with st.sidebar:
    st.header("🧭 Controls")
    if st.session_state.groups:
        st.button("🖼️ Confirm Current Group", on_click=confirm_group)
        if st.session_state.confirm_triggered and not st.session_state.upload_triggered:
            st.button("📤 Upload to AI", on_click=upload_group)
    if st.session_state.upload_triggered and not st.session_state.final_confirm_triggered:
        st.button("✅ Final Confirmation — Proceed to Next Group", on_click=final_confirm)

# --- Render current group only ---
if st.session_state.groups:
    group = st.session_state.groups[0]
    group_idx = len(st.session_state.submitted_groups) + 1
    st.markdown(f"---\n### Claim Group {group_idx}")
    group["claimant_id"] = st.selectbox(
        "Claimant ID",
        ["Donald Trump", "Joe Biden"],
        index=0 if group["claimant_id"] == "Donald Trump" else 1,
        key=f"claimant_id_{group_idx}"
    )

    cols = st.columns(4)
    for img_idx in range(4):
        uploader_key = f"img_{group_idx}_{img_idx}"
        type_key = f"type_{group_idx}_{img_idx}"

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
        st.markdown(f"### Confirmation Group {group_idx}")
        st.image(preview_image, caption="🖼️ Group Preview Before Upload", use_container_width=True)

# --- Display editable entity tables after upload ---
if st.session_state.upload_triggered:
    st.markdown(f"---\n### 📑 Entity Tables for Group {group_idx}")
    st.write(f"**Claimant ID:** {group['claimant_id']}")
    for img_idx, image in enumerate(group["images"]):
        if image:
            doc_type = group["doc_types"][img_idx]
            st.markdown(f"**Document {img_idx + 1} ({doc_type}) — Editable Entity Table**")
            entities = extract_entities(image)

            cols = st.columns(4)
            cols[0].markdown("**brand_name**")
            cols[0].write(entities["brand_name"])

            cols[1].markdown("**payment_type**")
            cols[1].selectbox(
                "", ["Credit Card", "Cash", "Bank Transfer"],
                index=0, key=f"payment_type_{group_idx}_{img_idx}"
            )

            cols[2].markdown("**category**")
            cols[2].selectbox(
                "", ["Meals", "Transport", "Office Supplies"],
                index=0, key=f"category_{group_idx}_{img_idx}"
            )

            cols[3].markdown("**tax_code**")
            cols[3].selectbox(
                "", ["TX123", "TX456", "TX789"],
                index=0, key=f"tax_code_{group_idx}_{img_idx}"
            )
