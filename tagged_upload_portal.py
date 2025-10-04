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
tag_number = st.text_input("Enter a 2-digit number between 20 and 30", max_chars=2)

submit_tag = st.button("Submit Number")

# Validate tag number
if submit_tag:
    if tag_number.isdigit() and 20 <= int(tag_number) <= 30:
        st.success(f"✅ Tag number {tag_number} accepted")

        # Step 2: Upload section
        st.subheader("Step 2: Upload your receipt")
        uploaded_file = st.file_uploader("Upload your receipt", type=["pdf", "png", "jpg", "jpeg"])
        email = st.text_input("Enter your email (optional)")

        if uploaded_file:
            now = datetime.now()
            folder = f"{tag_number}/{now.strftime('%Y-%m')}/"
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
                st.info(f"Traceable via tag `{tag_number}` and email `{email}`")
        else:
            st.warning("Please upload a file to proceed.")
    else:
        st.error("❌ Invalid tag number. Please enter a number between 20 and 30.")
