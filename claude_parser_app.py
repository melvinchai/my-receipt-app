import re
import base64
import streamlit as st
from google.cloud import storage
from google.oauth2 import service_account
import anthropic

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

if not CLAUDE_API_KEY:
    st.error("Missing Claude API key in secrets (claudeparser-key).")
    st.stop()
if not PROJECT_ID or not GCS_BUCKET:
    st.error("Missing GCS project or bucket in secrets.")
    st.stop()

# -----------------------------
# Helper: sanitize private_key into canonical PEM
# -----------------------------
def sanitize_pem(raw: str) -> str:
    if not isinstance(raw, str):
        raise TypeError("private_key must be a string")

    # Convert escaped sequences if someone pasted JSON with \n escapes
    s = raw.replace("\\n", "\n").strip()

    # Find header/footer tolerant to stray whitespace/quotes
    start = s.find("-----BEGIN PRIVATE KEY-----")
    end = s.find("-----END PRIVATE KEY-----")
    if start == -1 or end == -1:
        raise ValueError("PEM header/footer not found")

    # Extract body between header and footer
    body = s[start + len("-----BEGIN PRIVATE KEY-----"):end]

    # Clean every line: remove non-base64 chars (allow A-Z a-z 0-9 + / =)
    body_lines = []
    for line in body.splitlines():
        cleaned = re.sub(r"[^A-Za-z0-9+/=]", "", line)
        if cleaned:
            body_lines.append(cleaned)

    if not body_lines:
        raise ValueError("PEM body empty after cleaning")

    # Rebuild canonical PEM
    canonical = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(body_lines) + "\n-----END PRIVATE KEY-----"

    # Validate base64 decode of concatenated body
    try:
        base64.b64decode("".join(body_lines), validate=True)
    except Exception as e:
        raise ValueError(f"PEM body failed base64 validation: {e}")

    return canonical

# -----------------------------
# Build and normalize GCS service account dict explicitly
# -----------------------------
raw_gcs = st.secrets.get("gcs")
if not raw_gcs:
    st.error("Missing [gcs] block in secrets.toml")
    st.stop()

try:
    cleaned_key = sanitize_pem(raw_gcs.get("private_key", ""))
except Exception as e:
    st.error("Private key sanitize failed")
    st.exception(e)
    st.stop()

gcs_info = {
    "type": raw_gcs.get("type"),
    "project_id": raw_gcs.get("project_id"),
    "private_key_id": raw_gcs.get("private_key_id"),
    "private_key": cleaned_key,
    "client_email": raw_gcs.get("client_email"),
    "client_id": raw_gcs.get("client_id"),
    "auth_uri": raw_gcs.get("auth_uri"),
    "token_uri": raw_gcs.get("token_uri"),
    "auth_provider_x509_cert_url": raw_gcs.get("auth_provider_x509_cert_url"),
    "client_x509_cert_url": raw_gcs.get("client_x509_cert_url"),
    "universe_domain": raw_gcs.get("universe_domain"),
}

# Optional debug (temporary): show presence of keys
st.write("Secrets keys present:", sorted(list(st.secrets.keys())))
st.write("GCS keys present:", sorted([k for k in gcs_info.keys() if gcs_info.get(k)]))

# Safe preview (temporary): show first/last 60 chars of cleaned_key for structural checking
st.write("private_key head:", cleaned_key[:60])
st.write("private_key tail:", cleaned_key[-60:])

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

    # GCS sanity check: list or access bucket
    try:
        bucket = storage_client.get_bucket(GCS_BUCKET)
        blobs = [b.name for b in bucket.list_blobs(max_results=5)]
        st.write("Bucket OK, sample objects:", blobs)
    except Exception as e:
        st.error("GCS bucket access failed.")
        st.exception(e)

    # TODO: Add receipt parsing logic (upload -> Claude -> structured output)
