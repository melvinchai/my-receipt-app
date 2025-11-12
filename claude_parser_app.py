import os
import time
import uuid
import hashlib
import requests
import streamlit as st
import pandas as pd
from io import BytesIO
from google.cloud import storage
from google.oauth2 import service_account

# ========== Config ==========
APP_TITLE = "Claude Receipt Parser (Files API + Master Inventory in GCS)"
BASE_URL = "https://api.anthropic.com/v1"
MODEL_DEFAULT = "claude-haiku-4.5"
MAX_UPLOAD_MB = 15
ALLOWED_EXTS = ["jpg", "jpeg", "png", "pdf"]
MASTER_CSV_NAME = "parsed_inventory.csv"   # single master file in GCS

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

def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

def upload_file_to_anthropic(file_path: str, filename: str) -> str:
    headers = {
        "x-api-key": CLAUDE_KEY,
        "anthropic-version": "2023-06-01",
    }
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/files",
            headers=headers,
            files={"file": (filename, f, "application/octet-stream")},
        )
    resp.raise_for_status()
    return resp.json()["id"]

def call_claude_with_file(model: str, file_id: str, instruction: str):
    headers = {
        "x-api-key": CLAUDE_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    data = {
        "model": model,
        "max_tokens": 800,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "file", "file_id": file_id},
                ],
            }
        ],
    }
    resp = requests.post(f"{BASE_URL}/messages", headers=headers, json=data)
    resp.raise_for_status()
    return resp.json()

def load_master_inventory() -> pd.DataFrame:
    blob = gcs_bucket.blob(MASTER_CSV_NAME)
    if blob.exists():
        data = blob.download_as_bytes()
        return pd.read_csv(BytesIO(data))
    else:
        return pd.DataFrame(columns=["timestamp","filename","file_hash","input_tokens","output_tokens","response_json"])

def save_master_inventory(df: pd.DataFrame):
    blob = gcs_bucket.blob(MASTER_CSV_NAME)
    blob.upload_from_string(df.to_csv(index=False), content_type="text/csv")

def upload_to_gcs(local_path: str, dest_name: str):
    blob = gcs_bucket.blob(dest_name)
    blob.upload_from_filename(local_path)
    return f"gs://{GCS_BUCKET}/{dest_name}"

def append_to_inventory(filename: str, file_path: str, result: dict):
    usage = result.get("usage", {})
    row = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "filename": filename,
        "file_hash": file_hash(file_path),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "response_json": str(result),
    }

    df = load_master_inventory()
    if row["file_hash"] in df["file_hash"].values:
        st.warning("Duplicate receipt detected — not added to inventory.")
        return df, False  # duplicate

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_master_inventory(df)
    return df, True  # new entry

# ========== UI ==========
st.title(APP_TITLE)
st.caption("Upload a receipt, parse with Claude, confirm to save unique results + image into GCS.")

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
run = st.button("Parse with Claude (Files API)")

if run:
    if uploaded_file is None:
        st.error("Please upload a file first.")
        st.stop()

    size_bytes = len(uploaded_file.getbuffer())
    st.write(f"Uploaded file size: {human_bytes(size_bytes)}")
    if size_bytes > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"File exceeds {MAX_UPLOAD_MB} MB limit.")
        st.stop()

    with st.spinner("Saving file locally..."):
        local_path = save_temp_file(uploaded_file)

    with st.spinner("Uploading file to Anthropic..."):
        try:
            file_id = upload_file_to_anthropic(local_path, uploaded_file.name)
            st.success(f"Uploaded to Anthropic, file_id: {file_id}")
        except Exception as e:
            st.error(f"Error uploading to Anthropic: {e}")
            st.stop()

    with st.spinner("Calling Claude with file reference..."):
        try:
            result = call_claude_with_file(model, file_id, instruction)
            st.subheader("Claude response")
            st.json(result)

            if "usage" in result:
                st.subheader("Token usage")
                st.json(result["usage"])

            if st.button("Confirm and save to master inventory"):
                df, is_new = append_to_inventory(uploaded_file.name, local_path, result)
                if is_new:
                    try:
                        dest_name = f"receipts/{uploaded_file.name}"
                        gcs_uri = upload_to_gcs(local_path, dest_name)
                        st.success(f"Result saved. Image also stored in GCS: {gcs_uri}")
                    except Exception as e:
                        st.warning(f"Image upload failed: {e}")
                else:
                    st.info("Duplicate detected — image not uploaded again.")

                # Preview master inventory
                st.subheader("Master Inventory Preview")
                st.dataframe(df)

                # Download master CSV
                blob = gcs_bucket.blob(MASTER_CSV_NAME)
                data = blob.download_as_bytes()
                st.download_button(
                    "Download master inventory CSV",
                    data=data,
                    file_name=MASTER_CSV_NAME,
                    mime="text/csv",
                )
        except Exception as e:
            st.error(f"Error calling Claude: {e}")
