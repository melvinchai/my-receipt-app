import streamlit as st
import os, io, json, traceback
from PIL import Image, ImageOps
from google.cloud import vision

st.set_page_config(page_title="Google Vision OCR", layout="centered")
st.title("🧠 Google Vision OCR Parser")

# --- Authenticate using Streamlit secrets ---
try:
    service_account_info = st.secrets["gcs"]
    with open("/tmp/vision_key.json", "w") as f:
        json.dump(service_account_info, f)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/tmp/vision_key.json"
    client = vision.ImageAnnotatorClient()
    st.success("✅ Vision API client initialized")
except Exception as e:
    st.error("❌ Failed to initialize Vision client")
    st.exception(e)

# --- Upload file ---
uploaded_file = st.file_uploader("Upload a receipt (JPG, PNG, PDF)", type=["jpg", "jpeg", "png", "pdf"])
if uploaded_file:
    try:
        file_bytes = uploaded_file.read()
        file_ext = uploaded_file.name.lower().split(".")[-1]

        if file_ext in ["jpg", "jpeg", "png"]:
            img = Image.open(io.BytesIO(file_bytes))
            img = ImageOps.exif_transpose(img)
            st.image(img, caption="Uploaded Image", use_column_width=True)
            image = vision.Image(content=file_bytes)
        elif file_ext == "pdf":
            image = vision.Image(content=file_bytes)
            st.info("📄 PDF uploaded — Vision will process first page only")
        else:
            st.error("Unsupported file type")
            st.stop()

        # --- OCR call ---
        response = client.document_text_detection(image=image)
        if response.error.message:
            raise RuntimeError(response.error.message)

        full_text = response.full_text_annotation.text
        st.subheader("📄 Extracted Text")
        st.text(full_text)

        # --- Build structured JSON ---
        structured = {
            "filename": uploaded_file.name,
            "text": full_text,
            "blocks": []
        }
        for page in response.full_text_annotation.pages:
            for block in page.blocks:
                block_text = ""
                for para in block.paragraphs:
                    for word in para.words:
                        word_text = "".join([s.text for s in word.symbols])
                        block_text += word_text + " "
                structured["blocks"].append(block_text.strip())

        st.subheader("🧾 Structured JSON")
        st.json(structured)

        st.download_button(
            "Download JSON",
            data=json.dumps(structured, indent=2),
            file_name="vision_receipt.json",
            mime="application/json"
        )

    except Exception as e:
        st.error("❌ OCR failed")
        st.exception(e)
        st.write(traceback.format_exc())
