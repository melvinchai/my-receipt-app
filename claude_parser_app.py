import os
import json
import base64
import streamlit as st
from google.cloud import storage
from google.oauth2 import service_account
import anthropic

# ========== Config ==========
APP_TITLE = "Claude Receipt Parser (Audit-Grade JSON)"
MODEL_DEFAULT = "claude-sonnet-4-5-20250929"
MAX_UPLOAD_MB = 15
ALLOWED_EXTS = ["jpg", "jpeg", "png", "pdf", "json"]

MASTER_CSV_NAME = "uploads/parsed_inventory.csv"

# ========== Secrets ==========
CLAUDE_KEY = st.secrets["claudeparser-key"]
GCS_BUCKET = st.secrets["GCS_BUCKET"]
GOOGLE_CLOUD_PROJECT = st.secrets["GOOGLE_CLOUD_PROJECT"]
gcs_creds_info = st.secrets["gcs"]

gcs_credentials = service_account.Credentials.from_service_account_info(gcs_creds_info)
gcs_client = storage.Client(project=GOOGLE_CLOUD_PROJECT, credentials=gcs_credentials)
gcs_bucket = gcs_client.bucket(GCS_BUCKET)

client = anthropic.Anthropic(api_key=CLAUDE_KEY)

# ========== Helpers ==========
def call_claude_with_inputs(model: str, ocr_json: dict, image_file=None):
    """Send OCR JSON (mandatory) and optional image to Claude."""
    content_blocks = [
        {"type": "text", "text": build_instruction(ocr_json)}
    ]

    if image_file is not None:
        data = image_file.read()
        base64_data = base64.b64encode(data).decode("utf-8")
        media_type = "image/jpeg"
        lower = image_file.name.lower()
        if lower.endswith(".png"):
            media_type = "image/png"
        elif lower.endswith(".pdf"):
            media_type = "application/pdf"

        content_blocks.insert(0, {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64_data,
            },
        })

    try:
        message = client.messages.create(
            model=model,
            max_tokens=2048,
            temperature=0,
            messages=[{"role": "user", "content": content_blocks}],
        )
        return message
    except Exception as e:
        st.error(f"Error calling Claude: {e}")
        return None

def build_instruction(ocr_json: dict) -> str:
    """Strict prompt enforcing OCR-first discipline."""
    return (
        "You are an audit‑grade receipt parser.\n\n"
        "Primary input: OCR JSON (contains filename, ocr_text, raw_rows).\n"
        "Secondary input: Original receipt image (optional, for layout verification).\n\n"
        f"OCR JSON:\n{json.dumps(ocr_json, indent=2)}\n\n"
        "Rules:\n"
        "- Use OCR JSON as authoritative.\n"
        "- Extract vendor_name, date, currency, total_amount, payment_method, invoice_number (if any).\n"
        "- Extract line_items (objects with: code, description, quantity, unit_price, line_total).\n"
        "- If OCR text is incomplete or garbled, consult the image.\n"
        "- Never invent values. If uncertain, mark as 'MISSING'.\n"
        "- Return only valid JSON. Do not include prose or Markdown.\n"
    )

# ========== UI ==========
st.title(APP_TITLE)
st.caption("Upload OCR JSON (mandatory) and optionally the receipt image. Claude will parse audit‑grade JSON.")

json_file = st.file_uploader("Upload OCR JSON", type=["json"])
image_file = st.file_uploader("Upload Receipt Image (optional)", type=["jpg","jpeg","png","pdf"])

if json_file is not None:
    try:
        ocr_json = json.load(json_file)
        st.subheader("📂 OCR JSON Preview")
        st.json(ocr_json)

        if st.button("Process with Claude"):
            message = call_claude_with_inputs(MODEL_DEFAULT, ocr_json, image_file)
            if message:
                st.success("Claude responded.")
                st.subheader("📜 Parsed JSON Output")
                st.write(message.content)

                # Save parsed result to GCS
                parsed_text = json.dumps(message.content, indent=2)
                dest_name = f"uploads/{json_file.name.rsplit('.',1)[0]}_claude.json"
                blob = gcs_bucket.blob(dest_name)
                blob.upload_from_string(parsed_text, content_type="application/json")
                st.success(f"Parsed JSON uploaded to GCS: gs://{GCS_BUCKET}/{dest_name}")

    except Exception as e:
        st.error(f"Failed to load JSON: {e}")
else:
    st.info("Please upload an OCR JSON file to begin.")
