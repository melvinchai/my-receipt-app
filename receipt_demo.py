import streamlit as st
from google.cloud import documentai_v1beta3 as documentai
import pandas as pd
from PIL import Image
import tempfile
import fitz  # PyMuPDF
from google.oauth2 import service_account
import json
from io import BytesIO
import re

# Load credentials
try:
    creds_json = json.loads(st.secrets["google"]["credentials"])
    creds = service_account.Credentials.from_service_account_info(creds_json)
except Exception as e:
    st.error(f"❌ Failed to load credentials: {e}")
    st.stop()

# Streamlit setup
st.set_page_config(page_title="Receipt Parser Demo", layout="wide")
st.title("📄 Expense Report Demo with Document AI")

# GCP config
PROJECT_ID = "malaysia-receipt-saas"
LOCATION = "us"
PROCESSOR_ID = "8fb44aee4495bb0f"

# Sample records
sample_expenses = [
    {"Date": "2025-09-20", "Vendor": "Grab", "Description": "Client transport", "Category": "Travel", "Amount (MYR)": 45.00, "Payment Method": "Credit Card", "Tax Code": "SST", "Notes": "Meeting"},
    {"Date": "2025-09-19", "Vendor": "Starbucks", "Description": "Coffee", "Category": "Meals", "Amount (MYR)": 18.50, "Payment Method": "Cash", "Tax Code": "Non-tax", "Notes": "Partner catch-up"},
    {"Date": "2025-09-18", "Vendor": "Shopee", "Description": "Printer ink", "Category": "Office Supplies", "Amount (MYR)": 120.00, "Payment Method": "Bank Transfer", "Tax Code": "SST", "Notes": "Restock"},
    {"Date": "2025-09-17", "Vendor": "Petronas", "Description": "Fuel", "Category": "Fuel", "Amount (MYR)": 85.00, "Payment Method": "Credit Card", "Tax Code": "SST", "Notes": "Delivery"},
    {"Date": "2025-09-16", "Vendor": "Zoom", "Description": "Subscription", "Category": "Software Subscriptions", "Amount (MYR)": 60.00, "Payment Method": "Credit Card", "Tax Code": "SST", "Notes": "Monthly"},
    {"Date": "2025-09-15", "Vendor": "Udemy", "Description": "Course", "Category": "Training", "Amount (MYR)": 150.00, "Payment Method": "Credit Card", "Tax Code": "Non-tax", "Notes": "HR training"}
]

# Aliases
FIELD_ALIASES = {
    "purchase_date": "invoice_date", "receipt_date": "invoice_date", "date_of_receipt": "invoice_date",
    "transaction_date": "invoice_date", "date": "invoice_date",
    "receipt_total": "invoice_total", "total_amount": "invoice_total", "amount_due": "invoice_total",
    "grand_total": "invoice_total", "final_amount": "invoice_total",
    "merchant_name": "brand_name", "store_name": "brand_name", "retailer": "brand_name",
    "payment_method": "payment_type", "method_of_payment": "payment_type", "card_type": "payment_type",
    "payment_type": "payment_type",
    "receipt_type": "category", "transaction_category": "category", "expense_type": "category",
    "tax": "tax_code", "tax_rate": "tax_code", "vat": "tax_code"
}

# Fallback logic
def fallback_from_text(text, field):
    if not text:
        return ""
    if field == "brand_name":
        lines = text.split("\n")
        for line in lines[:5]:
            if re.search(r"(sdn bhd|berhad|enterprise|store|cafe|restaurant|mart)", line, re.IGNORECASE):
                return line.strip()
        return lines[0].strip()
    if field == "payment_type":
        if re.search(r"\bvisa\b|\bmastercard\b|\bcredit card\b", text, re.IGNORECASE):
            return "Credit Card"
        if re.search(r"\bcash\b", text, re.IGNORECASE):
            return "Cash"
        if re.search(r"\bgrabpay\b|\btouch[ -]?n[ -]?go\b", text, re.IGNORECASE):
            return "E-Wallet"
        return ""
    if field == "category":
        if re.search(r"(entertainment|meals|fuel|transport|training|software|subscription|office supplies|coffee|kopi|restaurant|food|cafe|chicken|beverage|tea|drink|lunch|dinner|snack)", text, re.IGNORECASE):
            return "Meals"
        return ""
    if field == "tax_code":
        if re.search(r"6[%]|sst", text, re.IGNORECASE):
            return "SST"
        return "Non-tax"
    return ""

# Summary extractor
def extract_summary(document):
    summary = {}
    desired_fields = ["invoice_date", "brand_name", "invoice_total", "payment_type", "category", "tax_code"]
    field_candidates = {field: [] for field in desired_fields}
    if document and document.entities:
        for entity in document.entities:
            normalized_type = entity.type_.replace("-", "_").lower()
            key = FIELD_ALIASES.get(normalized_type, normalized_type)
            if key in desired_fields and entity.mention_text.strip():
                field_candidates[key].append((entity.mention_text, entity.confidence, entity.type_))
    full_text = document.text if document and document.text else ""
    for field in desired_fields:
        if field_candidates[field]:
            best = max(field_candidates[field], key=lambda x: x[1])
            summary[field] = best[0]
        else:
            summary[field] = fallback_from_text(full_text, field)
    return summary

# Document AI client
def process_document(file_path, mime_type):
    try:
        client_options = {"api_endpoint": f"{LOCATION}-documentai.googleapis.com"}
        client = documentai.DocumentProcessorServiceClient(client_options=client_options, credentials=creds)
        name = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{PROCESSOR_ID}"
        with open(file_path, "rb") as f:
            document = documentai.RawDocument(content=f.read(), mime_type=mime_type)
            request = documentai.ProcessRequest(name=name, raw_document=document)
            result = client.process_document(request=request)
            return result.document
    except Exception as e:
        st.error(f"❌ Failed to process document: {e}")
        return None

# Upload and process
uploaded_file = st.file_uploader("Upload a receipt (image or PDF)", type=["jpg", "jpeg", "png", "pdf"])
if uploaded_file:
    mime_type = "application/pdf" if uploaded_file.type == "application/pdf" else "image/jpeg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf" if mime_type == "application/pdf" else ".jpg") as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name

    try:
        if mime_type == "application/pdf":
            doc = fitz.open(tmp_path)
            page = doc.load_page(0)
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        else:
            img = Image.open(tmp_path)

        if img.width > img.height:
            img = img.rotate(270, expand=True)

        st.image(img, caption="Uploaded Receipt", use_container_width=True)
    except Exception as e:
        st.warning(f"⚠️ Could not display image: {e}")

    document = process_document(tmp_path, mime_type)
    if document:
        parsed = extract_summary(document)
        new_record = {
            "Date": parsed.get("invoice_date", ""),
            "Vendor": parsed.get("brand_name", ""),
            "Description": "Parsed from receipt",
            "Category": parsed.get("category", "Uncategorized"),
            "Amount (MYR)": float(parsed.get("invoice_total", "0") or 0),
            "Payment Method": parsed.get("payment_type", "Unknown"),
            "Tax Code": parsed.get("tax_code", "Unknown"),
            "Notes": "Auto-parsed"
        }

        full_report = sample_expenses + [new_record]
        df = pd.DataFrame(full_report)

        st.subheader("📊 Full Expense Report")
        st.dataframe(df, use_container_width=True)

        csv_buffer = BytesIO()
        df.to_csv(csv_buffer, index=False)
        st.download_button("📥 Download as CSV", data=csv_buffer.getvalue(), file_name="expense_report.csv", mime="text/csv")

        json_buffer = BytesIO()
        json_buffer.write(json.dumps(full_report, indent=2).encode())
