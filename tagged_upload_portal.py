import streamlit as st
from google.cloud import storage
from google.oauth2 import service_account
from datetime import datetime
import tempfile
import os

# 🧭 Sidebar Navigation
menu = st.sidebar.selectbox("Menu", ["Upload Receipt", "View History", "Manage Tags"])

# 🔐 Authenticate with GCS
credentials = service_account.Credentials.from_service_account_info(st.secrets["gcs"])
client = storage.Client(credentials=credentials, project=st.secrets["gcs"]["project_id"])
bucket_name = "receipt-upload-bucket-mc"
bucket = client.bucket(bucket_name)

# 📤 Upload Receipt Module
if menu == "Upload Receipt":
    st.header("📤 Receipt Upload Portal")

    # Tag selection (01–99, 2-digit format)
    valid_tags = [f"{i:02}" for i in range(1, 100)]
    tag_number = st.selectbox("Your assigned tag number", valid_tags, key="tag_input")
    st.session_state.valid_tag = tag_number
    st.info(f"Tag selected: {tag_number}")

    # 🔘 Mass Upload toggle (radio-style)
    mass_upload = st.radio("Mass Upload", ["Off", "On"], index=0)
    now = datetime.now()
    folder = f"{tag_number}/{now.strftime('%Y-%m')}/"

    if mass_upload == "Off":
        uploaded_file = st.file_uploader("Upload a receipt", type=["pdf", "png", "jpg", "jpeg"])
        if uploaded_file:
            filename = uploaded_file.name
            blob_path = folder + filename

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(uploaded_file.read())
                tmp_path = tmp.name

            bucket.blob(blob_path).upload_from_filename(tmp_path)
            os.remove(tmp_path)

            if filename.lower().endswith((".png", ".jpg", ".jpeg")):
                st.image(uploaded_file, caption=f"Preview: {filename}", use_column_width=True)

            st.success(f"✅ Uploaded to `{blob_path}` in `{bucket_name}`")

    elif mass_upload == "On":
        uploaded_files = st.file_uploader("Upload multiple receipts", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        if uploaded_files:
            for file in uploaded_files:
                filename = file.name
                blob_path = folder + filename

                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(file.read())
                    tmp_path = tmp.name

                bucket.blob(blob_path).upload_from_filename(tmp_path)
                os.remove(tmp_path)

                st.success(f"✅ Uploaded `{filename}` to `{blob_path}`")

# 🕵️ View History Placeholder
elif menu == "View History":
    st.header("📜 Receipt History")
    st.info("Coming soon: View past uploads by tag and date.")

# 🏷️ Manage Tags Placeholder
elif
