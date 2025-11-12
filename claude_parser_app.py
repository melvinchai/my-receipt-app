import streamlit as st
from google.cloud import storage
from google.oauth2 import service_account
import anthropic

# -----------------------------
# Streamlit page config
# -----------------------------
st.set_page_config(page_title="Claude Parser", layout="centered")

# -----------------------------
# Load secrets
# -----------------------------
CLAUDE_API_KEY = st.secrets["claudeparser-key"]
GCS_BUCKET = st.secrets["GCS_BUCKET"]
PROJECT_ID = st.secrets["GOOGLE_CLOUD_PROJECT"]

# Normalize private_key formatting from triple-quoted TOML
gcs_info = dict(st.secrets["gcs"])
if "private_key" in gcs_info:
    gcs_info["private_key"] = gcs_info["private_key"].replace("\\n", "\n")

# Build credentials explicitly
gcs_credentials = service_account.Credentials.from_service_account_info(gcs_info)

# -----------------------------
# Initialize clients
# -----------------------------
storage_client = storage.Client(project=PROJECT_ID, credentials=gcs_credentials)
claude_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

# -----------------------------
# App UI / Logic
# -----------------------------
st.title("Claude Receipt Parser")

uploaded_file = st.file_uploader("Upload a receipt image or PDF", type=["jpg", "jpeg", "png", "pdf"])

if uploaded_file is not None:
    st.write("File uploaded:", uploaded_file.name)

    # Test Claude connectivity
    response = claude_client.messages.create(
        model="claude-3-opus-20240229",
        max_tokens=100,
        messages=[{"role": "user", "content": "Hello Claude, confirm API connectivity."}]
    )
    st.write("Claude test response:", response.content[0].text)

    # TODO: Add receipt parsing logic here
    # Example: send uploaded_file.getvalue() to Claude for structured parsing
