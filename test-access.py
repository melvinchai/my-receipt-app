import streamlit as st
import pandas as pd
import time

# Initialize tab state
if "view" not in st.session_state:
    st.session_state.view = "Upload"

# Tab selector
view = st.radio("Choose view", ["Upload", "Status Report", "Expense Summary"], index=["Upload", "Status Report", "Expense Summary"].index(st.session_state.view))
st.session_state.view = view

# Dummy data
dummy_expense = pd.DataFrame({
    "Date": ["2025-09-26", "2025-09-27"],
    "Vendor": ["Grab", "Kopi ABC"],
    "Amount": [12.50, 8.90],
    "Category": ["Transport", "Meals"]
})

dummy_status = pd.DataFrame({
    "Filename": ["grab.jpg", "kopi.jpeg"],
    "Status": ["✅ Parsed", "⚠️ Fallback"],
    "Notes": ["Brand: Grab", "Category inferred from 'kopi'"]
})

# Upload tab
if view == "Upload":
    st.header("Receipt Processing")
    st.write("Upload receipts for parsing and categorization.")

    with st.form("upload_form"):
        uploaded_file = st.file_uploader("Upload receipt", type=["jpg", "jpeg", "png", "pdf"])
        fallback = st.checkbox("Enable fallback logic", value=True)
        submit = st.form_submit_button("Process")

    if submit and uploaded_file:
        with st.spinner("Parsing receipt..."):
            time.sleep(2)  # Simulate processing
        st.success("Receipt processed successfully!")

# Status tab
elif view == "Status Report":
    st.header("Status Report")
    st.dataframe(dummy_status)

# Summary tab
elif view == "Expense Summary":
    st.header("Expense Report")
    st.dataframe(dummy_expense)

    st.download_button("Download Expense Report", dummy_expense.to_csv(index=False), file_name="expense_report.csv")
    st.download_button("Download Status Report", dummy_status.to_csv(index=False), file_name="status_report.csv")
