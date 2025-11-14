import streamlit as st
import os, io, json, traceback
from PIL import Image, ImageOps
from google.cloud import vision

st.set_page_config(page_title="Google Vision OCR", layout="centered")
st.title("🧠 Google Vision OCR Parser")

# --- Authenticate using Streamlit secrets ---
try:
    service_account_info = dict(st.secrets["gcs"])  # Convert AttrDict → dict
    key_path = "/tmp/vision_key.json"
    with open(key_path, "w") as f:
        json.dump(service_account_info, f)

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = key_path
    client = vision.ImageAnnotatorClient()
    st.success("✅ Vision API client initialized")

except Exception as e:
    st.error("❌ Failed to initialize Vision client")
    st.write("🔍 Check if [gcs] block exists and private_key is properly escaped")
    st.exception(e)
    st.stop()

# --- Upload file ---
uploaded_file = st.file_uploader("Upload a receipt (JPG, PNG, PDF)", type=["jpg", "jpeg", "png", "pdf"])
if uploaded_file:
    try:
        file_bytes = uploaded_file.read()
        file_ext = uploaded_file.name.lower().split(".")[-1]

        # --- Display image preview ---
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
        st.subheader("📄 Raw OCR Text")
        st.text(full_text)

        # --- Row grouping ---
        def group_words_into_rows(response, y_tolerance=10):
            rows, current_row, last_y = [], [], None
            for page in response.full_text_annotation.pages:
                for block in page.blocks:
                    for para in block.paragraphs:
                        for word in para.words:
                            word_text = "".join([s.text for s in word.symbols])
                            y = word.bounding_box.vertices[0].y
                            if last_y is None or abs(y - last_y) <= y_tolerance:
                                current_row.append(word_text)
                            else:
                                rows.append(current_row)
                                current_row = [word_text]
                            last_y = y
            if current_row:
                rows.append(current_row)
            return rows

        rows = group_words_into_rows(response)

        # --- Parse row into structured fields ---
        def parse_row(row):
            try:
                code = row[0]
                qty_idx = next(i for i, t in enumerate(row) if t.startswith("x"))
                at_idx = row.index("@")
                eq_idx = row.index("=")

                description = " ".join(row[1:qty_idx])
                quantity = row[qty_idx].replace("x", "")
                unit_price = row[at_idx + 1]
                line_total = row[eq_idx + 1]

                return {
                    "code": {"value": code, "source": "OCR"},
                    "description": {"value": description, "source": "OCR"},
                    "quantity": {"value": quantity, "source": "OCR"},
                    "unit_price": {"value": unit_price, "source": "OCR"},
                    "line_total": {"value": line_total, "source": "OCR"}
                }
            except Exception:
                return {"raw_row": " ".join(row), "source": "OCR"}

        structured = {
            "filename": uploaded_file.name,
            "ocr_text": full_text,
            "items": [parse_row(row) for row in rows]
        }

        st.subheader("🧾 Extracted Line Items (Human‑Verifiable)")
        st.json(structured)

        st.download_button(
            "Download JSON",
            data=json.dumps(structured, indent=2),
            file_name="vision_receipt.json",
            mime="application/json"
        )

    except Exception as e:
        st.error("❌ OCR failed")
        st.write("🔍 Check file format, Vision API response, and memory limits")
        st.exception(e)
        st.write(traceback.format_exc())
