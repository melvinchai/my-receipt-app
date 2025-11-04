import streamlit as st
import pandas as pd

st.set_page_config(page_title="Admin: Parsing Rules Viewer", layout="wide")
st.title("📋 Admin Module: View Parsing Rules")

# --- Upload Excel ---
uploaded_file = st.file_uploader("Upload parsing_rules.xlsx", type=["xlsx"])

if uploaded_file:
    try:
        df = pd.read_excel(uploaded_file)
        st.success("Parsing rules loaded successfully.")
        st.subheader("📄 Displaying Rules")
        st.dataframe(df, use_container_width=True)
    except Exception as e:
        st.error(f"Failed to read Excel file: {e}")
else:
    st.info("Please upload your parsing_rules.xlsx file to view its contents.")
