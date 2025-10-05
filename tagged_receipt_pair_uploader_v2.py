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

# Load credentials from Streamlit Secrets
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

# GCS Setup
client = storage.Client(credentials=gcs_creds, project=st.secrets["gcs"]["project_id"])
bucket_name = "receipt-upload-bucket-mc"
bucket = client.bucket(bucket_name)

# Token-to-tag map and tag resolution
token_map = {f"{i:02}": f"{i:02}" for i in range(1, 100)}
upload_token = st.query_params.get("token", "")
tag_id = token_map.get(upload_token)
if not tag_id:
    st.error("❌ Invalid or missing upload token.")
    st.stop()

now = datetime.now()
folder = f"{tag_id}/{now.strftime('%Y-%m')}/"

# Document AI Setup (use your deployed processor)
PROJECT_ID = "malaysia-receipt-saas"
LOCATION = "us"
PROCESSOR_ID = "81bb3655848a4bb8"
docai_client = documentai.DocumentProcessorServiceClient(
    client_options={"api_endpoint": f"{LOCATION}-documentai.googleapis.com"},
    credentials=docai_creds
)
processor_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{PROCESSOR_ID}"

# Helper: extract fixed fields using your custom schema names
def extract_fixed_fields_custom(document, source):
    fields = {
        "merchant_name": "",
        "date": "",
        "total": "",
        "reference_number": ""
    }
    if not document or not getattr(document, "entities", None):
        return fields

    for entity in document.entities:
        t = getattr(entity, "type_", "")
        text = getattr(entity, "mention_text", "")
        # Receipt mapping: use document_issuer_name, document_issue_date, transaction_total_amount
        if source == "receipt":
            if t == "document_issuer_name":
                fields["merchant_name"] = text
            elif t == "document_issue_date":
                fields["date"] = text
            elif t == "transaction_total_amount":
                fields["total"] = text
            elif t == "reference_number":
                fields["reference_number"] = text
        # Payment mapping: use document_issuer_bank_name, document_issue_date, transaction_total_amount
        elif source == "payment":
            if t == "document_issuer_bank_name":
                fields["merchant_name"] = text
            elif t == "document_issue_date":
                fields["date"] = text
            elif t == "transaction_total_amount":
                fields["total"] = text
            elif t == "reference_number":
                fields["reference_number"] = text
    return fields

def trace_all_fields(document):
    rows = []
    if not document or not getattr(document, "entities", None):
        return pd.DataFrame(rows)
    for entity in document.entities:
        rows.append({
            "type": getattr(entity, "type_", ""),
            "mention_text": getattr(entity, "mention_text", ""),
            "confidence": round(getattr(entity, "confidence", 0), 3) if getattr(entity, "confidence", None) is not None else None
        })
    return pd.DataFrame(rows)

def process_document_bytes(file_bytes, mime_type):
    raw_doc = documentai.RawDocument(content=file_bytes, mime_type=mime_type)
    request = documentai.ProcessRequest(name=processor_name, raw_document=raw_doc)
    result = docai_client.process_document(request=request)
    return result.document

def generate_preview(receipt_file, payment_file, claimant):
    receipt_img = Image.open(receipt_file)
    payment_img = Image.open(payment_file)
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

def upload_bytes_to_gcs(file_bytes, filename):
    blob_path = folder + filename
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    blob = bucket.blob(blob_path)
    blob.metadata = {"upload_token": upload_token, "timestamp": now.isoformat()}
    blob.upload_from_filename(tmp_path)
    blob.patch()
    os.remove(tmp_path)
    return blob_path

# UI
menu = st.sidebar.selectbox("Menu", ["Upload Receipt Pair", "Coming Soon", "Contact"])

if menu == "Upload Receipt Pair":
    claimant_id = st.selectbox("Claimant ID", ["Donald Trump", "Joe Biden"])
    col1, col2 = st.columns(2)
    receipt_file = col1.file_uploader("Upload Receipt or Bill", type=["jpg", "jpeg", "png"])
    payment_file = col2.file_uploader("Upload Payment Proof", type=["jpg", "jpeg", "png"])

    if receipt_file and payment_file:
        st.markdown("---")
        st.subheader("🖼️ Combined Preview")
        grayscale = st.checkbox("🖤 Convert preview to grayscale", value=False)

        preview_img = generate_preview(receipt_file, payment_file, claimant_id)
        if grayscale:
            preview_img = preview_img.convert("L")
        st.image(preview_img, caption="🧾 Combined Receipt + Payment Proof", use_container_width=True)

        pdf_buf = convert_image_to_pdf(preview_img)
        st.download_button("📥 Download Combined PDF", pdf_buf, "receipt_pair.pdf", "application/pdf")

        # Process documents
        receipt_bytes = receipt_file.getvalue()
        payment_bytes = payment_file.getvalue()

        receipt_doc = None
        payment_doc = None
        try:
            receipt_doc = process_document_bytes(receipt_bytes, "image/jpeg")
        except Exception as e:
            st.error(f"Document AI error for receipt: {e}")
        try:
            payment_doc = process_document_bytes(payment_bytes, "image/jpeg")
        except Exception as e:
            st.error(f"Document AI error for payment: {e}")

        # Extract fields using custom schema names
        receipt_row = extract_fixed_fields_custom(receipt_doc, source="receipt")
        payment_row = extract_fixed_fields_custom(payment_doc, source="payment")
        receipt_row["Type"] = "receipt"
        payment_row["Type"] = "payment"

        combined_df = pd.DataFrame([receipt_row, payment_row])
        combined_df = combined_df[["Type", "merchant_name", "date", "total", "reference_number"]]

        # Reconciliation (transaction_total_amount)
        def normalise_amount(s):
            if not s:
                return None
            return s.replace(",", "").replace("RM", "").strip()
        r_total_raw = normalise_amount(receipt_row.get("total", "")) or ""
        p_total_raw = normalise_amount(payment_row.get("total", "")) or ""
        try:
            if r_total_raw and p_total_raw and float(r_total_raw) == float(p_total_raw):
                st.success(f"✅ Amounts match: RM {r_total_raw}")
            elif r_total_raw and p_total_raw:
                st.warning(f"⚠️ Mismatch: Receipt shows RM {r_total_raw}, payment shows RM {p_total_raw}")
            else:
                st.info("ℹ️ Unable to compare amounts—missing values")
        except Exception:
            st.info("ℹ️ Unable to compare amounts—non-numeric values")

        # Summary table (fixed two rows)
        st.subheader("📊 Summary Table")
        st.dataframe(combined_df, use_container_width=True)

        csv_buf = combined_df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download Summary CSV", csv_buf, "receipt_summary.csv", "text/csv")

        # Upload only if both produced entities
        receipt_has_entities = receipt_doc is not None and getattr(receipt_doc, "entities", None)
        payment_has_entities = payment_doc is not None and getattr(payment_doc, "entities", None)
        if receipt_has_entities and payment_has_entities:
            receipt_blob_path = upload_bytes_to_gcs(receipt_bytes, f"{tag_id}_receipt.jpg")
            payment_blob_path = upload_bytes_to_gcs(payment_bytes, f"{tag_id}_payment.jpg")
            st.success(f"✅ Receipt uploaded to `{receipt_blob_path}`")
            st.success(f"✅ Payment proof uploaded to `{payment_blob_path}`")
        else:
            st.warning("⚠️ Upload skipped—no entities extracted from one or both documents.")

        # Processor Field Trace
        st.markdown("---")
        st.subheader("🧠 Processor Field Trace")
        st.markdown("**Receipt Fields Extracted:**")
        try:
            st.dataframe(trace_all_fields(receipt_doc), use_container_width=True)
        except Exception:
            st.write("No receipt trace available")

        st.markdown("**Payment Fields Extracted:**")
        try:
            st.dataframe(trace_all_fields(payment_doc), use_container_width=True)
        except Exception:
            st.write("No payment trace available")

elif menu == "Coming Soon":
    st.header("🚧 Coming Soon")
    st.info("This feature is under development. Stay tuned!")

elif menu == "Contact":
    st.header("📞 Contact")
    st.markdown(
        "Please contact **Melvin Chia**  \n"
        "📧 Email: [melvinchia@yahoo.com](mailto:melvinchia@yahoo.com)  \n"
        "📱 WhatsApp: [60127571152](https://wa.me/60127571152)"
    )
