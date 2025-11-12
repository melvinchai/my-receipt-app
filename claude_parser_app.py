import streamlit as st
from google.cloud import storage
import pandas as pd
from PIL import Image, ImageOps
from PyPDF2 import PdfReader
import io, json, datetime
import anthropic

# -----------------------------
# Config
# -----------------------------
st.set_page_config(page_title="Claude Parser", layout="centered")

GCS_BUCKET = st.secrets["GCS_BUCKET"]
PROJECT_ID = st.secrets["GOOGLE_CLOUD_PROJECT"]
CLAUDE_API_KEY = st.secrets["CLAUDE_API_KEY"]

storage_client = storage.Client(project=PROJECT_ID)
claude_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

SCHEMA_FILE = "fields-schema.xlsx"
INVENTORY_BLOB = "token-inventory.xlsx"
PARSED_SUFFIX = "_parsed.json"

# -----------------------------
# Helpers
# -----------------------------
def read_schema(path):
    xl = pd.ExcelFile(path)
    sheets = {}
    for sheet in xl.sheet_names:
        df = xl.parse(sheet)
        df.columns = [c.strip().lower() for c in df.columns]
        if "field_name" in df.columns:
            sheets[sheet] = df
    return sheets

def build_prompt(doc_type, df):
    fields = []
    for _, row in df.iterrows():
        fields.append({
            "name": str(row.get("field_name", "")).strip(),
            "description": str(row.get("description", "")),
            "dtype": str(row.get("dtype", "string")),
            "required": bool(row.get("required", False))
        })
    field_names = ", ".join([f["name"] for f in fields])
    return f"""
You are an extraction engine. Return STRICT JSON only.

Document type: {doc_type}
Fields: {json.dumps(fields, indent=2)}

Return JSON with keys exactly: [{field_names}]
"""

def preview(uploaded_file):
    meta = {"text": None}
    if uploaded_file.type == "application/pdf":
        reader = PdfReader(uploaded_file)
        text = []
        for page in reader.pages:
            txt = page.extract_text() or ""
            text.append(txt)
        meta["text"] = "\n".join(text)[:5000]
        st.text_area("PDF Preview", meta["text"], height=200)
    else:
        image = Image.open(uploaded_file)
        image = ImageOps.exif_transpose(image)
        st.image(image, caption="Selected image", use_column_width=True)
    return meta

def call_claude(prompt, content):
    msg = claude_client.messages.create(
        model="claude-3-opus-20240229",
        max_tokens=1500,
        messages=[
            {"role": "system", "content": "Return strictly valid JSON."},
            {"role": "user", "content": f"{prompt}\n\nDocument:\n{content}"}
        ]
    )
    return msg.content[0].text

def parse_json(raw):
    try:
        return json.loads(raw)
    except:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1:
            return json.loads(raw[start:end+1])
    return {}

def upload_blob(name, fileobj):
    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(name)
    fileobj.seek(0)
    blob.upload_from_file(fileobj, rewind=True)
    return f"gs://{GCS_BUCKET}/{name}"

def upload_bytes(name, data, content_type="application/json"):
    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(name)
    blob.upload_from_string(data, content_type=content_type)
    return f"gs://{GCS_BUCKET}/{name}"

def read_inventory():
    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(INVENTORY_BLOB)
    if not blob.exists():
        return pd.DataFrame(columns=["fields","date_uploaded","file_name","document_type"])
    bio = io.BytesIO()
    blob.download_to_file(bio)
    bio.seek(0)
    return pd.read_excel(bio)

def write_inventory(df):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    out.seek(0)
    upload_blob(INVENTORY_BLOB, out)

def base_name(fname):
    return fname.rsplit(".",1)[0]

# -----------------------------
# Sidebar menu
# -----------------------------
menu = st.sidebar.radio("Menu", ["Claude Parsing"])

if menu == "Claude Parsing":
    st.title("Claude Parser")

    schemas = read_schema(SCHEMA_FILE)
    if not schemas:
        st.stop()

    doc_type = st.selectbox("Document type", list(schemas.keys()))
    schema_df = schemas[doc_type]

    uploaded = st.file_uploader("Upload file", type=["pdf","png","jpg","jpeg"])
