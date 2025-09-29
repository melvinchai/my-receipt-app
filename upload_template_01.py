import streamlit as st
import pandas as pd
from PIL import Image

st.set_page_config(page_title="Grouped Document Uploader", layout="wide")
st.title("📄 Grouped Document Uploader")

# Initialize session state
if "groups" not in st.session_state:
    st.session_state.groups = [{
        "claimant_id": "Donald Trump",
        "images": [None]*4,
        "doc_types": ["receipt", "proof of payment", "", ""],
        "preview_index": None  # Track which image to enlarge
    }]

# Simulated entity extraction
def extract_entities(image):
    return pd.DataFrame({
        "Field": ["brand_name", "payment_type", "category", "tax_code"],
        "Value": ["MockBrand", "Credit Card", "Meals", "TX123"]
    })

# Render each group
for group_idx, group in enumerate(st.session_state.groups):
    st.subheader(f"Claim Group {group_idx + 1}")
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
        remove_key = f"remove_{group_idx}_{img_idx}"
        preview_key = f"preview_{group_idx}_{img_idx}"

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
            cols[img_idx].image(image, caption="Preview", width=100)

            # Enlarge on click
            if cols[img_idx].button("🔍 Enlarge", key=preview_key):
                group["preview_index"] = img_idx
                st.experimental_rerun()

            # Remove button
            if cols[img_idx].button("Remove", key=remove_key):
                st.session_state[uploader_key] = None
                group["images"][img_idx] = None
                group["preview_index"] = None
                st.experimental_rerun()

    # Show enlarged image if triggered
    if group["preview_index"] is not None:
        enlarged = group["images"][group["preview_index"]]
        if enlarged:
            st.markdown(f"### 🔍 Enlarged View: Document {group['preview_index'] + 1}")
            st.image(Image.open(enlarged), use_column_width=True)
            if st.button("Close Preview", key=f"close_{group_idx}"):
                group["preview_index"] = None
                st.experimental_rerun()

# Add more groups
if st.button("➕ Add More Claim Group"):
    st.session_state.groups.append({
        "claimant_id": "Donald Trump",
        "images": [None]*4,
        "doc_types": ["receipt", "proof of payment", "", ""],
        "preview_index": None
    })

# Submit and extract
if st.button("✅ Submit"):
    for group_idx, group in enumerate(st.session_state.groups):
        st.markdown(f"---\n### 📑 Entity Tables for Claim Group {group_idx + 1}")
        st.write(f"**Claimant ID:** {group['claimant_id']}")
        for img_idx, image in enumerate(group["images"]):
            if image:
                doc_type = group["doc_types"][img_idx]
                st.markdown(f"**Document {img_idx + 1} ({doc_type})**")
                entity_df = extract_entities(image)
                st.dataframe(entity_df)
