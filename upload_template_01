import streamlit as st
import pandas as pd

st.set_page_config(page_title="Grouped Receipt Uploader", layout="wide")
st.title("📸 Grouped Receipt Uploader")

# Initialize session state
if "groups" not in st.session_state:
    st.session_state.groups = [{"images": [None]*4}]

# Simulated entity extraction
def extract_entities(image):
    # Replace with actual parser logic
    return pd.DataFrame({
        "Field": ["brand_name", "payment_type", "category", "tax_code"],
        "Value": ["MockBrand", "Credit Card", "Meals", "TX123"]
    })

# Render each group
for group_idx, group in enumerate(st.session_state.groups):
    st.subheader(f"Claim Group {group_idx + 1}")
    cols = st.columns(4)
    for img_idx in range(4):
        key = f"group{group_idx}_img{img_idx}"
        uploaded = cols[img_idx].file_uploader(
            f"Voucher {img_idx + 1}",
            type=["jpg", "jpeg", "png"],
            key=key
        )
        group["images"][img_idx] = uploaded

# Add more groups
if st.button("➕ Add More Claim Group"):
    st.session_state.groups.append({"images": [None]*4})

# Submit and extract
if st.button("✅ Submit"):
    for group_idx, group in enumerate(st.session_state.groups):
        st.markdown(f"---\n### 🧾 Entity Tables for Claim Group {group_idx + 1}")
        for img_idx, image in enumerate(group["images"]):
            if image:
                st.markdown(f"**Voucher {img_idx + 1}**")
                entity_df = extract_entities(image)
                st.dataframe(entity_df)
