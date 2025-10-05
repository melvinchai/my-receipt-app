import streamlit as st
import pandas as pd
from PIL import Image, ImageOps, ImageDraw
from google.cloud import storage, documentai_v1beta3 as documentai
from google.oauth2 import service_account
from datetime import datetime
import tempfile
import io
import os

st.set_page_config(page_title="Tagged Receipt Pair Uploader", layout="wide")
st.title("📄 Tagged Receipt Pair Uploader with Document AI")

# 🔐 Load credentials from Streamlit Secrets
gcs_creds = service_account.Credentials.from_service_account_info({
    "type": st.secrets["gcs"]["type"],
    "project_id": st.secrets["gcs"]["project_id"],
    "private_key_id": st.secrets["gcs"]["private_key_id"],
    "private_key": st.secrets["gcs"]["private_key"].replace("\\n", "\n"),
    "client_email": st.secrets["gcs"]["client_email"],
    "client_id": st.secrets["gcs"]["client_id"],
    "auth_uri": st.secrets["gcs"]["auth_uri"],
    "token_uri": st.secrets["gcs"]["token_uri"],
    "auth_provider_x509_cert_url": st.secrets["gcs"]["auth_provider_x509_cert_url"],
    "client_x509_cert_url": st.secrets["gcs"]["client_x509_cert_url"],
    "universe_domain": st.secrets["gcs"]["universe_domain"]
})

docai_creds = gcs_creds  # Reuse same credentials for Document AI

# 📦 GCS Setup
client = storage.Client(credentials=gcs_creds, project=st.secrets["gcs"]["project_id"])
bucket_name = "receipt-upload-bucket-mc"
bucket = client.bucket(bucket_name)

# 🧩 Token-to-tag map
token_map = {f"{i:02}": f"{i:02}" for i in range(1, 100)}
upload_token = st.query_params.get("token", "")
tag_id = token_map.get(upload_token)
if not tag_id:
    st.error("❌ Invalid or missing upload token.")
    st.stop()

now = datetime.now()
folder = f"{tag_id}/{now.strftime('%Y-%m')}/"

# 📄 Document AI Setup
PROJECT_ID = "malaysia-receipt-saas"
LOCATION = "us"
PROCESSOR_ID = "8fb44aee4495bb0f"
docai_client = documentai.DocumentProcessorServiceClient(
    client_options={"api_endpoint": f"{LOCATION}-documentai.googleapis.com"},
    credentials=docai_creds
)
processor_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{PROCESSOR_ID}"

# 🧠 Helpers
def extract_entities(document):
    entities = []
    if document and document.entities:
        for entity in document.entities:
            entities.append({
                "Field": entity.type_,
                "Value": entity.mention_text,
                "Confidence": round(entity.confidence, 2)
            })
    return pd.DataFrame(entities)

def extract_summary(document):
    summary = {}
    FIELD_ALIASES = {
        "purchase_date": "invoice_date",
        "receipt_date": "invoice_date",
        "date_of_receipt": "invoice_date"
    }
    desired_fields = ["invoice_date", "brand_name", "invoice_total"]
    if document and document.entities:
        for entity in document.entities:
            key = FIELD_ALIASES.get(entity.type_, entity.type_)
            if key in desired_fields:
                summary[key] = entity.mention_text
    for field in desired_fields:
        summary.setdefault(field, "")
    return summary

def process_document(file_bytes, mime_type):
    raw_doc = documentai.RawDocument(content=file_bytes, mime_type=mime_type)
    request = documentai.ProcessRequest(name=processor_name, raw_document=raw_doc)
    result = docai_client.process_document(request=request)
    return result.document

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
        st.download_button("📥 Download Combined PDF", pdf_buf, "receipt_pair.pdf", "application/pdf")

        receipt_doc = process_document(receipt_file.getvalue(), "image/jpeg")
        payment_doc = process_document(payment_file.getvalue(), "image/jpeg")
        receipt_summary = extract_summary(receipt_doc)
        payment_summary = extract_summary(payment_doc)
        combined_df = pd.DataFrame([{
            "Claimant": claimant_id,
            **receipt_summary,
            **payment_summary
        }])
        st.subheader("📊 Summary Table")
        st.dataframe(combined_df, use_container_width=True)
        csv_buf = combined_df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download Summary CSV", csv_buf, "receipt_summary.csv", "text/csv")
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
