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

# 2) HANDLING FINAL CONFIRMATION – NO experimental_rerun()
def final_confirm():
    # Move group1 to submitted
    group = st.session_state.groups.pop(0)
    st.session_state.submitted_groups.append(group)
    # Reset all interim flags
    st.session_state.confirm_triggered = False
    st.session_state.upload_triggered = False
    st.session_state.final_confirm_triggered = True
    # Tell the next run to reinitialize groups
    st.session_state.init_next_group = True

# 3) ONCE INIT FLAG IS SET, REPLACE WITH A FRESH GROUP
if st.session_state.init_next_group:
    st.session_state.groups = [{
        "claimant_id": "Donald Trump",
        "images": [None]*4,
        "doc_types": ["receipt", "proof of payment", "", ""]
    }]
    # reset flags so we show Upload → Final Confirm again
    st.session_state.init_next_group = False
    st.session_state.final_confirm_triggered = False

# 4) YOUR OTHER CONTROLS
def confirm_group():
    st.session_state.confirm_triggered = True

def upload_group():
    st.session_state.upload_triggered = True

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

# 5) ENTITY EXTRACT & PREVIEW HELPERS
def extract_entities(image):
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
        im = ImageOps.exif_transpose(im).resize((300,300))
        pil_imgs.append(im)
    w = 310 * len(pil_imgs)
    preview = Image.new("RGB", (w, 320), "white")
    for i, im in enumerate(pil_imgs):
        preview.paste(im, (i*310, 10))
    draw = ImageDraw.Draw(preview)
    draw.text((10,290), f"Claimant: {group['claimant_id']}", fill="black")
    return preview

# 6) RENDER CURRENT GROUP UPLOAD FORM
if st.session_state.groups:
    group = st.session_state.groups[0]
    idx = len(st.session_state.submitted_groups) + 1
    st.markdown(f"---\n### Claim Group {idx}")
    group["claimant_id"] = st.selectbox(
        "Claimant ID",
        ["Donald Trump","Joe Biden"],
        index=0 if group["claimant_id"]=="Donald Trump" else 1,
        key=f"claimant_id_{idx}"
    )
    cols = st.columns(4)
    for i in range(4):
        up_key = f"img_{idx}_{i}"
        tp_key = f"type_{idx}_{i}"
        uploaded = cols[i].file_uploader(
            f"Document {i+1}", type=["jpg","png"], key=up_key
        )
        group["images"][i] = uploaded
        group["doc_types"][i] = cols[i].selectbox(
            "Type", ["receipt","proof of payment","other"],
            index=0 if i==0 else 1, key=tp_key
        )
        if uploaded:
            img = Image.open(uploaded)
            img = ImageOps.exif_transpose(img)
            st.image(img, use_container_width=True,
                     caption=f"Doc {i+1} — {group['doc_types'][i]}")

# 7) SHOW PREVIEW AFTER CONFIRM
if st.session_state.confirm_triggered and st.session_state.groups:
    prev = generate_group_preview(st.session_state.groups[0])
    if prev:
        st.markdown(f"### Confirmation Group {idx}")
        st.image(prev, caption="🖼️ Group Preview Before Upload",
                 use_container_width=True)

# 8) DISPLAY ENTITY TABLES AFTER UPLOAD
if st.session_state.upload_triggered:
    st.markdown(f"---\n### 📑 Entity Tables for Group {idx}")
    st.write(f"**Claimant ID:** {group['claimant_id']}")
    for i, img in enumerate(group["images"]):
        if not img:
            continue
        dt = group["doc_types"][i]
        st.markdown(f"**Document {i+1} ({dt}) — Editable Entity Table**")
        ent = extract_entities(img)
        row_cols = st.columns(4)
        row_cols[0].markdown("**brand_name**");  row_cols[0].write(ent["brand_name"])
        row_cols[1].markdown("**payment_type**")
        row_cols[1].selectbox("", ["Credit Card","Cash","Bank Transfer"],
                              index=0, key=f"payment_type_{idx}_{i}")
        row_cols[2].markdown("**category**")
        row_cols[2].selectbox("", ["Meals","Transport","Office Supplies"],
                              index=0, key=f"category_{idx}_{i}")
        row_cols[3].markdown("**tax_code**")
        row_cols[3].selectbox("", ["TX123","TX456","TX789"],
                              index=0, key=f"tax_code_{idx}_{i}")
