import streamlit as st
import pandas as pd
from PIL import Image, ImageOps
import io

st.set_page_config(page_title="Grouped Document Uploader", layout="wide")
st.title("📄 Grouped Document Uploader")

# ✅ Always initialize session state first
if "groups" not in st.session_state:
    st.session_state.groups = [{
        "claimant_id": "Donald Trump",
        "images": [None]*4,
        "doc_types": ["receipt", "proof of payment", "", ""]
    }]

# ✅ Sidebar controls
with st.sidebar:
    st.header("🧭 Controls")
    if st.button("➕ Add More Claim Group"):
        st.session_state.groups.append({
            "claimant_id": "Donald Trump",
            "images": [None]*4,
            "doc_types": ["receipt", "proof of payment", "", ""]
        })
        st.experimental_rerun()

    submit_triggered = st.button("✅ Submit")

# --- Simulated entity extraction ---
def extract_entities(image):
    return pd.DataFrame({
        "Field": ["brand_name", "payment_type", "category", "tax_code"],
        "Value": ["MockBrand", "Credit Card", "Meals", "TX123"]
    })

# --- Render each group ---
for group_idx, group in enumerate(st.session_state.groups):
    st.markdown(f"---\n### Claim Group {group_idx + 1}")
    group["claimant_id"] = st.selectbox(
        f"Claimant ID for Group {group_idx + 1}",
        ["Donald Trump", "Joe Biden"],
        index=0 if group["claimant_id"] == "Donald Trump" else 1,
        key=f"claimant_{group_idx}"
    )

    cols = st.columns(4)
    for img_idx in range(4):
        uploader_key = f"group{group_idx}_img{img_idx}"
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

        # ✅ Fail-safe full image preview with EXIF rotation
        if uploaded:
            image = Image.open(uploaded)
            image = ImageOps.exif_transpose(image)
            st.image(image, caption=f"Document {img_idx + 1} — {group['doc_types'][img_idx]}", use_container_width=True)

# --- Submit logic ---
if submit_triggered:
    for group_idx, group in enumerate(st.session_state.groups):
        st.markdown(f"---\n### 📑 Entity Tables for Claim Group {group_idx + 1}")
        st.write(f"**Claimant ID:** {group['claimant_id']}")
        for img_idx, image in enumerate(group["images"]):
            if image:
                doc_type = group["doc_types"][img_idx]
                st.markdown(f"**Document {img_idx + 1} ({doc_type})**")
                entity_df = extract_entities(image)
                st.dataframe(entity_df)
