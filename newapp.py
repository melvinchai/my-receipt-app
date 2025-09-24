#redeploy
import streamlit as st
from google.cloud import documentai_v1beta3 as documentai
import pandas as pd
from PIL import Image
import tempfile
import fitz  # PyMuPDF
from google.oauth2 import service_account
import json

# Load credentials from full JSON string
try:
    creds_json = json.loads(st.secrets["google"]["credentials"])
    creds = service_account.Credentials.from_service_account_info(creds_json)
except Exception as e:
    st.error(f"❌ Failed to load credentials: {e}")
    st.stop()

# Streamlit setup
st.set_page_config(page_title="Receipt Parser", layout="wide")
st.title("📄 v1 Malaysian Receipt Parser with Document AI")

# GCP config
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

# Alias map
FIELD_ALIASES = {
    "purchase_date": "invoice_date",
    "receipt_date": "invoice_date",
    "date_of_receipt": "invoice_date",
    "transaction_date": "invoice_date",
    "date": "invoice_date",
    "receipt_total": "invoice_total",
    "total_amount": "invoice_total",
    "amount_due": "invoice_total",
    "grand_total": "invoice_total",
    "final_amount": "invoice_total"
}

# Enhanced summary extractor with normalization
def extract_summary(document):
    summary = {}
    desired_fields = ["invoice_date", "brand_name", "invoice_total"]
    field_candidates = {field: [] for field in desired_fields}

    if document and document.entities:
        for entity in document.entities:
            normalized_type = entity.type_.replace("-", "_").lower()
            key = FIELD_ALIASES.get(normalized_type, normalized_type)
            if key in desired_fields and entity.mention_text.strip():
                field_candidates[key].append((entity.mention_text, entity.confidence, entity.type_))

    for field in desired_fields:
        if field_candidates[field]:
            best = max(field_candidates[field], key=lambda x: x[1])
            summary[field] = best[0]
            summary[f"{field}_source"] = best[2]
        else:
            summary[field] = ""
            summary[f"{field}_source"] = "N/A"

    return summary

# Upload and process
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
                st.write(f"**{field.replace('_', ' ').title()} (from `{
