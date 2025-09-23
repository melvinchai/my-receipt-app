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
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name

    try:
        if uploaded_file.type == "application/pdf":
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
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
            for field, value in summary.items():
                st.write(f"**{field.replace('_', ' ').title()}:** {value}")

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
