import os
import time
import uuid
import requests
import streamlit as st
from google.cloud import storage
from google.oauth2 import service_account

# ========== Config ==========
APP_TITLE = "Claude Receipt Parser (REST API Attachments)"
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
MODEL_DEFAULT = "claude-haiku-4.5"
MAX_UPLOAD_MB = 15
ALLOWED_EXTS = ["jpg", "jpeg", "png", "pdf"]

# ========== Secrets ==========
CLAUDE_KEY = st.secrets["claudeparser-key"]
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
    temp_dir = "/tmp"
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}_{uploaded_file.name}")
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return temp_path

def upload_to_gcs(local_path: str, dest_name: str = None) -> str:
    if dest_name is None:
        dest_name = f"uploads/{int(time.time())}_{os.path.basename(local_path)}"
    blob = gcs_bucket.blob(dest_name)
    blob.upload_from_filename(local_path)
    return f"gs://{GCS_BUCKET}/{dest_name}"

def call_claude_rest(model: str, file_path: str, filename: str, instruction: str):
    headers = {
        "x-api-key": CLAUDE_KEY,
        "anthropic-version": "2023-06-01",
    }
    # multipart form-data: file + JSON fields
    files = {
        "file": (filename, open(file_path, "rb"), "application/octet-stream")
    }
    data = {
        "model": model,
        "max_tokens": 800,
        "messages": [
            {"role": "user", "content": instruction}
        ]
    }
    resp = requests.post(CLAUDE_API_URL, headers=headers, data={"model": model, "max_tokens": 800}, files=files)
    return resp.json()

# ========== UI ==========
st.title(APP_TITLE)
st.caption("Send receipt image/PDF directly to Claude via REST API attachments.")

uploaded_file = st.file_uploader("Upload a receipt image or PDF", type=ALLOWED_EXTS)

instruction_default = """
You are an audit‑grade receipt parser. From the attached file, extract:
- Vendor name
- Date
- Currency and total amount
- Line items (description, quantity, unit price, line total)
- Payment method
Return a concise JSON object with these fields. If text is unclear, mark fields as null with a reason.
"""
instruction = st.text_area("Parsing instruction", instruction_default, height=160)
model = st.text_input("Claude model", MODEL_DEFAULT)
run = st.button("Parse with Claude (REST API)")

if run:
    if uploaded_file is None:
        st.error("Please upload a file first.")
        st.stop()

    size_bytes = len(uploaded_file.getbuffer())
    st.write(f"Uploaded file size: {human_bytes(size_bytes)}")
    if size_bytes > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"File exceeds {MAX_UPLOAD_MB} MB limit.")
        st.stop()

    with st.spinner("Saving file and uploading to GCS..."):
        local_path = save_temp_file(uploaded_file)
        try:
            gcs_uri = upload_to_gcs(local_path)
            st.success(f"Stored in GCS: {gcs_uri}")
        except Exception as e:
            st.warning(f"GCS upload failed: {e}")

    with st.spinner("Calling Claude REST API..."):
        try:
            result = call_claude_rest(model, local_path, uploaded_file.name, instruction)
            st.subheader("Claude response")
            st.json(result)

            # Show token usage if available
            if "usage" in result:
                st.write("Token usage:")
                st.json(result["usage"])
        except Exception as e:
            st.error(f"Error calling Claude REST API: {e}")
