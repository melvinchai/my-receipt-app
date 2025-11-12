# claude_parser_app.py
import re
import base64
import streamlit as st
from google.cloud import storage
from google.oauth2 import service_account
import anthropic

# Streamlit UI
st.set_page_config(page_title="Claude Parser", layout="centered")
st.title("Claude Receipt Parser")

# Load top-level secrets
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
# PEM sanitizer (robust)
# -----------------------------
def sanitize_pem(raw: str) -> str:
    if not isinstance(raw, str):
        raise TypeError("private_key must be a string")

    # convert escaped newlines and trim
    s = raw.replace("\\n", "\n").strip()

    # remove surrounding quotes if present
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()

    # locate header/footer
    start = s.find("-----BEGIN PRIVATE KEY-----")
    end = s.find("-----END PRIVATE KEY-----")
    if start == -1 or end == -1:
        raise ValueError("PEM header/footer not found")

    body = s[start + len("-----BEGIN PRIVATE KEY-----"):end]

    # keep only base64 chars per line
    body_lines = []
    for line in body.splitlines():
        cleaned = re.sub(r"[^A-Za-z0-9+/=]", "", line)
        if cleaned:
            body_lines.append(cleaned)

    if not body_lines:
        raise ValueError("PEM body empty after cleaning")

    canonical = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(body_lines) + "\n-----END PRIVATE KEY-----"

    # validate base64
    try:
        base64.b64decode("".join(body_lines), validate=True)
    except Exception as e:
        raise ValueError(f"PEM body failed base64 validation: {e}")

    return canonical

# -----------------------------
# Build service account dict
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

# Temporary debug (remove in production)
st.write("Secrets keys present:", sorted(list(st.secrets.keys())))
st.write("GCS keys present:", sorted([k for k in gcs_info.keys() if gcs_info.get(k)]))
st.write("private_key head:", cleaned_key[:60])
st.write("private_key tail:", cleaned_key[-60:])

# Create credentials
try:
    gcs_credentials = service_account.Credentials.from_service_account_info(gcs_info)
except Exception as exc:
    st.error("Failed to build GCS credentials from service account info.")
    st.exception(exc)
    st.stop()

# Initialize clients
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
# Model probe: try Haiku first, then fallbacks
# -----------------------------
MODEL_CANDIDATES = [
    "claude-haiku-4-5",  # recommended Haiku model (fast, cost-efficient)
    "claude-3.11",
    "claude-3.1",
    "claude-2",
    "claude-instant"
]

working_model = None
probe_exc = None
for m in MODEL_CANDIDATES:
    try:
        probe_resp = claude_client.messages.create(
            model=m,
            max_tokens=40,
            messages=[{"role": "user", "content": "Ping. Confirm API connectivity and reply OK."}]
        )
        # robustly extract text
        try:
            text = getattr(probe_resp.content[0], "text", None) or probe_resp.content
        except Exception:
            text = probe_resp
        st.success(f"Claude OK with model: {m}")
        st.write(text)
        working_model = m
        break
    except Exception as e:
        probe_exc = e

if not working_model:
    st.error("Claude connectivity failed for all probed models. Confirm API key and accessible models in Anthropic Console.")
    st.exception(probe_exc)
    # do not stop; continue to let user inspect GCS result if helpful

# -----------------------------
# File upload and checks
# -----------------------------
uploaded_file = st.file_uploader("Upload a receipt image or PDF", type=["jpg", "jpeg", "png", "pdf"])

if uploaded_file is not None:
    st.write("File uploaded:", uploaded_file.name)

    # Repeat a simple model check on the working model before parsing
    if working_model:
        try:
            resp = claude_client.messages.create(
                model=working_model,
                max_tokens=120,
                messages=[{"role": "user", "content": "Confirm you are ready to parse a receipt. Respond with single word OK."}]
            )
            try:
                text = getattr(resp.content[0], "text", None) or resp.content
            except Exception:
                text = resp
            st.write("Claude reply:", text)
        except Exception as e:
            st.error("Claude call failed on working model.")
            st.exception(e)

    # GCS check: confirm access to bucket
    try:
        bucket = storage_client.get_bucket(GCS_BUCKET)
        blobs = [b.name for b in bucket.list_blobs(max_results=5)]
        st.write("Bucket OK, sample objects:", blobs)
    except Exception as e:
        st.error("GCS bucket access failed.")
        st.exception(e)

    # Placeholder: upload to GCS (optional) and parse flow scaffold
    try:
        blob = bucket.blob(f"uploads/{uploaded_file.name}")
        blob.upload_from_file(uploaded_file, content_type=uploaded_file.type)
        st.write("Uploaded file to GCS:", f"gs://{GCS_BUCKET}/uploads/{uploaded_file.name}")
    except Exception as e:
        st.error("Upload to GCS failed.")
        st.exception(e)

    # TODO: implement receipt -> Claude parsing prompt and structured mapping
    st.info("Next: implement structured extraction prompt to Claude and map to JSON fields.")
