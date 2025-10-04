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

# 🧩 Hardcoded token-to-tag map (01–99)
token_map = {f"{i:02}": f"{i:02}" for i in range(1, 100)}

# 🔍 Extract token from URL
query_params = st.experimental_get_query_params()
upload_token = query_params.get("token", [""])[0]
tag_number = token_map.get(upload_token)

# 🚫 Validate token
if not tag_number:
    st.error("❌ Invalid or missing upload token.")
    st.stop()

# 📤 Upload Receipt Module
if menu == "Upload Receipt":
    st.header("📤 Receipt Upload Portal")
    st.info(f"Your assigned tag: {tag_number}")

    # ✅ Mass Upload toggle (checkbox-style)
    mass_upload_enabled = st.checkbox("Enable Mass Upload", value=False)
    now = datetime.now()
    folder = f"{tag_number}/{now.strftime('%Y-%m')}/"

    if not mass_upload_enabled:
        uploaded_file = st.file_uploader("Upload a receipt", type=["pdf", "png", "jpg", "jpeg"])
        if uploaded_file:
            filename = uploaded_file.name
            blob_path = folder + filename

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(uploaded_file.read())
                tmp_path = tmp.name

            blob = bucket.blob(blob_path)
            blob.metadata = {
                "upload_token": upload_token,
                "timestamp": now.isoformat()
            }
            blob.upload_from_filename(tmp_path)
            blob.patch()
            os.remove(tmp_path)

            if filename.lower().endswith((".png", ".jpg", ".jpeg")):
                st.image(uploaded_file, caption=f"Preview: {filename}", use_column_width=True)

            st.success(f"✅ Uploaded to `{blob_path}` in `{bucket_name}`")

    else:
        uploaded_files = st.file_uploader("Upload multiple receipts", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        if uploaded_files:
            for file in uploaded_files:
                filename = file.name
                blob_path = folder + filename

                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(file.read())
                    tmp_path = tmp.name

                blob = bucket.blob(blob_path)
                blob.metadata = {
                    "upload_token": upload_token,
                    "timestamp": now.isoformat()
                }
                blob.upload_from_filename(tmp_path)
                blob.patch()
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
