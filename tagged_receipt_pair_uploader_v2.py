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

# Helpers using your custom schema names
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
        if source == "receipt":
            if t == "document_issuer_name":
                fields["merchant_name"] = text
            elif t == "document_issue_date":
                fields["date"] = text
            elif t == "transaction_total_amount":
                fields["total"] = text
            elif t == "reference_number":
                fields["reference_number"] = text
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

def generate_preview_single(receipt_file, claimant):
    receipt_img = Image.open(receipt_file)
    receipt_img = ImageOps.exif_transpose(receipt_img).resize((600, 800))
    preview = Image.new("RGB", receipt_img.size, "white")
    preview.paste(receipt_img, (0, 0))
    draw = ImageDraw.Draw(preview)
    draw.text((10, preview.height - 30), f"Claimant: {claimant}", fill="black")
    return preview

def generate_preview_pair(receipt_file, payment_file, claimant):
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

def upload_bytes_to_gcs(file_bytes, filename, metadata=None):
    blob_path = folder + filename
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    blob = bucket.blob(blob_path)
    meta = {"upload_token": upload_token, "timestamp": now.isoformat()}
    if metadata:
        meta.update(metadata)
    blob.metadata = meta
    blob.upload_from_filename(tmp_path)
    blob.patch()
    os.remove(tmp_path)
    return blob_path

# UI
menu = st.sidebar.selectbox("Menu", ["Upload Receipt Pair", "Coming Soon", "Contact"])

if menu == "Upload Receipt Pair":
    claimant_name = st.text_input("Claimant name", value="", help="Enter claimant name (free text)")
    payment_optional_note = st.info("Payment proof is optional. If no payment proof is provided, the app will process the receipt only and produce a single-line summary.")
    col1, col2 = st.columns(2)
    receipt_file = col1.file_uploader("Upload Receipt or Bill", type=["jpg", "jpeg", "png"])
    payment_file = col2.file_uploader("Upload Payment Proof (optional)", type=["jpg", "jpeg", "png"])

    if receipt_file:
        st.markdown("---")
        st.subheader("🖼️ Preview")
        grayscale = st.checkbox("🖤 Convert preview to grayscale", value=False)

        if payment_file:
            preview_img = generate_preview_pair(receipt_file, payment_file, claimant_name)
        else:
            preview_img = generate_preview_single(receipt_file, claimant_name)

        if grayscale:
            preview_img = preview_img.convert("L")

        st.image(preview_img, caption="🧾 Receipt Preview", use_container_width=True)

        pdf_buf = convert_image_to_pdf(preview_img)
        st.download_button("📥 Download PDF (visual)", pdf_buf, "receipt_visual.pdf", "application/pdf")

        # Process documents
        receipt_bytes = receipt_file.getvalue()
        payment_bytes = payment_file.getvalue() if payment_file else None

        receipt_doc = None
        payment_doc = None

        try:
            receipt_doc = process_document_bytes(receipt_bytes, "image/jpeg")
        except Exception as e:
            st.error(f"Document AI error for receipt: {e}")

        if payment_bytes:
            try:
                payment_doc = process_document_bytes(payment_bytes, "image/jpeg")
            except Exception as e:
                st.error(f"Document AI error for payment: {e}")
                payment_doc = None

        # Extract fields
        receipt_row = extract_fixed_fields_custom(receipt_doc, source="receipt")
        receipt_row["Type"] = "receipt"

        if payment_doc:
            payment_row = extract_fixed_fields_custom(payment_doc, source="payment")
            payment_row["Type"] = "payment"
            combined_df = pd.DataFrame([receipt_row, payment_row])
        else:
            # Single-line summary when no payment proof provided
            combined_df = pd.DataFrame([receipt_row])

        # Ensure fixed columns for audit: Type, merchant_name, date, total, reference_number
        cols = ["Type", "merchant_name", "date", "total", "reference_number"]
        for c in cols:
            if c not in combined_df.columns:
                combined_df[c] = ""

        combined_df = combined_df[cols]

        # Reconciliation only if payment_doc exists
        if payment_doc:
            def normalise_amount(s):
                if not s:
                    return None
                return s.replace(",", "").replace("RM", "").strip()
            try:
                r_total = normalise_amount(receipt_row.get("total", "")) or ""
                p_total = normalise_amount(payment_row.get("total", "")) or ""
                if r_total and p_total:
                    if float(r_total) == float(p_total):
                        st.success(f"✅ Amounts match: RM {r_total}")
                    else:
                        st.warning(f"⚠️ Mismatch: Receipt shows RM {r_total}, payment shows RM {p_total}")
                else:
                    st.info("ℹ️ Unable to compare amounts—missing values")
            except Exception:
                st.info("ℹ️ Unable to compare amounts—non-numeric values")
        else:
            st.info("ℹ️ No payment proof provided; reconciliation skipped. Summary contains the receipt only.")

        # Summary table and CSV
        st.subheader("📊 Summary Table")
        st.dataframe(combined_df, use_container_width=True)

        csv_buf = combined_df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download Summary CSV", csv_buf, "receipt_summary.csv", "text/csv")

        # Upload gating: require receipt parsed (entities) to upload. Payment optional.
        receipt_has_entities = receipt_doc is not None and getattr(receipt_doc, "entities", None)
        payment_has_entities = payment_doc is not None and getattr(payment_doc, "entities", None)

        if receipt_has_entities:
            # upload receipt visual and raw bytes
            metadata = {"claimant_name": claimant_name or "", "payment_proof_included": str(bool(payment_file))}
            receipt_blob_path = upload_bytes_to_gcs(receipt_bytes, f"{tag_id}_receipt.jpg", metadata=metadata)
            st.success(f"✅ Receipt uploaded to `{receipt_blob_path}`")
            if payment_bytes and payment_has_entities:
                payment_blob_path = upload_bytes_to_gcs(payment_bytes, f"{tag_id}_payment.jpg", metadata=metadata)
                st.success(f"✅ Payment proof uploaded to `{payment_blob_path}`")
            elif payment_bytes and not payment_has_entities:
                st.warning("⚠️ Payment proof uploaded skipped because parsing failed; receipt was uploaded.")
        else:
            st.warning("⚠️ Upload skipped—receipt did not parse or Document AI failed.")

        # Processor Field Trace (always show receipt trace; payment trace if available)
        st.markdown("---")
        st.subheader("🧠 Processor Field Trace")
        st.markdown("**Receipt Fields Extracted:**")
        try:
            st.dataframe(trace_all_fields(receipt_doc), use_container_width=True)
        except Exception:
            st.write("No receipt trace available")

        if payment_doc:
            st.markdown("**Payment Fields Extracted:**")
            try:
                st.dataframe(trace_all_fields(payment_doc), use_container_width=True)
            except Exception:
                st.write("No payment trace available")
    else:
        st.info("Please upload at least the receipt to proceed. Payment proof is optional.")

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
