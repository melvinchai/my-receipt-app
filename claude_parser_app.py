import streamlit as st
import pandas as pd
import base64
import requests
import os
from io import BytesIO
from datetime import datetime
from google.cloud import storage
from PIL import Image
import fitz  # PyMuPDF

# --- CONFIG ---
BUCKET_NAME = "receipt-upload-bucket-mc"
TOKEN = "99"
INVENTORY_FILE = "master_inventory.xlsx"
SCHEMA_FILE = "field_schema.xlsx"

st.set_page_config(page_title="Claude Document Parser", layout="wide")
st.title("📄 Claude-Powered Business Document Parser")

# --- Load schema from repo ---
try:
    schema_df = pd.read_excel(SCHEMA_FILE)
except Exception as e:
    st.error("⚠️ Could not load field_schema.xlsx from repo. Please make sure it's in the root folder.")
    st.stop()

doc_types = sorted(schema_df["Document Type"].unique())
default_type = "Receipt"
selected_type = st.selectbox("Select expected document type", options=[default_type] + doc_types)

# --- Upload document ---
uploaded_file = st.file_uploader("Upload a document (PDF, JPEG, PNG)", type=["pdf", "jpg", "jpeg", "png"])
if not uploaded_file:
    st.stop()

file_bytes = uploaded_file.read()
base64_doc = base64.b64encode(file_bytes).decode("utf-8")

# --- Display preview ---
st.subheader("🖼️ Document Preview")
file_ext = uploaded_file.name.lower().split(".")[-1]

if file_ext == "pdf":
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=150)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        st.image(img, caption="Page 1 of PDF", use_column_width=True)
    except Exception as e:
        st.warning("Could not render PDF preview.")
else:
    try:
        img = Image.open(BytesIO(file_bytes))
        st.image(img, caption=uploaded_file.name, use_column_width=True)
    except Exception as e:
        st.warning("Could not render image preview.")

# --- Claude prompt ---
fields = schema_df[schema_df["Document Type"] == selected_type]
field_list = "\n".join([f"- {row['Field Name']}: {row['Field Description / Hint']}" for _, row in fields.iterrows()])
prompt = f"""
You are a business document parser. The user expects a document of type '{selected_type}'.
Extract the following fields:
{field_list}

Also determine the actual document type (e.g., Receipt, Invoice, P.O, GRN, Bank Statement, Insurance Policy).
Return results in JSON with keys: 'document_type', 'fields': [{{'name':..., 'value':..., 'confidence':...}}]
"""

# --- Claude API call ---
headers = {
    "x-api-key": st.secrets["CLAUDE_API_KEY"],
    "anthropic-version": "2023-06-01",
    "Content-Type": "application/json"
}
payload = {
    "model": "claude-3-haiku-20240307",
    "max_tokens": 1500,
    "temperature": 0.2,
    "messages": [
        {"role": "user", "content": prompt},
        {"role": "user", "content": f"[Document Base64]\n{base64_doc}"}
    ]
}

if st.button("🔍 Parse Document"):
    with st.spinner("Parsing with Claude..."):
        response = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
        result = response.json()
        parsed = result.get("content", "{}")
        parsed_json = eval(parsed) if isinstance(parsed, str) else parsed

        actual_type = parsed_json.get("document_type", "Unknown")
        raw_fields = parsed_json.get("fields", [])
        normalized_fields = []

        for item in raw_fields:
            if isinstance(item, dict) and "name" in item and "value" in item:
                normalized_fields.append({
                    "name": item["name"],
                    "value": item["value"],
                    "confidence": item.get("confidence", 0.0)
                })
            else:
                for k, v in item.items():
                    normalized_fields.append({
                        "name": k,
                        "value": v,
                        "confidence": 0.0
                    })

        df = pd.DataFrame(normalized_fields)
        df["value"] = df["value"].astype(str)
        df["confidence"] = df["confidence"].astype(float)

        st.subheader(f"📄 Detected Document Type: `{actual_type}`")
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

        if st.button("✅ Confirm and Submit"):
            # --- Upload to GCS ---
            folder_name = f"{TOKEN}-{actual_type.lower().replace(' ', '-')}"
            blob_name = f"{folder_name}/{uploaded_file.name}"

            client = storage.Client()
            bucket = client.bucket(BUCKET_NAME)
            blob = bucket.blob(blob_name)
            blob.upload_from_string(file_bytes)
            st.success(f"Uploaded to bucket folder: `{folder_name}`")

            # --- Update inventory ---
            new_row = {
                "Document Type": actual_type,
                "Document Number": next((f["value"] for f in normalized_fields if "number" in f["name"].lower()), ""),
                "Upload Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            for f in normalized_fields:
                new_row[f["name"]] = f["value"]

            if os.path.exists(INVENTORY_FILE):
                inventory_df = pd.read_excel(INVENTORY_FILE)
            else:
                inventory_df = pd.DataFrame()

            inventory_df = pd.concat([inventory_df, pd.DataFrame([new_row])], ignore_index=True)
            inventory_df.sort_values(by=["Document Type", "Document Number", "Upload Date"], inplace=True)
            inventory_df.to_excel(INVENTORY_FILE, index=False)
            st.success("Inventory updated.")
