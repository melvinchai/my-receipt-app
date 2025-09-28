# redeploy trigger: 2025-09-29
import streamlit as st

# Set clean layout
st.set_page_config(page_title="Demo Offline", layout="centered")

# Hide default Streamlit UI elements
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# Display offline message
st.title("🚧 Demo Offline")
st.warning("This demo is temporarily offline. Please contact melvinchia8@gmail for access or updates.")

"""
# 🔒 Parser logic temporarily disabled

import streamlit as st
from google.cloud import documentai_v1beta3 as documentai
import json
import pandas as pd
from PIL import Image
import tempfile
import fitz
from google.oauth2 import service_account

# Load credentials from Streamlit Secrets
creds = service_account.Credentials.from_service_account_info(
    json.loads(st.secrets["google"]["credentials"])
)

# Set up Streamlit page
st.set_page_config(page_title="Receipt Parser", layout="wide")
st.title("📄 v1 Malaysian Receipt Parser with Document AI")

# GCP Configuration
PROJECT_ID = "malaysia-receipt-saas"
LOCATION = "us"
PROCESSOR_ID = "8fb44aee4495bb0f"

# Document AI client
def process_document(file_path, mime_type):
    try:
        client_options = {"api_endpoint": f"{LOCATION}-documentai.googleapis.com"}
        client = documentai.DocumentProcessorServiceClient(
            client_options=client_options, credentials=creds
        )
        name = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{PROCESSOR_ID}"
        with open(file_path, "rb") as f:
            document = documentai.RawDocument(content=f.read(), mime_type=mime_type)
        request = documentai.ProcessRequest(name=name, raw_document=document)
        result = client.process_document(request=request)
        return result.document
    except Exception as e:
        st.error(f"❌ Failed to process document: {e}")
        return None

# Extract full text
def extract_text(document):
    return document.text if document and document.text else "No text found."

# Extract entities
def extract_entities(document):
    entities = []
    if document and document.entities:
        for entity in document.entities:
            entities.append({
                "Field": entity.type_,
                "Value": entity.mention_text,
                "Confidence": round(entity.confidence, 2)
            })
    return pd.DataFrame(entities)

# ✅ Updated summary extractor with aliasing and fixed order
def extract_summary(document):
    summary = {}
    FIELD_ALIASES = {
        "purchase_date": "invoice_date",
        "receipt_date": "invoice_date",
        "date_of_receipt": "invoice_date"
    }
    desired_fields = ["invoice_date", "brand_name", "invoice_total"]
    if document and document.entities:
        for entity in document.entities:
            key = FIELD_ALIASES.get(entity.type_, entity.type_)
            if key in desired_fields:
                summary[key] = entity.mention_text
    for field in desired_fields:
        summary.setdefault(field, "")
    return summary

# Upload and process receipt
uploaded_file = st.file_uploader("Upload a receipt (image or PDF)", type=["jpg", "jpeg", "png", "pdf"])
if uploaded_file:
    mime_type = "application/pdf" if uploaded_file.type == "application/pdf" else "image/jpeg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf" if mime_type == "application/pdf" else ".jpg") as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name

    try:
        if mime_type == "application/pdf":
            doc = fitz.open(tmp_path)
            page = doc.load_page(0)
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        else:
            img = Image.open(tmp_path)
        st.image(img, caption="Uploaded Receipt", use_container_width=True)
    except Exception as e:
        st.warning(f"⚠️ Could not display image: {e}")

    document = process_document(tmp_path, mime_type)
    if document:
        st.subheader("🧠 Extracted Text")
        st.text_area("Full Text", extract_text(document), height=300)

        st.subheader("📋 Summary Box: Fields to be downloaded for Excel")
        summary = extract_summary(document)
        if summary:
            for field in ["invoice_date", "brand_name", "invoice_total"]:
                st.write(f"**{field.replace('_', ' ').title()}:** {summary[field]}")
            df = pd.DataFrame([summary])
            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name="receipt_summary.csv",
                mime="text/csv"
            )
        else:
            st.info("No summary fields found.")

        st.subheader("🔍 Entity Table (Editable)")
        entity_df = extract_entities(document)
        if not entity_df.empty:
            edited_df = st.data_editor(entity_df, num_rows="dynamic")

            st.subheader("💬 Feedback Loop")
            if st.button("Submit Corrections"):
                corrected_entities = edited_df.to_dict(orient="records")
                try:
                    with open("corrected_entities.json", "w") as f:
                        json.dump(corrected_entities, f, indent=2)
                    st.success("✅ Corrections saved! You can use these for retraining later.")
                except Exception as e:
                    st.error(f"❌ Failed to save corrections: {e}")
        else:
            st.info("No entities found in the document.")
    else:
        st.warning("⚠️ No document returned. Please check your processor ID or credentials.")
"""
