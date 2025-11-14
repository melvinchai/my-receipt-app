import os
import uuid
import base64
import json
import streamlit as st
import pandas as pd
from io import BytesIO
from google.cloud import storage
from google.oauth2 import service_account
import anthropic
from datetime import datetime

# ========== Config ==========
APP_TITLE = "Claude Receipt Parser (Claimability Stage)"
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

def versioned_filename(base_name: str) -> str:
    """Ensure no overwrites in GCS by versioning filenames."""
    name, ext = os.path.splitext(base_name)
    counter = 1
    new_name = base_name
    while gcs_bucket.blob(f"uploads/{new_name}").exists():
        counter += 1
        new_name = f"{name}_v{counter}{ext}"
    return new_name

def call_claude_with_image_and_json(model: str, file_path: str, ocr_json: dict, instruction: str):
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
    return text.strip()

def flatten_result(filename: str, file_path: str, message):
    if not message:
        st.error("No message object returned from Claude.")
        return None, None, None
    parsed_json = None
    for block in getattr(message, "content", []):
        block_text = getattr(block, "text", None) or (isinstance(block, dict) and block.get("text"))
        if not block_text:
            continue
        cleaned = clean_json_text(block_text)
        try:
            candidate = json.loads(cleaned)
            parsed_json = candidate
            break
        except Exception:
            continue
    if not parsed_json:
        return None, None, None

    now = datetime.now()
    system_date = now.strftime("%Y-%m-%d")
    system_time = now.strftime("%H:%M:%S")

    row = {
        "system_date": system_date,
        "system_time": system_time,
        "date": parsed_json.get("date"),
        "filename": filename,
        "vendor_name": parsed_json.get("vendor_name"),
        "total_amount": parsed_json.get("total_amount"),
        "invoice_number": parsed_json.get("invoice_number"),
    }

    usage = getattr(message, "usage", None)
    return row, parsed_json, usage

def upload_to_gcs(local_path: str, dest_name: str):
    blob = gcs_bucket.blob(dest_name)
    blob.upload_from_filename(local_path)
    return f"gs://{GCS_BUCKET}/{dest_name}"

def upload_string_to_gcs(content: str, dest_name: str, content_type: str = "text/plain"):
    blob = gcs_bucket.blob(dest_name)
    blob.upload_from_string(content, content_type=content_type)
    return f"gs://{GCS_BUCKET}/{dest_name}"

def save_list_file(filename: str, parsed_json: dict):
    lines = [
        f"Vendor: {parsed_json.get('vendor_name')}",
        f"Receipt Date: {parsed_json.get('date')} {parsed_json.get('time')}",
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
        cat = item.get("expense_category")
        claim = item.get("claimable")
        lines.append(f" - {desc} x{qty} @ {unit} = {total} | {cat} | Claimable: {claim}")
    content = "\n".join(lines)
    list_filename = filename.rsplit(".", 1)[0] + ".list"
    dest_name = f"uploads/{list_filename}"
    uri = upload_string_to_gcs(content, dest_name, content_type="text/plain")
    return uri

def display_receipt_list(parsed_json: dict, usage: dict):
    st.subheader("🧾 Receipt summary")
    st.write(f"**Vendor:** {parsed_json.get('vendor_name')}")
    st.write(f"**Receipt date/time:** {parsed_json.get('date')} {parsed_json.get('time')}")
    st.write(f"**Currency:** {parsed_json.get('currency')}")
    st.write(f"**Total amount:** {parsed_json.get('total_amount')}")
    st.write(f"**Payment method:** {parsed_json.get('payment_method')}")
    st.subheader("🛍️ Line items")
    items = parsed_json.get("line_items", [])
    df = pd.DataFrame(items)
    if not df.empty:
        st.dataframe(df)
    if usage:
        st.caption(f"🔢 Tokens used — Prompt: {usage.get('input_tokens')}, "
                   f"Completion: {usage.get('output_tokens')}, "
                   f"Total: {usage.get('total_tokens')}")

def build_instruction() -> str:
    return (
        "You are an audit‑grade receipt parser. Use the OCR JSON as authoritative. "
        "Cross-check against the attached image. Extract exactly these fields:\n"
        "- vendor_name\n"
        "- date\n"
        "- currency\n"
        "- total_amount\n"
        "- payment_method\n"
        "- invoice_number (if any)\n"
        "- line_items (array of objects with keys: description, code (if any), quantity, unit_price, line_total, expense_category, claimable)\n\n"
        "Rules for expense_category:\n"
        "- Food & Beverage: meals, groceries, restaurants\n"
        "- Transport: taxi, train, fuel, parking\n"
        "- Office Supplies: stationery, printing, small equipment\n"
        "- Utilities: electricity, internet, phone\n"
        "- Entertainment: movies, alcohol, leisure\n"
        "- Other: anything else\n\n"
        "Rules for claimable:\n"
        "- Food & Beverage, Transport, Office Supplies, Utilities → claimable\n"
        "- Alcohol, personal entertainment, personal shopping → not claimable\n\n"
        "Return
# ========== UI ==========
st.title(APP_TITLE)
st.caption("Upload a receipt image (JPEG/PDF) and its raw OCR JSON. "
           "Claude Sonnet will parse audit‑grade JSON using OCR as authoritative, "
           "cross‑checking against the image. Each line item will be tagged with "
           "expense_category and claimable status. These outputs are uploaded to GCS "
           "and serve as input for reimbursement determination in a later phase.")

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
        row, parsed_json, usage = flatten_result(uploaded_file.name, temp_path, message)

        if not parsed_json:
            st.error("Parse failed. Nothing will be uploaded. Inspect traces above and adjust the prompt or input.")
        else:
            # Display human-readable summary with token usage
            display_receipt_list(parsed_json, usage)

            # Show the minimal row that would go into the inventory
            st.subheader("📄 Inventory record (pending confirmation)")
            st.write(row)

            # Confirmation step: only on click do we upload and append
            if st.button("Confirm upload to GCS and append to inventory"):
                # Versioned image upload
                versioned_name = versioned_filename(uploaded_file.name)
                dest_image = f"uploads/{versioned_name}"
                gcs_image_uri = upload_to_gcs(temp_path, dest_image)
                st.success(f"Image uploaded to GCS: {gcs_image_uri}")

                # Save .list file alongside image
                list_uri = save_list_file(versioned_name, parsed_json)
                st.success(f"List file uploaded to GCS: {list_uri}")

                # Save JSON file alongside image
                json_filename = versioned_name.rsplit(".", 1)[0] + ".json"
                dest_json = f"uploads/{json_filename}"
                upload_string_to_gcs(json.dumps(parsed_json, indent=2), dest_json, content_type="application/json")
                st.success(f"JSON file uploaded to GCS: gs://{GCS_BUCKET}/{dest_json}")

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
