import os
import io
import time
import uuid
import base64
import streamlit as st
from typing import Optional, Tuple

import anthropic
from google.cloud import storage
from google.oauth2 import service_account


# ========== Configuration ==========
APP_TITLE = "Claude Receipt Parser (Attachments + GCS)"
MODEL_DEFAULT = "claude-haiku-4.5"
MAX_UPLOAD_MB = 15  # hard guard to avoid oversized requests
ALLOWED_EXTS = ["jpg", "jpeg", "png", "pdf"]


# ========== Secrets & Clients ==========
st.set_page_config(page_title=APP_TITLE, layout="centered")

# Anthropic key
CLAUDE_KEY = st.secrets["claudeparser-key"]
claude_client = anthropic.Anthropic(api_key=CLAUDE_KEY)

# Google Cloud Storage
GCS_BUCKET = st.secrets["GCS_BUCKET"]
GOOGLE_CLOUD_PROJECT = st.secrets["GOOGLE_CLOUD_PROJECT"]

gcs_creds_info = st.secrets["gcs"]
gcs_credentials = service_account.Credentials.from_service_account_info(gcs_creds_info)
gcs_client = storage.Client(project=GOOGLE_CLOUD_PROJECT, credentials=gcs_credentials)
gcs_bucket = gcs_client.bucket(GCS_BUCKET)


# ========== Helpers ==========
def human_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(n)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f"{size:.2f} {u}"
        size /= 1024

def save_temp_file(uploaded_file) -> str:
    """Save the uploaded file to a temp path and return it."""
    fname = uploaded_file.name
    temp_dir = "/tmp"
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}_{fname}")
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return temp_path

def upload_to_gcs(local_path: str, dest_name: Optional[str] = None) -> str:
    """Upload a local file to GCS and return the gs:// URI."""
    if dest_name is None:
        dest_name = f"uploads/{int(time.time())}_{os.path.basename(local_path)}"
    blob = gcs_bucket.blob(dest_name)
    blob.upload_from_filename(local_path)
    return f"gs://{GCS_BUCKET}/{dest_name}"

def call_claude_with_attachment(model: str, file_path: str, filename: str, instruction: str) -> anthropic.types.Message:
    """
    Send the file as an attachment instead of embedding base64.
    Returns the raw Claude message object.
    """
    with open(file_path, "rb") as f:
        resp = claude_client.messages.create(
            model=model,
            max_tokens=800,
            messages=[{"role": "user", "content": instruction}],
            attachments=[{"file": f, "filename": filename}],
        )
    return resp

def extract_text_from_message(message: anthropic.types.Message) -> str:
    """
    Safely pull out text content from Claude's response.
    """
    parts = []
    for block in getattr(message, "content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts).strip()

def is_allowed_extension(filename: str) -> bool:
    ext = filename.split(".")[-1].lower()
    return ext in ALLOWED_EXTS


# ========== UI ==========
st.title(APP_TITLE)
st.caption("Attachments-based parsing to avoid token limits. Files stored to GCS for audit traceability.")

with st.expander("Status checks", expanded=True):
    st.write("Claude OK with model probe:", MODEL_DEFAULT)
    st.write("GCS bucket:", GCS_BUCKET)
    st.write("Project:", GOOGLE_CLOUD_PROJECT)

uploaded_file = st.file_uploader(
    "Upload a receipt image or PDF",
    type=ALLOWED_EXTS,
    help="Accepted: jpg, jpeg, png, pdf (<= 15 MB)"
)

instruction_default = (
    "You are an audit-grade receipt parser. From the attached file, extract:\n"
    "- Vendor name\n"
    "- Date\n"
    "- Currency and total amount\n"
    "- Line items (description, quantity, unit price, line total)\n"
    "- Payment method\n"
    "Return a concise JSON object with these fields. If text is unclear, mark fields as null with a reason."
)

instruction = st.text_area("Parsing instruction", instruction_default, height=160)

model = st.text_input("Claude model", MODEL_DEFAULT)

run = st.button("Parse with Claude")

# ========== Main flow ==========
if run:
    if uploaded_file is None:
        st.error("Please upload a file first.")
        st.stop()

    if not is_allowed_extension(uploaded_file.name):
        st.error("Unsupported file type. Allowed: jpg, jpeg, png, pdf.")
        st.stop()

    size_bytes = len(uploaded_file.getbuffer())
    st.write(f"Uploaded file size: {human_bytes(size_bytes)}")

    if size_bytes > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"File exceeds {MAX_UPLOAD_MB} MB limit. Please upload a smaller file.")
        st.stop()

    with st.spinner("Saving file and uploading to GCS..."):
        local_path = save_temp_file(uploaded_file)
        try:
            gcs_uri = upload_to_gcs(local_path)
            st.success(f"Stored in GCS: {gcs_uri}")
        except Exception as e:
            st.warning(f"GCS upload failed: {e}. Proceeding with Claude parsing anyway.")

    with st.spinner("Calling Claude with attachment..."):
        try:
            message = call_claude_with_attachment(
                model=model,
                file_path=local_path,
                filename=uploaded_file.name,
                instruction=instruction
            )
            text = extract_text_from_message(message)
            if text:
                st.subheader("Claude parsed result")
                st.code(text, language="json")
            else:
                st.warning("Claude returned no text content. Raw response below.")
                st.json(message)
        except anthropic.BadRequestError as e:
            st.error(f"Anthropic BadRequestError: {e}")
        except Exception as e:
            st.error(f"Unexpected error calling Claude: {e}")

    # Final audit notes
    with st.expander("Audit log"):
        st.write({
            "filename": uploaded_file.name,
            "size_bytes": size_bytes,
            "model": model,
            "gcs_uri": gcs_uri if 'gcs_uri' in locals() else None,
            "timestamp": int(time.time()),
        })
