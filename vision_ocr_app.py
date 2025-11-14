import os
import io
import json
import streamlit as st
from PIL import Image, ImageOps
from google.cloud import vision

st.set_page_config(page_title="Google Vision OCR", layout="centered")
st.title("🧾 Audit‑grade OCR Viewer")

# ---------- Vision client ----------
def init_vision_client():
    sa_info = dict(st.secrets["gcs"])
    key_path = "/tmp/vision_key.json"
    with open(key_path, "w") as f:
        json.dump(sa_info, f)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = key_path
    return vision.ImageAnnotatorClient()

client = init_vision_client()

# ---------- Upload ----------
uploaded_file = st.file_uploader("Upload a receipt (JPG, PNG, PDF)", type=["jpg","jpeg","png","pdf"])
if not uploaded_file:
    st.info("Upload a receipt to begin.")
    st.stop()

file_bytes = uploaded_file.read()
file_ext = uploaded_file.name.lower().split(".")[-1]

if file_ext in ["jpg","jpeg","png"]:
    img = Image.open(io.BytesIO(file_bytes))
    img = ImageOps.exif_transpose(img)
    st.image(img, caption="Uploaded Image", use_column_width=True)
    image = vision.Image(content=file_bytes)
else:
    st.info("📄 PDF uploaded — Vision will process the first page")
    image = vision.Image(content=file_bytes)

# ---------- OCR ----------
response = client.document_text_detection(image=image)
if response.error.message:
    st.error(response.error.message)
    st.stop()

full_text = response.full_text_annotation.text or ""
lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]

# ---------- Display ----------
st.subheader("📜 Raw OCR Text")
st.text(full_text)

st.subheader("🔎 Raw OCR Rows (for audit)")
for i, ln in enumerate(lines, start=1):
    st.text(f"Row {i}: {ln}")

# ---------- Audit artifacts ----------
structured = {
    "filename": uploaded_file.name,
    "ocr_text": full_text,
    "raw_rows": lines
}

st.subheader("📂 Audit Artifacts")
st.download_button("Raw OCR text (.txt)", full_text, "ocr_raw.txt", "text/plain")
st.download_button("Structured JSON (.json)", json.dumps(structured, indent=2), "vision_receipt.json", "application/json")
st.download_button("Original file", file_bytes, uploaded_file.name,
                   mime="application/pdf" if file_ext=="pdf" else f"image/{file_ext}")

st.caption("Audit‑only mode: no merchant info, no line items, no totals. Just raw OCR + artifacts.")
