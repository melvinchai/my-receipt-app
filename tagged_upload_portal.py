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

    # Tag selection (no range prompt)
    valid_tags = [f"{i:02}" for i in range(20, 31)]
    tag_number = st.selectbox("Your assigned tag number", valid_tags, key="tag_input")
    st.session_state.valid_tag = tag_number
    st.info(f"Tag selected: {tag_number}")

    # 🔘 Toggle in main panel, above upload box
    show_upload = st.toggle("Upload your receipt")

    if show_upload:
        upload_mode = st.radio("Upload Mode", ["Single Upload", "Mass Upload"])
        now = datetime.now()
        folder = f"{tag_number}/{now.strftime('%Y-%m')}/"

        if upload_mode == "Single Upload":
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

        elif upload_mode == "Mass Upload":
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
elif menu == "Manage Tags":
    st.header("🏷️ Tag Management")
    st.info("Coming soon: Reassign tags, audit contributor activity, and more.")
