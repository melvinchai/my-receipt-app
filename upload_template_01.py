import streamlit as st
import pandas as pd
from PIL import Image

st.set_page_config(page_title="Grouped Document Uploader", layout="wide")
st.title("📄 Grouped Document Uploader")

# Initialize session state
if "groups" not in st.session_state:
    st.session_state.groups = [{
        "claimant_id": "",
        "images": [None]*4,
        "doc_types": ["receipt", "proof of payment", "", ""]
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
    group["claimant_id"] = st.text_input(
        f"Claimant ID for Group {group_idx + 1}",
        value=group["claimant_id"],
        key=f"claimant_{group_idx}"
    )

    cols = st.columns(4)
    for img_idx in range(4):
        key = f"group{group_idx}_img{img_idx}"
        uploaded = cols[img_idx].file_uploader(
            f"Document {img_idx + 1}",
            type=["jpg", "jpeg", "png"],
            key=key
        )
        group["images"][img_idx] = uploaded

        # Document type selector
        group["doc_types"][img_idx] = cols[img_idx].selectbox(
            "Type",
            ["receipt", "proof of payment", "other"],
            index=0 if img_idx == 0 else 1,
            key=f"type_{group_idx}_{img_idx}"
        )

        # Thumbnail preview
        if uploaded:
            image = Image.open(uploaded)
            cols[img_idx].image(image, caption="Preview", width=100)

            # Remove button
            if cols[img_idx].button("Remove", key=f"remove_{group_idx}_{img_idx}"):
                group["images"][img_idx] = None
                st.experimental_rerun()

# Add more groups
if st.button("➕ Add More Claim Group"):
    st.session_state.groups.append({
        "claimant_id": "",
        "images": [None]*4,
        "doc_types": ["receipt", "proof of payment", "", ""]
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
