import streamlit as st
import pandas as pd

# --- Load Excel from local repo ---
@st.cache_data
def load_rule_sheet(sheet_name, local_path="invoice_rules.xlsx"):
    xls = pd.ExcelFile(local_path)
    return pd.read_excel(xls, sheet_name=sheet_name)

# --- Rule Evaluation with Debugging ---
def classify_invoice(data, rules_df):
    for _, row in rules_df.iterrows():
        try:
            if eval(row['Condition'], {}, data):
                return row['Action'], row['Condition']
        except Exception:
            continue
    return "Unclassified", "No matching condition"

def validate_invoice(data, validation_df):
    errors = []
    for _, row in validation_df.iterrows():
        try:
            if eval(row['Condition'], {}, data):
                errors.append(row['ErrorMessage'])
        except Exception:
            continue
    return errors

def determine_submission_action(data, submission_df):
    for _, row in submission_df.iterrows():
        try:
            if eval(row['Condition'], {}, data):
                return row['Action'], row['Condition']
        except Exception:
            continue
    return "Unknown", "No matching condition"

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

    # Load rule sheets from local Excel
    xls_path = "invoice_rules.xlsx"
    classification_df = load_rule_sheet("ClassificationRules", xls_path)
    validation_df = load_rule_sheet("ValidationRules", xls_path)
    submission_df = load_rule_sheet("SubmissionRules", xls_path)

    invoice_type_result, matched_classification = classify_invoice(data, classification_df)
    validation_errors = validate_invoice(data, validation_df)
    submission_action, matched_submission = determine_submission_action(data, submission_df)

    st.subheader("📌 Classification Result")
    st.write(f"**Invoice Type:** `{invoice_type_result}`")
    st.caption(f"Matched rule: `{matched_classification}`")

    if validation_errors:
        st.error("Validation Errors:")
        for err in validation_errors:
            st.write(f"- {err}")
    else:
        st.success(f"✅ Submission Action: `{submission_action}`")
        st.caption(f"Matched rule: `{matched_submission}`")
