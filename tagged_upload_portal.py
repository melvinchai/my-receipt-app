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

# Upload form
uploaded_file = st.file_uploader("Upload your receipt", type=["pdf", "png", "jpg", "jpeg"])
tag = st.text_input("Enter a 3-letter tag (e.g. WTR, ELE, FOD)")
email = st.text_input("Enter your email (optional)")

if uploaded_file and tag:
    # Build folder path: TAG/YYYY-MM/
    now = datetime.now()
    folder = f"{tag.upper()}/{now.strftime('%Y-%m')}/"
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
    if email:
        st.info(f"Traceable via tag `{tag.upper()}` and email `{email}`")

else:
    st.warning("Please upload a file and enter a tag to proceed.")
