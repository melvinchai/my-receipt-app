import os
import time
import uuid
import hashlib
import base64
import json
import streamlit as st
import pandas as pd
from io import BytesIO
from google.cloud import storage
from google.oauth2 import service_account
import anthropic

# ========== Config ==========
APP_TITLE = "Claude Receipt Parser (Flattened Master Inventory in GCS)"
MODEL_DEFAULT = "claude-sonnet-4-5-20250929"
MAX_UPLOAD_MB = 15
ALLOWED_EXTS = ["jpg", "jpeg", "png", "pdf"]
MASTER_CSV_NAME = "parsed_inventory.csv"

# Pricing per million tokens (illustrative)
PRICING = {
    "claude-haiku-4-5-20250929": {"input": 0.25, "output": 1.25},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
    "claude-opus-4-5-20250929": {"input": 15.00, "output": 75.00},
}
STARTING_CREDIT = 4.90

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

def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

def call_claude_with_image(model: str, file_path: str, instruction: str):
    with open(file_path, "rb") as f:
        data = f.read()
    base64_data = base64.b64encode(data).decode("utf-8")

    # Infer media type (simple heuristic)
    media_type = "image/jpeg"
    lower = file_path.lower()
    if lower.endswith(".png"):
        media_type = "image/png"
    elif lower.endswith(".pdf"):
        media_type = "application/pdf"

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
                    {
                        "type": "text",
                        "text": instruction,
                    },
                ],
            }
        ],
    )
    return message

def load_master_inventory() -> pd.DataFrame:
    blob = gcs_bucket.blob(MASTER_CSV_NAME)
    if blob.exists():
        data = blob.download_as_bytes()
        return pd.read_csv(BytesIO(data))
    else:
        return pd.DataFrame(columns=[
            "timestamp","filename","file_hash","vendor_name","store_location",
            "date","time","currency","total_amount","subtotal","rounding",
            "payment_method","invoice_number","loyalty_account",
            "loyalty_opening","loyalty_earned","loyalty_closing","line_items"
        ])

def save_master_inventory(df: pd.DataFrame):
    blob = gcs_bucket.blob(MASTER_CSV_NAME)
    blob.upload_from_string(df.to_csv(index=False), content_type="text/csv")

def upload_to_gcs(local_path: str, dest_name: str):
    blob = gcs_bucket.blob(dest_name)
    blob.upload_from_filename(local_path)
    return f"gs://{GCS_BUCKET}/{dest_name}"

def flatten_result(filename: str, file_path: str, message):
    parsed_json = None
    # Anthropics returns content blocks; find the text block with JSON
    for block in getattr(message, "content", []):
        # SDK may represent blocks as dicts or objects depending on version
        block_type = getattr(block, "type", None) or (isinstance(block, dict) and block.get("type"))
        block_text = getattr(block, "text", None) or (isinstance(block, dict) and block.get("text"))
        if block_type == "text" and block_text:
            try:
                parsed_json = json.loads(block_text)
                break
            except Exception:
                continue
    if not parsed_json:
        return None, None

    row = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "filename": filename,
        "file_hash": file_hash(file_path),
        "vendor_name": parsed_json.get("vendor_name"),
        "store_location": parsed_json.get("store_location"),
        "date": parsed_json.get("date"),
        "time": parsed_json.get("time"),
        "currency": parsed_json.get("currency"),
        "total_amount": parsed_json.get("total_amount"),
        "subtotal": parsed_json.get("subtotal"),
        "rounding": parsed_json.get("rounding"),
        "payment_method": parsed_json.get("payment_method"),
        "invoice_number": parsed_json.get("invoice_number"),
        "loyalty_account": parsed_json.get("loyalty_account"),
        "loyalty_opening": (parsed_json.get("loyalty_points", {}) or {}).get("opening_balance"),
        "loyalty_earned": (parsed_json.get("loyalty_points", {}) or {}).get("earned"),
        "loyalty_closing": (parsed_json.get("loyalty_points", {}) or {}).get("closing_balance"),
        "line_items": json.dumps(parsed_json.get("line_items"), ensure_ascii=False),
    }
    return row, parsed_json

def append_to_inventory(filename: str, file_path: str, message):
    df = load_master_inventory()
    row, parsed_json = flatten_result(filename, file_path, message)
    if not row:
        st.error("Could not flatten Claude response into schema.")
        return df, False, None

    if not df.empty and row["file_hash"] in df["file_hash"].values:
        st.warning("Duplicate receipt detected — not added to inventory.")
        return df, False, parsed_json

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_master_inventory(df)
    return df, True, parsed_json

def display_receipt_json(receipt_json: dict):
    st.subheader("🧾 Receipt summary")
    st.write(f"**Vendor:** {receipt_json.get('vendor_name')}")
    st.write(f"**Store location:** {receipt_json.get('store_location')}")
    st.write(f"**Date:** {receipt_json.get('date')} {receipt_json.get('time')}")
    st.write(f"**Currency:** {receipt_json.get('currency')}")
    st.write(f"**Subtotal:** {receipt_json.get('subtotal')}")
    st.write(f"**Rounding:** {receipt_json.get('rounding')}")
    st.write(f"**Total amount:** {receipt_json.get('total_amount')}")
    st.write(f"**Payment method:** {receipt_json.get('payment_method')}")
    st.write(f"**Invoice number:** {receipt_json.get('invoice_number')}")

    lp = receipt_json.get("loyalty_points")
    if lp:
        st.subheader("🎟️ Loyalty information")
        st.write(f"**Account:** {receipt_json.get('loyalty_account')}")
        st.write(f"Opening balance: {lp.get('opening_balance')}")
        st.write(f"Earned: {lp.get('earned')}")
        st.write(f"Closing balance: {lp.get('closing_balance')}")

    items = receipt_json.get("line_items") or []
    if items:
        st.subheader("🛍️ Line items")
        df = pd.DataFrame(items)
        st.dataframe(df)

def calculate_cost(model: str, usage: dict, credit_remaining: float):
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    rate_in = PRICING[model]["input"] / 1_000_000
    rate_out = PRICING[model]["output"] / 1_000_000

    cost_in = input_tokens * rate_in
    cost_out = output_tokens * rate_out
    total_cost = cost_in + cost_out
    new_credit = credit_remaining - total_cost

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": usage.get("total_tokens", input_tokens + output_tokens),
        "cost_in": round(cost_in, 4),
        "cost_out": round(cost_out, 4),
        "total_cost": round(total_cost, 4),
        "credit_remaining": round(new_credit, 4),
    }
# ========== UI ==========
st.title(APP_TITLE)
st.caption("Upload your receipt below (PDF or image up to 15 MB)")

uploaded_file = st.file_uploader("Choose a file", type=ALLOWED_EXTS)

if uploaded_file is not None:
    st.write(f"File uploaded: {uploaded_file.name} ({human_bytes(uploaded_file.size)})")

    # Size guard
    if uploaded_file.size > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"File exceeds {MAX_UPLOAD_MB} MB limit.")
    else:
        # Save locally
        temp_path = save_temp_file(uploaded_file)

        # Upload to GCS
        gcs_uri = upload_to_gcs(temp_path, f"uploads/{uuid.uuid4()}_{uploaded_file.name}")
        st.success(f"Uploaded to GCS: {gcs_uri}")

        # Parse with Claude
        instruction = (
            "Parse this receipt into structured JSON with keys: "
            "vendor_name, store_location, date, time, currency, subtotal, rounding, "
            "total_amount, payment_method, invoice_number, loyalty_account, "
            "loyalty_points{opening_balance, earned, closing_balance}, "
            "line_items[list of {item, qty, unit_price, total}]. "
            "Return only JSON with no extra text."
        )
        message = call_claude_with_image(MODEL_DEFAULT, temp_path, instruction)

        # Append to inventory and display
        df, added, receipt_json = append_to_inventory(uploaded_file.name, temp_path, message)

        if added:
            st.success("Receipt added to inventory.")
        else:
            st.warning("Receipt not added (duplicate or parse failure).")

        if receipt_json:
            display_receipt_json(receipt_json)

        st.subheader("📊 Master inventory")
        st.dataframe(df)
else:
    st.info("Upload a receipt to begin.")
