import streamlit as st
import json
from google.cloud import documentai_v1beta3 as documentai

st.set_page_config(page_title="Tagged Receipt Pair Uploader", layout="wide")

st.title("🧾 Tagged Receipt Pair Uploader")

# Upload receipt image
receipt_file = st.file_uploader("Upload receipt image", type=["jpg", "jpeg", "png"])
tagged_json_file = st.file_uploader("Upload tagged JSON (optional)", type=["json"])

tagged_data = None
if tagged_json_file:
    try:
        tagged_data = json.load(tagged_json_file)
        st.success("✅ Tagged metadata loaded.")
        st.json(tagged_data)
    except Exception as e:
        st.error(f"❌ Failed to parse tagged JSON: {e}")

# Dummy parser function (replace with your actual Document AI logic)
def extract_fixed_fields_custom(document=None, source="receipt", tagged_data=None):
    fields = {
        "merchant_name": "",
        "date": "",
        "subtotal": "",
        "tax": "",
        "grand_total": "",
        "reference_number": ""
    }

    # Use tagged metadata if available
    if tagged_data:
        for key in fields:
            if key in tagged_data:
                fields[key] = tagged_data[key]
        return fields

    # Fallback dummy values if no tagged data
    fields["merchant_name"] = "Unknown Merchant"
    fields["grand_total"] = "Unknown Total"
    return fields

# Display results
if receipt_file:
    st.image(receipt_file, caption="Uploaded Receipt", use_column_width=True)
    receipt_fields = extract_fixed_fields_custom(source="receipt", tagged_data=tagged_data)

    st.subheader("📋 Parsed Receipt Summary")
    st.table(receipt_fields)
