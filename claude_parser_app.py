import os
import time
import uuid
import base64
import json
import streamlit as st
import pandas as pd
from io import BytesIO
from google.cloud import storage
from google.oauth2 import service_account
import anthropic

# ========== Config ==========
APP_TITLE = "Claude Receipt Parser (Minimal Inventory)"
MODEL_DEFAULT = "claude-sonnet-4-5-20250929"
MAX_UPLOAD_MB = 15
ALLOWED_EXTS = ["jpg", "jpeg", "png", "pdf"]
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

def call_claude_with_image(model: str, file_path: str, instruction: str):
    with open(file_path, "rb") as f:
        data = f.read()
    base64_data = base64.b64encode(data).decode("utf-8")

    media_type = "image/jpeg"
    lower = file_path.lower()
    if lower.endswith(".png"):
        media_type = "image/png"
    elif lower.endswith(".pdf"):
        media_type = "application/pdf"

    st.info("Sending request to Claude...")
    st.write({"model": model, "instruction_preview": instruction[:120] + "..."})

    try:
        message = client.messages.create(
            model=model,
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64_data,
                            },
                        },
                        {"type": "text", "text": instruction},
                    ],
                }
            ],
        )
        st.success("Claude responded.")
        st.write("Raw Claude content blocks:")
        st.write(message.content)
        return message
    except Exception as e:
        st.error(f"Error calling Claude: {e}")
        return None

def load_master_inventory() -> pd.DataFrame:
    blob = gcs_bucket.blob(MASTER_CSV_NAME)
    if blob.exists():
        data = blob.download_as_bytes()
        return pd.read_csv(BytesIO(data))
    else:
        return pd.DataFrame(columns=[
            "system_date","system_time","date","filename",
            "vendor_name","total_amount","invoice_number"
        ])

def save_master_inventory(df: pd.DataFrame):
    blob = gcs_bucket.blob(MASTER_CSV_NAME)
    blob.upload_from_string(df.to_csv(index=False), content_type="text/csv")

def upload_to_gcs(local_path: str, dest_name: str):
    blob = gcs_bucket.blob(dest_name)
    blob.upload_from_filename(local_path)
    return f"gs://{GCS_BUCKET}/{dest_name}"

def flatten_result(filename: str, file_path: str, message):
    if not message:
        st.error("No message object returned from Claude.")
        return None, None

    parsed_json = None
    for block in getattr(message, "content", []):
        block_type = getattr(block, "type", None) or (isinstance(block, dict) and block.get("type"))
        block_text = getattr(block, "text", None) or (isinstance(block, dict) and block.get("text"))
        st.write(f"Block type: {block_type}")
        if block_text:
            st.text(f"Block text preview: {block_text[:200]}...")
            try:
                parsed_json = json.loads(block_text)
                st.success("Successfully parsed JSON.")
                break
            except Exception as e:
                st.warning(f"JSON parse failed: {e}")
    if not parsed_json:
        st.error("No valid JSON found in Claude response.")
        return None, None

    row = {
        "system_date": time.strftime("%Y-%m-%d"),
        "system_time": time.strftime("%H:%M:%S"),
        "date": parsed_json.get("date"),
        "filename": filename,
        "vendor_name": parsed_json.get("vendor_name"),
        "total_amount": parsed_json.get("total_amount"),
        "invoice_number": parsed_json.get("invoice_number"),
    }
    return row, parsed_json

def append_to_inventory(row: dict):
    df = load_master_inventory()
    if not df.empty and row["filename"] in df["filename"].values:
        st.warning("Duplicate receipt detected — not added to inventory.")
        return df, False
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_master_inventory(df)
    return df, True

def save_list_file(filename: str, parsed_json: dict):
    lines = [
        f"Vendor: {parsed_json.get('vendor_name')}",
        f"Store Location: {parsed_json.get('store_location')}",
        f"Date: {parsed_json.get('date')} {parsed_json.get('time')}",
        f"Currency: {parsed_json.get('currency')}",
        f"Subtotal: {parsed_json.get('subtotal')}",
        f"Rounding: {parsed_json.get('rounding')}",
        f"Total Amount: {parsed_json.get('total_amount')}",
        f"Payment Method: {parsed_json.get('payment_method')}",
    ]
    if parsed_json.get("invoice_number"):
        lines.append(f"Invoice Number: {parsed_json.get('invoice_number')}")
    lines.append("Line Items:")
    for item in parsed_json.get("line_items", []):
        lines.append(
            f" - {item.get('description')} (code {item.get('code')}) "
            f"x{item.get('quantity')} @ {item.get('unit_price')} = {item.get('line_total')}"
        )

    content = "\n".join(lines)
    list_filename = filename.rsplit(".", 1)[0] + ".list"
    blob = gcs_bucket.blob(f"uploads/{list_filename}")
    blob.upload_from_string(content, content_type="text/plain")
    return f"gs://{GCS_BUCKET}/uploads/{list_filename}"

def display_receipt_list(parsed_json: dict):
    st.subheader("🧾 Receipt Summary")
    st.write(f"**Vendor:** {parsed_json.get('vendor_name')}")
    st.write(f"**Store Location:** {parsed_json.get('store_location')}")
    st.write(f"**Date:** {parsed_json.get('date')} {parsed_json.get('time')}")
    st.write(f"**Currency:** {parsed_json.get('currency')}")
    st.write(f"**Subtotal:** {parsed_json.get('subtotal')}")
    st.write(f"**Rounding:** {parsed_json.get('rounding')}")
    st.write(f"**Total Amount:** {parsed_json.get('total_amount')}")
    st.write(f"**Payment Method:** {parsed_json.get('payment_method')}")
    if parsed_json.get("invoice_number"):
        st.write(f"**Invoice Number:** {parsed_json.get('invoice_number')}")
    st.subheader("🛍️ Line Items")
    df = pd.DataFrame(parsed_json.get("line_items", []))
    st.dataframe(df)
# ========== UI ==========
st.title(APP_TITLE)
st.caption("Upload your receipt below (PDF or image up to 15 MB)")

uploaded_file = st.file_uploader("Choose a file", type=ALLOWED_EXTS)

if uploaded_file is not None:
    st.write(f"File uploaded: {uploaded_file.name} ({human_bytes(uploaded_file.size)})")

    if uploaded_file.size > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"File exceeds {MAX_UPLOAD_MB} MB limit.")
    else:
        # FIXED: call the helper correctly
        temp_path = save_temp_file(uploaded_file)

        # Prompt Claude
        instruction = (
            "You are an audit‑grade receipt parser. From the attached file, extract:\n"
            "- Vendor name\n- Date\n- Currency and total amount\n"
            "- Line items (description, quantity, unit price, line total)\n"
            "- Payment method\n- Invoice number (if any)\n"
            "Return only a valid JSON object with these fields."
        )
        message = call_claude_with_image(MODEL_DEFAULT, temp_path, instruction)

        row, parsed_json = flatten_result(uploaded_file.name, temp_path, message)

        if not parsed_json:
            st.error("Parse failed — nothing uploaded to GCS.")
        else:
            # Show parsed JSON in human-readable form
            display_receipt_list(parsed_json)

            # Confirmation step
            if st.button("Confirm Upload"):
                # Upload image
                gcs_uri = upload_to_gcs(temp_path, f"uploads/{uploaded_file.name}")
                st.success(f"Uploaded to GCS: {gcs_uri}")

                # Save .list file
                list_uri = save_list_file(uploaded_file.name, parsed_json)
                st.success(f"List file saved to GCS: {list_uri}")

                # Append to inventory
                df, added = append_to_inventory(row)
                if added:
                    st.success("Receipt added to inventory.")
                st.subheader("📊 Master Inventory")
                st.dataframe(df)
