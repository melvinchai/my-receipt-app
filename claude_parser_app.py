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
APP_TITLE = "Claude Receipt Parser (Audit-Grade JSON)"
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

def call_claude_with_image_and_json(model: str, file_path: str, ocr_json: dict, instruction: str):
    """Send both receipt image and authoritative OCR JSON to Claude Sonnet."""
    with open(file_path, "rb") as f:
        data = f.read()
    base64_data = base64.b64encode(data).decode("utf-8")

    media_type = "image/jpeg"
    lower = file_path.lower()
    if lower.endswith(".png"):
        media_type = "image/png"
    elif lower.endswith(".pdf"):
        media_type = "application/pdf"

    combined_instruction = (
        f"{instruction}\n\n"
        "Authoritative OCR JSON (do not ignore, do not hallucinate):\n"
        f"{json.dumps(ocr_json, indent=2)}"
    )

    try:
        message = client.messages.create(
            model=model,
            max_tokens=2048,
            temperature=0,
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
                        {"type": "text", "text": combined_instruction},
                    ],
                }
            ],
        )
        return message
    except Exception as e:
        st.error(f"Error calling Claude: {e}")
        return None

def clean_json_text(block_text: str) -> str:
    text = block_text.strip()
    if text.startswith("```"):
        text = text.strip("` \n")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    first_json_idx = None
    for i, ch in enumerate(text):
        if ch in "{[":
            first_json_idx = i
            break
    if first_json_idx is not None:
        text = text[first_json_idx:]
    open_braces = 0
    end_idx = None
    for i, ch in enumerate(text):
        if ch == "{":
            open_braces += 1
        elif ch == "}":
            open_braces -= 1
            if open_braces == 0:
                end_idx = i + 1
                break
    if end_idx:
        text = text[:end_idx]
    return text.strip()

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

def upload_string_to_gcs(content: str, dest_name: str, content_type: str = "text/plain"):
    blob = gcs_bucket.blob(dest_name)
    blob.upload_from_string(content, content_type=content_type)
    return f"gs://{GCS_BUCKET}/{dest_name}"

def flatten_result(filename: str, file_path: str, message):
    if not message:
        st.error("No message object returned from Claude.")
        return None, None
    parsed_json = None
    for idx, block in enumerate(getattr(message, "content", [])):
        block_type = getattr(block, "type", None) or (isinstance(block, dict) and block.get("type"))
        block_text = getattr(block, "text", None) or (isinstance(block, dict) and block.get("text"))
        if block_text is None:
            continue
        cleaned = clean_json_text(block_text)
        try:
            candidate = json.loads(cleaned)
            required = ["vendor_name","date","currency","total_amount","line_items","payment_method"]
            missing = [k for k in required if k not in candidate]
            if missing:
                st.warning(f"JSON parsed but missing required keys: {missing}")
            parsed_json = candidate
            break
        except Exception:
            continue
    if not parsed_json:
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
    if not df.empty and row["filename"] in df["filename"].values and row["system_date"] in df["system_date"].values:
        return df, False
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_master_inventory(df)
    return df, True

def save_list_file(filename: str, parsed_json: dict):
    lines = [
        f"Vendor: {parsed_json.get('vendor_name')}",
        f"Date: {parsed_json.get('date')} {parsed_json.get('time')}",
        f"Currency: {parsed_json.get('currency')}",
        f"Total Amount: {parsed_json.get('total_amount')}",
        f"Payment Method: {parsed_json.get('payment_method')}",
    ]
    lines.append("Line Items:")
    for item in parsed_json.get("line_items", []):
        desc = item.get("description")
        qty = item.get("quantity")
        unit = item.get("unit_price")
        total = item.get("line_total")
        lines.append(f" - {desc} x{qty} @ {unit} = {total}")
    content = "\n".join(lines)
    list_filename = filename.rsplit(".", 1)[0] + ".list"
    dest_name = f"uploads/{list_filename}"
    uri = upload_string_to_gcs(content, dest_name, content_type="text/plain")
    return uri

def display_receipt_list(parsed_json: dict):
    st.subheader("🧾 Receipt summary")
    st.write(f"**Vendor:** {parsed_json.get('vendor_name')}")
    st.write(f"**Date:** {parsed_json.get('date')} {parsed_json.get('time')}")
    st.write(f"**Currency:** {parsed_json.get('currency')}")
    st.write(f"**Total amount:** {parsed_json.get('total_amount')}")
    st.write(f"**Payment method:** {parsed_json.get('payment_method')}")
    st.subheader("🛍️ Line items")
    items = parsed_json.get("line_items", [])
    df = pd.DataFrame(items)
    if not df.empty:
        st.dataframe(df)

def build_instruction() -> str:
    return (
        "You are an audit‑grade receipt parser. Use the OCR JSON as authoritative. "
        "Cross-check against the attached image. Extract exactly these fields:\n"
        "- vendor_name\n"
        "- date\n"
        "- currency\n"
        "- total_amount\n"
        "- payment_method\n

# ========== UI ==========
st.title(APP_TITLE)
st.caption("Upload a receipt image (JPEG/PDF) and its raw OCR JSON. "
           "Claude Sonnet will parse audit‑grade JSON using OCR as authoritative, "
           "cross‑checking against the image. Review before confirming upload to GCS.")

# Upload widgets
uploaded_file = st.file_uploader("Choose a receipt image", type=ALLOWED_EXTS)
ocr_file = st.file_uploader("Upload raw OCR JSON", type=["json"])

if uploaded_file and ocr_file:
    st.write(f"File uploaded: {uploaded_file.name} ({human_bytes(uploaded_file.size)})")

    # Size guard
    if uploaded_file.size > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"File exceeds {MAX_UPLOAD_MB} MB limit.")
    else:
        # Save locally only (no GCS upload yet)
        temp_path = save_temp_file(uploaded_file)
        st.info(f"Temporary file saved: {temp_path}")

        # Load OCR JSON
        try:
            ocr_json = json.load(ocr_file)
        except Exception as e:
            st.error(f"Failed to parse OCR JSON: {e}")
            st.stop()

        # Prompt Claude with both image + OCR JSON
        instruction = build_instruction()
        message = call_claude_with_image_and_json(MODEL_DEFAULT, temp_path, ocr_json, instruction)

        # Parse result and build minimal row
        row, parsed_json = flatten_result(uploaded_file.name, temp_path, message)

        if not parsed_json:
            st.error("Parse failed. Nothing will be uploaded. Inspect traces above and adjust the prompt or input.")
        else:
            # Display human-readable summary
            display_receipt_list(parsed_json)

            # Show the minimal row that would go into the inventory
            st.subheader("📄 Inventory record (pending confirmation)")
            st.write(row)

            # Confirmation step: only on click do we upload and append
            if st.button("Confirm upload to GCS and append to inventory"):
                # Upload image
                dest_image = f"uploads/{uploaded_file.name}"
                gcs_image_uri = upload_to_gcs(temp_path, dest_image)
                st.success(f"Image uploaded to GCS: {gcs_image_uri}")

                # Save .list file alongside image
                list_uri = save_list_file(uploaded_file.name, parsed_json)
                st.success(f"List file uploaded to GCS: {list_uri}")

                # Append to inventory CSV in GCS
                df, added = append_to_inventory(row)
                if added:
                    st.success("Inventory record appended.")
                else:
                    st.warning("Inventory record not appended (likely duplicate).")

                st.subheader("📊 Master inventory (from GCS)")
                df_latest = load_master_inventory()
                st.dataframe(df_latest)
else:
    st.info("Upload both a receipt image and OCR JSON to begin parsing.")

        
