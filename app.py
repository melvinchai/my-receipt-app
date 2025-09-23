#redeploy
import streamlit as st
from google.cloud import documentai_v1beta3 as documentai
import json
import pandas as pd
from PIL import Image
import tempfile
import fitz  # PyMuPDF for PDF rendering
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
            client_options=client_options,
            credentials=creds
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

# ✅ Updated summary extractor with aliasing
def extract_summary(document):
    summary = {}
    FIELD_ALIASES = {
        "invoice_total": "total_amount",
        "amount_paid": "total_amount",
        "amount": "total_amount",
        "purchase_date": "receipt_date",
        "date_of_receipt": "receipt_date"
    }

    if document and document.entities:
        for entity in document.entities:
            if entity.type_ in
