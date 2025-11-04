import streamlit as st
import pytesseract
from PIL import Image
import os
import json
from guided_parser import GuidedParser
from rule_loader import RuleLoader

# --- UI Setup ---
st.set_page_config(page_title="Insurance Parser", layout="centered")
st.title("📄 Insurance Document Parser")
st.markdown("Upload an insurance document to extract metadata based on admin-defined rules.")

# --- Inputs ---
uploaded_file = st.file_uploader("Upload image", type=["png", "jpg", "jpeg"])
insurer_name = st.text_input("Insurer name (e.g. Coles, Zurich)")
asset_type = st.selectbox("Asset type", ["Car", "Motorcycle", "Property"])
token = st.text_input("Contributor token (e.g. hong123)")

# --- Parse Trigger ---
if uploaded_file and insurer_name and asset_type and token:
    image = Image.open(uploaded_file)
    ocr_text = pytesseract.image_to_string(image)

    # Load rules
    loader = RuleLoader("parsing_rules.xlsx")
    parser = GuidedParser(ocr_text, insurer_name, loader)
    metadata = parser.extract_fields()

    # --- Display Results ---
    st.subheader("📋 Parsed Metadata")
    if "error" in metadata:
        st.error(metadata["error"])
    else:
        for field, details in metadata.items():
            st.write(f"**{field}**: {details['value']}  \n*Source:* `{details['source']}`  \n*Notes:* {details['notes']}")

        # --- Save Metadata ---
        folder_path = f"data/{token}/{asset_type}/{insurer_name}/"
        os.makedirs(folder_path, exist_ok=True)

        with open(os.path.join(folder_path, "metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2)

        st.success(f"Metadata saved to `{folder_path}`")

else:
    st.info("Please upload an image and fill in all fields to begin parsing.")
