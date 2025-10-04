import streamlit as st
from datetime import datetime
from google.cloud import storage
import tempfile

# Configuration
BUCKET_NAME = "receipt-upload-bucket-mc"
VALID_TAGS = [str(i).zfill(2) for i in range(20, 31)]  # ['20', '21', ..., '30']

st.set_page_config(page_title="Receipt Upload", page_icon="📤")
st.title("📤 Receipt Upload Portal")

# Step 1: Ask for 2-digit tag
tag = st.text_input("Enter your assigned 2-digit ID (between 20 and 30):")

# Step 2: Validate tag
if tag in VALID_TAGS:
    st.success(f"✅ Tag `{tag}` accepted. You may now upload your receipts.")
    
    # Step 3: Upload files
    uploaded_files = st.file_uploader("Upload your receipt(s)", type=["pdf", "jpg", "jpeg", "png"], accept_multiple_files=True)

    if uploaded_files:
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        month_folder = datetime.now().strftime("%Y-%m")

        for file in uploaded_files:
            blob_path = f"uploads/{tag}/{month_folder}/{file.name}"
            blob = bucket.blob(blob_path)

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(file.read())
                tmp.seek(0)
                blob.upload_from_file(tmp)
                st.success(f"📁 Uploaded to: `{blob_path}`")
else:
    if tag:
        st.warning("❌ Invalid ID. Please enter a number between 20 and 30.")
    else:
        st.info("Please enter your assigned 2-digit ID to begin.")
