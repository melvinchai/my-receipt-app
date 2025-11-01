import streamlit as st
import pandas as pd
import gcsfs

# --- Load Excel from GCS ---
@st.cache_data
def load_rule_sheet(sheet_name, gcs_path):
    fs = gcsfs.GCSFileSystem()
    with fs.open(gcs_path, 'rb') as f:
        xls = pd.ExcelFile(f)
        return pd.read_excel(xls, sheet_name=sheet_name)

# --- Rule Evaluation ---
def classify_invoice(data, rules_df):
    for _, row in rules_df.iterrows():
        try:
            if eval(row['Condition'], {}, data):
                return row['Action']
        except Exception:
            continue
    return "Unclassified"

def validate_invoice(data, validation_df):
    errors = []
    for _, row in validation_df.iterrows():
        try:
            if eval(row['Condition'], {}, data):
                errors.append(row['ErrorMessage'])
        except Exception:
            continue
    return errors

# --- Streamlit UI ---
st.title("🧾 LHDN Invoice Classifier")

with st.form("invoice_form"):
    buyer_TIN = st.text_input("Buyer TIN (leave blank if none)")
    seller_registered = st.selectbox("Is seller registered?", ["Yes", "No"]) == "Yes"
    buyer_registered = st.selectbox("Is buyer registered?", ["Yes", "No"]) == "Yes"
    buyer_country = st.text_input("Buyer country (e.g., MY)")
    amount = st.number_input("Invoice amount", min_value=0.0)
    currency = st.selectbox("Currency", ["MYR", "USD", "SGD"])
    invoice_type = st.selectbox("Invoice type", ["Standard", "Credit Note", "Debit Note"])
    payment_method = st.selectbox("Payment method", ["Cash", "eWallet", "Bank Transfer"])
    channel = st.selectbox("Sales channel", ["Online", "Offline"])
    invoice_date = st.date_input("Invoice date")
    status = st.selectbox("Invoice status", ["Draft", "Approved", "Rejected", "Pending"])
    submitted = st.form_submit_button("Classify Invoice")

if submitted:
    data = {
        "buyer_TIN": buyer_TIN or None,
        "seller_registered": seller_registered,
        "buyer_registered": buyer_registered,
        "buyer_country": buyer_country,
        "amount": amount,
        "currency": currency,
        "invoice_type": invoice_type,
        "payment_method": payment_method,
        "channel": channel,
        "invoice_date": str(invoice_date),
        "status": status
    }

    # Load rules from GCS
    gcs_path = "your-bucket-name/rules/invoice_rules.xlsx"
    classification_df = load_rule_sheet("ClassificationRules", gcs_path)
    validation_df = load_rule_sheet("ValidationRules", gcs_path)
    submission_df = load_rule_sheet("SubmissionRules", gcs_path)

    invoice_type_result = classify_invoice(data, classification_df)
    validation_errors = validate_invoice(data, validation_df)

    st.subheader("📌 Classification Result")
    st.write(f"**Invoice Type:** `{invoice_type_result}`")

    if validation_errors:
        st.error("Validation Errors:")
        for err in validation_errors:
            st.write(f"- {err}")
    else:
        st.success("Invoice is valid and ready for submission.")

