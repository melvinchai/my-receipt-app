import streamlit as st
from google.cloud import storage
from google.oauth2 import service_account
from datetime import datetime
import tempfile
import os

st.title("📤 Receipt Upload Portal")

# Authenticate with GCS using Streamlit Secrets
credentials = service_account.Credentials.from_service_account_info(st.secrets["gcs"])
client = storage.Client(credentials=credentials, project=st.secrets["gcs"]["project_id"])
bucket_name = "receipt-upload-bucket-mc"
bucket = client.bucket(bucket_name)

# Step 1: Tag number input
st.subheader("Step 1: Enter your tag number")
tag_number = st.number_input("Enter a tag number (20–30)", min_value=20, max_value=30, step=1, format="%d", key="tag_input")
submit_tag = st.button("Submit Number")

# Store tag number in session state
if submit_tag:
    st.session_state.valid_tag = str(tag_number)
    st.success(f"✅ Tag number {tag_number} accepted")

# Step 2: Upload section (only if tag is valid)
if "valid_tag" in st.session_state:
    st.subheader("Step 2: Upload your receipt")
    uploaded_file = st.file_uploader("Upload your receipt", type=["pdf", "png", "jpg", "jpeg"])

    if uploaded_file:
        now = datetime.now()
        folder = f"{st.session_state.valid_tag}/{now.strftime('%Y-%m')}/"
        filename = uploaded_file.name
        blob_path = folder + filename

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(uploaded_file.read())
            tmp_path = tmp.name

        # Upload to GCS
        blob = bucket.blob(blob_path)
        blob.upload_from_filename(tmp_path)

        # Clean up
        os.remove(tmp_path)

        st.success(f"✅ Uploaded to `{blob_path}` in `{bucket_name}`")
    else:
        st.warning("Please upload a file to proceed.")
