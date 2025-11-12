import os
import json
import logging
import streamlit as st
from google.cloud import storage
from google.oauth2 import service_account
from pathlib import Path
from PIL import Image, ImageOps
from PyPDF2 import PdfReader

# === TRACE LOGGING CONFIG ===
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("claude_parser")

# === CONFIG ===
SCHEMA_PATH = Path("schemas/default_schema.json")
BUCKET_NAME = st.secrets["GCS_BUCKET"]
PROJECT_ID = st.secrets["GOOGLE_CLOUD_PROJECT"]

# Decode private key correctly
raw_info = dict(st.secrets["gcs"])
raw_info["private_key"] = raw_info["private_key"].replace("\\n", "\n")
GCS_CREDENTIALS = service_account.Credentials.from_service_account_info(raw_info)

# === UTILITIES ===
def load_schema():
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)
        logger.debug("Schema loaded successfully: %s", SCHEMA_PATH)
        return schema
    except Exception as e:
        logger.error("Schema load failed: %s", e)
        return {}

def preview_document(uploaded_file):
    try:
        if uploaded_file.type == "application/pdf":
            reader = PdfReader(uploaded_file)
            for i, page in enumerate(reader.pages):
                text_preview = page.extract_text()
                if text_preview:
                    st.text_area(f"PDF Page {i+1}", text_preview[:2000], height=300)
            logger.debug("PDF preview rendered vertically")
        else:
            image = Image.open(uploaded_file)
            image = ImageOps.exif_transpose(image)
            st.image(image, caption="Uploaded Image Preview", use_column_width=True)
            logger.debug("Image preview rendered with correct orientation")
    except Exception as e:
        logger.error("Preview failed: %s", e)
        st.error("Could not preview document.")

def parse_with_claude(content, schema):
    try:
        parsed = {"raw": "claude_output_here"}  # placeholder
        logger.debug("Claude raw output: %s", parsed)

        if not isinstance(parsed, dict):
            logger.warning("Malformed Claude output, normalizing...")
            parsed = {"normalized": str(parsed)}

        normalized = {k: parsed.get(k, None) for k in schema.get("fields", [])}
        logger.debug("Normalized output: %s", normalized)
        return normalized
    except Exception as e:
        logger.error("Claude parsing failed: %s", e)
        return {"error": str(e)}

def upload_to_gcs(file_name, file_bytes):
    try:
        client = storage.Client(project=PROJECT_ID, credentials=GCS_CREDENTIALS)
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(file_name)
        blob.upload_from_string(file_bytes)
        logger.debug("Uploaded %s to GCS bucket %s", file_name, BUCKET_NAME)
        return f"gs://{BUCKET_NAME}/{file_name}"
    except Exception as e:
        logger.error("Upload failed: %s", e)
        return {"error": str(e)}

# === STREAMLIT APP ENTRYPOINT ===
def main():
    st.title("Claude Parser App")

    schema = load_schema()

    uploaded_file = st.file_uploader("Upload a document", type=["pdf", "png", "jpg", "jpeg"])
    if uploaded_file:
        preview_document(uploaded_file)

        file_bytes = uploaded_file.getvalue()
        gcs_path = upload_to_gcs(uploaded_file.name, file_bytes)
        st.write(f"Uploaded to: {gcs_path}")

        parsed_output = parse_with_claude(file_bytes, schema)
        st.json(parsed_output)

if __name__ == "__main__":
    main()
