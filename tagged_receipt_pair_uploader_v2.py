import streamlit as st
import pandas as pd
from PIL import Image, ImageOps, ImageDraw
from google.cloud import storage
from google.oauth2 import service_account
from datetime import datetime
import tempfile
import io
import os

st.set_page_config(page_title="Tagged Receipt Pair Uploader", layout="wide")
st.title("📄 Tagged Receipt Pair Uploader")

# 🔐 Authenticate with GCS
credentials = service_account.Credentials.from_service_account_info(st.secrets["gcs"])
client = storage.Client(credentials=credentials, project=st.secrets["gcs"]["project_id"])
bucket_name = "receipt-upload-bucket-mc"
bucket = client.bucket(bucket_name)

# 🧩 Hardcoded token-to-tag map (01–99)
token_map = {f"{i:02}": f"{i:02}" for i in range(1, 100)}
upload_token = st.query_params.get("token", "")
tag_id = token_map.get(upload_token)

# 🚫 Validate token
if not tag_id:
    st.error("❌ Invalid or missing upload token.")
    st.stop()

# 📅 Folder path
now = datetime.now()
folder = f"{tag_id}/{now.strftime('%Y-%m')}/"

# 🧠 Helpers
def extract_entities(image, doc_type):
    if doc_type == "receipt":
        return {
            "brand_name": "MockBrand",
            "category": "Meals",
            "tax_code": "TX123"
        }
    else:
        return {
            "payment_type": "Credit Card",
            "bank": "MockBank",
            "transaction_id": "TX999"
        }

def generate_preview(receipt, payment, claimant):
    receipt_img = Image.open(receipt)
    payment_img = Image.open(payment)
    receipt_img = ImageOps.exif_transpose(receipt_img).resize((300, 300))
    payment_img = ImageOps.exif_transpose(payment_img).resize((300, 300))

    preview = Image.new("RGB", (620, 340), "white")
    preview.paste(receipt_img, (10, 20))
    preview.paste(payment_img, (320, 20))
    draw = ImageDraw.Draw(preview)
    draw.text((10, 310), f"Claimant: {claimant}", fill="black")
    return preview

def convert_image_to_pdf(image):
    buf = io.BytesIO()
    image.save(buf, format="PDF")
    buf.seek(0)
    return buf

def generate_summary_table(receipt_entities, payment_entities):
    rows = []
    for k, v in receipt_entities.items():
        rows.append({"Document": "Receipt", "Field": k, "Value": v})
    for k, v in payment_entities.items():
        rows.append({"Document": "Payment Proof", "Field": k, "Value": v})
    return pd.DataFrame(rows)

def upload_to_gcs(file_obj, filename):
    blob_path = folder + filename
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(file_obj.read())
        tmp_path = tmp.name

    blob = bucket.blob(blob_path)
    blob.metadata = {
        "upload_token": upload_token,
        "timestamp": now.isoformat()
    }
    blob.upload_from_filename(tmp_path)
    blob.patch()
    os.remove(tmp_path)
    return blob_path

# 🧭 Sidebar Navigation
menu = st.sidebar.selectbox("Menu", ["Upload Receipt Pair", "Coming Soon", "Contact"])

# 📤 Upload Receipt and Payment Proof
if menu == "Upload Receipt Pair":
    claimant_id = st.selectbox("Claimant ID", ["Donald Trump", "Joe Biden"])

    col1, col2 = st.columns(2)
    receipt_file = col1.file_uploader("Upload Receipt or Bill", type=["jpg", "jpeg", "png"])
    payment_file = col2.file_uploader("Upload Payment Proof", type=["jpg", "jpeg", "png"])

    if receipt_file and payment_file:
        st.markdown("---")
        st.subheader("🖼️ Combined Preview")

        receipt_blob_path = upload_to_gcs(receipt_file, f"receipt_{now.strftime('%Y%m%d-%H%M%S')}.jpg")
        payment_blob_path = upload_to_gcs(payment_file, f"payment_{now.strftime('%Y%m%d-%H%M%S')}.jpg")

        preview_img = generate_preview(receipt_file, payment_file, claimant_id)
        st.image(preview_img, caption="🧾 Combined Receipt + Payment Proof", use_container_width=True)

        pdf_buf = convert_image_to_pdf(preview_img)
        st.download_button(
            label="📥 Download Combined PDF",
            data=pdf_buf,
            file_name="receipt_pair.pdf",
            mime="application/pdf"
        )

        receipt_entities = extract_entities(receipt_file, "receipt")
        payment_entities = extract_entities(payment_file, "payment")
        df = generate_summary_table(receipt_entities, payment_entities)

        st.subheader("📊 Summary Table")
        st.dataframe(df, use_container_width=True)

        csv_buf = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download Summary CSV",
            data=csv_buf,
            file_name="receipt_summary.csv",
            mime="text/csv"
        )

        st.success(f"✅ Receipt uploaded to `{receipt_blob_path}`")
        st.success(f"✅ Payment proof uploaded to `{payment_blob_path}`")

elif menu == "Coming Soon":
    st.header("🚧 Coming Soon")
    st.info("This feature is under development. Stay tuned!")

elif menu == "Contact":
    st.header("📞 Contact")
    st.markdown("""
    Please contact **Melvin Chia**  
    📧 Email: [melvinchia@yahoo.com](mailto:melvinchia@yahoo.com)  
    📱 WhatsApp: [60127571152](https://wa.me/60127571152)
    """)
