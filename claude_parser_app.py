import streamlit as st
from google.cloud import storage
from google.oauth2 import service_account
import anthropic
import textwrap

# -----------------------------
# Streamlit page config
# -----------------------------
st.set_page_config(page_title="Claude Parser", layout="centered")

# -----------------------------
# Load top-level secrets
# -----------------------------
CLAUDE_API_KEY = st.secrets.get("claudeparser-key")
GCS_BUCKET = st.secrets.get("GCS_BUCKET")
PROJECT_ID = st.secrets.get("GOOGLE_CLOUD_PROJECT")

# Quick checks
if not CLAUDE_API_KEY:
    st.error("Missing Claude API key in secrets (claudeparser-key).")
    st.stop()
if not PROJECT_ID or not GCS_BUCKET:
    st.error("Missing GCS project or bucket in secrets.")
    st.stop()

# -----------------------------
# Build and normalize GCS service account dict explicitly
# -----------------------------
raw_gcs = st.secrets.get("gcs")
if not raw_gcs:
    st.error("Missing [gcs] block in secrets.toml")
    st.stop()

def normalize_private_key(raw_key: str) -> str:
    if not isinstance(raw_key, str):
        raise TypeError("private_key must be a string")
    # Remove surrounding whitespace
    key = raw_key.strip()
    # Convert literal escaped sequences if someone pasted JSON with \n escapes
    key = key.replace("\\n", "\n")
    # Collapse repeated blank lines (defensive)
    key = "\n".join(line.rstrip() for line in key.splitlines())
    return key

# Compose the dict with exactly the keys Google expects
try:
    normalized_key = normalize_private_key(raw_gcs.get("private_key", ""))
except Exception as e:
    st.error(f"Failed to normalize private_key: {e}")
    st.stop()

# Basic validation before handing to google's loader
if not normalized_key.startswith("-----BEGIN PRIVATE KEY-----"):
    st.error("Private key is malformed: missing BEGIN header")
    st.code(normalized_key[:200])
    st.stop()
if not normalized_key.strip().endswith("-----END PRIVATE KEY-----"):
    st.error("Private key is malformed: missing END footer")
    st.code(normalized_key[-200:])
    st.stop()

gcs_info = {
    "type": raw_gcs.get("type"),
    "project_id": raw_gcs.get("project_id"),
    "private_key_id": raw_gcs.get("private_key_id"),
    "private_key": normalized_key,
    "client_email": raw_gcs.get("client_email"),
    "client_id": raw_gcs.get("client_id"),
    "auth_uri": raw_gcs.get("auth_uri"),
    "token_uri": raw_gcs.get("token_uri"),
    "auth_provider_x509_cert_url": raw_gcs.get("auth_provider_x509_cert_url"),
    "client_x509_cert_url": raw_gcs.get("client_x509_cert_url"),
    "universe_domain": raw_gcs.get("universe_domain"),
}

# Optional debug: show keys present (not values)
st.write("Secrets keys present:", sorted(list(st.secrets.keys())))
st.write("GCS keys present:", sorted([k for k in gcs_info.keys() if gcs_info.get(k)]))

# -----------------------------
# Create credentials with guarded error handling
# -----------------------------
try:
    gcs_credentials = service_account.Credentials.from_service_account_info(gcs_info)
except Exception as exc:
    st.error("Failed to build GCS credentials from service account info.")
    st.exception(exc)
    st.stop()

# -----------------------------
# Initialize clients
# -----------------------------
try:
    storage_client = storage.Client(project=PROJECT_ID, credentials=gcs_credentials)
except Exception as exc:
    st.error("Failed to initialize storage client.")
    st.exception(exc)
    st.stop()

try:
    claude_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
except Exception as exc:
    st.error("Failed to initialize Claude client.")
    st.exception(exc)
    st.stop()

# -----------------------------
# App UI / Logic
# -----------------------------
st.title("Claude Receipt Parser")

uploaded_file = st.file_uploader("Upload a receipt image or PDF", type=["jpg", "jpeg", "png", "pdf"])

if uploaded_file is not None:
    st.write("File uploaded:", uploaded_file.name)

    # Test Claude connectivity
    try:
        response = claude_client.messages.create(
            model="claude-3-opus-20240229",
            max_tokens=100,
            messages=[{"role": "user", "content": "Hello Claude, confirm API connectivity."}]
        )
        st.write("Claude test response:", getattr(response.content[0], "text", response.content))
    except Exception as e:
        st.error("Claude connectivity test failed.")
        st.exception(e)

    # Optional test: list buckets (sanity check for storage client)
    try:
        buckets = [b.name for b in storage_client.list_buckets(page_size=10)]
        st.write("Sample buckets:", buckets)
    except Exception as e:
        st.error("GCS list_buckets test failed.")
        st.exception(e)

    # TODO: Add receipt parsing logic here (upload -> Claude -> structured table)
