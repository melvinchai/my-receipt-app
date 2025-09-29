import streamlit as st
import pandas as pd
from PIL import Image
import io
import base64

st.set_page_config(page_title="Grouped Document Uploader", layout="wide")
st.title("📄 Grouped Document Uploader")

# Initialize session state
if "groups" not in st.session_state:
    st.session_state.groups = [{
        "claimant_id": "Donald Trump",
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

        # Thumbnail with click-to-enlarge
        if uploaded:
            image = Image.open(uploaded)
            buffered = io.BytesIO()
            image.save(buffered, format="PNG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode()

            html = f"""
            <style>
            .clickable-img {{
                width: 100px;
                transition: all 0.3s ease;
                cursor: pointer;
            }}
            .clickable-img.enlarged {{
                width: 500px;
                z-index: 1000;
            }}
            </style>
            <script>
            function toggleSize(e) {{
                e.classList.toggle('enlarged');
            }}
            </script>
            <img src="data:image/png;base64,{img_b64}" class="clickable-img" onclick="toggleSize(this)">
            """
            cols[img_idx].markdown(html, unsafe_allow_html=True)

            # Remove button
            if cols[img_idx].button("Remove", key=remove_key):
                st.session_state[uploader_key] = None
                group["images"][img_idx] = None
                st.experimental_rerun()

# Add more groups
if st.button("➕ Add More Claim Group"):
    st.session_state.groups.append({
        "claimant_id": "Donald Trump",
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
