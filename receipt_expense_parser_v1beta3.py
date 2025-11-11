import os
import json
import streamlit as st
from google.cloud import documentai_v1beta3 as documentai
from google.oauth2 import service_account

# Load service account from Streamlit secrets
service_account_info = {
    "type": st.secrets["gcs"]["type"],
    "project_id": st.secrets["gcs"]["project_id"],
    "private_key_id": st.secrets["gcs"]["private_key_id"],
    "private_key": st.secrets["gcs"]["private_key"],
    "client_email": st.secrets["gcs"]["client_email"],
    "client_id": st.secrets["gcs"]["client_id"],
    "auth_uri": st.secrets["gcs"]["auth_uri"],
    "token_uri": st.secrets["gcs"]["token_uri"],
    "auth_provider_x509_cert_url": st.secrets["gcs"]["auth_provider_x509_cert_url"],
    "client_x509_cert_url": st.secrets["gcs"]["client_x509_cert_url"],
    "universe_domain": st.secrets["gcs"]["universe_domain"]
}

# Authenticate using service account
credentials = service_account.Credentials.from_service_account_info(service_account_info)
client = documentai.DocumentProcessorServiceClient(credentials=credentials)

# Define processor details
project_id = "71856128205"
location = "us"
processor_id = "66c60dad11d1ad42"
name = f"projects/{project_id}/locations/{location}/processors/{processor_id}"

# Streamlit UI
st.title("🧾 Receipt Parser with Line Item Extraction")
uploaded_file = st.file_uploader("Upload a receipt image", type=["jpg", "jpeg", "png", "pdf"])

if uploaded_file:
    image_bytes = uploaded_file.read()
    mime_type = "application/pdf" if uploaded_file.name.endswith(".pdf") else "image/jpeg"

    # Prepare request
    request = documentai.ProcessRequest(
        name=name,
        raw_document=documentai.RawDocument(content=image_bytes, mime_type=mime_type)
    )

    # Call Document AI
    result = client.process_document(request=request)
    document = result.document

    # Display summary fields
    st.subheader("📌 Receipt Summary")
    for entity in document.entities:
        if entity.type_ in ["merchant_name", "purchase_date", "total_amount"]:
            st.write(f"**{entity.type_}**: {entity.mention_text} (confidence: {entity.confidence:.2f})")

    # Display line items
    st.subheader("📦 Line Items")
    for entity in document.entities:
        if entity.type_ == "line_item":
            item = {prop.type_: prop.mention_text for prop in entity.properties}
            st.write(f"- **Item**: {item.get('description', 'N/A')}, "
                     f"**Qty**: {item.get('quantity', 'N/A')}, "
                     f"**Unit Price**: {item.get('unit_price', 'N/A')}, "
                     f"**Total**: {item.get('amount', 'N/A')}")

    # Optional: show full OCR text
    st.subheader("📄 Full OCR Text")
    st.text(document.text)
