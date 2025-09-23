import streamlit as st
from google.cloud import documentai_v1beta3 as documentai
import os
import json
import pandas as pd
from PIL import Image
import tempfile
import fitz  # PyMuPDF for PDF rendering

# Set up Streamlit page
st.set_page_config(page_title="Receipt Parser", layout="wide")
st.title("📄 Malaysian Receipt Parser with Document AI")

# GCP Configuration
PROJECT_ID = "malaysia-receipt-saas"
LOCATION = "us"
PROCESSOR_ID = "8fb44aee4495bb0f"
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "malaysia-receipt-saas-3cb987586941.json"

# Document AI client
def process_document(file_path, mime_type):
    try:
        client_options = {"api_endpoint": f"{LOCATION}-documentai.googleapis.com"}
        client = documentai.DocumentProcessorServiceClient(client_options=client_options)
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

# Extract summary fields
def extract_summary(document):
    summary = {}
    if document and document.entities:
        for entity in document.entities:
            if entity.type_ in ["merchant_name", "total_amount", "receipt_date", "category"]:
                summary[entity.type_] = entity.mention_text
    return summary

# Upload and process receipt
uploaded_file = st.file_uploader("Upload a receipt (image or PDF)", type=["jpg", "jpeg", "png", "pdf"])
if uploaded_file:
    mime_type = "application/pdf" if uploaded_file.type == "application/pdf" else "image/jpeg"

    # Save uploaded file to temp path
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf" if mime_type == "application/pdf" else ".jpg") as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name

    try:
        if mime_type == "application/pdf":
            doc = fitz.open(tmp_path)
            page = doc.load_page(0)
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height],
