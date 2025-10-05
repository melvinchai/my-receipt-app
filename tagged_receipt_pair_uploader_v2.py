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

docai_creds = gcs_creds

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
PROCESSOR_ID = "81bb3655848a4bb8"
docai_client = documentai.DocumentProcessorServiceClient(
    client_options={"api_endpoint": f"{LOCATION}-documentai.googleapis.com"},
    credentials=docai_creds
)
processor_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{PROCESSOR_ID}"

# 🧠 Helpers
def extract_fixed_fields(document, source):
    fields = {
        "merchant_name": "",
        "date": "",
        "total": "",
        "reference_number": ""
    }

    if document and document.entities:
        for entity in document.entities:
            if source == "receipt" and entity.type_ in ["merchant_name", "date", "total_amount"]:
                if entity.type_ == "total_amount":
                    fields["total"] = entity.mention_text
                else:
                    fields[entity.type_] = entity.mention_text
            elif source == "payment" and entity.type_ in ["payee_name", "date", "amount", "reference_number"]:
                if entity.type_ == "payee_name":
                    fields["merchant_name"] = entity.mention_text
                elif entity.type_ == "amount":
                    fields["total"] = entity.mention_text
                else:
                    fields[entity.type_] = entity.mention_text
    return fields

def trace_all_fields(document):
    trace = []
    if document and document.entities:
        for entity in document.entities:
            trace.append({
                "type": entity.type_,
                "mention_text": entity.mention_text,
                "confidence": round(entity.confidence, 3)
            })
    return pd.DataFrame(trace)

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

        grayscale = st.toggle("🖤 Convert preview to grayscale", value=False)

        preview_img = generate_preview(receipt_file, payment_file, claimant_id)
        if grayscale:
            preview_img = preview_img.convert("L")

        st.image(preview_img, caption="🧾 Combined Receipt + Payment Proof", use_container_width=True)

        pdf_buf = convert_image_to_pdf(preview_img)
        st.download_button("📥 Download Combined PDF", pdf_buf, "receipt_pair.pdf", "application/pdf")

        receipt_doc = process_document(receipt_file.getvalue(), "image/jpeg")
        payment_doc = process_document(payment_file.getvalue(), "image/jpeg")

        receipt_row = extract_fixed_fields(receipt_doc, source="receipt")
        payment_row = extract_fixed_fields(payment_doc, source="payment")

        receipt_row["Type"] = "receipt"
        payment_row["Type"] = "payment"

        combined_df = pd.DataFrame([receipt_row, payment_row])
        combined_df = combined_df[["Type", "merchant_name", "date", "total", "reference_number"]]

        # 🧮 Reconciliation logic
        try:
            r_total = receipt_row["total"].replace(",", "").replace("RM", "").strip()
            p_total = payment_row["total"].replace(",", "").replace("RM", "").strip()
            if float(r_total) == float(p_total):
                st.success(f"✅ Amounts match: RM {r_total}")
            else:
                st.warning(f"⚠️ Mismatch: Receipt shows RM {r_total}, payment shows RM {p_total}")
        except:
            st.info("ℹ️ Unable to compare amounts—missing or non-numeric values")

        st.subheader("📊 Summary Table")
        st.dataframe(combined_df, use_container_width=True)

        csv_buf = combined_df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download Summary CSV", csv_buf, "receipt_summary.csv", "text/csv")

        # ✅ Upload only if parsing succeeded
        if receipt_doc.entities and payment_doc.entities:
            receipt_blob_path = upload_to_gcs(receipt_file, f"{tag_id}_receipt.jpg")
            payment_blob_path = upload_to_gcs(payment_file, f"{tag_id}_payment.jpg")
            st.success(f"✅ Receipt uploaded to `{receipt_blob_path}`")
            st.success(f"✅ Payment proof uploaded to `{payment_blob_path}`")
        else:
            st.warning("⚠️ Upload skipped—no entities extracted from one or both documents.")

        # 🧠 Trace extracted fields
        st.markdown("---")
        st.subheader("🧠 Processor Field Trace")

        st.markdown("**Receipt Fields Extracted:**")
        st.dataframe(trace_all_fields(receipt_doc), use_container_width=True)

        st.markdown("**Payment Fields Extracted:**")
        st.dataframe(trace_all_fields(payment_doc), use_container_width=True)

elif menu == "Coming Soon":
    st.header("🚧 Coming Soon")
    st.info("This feature is under development
