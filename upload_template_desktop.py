import streamlit as st
import pandas as pd
from PIL import Image, ImageOps, ImageDraw

st.set_page_config(page_title="Grouped Document Uploader", layout="wide")
st.title("📄 Grouped Document Uploader")

# 1) SESSION STATE INIT
if "groups" not in st.session_state:
    st.session_state.groups = [{
        "claimant_id": "Donald Trump",
        "images": [None]*4,
        "doc_types": ["receipt", "proof of payment", "", ""]
    }]
if "submitted_groups" not in st.session_state:
    st.session_state.submitted_groups = []
for flag in (
    "confirm_triggered",
    "upload_triggered",
    "final_confirm_triggered",
    "init_next_group",
):
    if flag not in st.session_state:
        st.session_state[flag] = False

# 2) CALLBACKS
def confirm_group():
    st.session_state.confirm_triggered = True

def upload_group():
    st.session_state.upload_triggered = True

def final_confirm():
    # Move Group 1 to submitted
    group = st.session_state.groups.pop(0)
    st.session_state.submitted_groups.append(group)
    # Reset flags and trigger next-group init
    st.session_state.confirm_triggered = False
    st.session_state.upload_triggered = False
    st.session_state.final_confirm_triggered = True
    st.session_state.init_next_group = True

# 3) INITIALIZE NEXT GROUP AFTER RERUN
if st.session_state.init_next_group:
    st.session_state.groups = [{
        "claimant_id": "Donald Trump",
        "images": [None]*4,
        "doc_types": ["receipt", "proof of payment", "", ""]
    }]
    st.session_state.init_next_group = False
    st.session_state.final_confirm_triggered = False

# 4) SIDEBAR CONTROLS
with st.sidebar:
    st.header("🧭 Controls")
    if st.session_state.groups:
        st.button("🖼️ Confirm Current Group", on_click=confirm_group)
        if st.session_state.confirm_triggered and not st.session_state.upload_triggered:
            st.button("📤 Upload to AI", on_click=upload_group)
    if st.session_state.upload_triggered and not st.session_state.final_confirm_triggered:
        st.button(
            "✅ Final Confirmation — Proceed to Next Group",
            on_click=final_confirm
        )

# 5) HELPERS
def extract_entities(image):
    # Stubbed AI extraction
    return {
        "brand_name": "MockBrand",
        "payment_type": "Credit Card",
        "category": "Meals",
        "tax_code": "TX123"
    }

def generate_group_preview(group):
    imgs = [img for img in group["images"] if img]
    if not imgs:
        return None
    pil_imgs = []
    for img in imgs:
        im = Image.open(img)
        im = ImageOps.exif_transpose(im).resize((300, 300))
        pil_imgs.append(im)
    w = 310 * len(pil_imgs)
    preview = Image.new("RGB", (w, 320), "white")
    for i, im in enumerate(pil_imgs):
        preview.paste(im, (i * 310, 10))
    draw = ImageDraw.Draw(preview)
    draw.text((10, 290), f"Claimant: {group['claimant_id']}", fill="black")
    return preview

# 6) RENDER CURRENT GROUP UPLOAD FORM
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
        up_key = f"img_{group_idx}_{img_idx}"
        tp_key = f"type_{group_idx}_{img_idx}"

        uploaded = cols[img_idx].file_uploader(
            f"Document {img_idx + 1}",
            type=["jpg", "jpeg", "png"],
            key=up_key
        )
        group["images"][img_idx] = uploaded

        group["doc_types"][img_idx] = cols[img_idx].selectbox(
            "Type",
            ["receipt", "proof of payment", "other"],
            index=0 if img_idx == 0 else 1,
            key=tp_key
        )

        if uploaded:
            im = Image.open(uploaded)
            im = ImageOps.exif_transpose(im)
            st.image(
                im,
                caption=f"Document {img_idx + 1} — {group['doc_types'][img_idx]}",
                use_container_width=True
            )

# 7) SHOW PREVIEW AFTER CONFIRM
if st.session_state.confirm_triggered and st.session_state.groups:
    prev = generate_group_preview(st.session_state.groups[0])
    if prev:
        st.markdown(f"### Confirmation Group {group_idx}")
        st.image(prev, caption="🖼️ Group Preview Before Upload", use_container_width=True)

# 8) DISPLAY ENTITY TABLES AS A TRUE TABLE AFTER UPLOAD
if st.session_state.upload_triggered:
    st.markdown(f"---\n### 📑 Entity Tables for Group {group_idx}")
    st.write(f"**Claimant ID:** {group['claimant_id']}")

    field_names = ["brand_name", "payment_type", "category", "tax_code"]
    options_map = {
        "payment_type": ["Credit Card", "Cash", "Bank Transfer"],
        "category": ["Meals", "Transport", "Office Supplies"],
        "tax_code": ["TX123", "TX456", "TX789"]
    }

    for img_idx, image in enumerate(group["images"]):
        if not image:
            continue

        doc_type = group["doc_types"][img_idx]
        st.markdown(f"**Document {img_idx + 1} ({doc_type}) — Editable Entity Table**")
        entities = extract_entities(image)

        # Header row
        h1, h2, h3 = st.columns([1, 2, 2])
        h1.markdown("**Field**")
        h2.markdown("**Extracted**")
        h3.markdown("**Correction**")

        # Data rows
        for field in field_names:
            c1, c2, c3 = st.columns([1, 2, 2])
            c1.write(field)
            c2.write(entities[field])

            if field == "brand_name":
                # no correction for brand_name
                c3.write(entities[field])
            else:
                opts = options_map[field]
                default_idx = opts.index(entities[field]) if entities[field] in opts else 0
                c3.selectbox(
                    "",
                    opts,
                    index=default_idx,
                    key=f"{field}_{group_idx}_{img_idx}"
                )
