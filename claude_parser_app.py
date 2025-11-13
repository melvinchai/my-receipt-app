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
# Store the inventory CSV in the same GCS folder as uploads
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

    # Infer media type
    media_type = "image/jpeg"
    lower = file_path.lower()
    if lower.endswith(".png"):
        media_type = "image/png"
    elif lower.endswith(".pdf"):
        media_type = "application/pdf"

    st.info("Sending request to Claude...")
    st.write({"model": model, "instruction_preview": instruction[:200] + ("..." if len(instruction) > 200 else "")})

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

def clean_json_text(block_text: str) -> str:
    """Strip markdown fences, 'json' labels, and leading prose; keep JSON object/array."""
    text = block_text.strip()

    # Remove triple backtick fences and optional 'json' language tag
    if text.startswith("```"):
        # Strip all backticks/newlines
        text = text.strip("` \n")
        # Remove leading 'json' tag if present
        if text.lower().startswith("json"):
            text = text[4:].strip()

    # If there is leading prose before the first JSON brace/bracket, slice from there
    first_json_idx = None
    for i, ch in enumerate(text):
        if ch in "{[":
            first_json_idx = i
            break
    if first_json_idx is not None:
        text = text[first_json_idx:]

    # Also try to trim trailing prose after last closing brace/bracket
    # Count braces to find likely end; simple heuristic
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
    """Extract parsed JSON from Claude content blocks and build minimal inventory row."""
    if not message:
        st.error("No message object returned from Claude.")
        return None, None

    parsed_json = None
    for idx, block in enumerate(getattr(message, "content", [])):
        # SDK often uses objects with attributes, but may also provide dicts
        block_type = getattr(block, "type", None) or (isinstance(block, dict) and block.get("type"))
        block_text = getattr(block, "text", None) or (isinstance(block, dict) and block.get("text"))

        st.write(f"Block #{idx} type: {block_type}")
        if block_text is None:
            st.warning("Block has no text; skipping.")
            continue

        st.text(f"Block #{idx} text preview (first 300 chars):\n{block_text[:300]}")
        cleaned = clean_json_text(block_text)
        st.text(f"Cleaned block #{idx} preview (first 300 chars):\n{cleaned[:300]}")

        try:
            candidate = json.loads(cleaned)
            # Basic schema validation: ensure required fields exist
            required = ["vendor_name", "date", "currency", "total_amount", "line_items", "payment_method"]
            missing = [k for k in required if k not in candidate]
            if missing:
                st.warning(f"JSON parsed but missing required keys: {missing}")
            parsed_json = candidate
            st.success("Successfully parsed JSON from Claude content.")
            break
        except Exception as e:
            st.warning(f"JSON parse failed for block #{idx}: {e}")

    if not parsed_json:
        st.error("No valid JSON found in Claude response.")
        return None, None

    # Build minimal CSV row
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
    # Duplicate protection by filename; you can switch to hash-based if needed
    if not df.empty and row["filename"] in df["filename"].values and row["system_date"] in df["system_date"].values:
        st.warning("Duplicate receipt (same filename uploaded today) — not added to inventory.")
        return df, False
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_master_inventory(df)
    return df, True

def save_list_file(filename: str, parsed_json: dict):
    """Save human-readable .list file alongside image in GCS uploads/."""
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
        desc = item.get("description")
        code = item.get("code")
        qty = item.get("quantity")
        unit = item.get("unit_price")
        total = item.get("line_total")
        code_part = f"(code {code}) " if code else ""
        lines.append(f" - {desc} {code_part}x{qty} @ {unit} = {total}")

    content = "\n".join(lines)
    list_filename = filename.rsplit(".", 1)[0] + ".list"
    dest_name = f"uploads/{list_filename}"
    uri = upload_string_to_gcs(content, dest_name, content_type="text/plain")
    return uri

def display_receipt_list(parsed_json: dict):
    st.subheader("🧾 Receipt summary")
    st.write(f"**Vendor:** {parsed_json.get('vendor_name')}")
    if parsed_json.get("store_location"):
        st.write(f"**Store location:** {parsed_json.get('store_location')}")
    # Show both receipt date/time and system date/time for clarity
    st.write(f"**Receipt date/time:** {parsed_json.get('date')} {parsed_json.get('time')}")
    st.write(f"**Currency:** {parsed_json.get('currency')}")
    if parsed_json.get("subtotal"):
        st.write(f"**Subtotal:** {parsed_json.get('subtotal')}")
    if parsed_json.get("rounding"):
        st.write(f"**Rounding:** {parsed_json.get('rounding')}")
    st.write(f"**Total amount:** {parsed_json.get('total_amount')}")
    st.write(f"**Payment method:** {parsed_json.get('payment_method')}")
    if parsed_json.get("invoice_number"):
        st.write(f"**Invoice number:** {parsed_json.get('invoice_number')}")

    st.subheader("🛍️ Line items")
    items = parsed_json.get("line_items", [])
    df = pd.DataFrame(items)
    if not df.empty:
        st.dataframe(df)
    else:
        st.info("No line items found.")

def build_instruction() -> str:
    """Strict prompt to force bare JSON with the agreed schema."""
    return (
        "You are an audit‑grade receipt parser. From the attached file, extract exactly these fields:\n"
        "- vendor_name\n- date\n- currency\n- total_amount\n- payment_method\n"
        "- invoice_number (if any)\n- line_items (array of objects with keys: description, code (if any), quantity, unit_price, line_total)\n\n"
        "Return only a valid JSON object with those keys. Do not include any prose, explanations, or Markdown. "
        "Do not wrap the JSON in backticks. Do not add extra fields. Ensure JSON is complete and syntactically valid."
    )
# ========== UI ==========
st.title(APP_TITLE)
st.caption("Upload a receipt (PDF or image up to 15 MB). Parse first, review, then confirm to upload to GCS and append to inventory.")

uploaded_file = st.file_uploader("Choose a file", type=ALLOWED_EXTS)

if uploaded_file is not None:
    st.write(f"File uploaded: {uploaded_file.name} ({human_bytes(uploaded_file.size)})")

    # Size guard
    if uploaded_file.size > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"File exceeds {MAX_UPLOAD_MB} MB limit.")
    else:
        # Save locally only (no GCS upload yet)
        temp_path = save_temp_file(uploaded_file)
        st.info(f"Temporary file saved: {temp_path}")

        # Prompt Claude
        instruction = build_instruction()
        message = call_claude_with_image(MODEL_DEFAULT, temp_path, instruction)

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
    st.info("Upload a receipt to begin parsing.")
