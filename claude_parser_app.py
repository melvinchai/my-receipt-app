# claude_parser_app.py
import re
import base64
import io
import json
import time
import streamlit as st
from google.oauth2 import service_account
import anthropic

# Optional google storage import (app runs without it; upload skipped if unavailable)
try:
    from google.cloud import storage as gcs_mod
    STORAGE_AVAILABLE = True
except Exception:
    gcs_mod = None
    STORAGE_AVAILABLE = False

st.set_page_config(page_title="Claude Parser — Direct Parse", layout="centered")
st.title("Claude Receipt Parser — Direct Parse then Review")

# -----------------------------
# Config / secrets
# -----------------------------
CLAUDE_API_KEY = st.secrets.get("claudeparser-key")
GCS_BUCKET = st.secrets.get("GCS_BUCKET")
PROJECT_ID = st.secrets.get("GOOGLE_CLOUD_PROJECT")
RAW_GCS = st.secrets.get("gcs")

if not CLAUDE_API_KEY:
    st.error("Missing Claude API key in secrets (claudeparser-key).")
    st.stop()

# -----------------------------
# Hardened PEM sanitizer (tolerant but safe)
# -----------------------------
def sanitize_pem_hardened(raw: str) -> str:
    if not isinstance(raw, str):
        raise TypeError("private_key must be a string")

    s = raw.replace("\\n", "\n").strip()

    # Remove accidental surrounding quotes
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()

    if "-----BEGIN PRIVATE KEY-----" not in s or "-----END PRIVATE KEY-----" not in s:
        raise ValueError("PEM header/footer not found; ensure the private_key in secrets contains full PEM")

    m = re.search(r"-----BEGIN PRIVATE KEY-----(.*)-----END PRIVATE KEY-----", s, re.S)
    if not m:
        raise ValueError("PEM parse failed; check quoting/newlines in secrets")

    body_raw = m.group(1)
    # Remove whitespace and non-base64 characters
    body_compact = re.sub(r"\s+", "", body_raw)
    body_clean = re.sub(r"[^A-Za-z0-9+/=]", "", body_compact)

    # If cleaning removed characters, keep the user informed
    if len(body_clean) != len(body_compact):
        st.warning("PEM body contained unexpected characters; attempting safe repair")

    # If length mod 4 != 0, attempt to add '=' padding (only padding; do not truncate)
    rem = len(body_clean) % 4
    if rem != 0:
        pad = 4 - rem
        st.warning(f"PEM body length not multiple of 4; adding {pad} '=' padding characters for validation")
        body_clean = body_clean + ("=" * pad)

    # Validate base64
    try:
        base64.b64decode(body_clean, validate=True)
    except Exception as e:
        raise ValueError(f"PEM base64 validation failed after cleaning: {e}")

    # Reflow into canonical 64-char lines
    lines = [body_clean[i:i+64] for i in range(0, len(body_clean), 64)]
    canonical = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(lines) + "\n-----END PRIVATE KEY-----"
    return canonical

# -----------------------------
# Build optional GCS credentials
# -----------------------------
gcs_info = None
gcs_credentials = None
storage_client = None
if RAW_GCS:
    try:
        cleaned_key = sanitize_pem_hardened(RAW_GCS.get("private_key", ""))
        gcs_info = {
            "type": RAW_GCS.get("type"),
            "project_id": RAW_GCS.get("project_id"),
            "private_key_id": RAW_GCS.get("private_key_id"),
            "private_key": cleaned_key,
            "client_email": RAW_GCS.get("client_email"),
            "client_id": RAW_GCS.get("client_id"),
            "auth_uri": RAW_GCS.get("auth_uri"),
            "token_uri": RAW_GCS.get("token_uri"),
            "auth_provider_x509_cert_url": RAW_GCS.get("auth_provider_x509_cert_url"),
            "client_x509_cert_url": RAW_GCS.get("client_x509_cert_url"),
            "universe_domain": RAW_GCS.get("universe_domain"),
        }
        gcs_credentials = service_account.Credentials.from_service_account_info(gcs_info)
        if STORAGE_AVAILABLE and PROJECT_ID:
            storage_client = gcs_mod.Client(project=PROJECT_ID, credentials=gcs_credentials)
    except Exception as e:
        st.warning("GCS credentials build failed; GCS upload will be skipped.")
        st.exception(e)
        gcs_info = None

# -----------------------------
# Traces (non-sensitive)
# -----------------------------
st.write("Secrets keys present:", sorted(list(st.secrets.keys())))
if gcs_info:
    st.write("Service account in secrets (client_email):", gcs_info.get("client_email"))
    st.write("GCS_BUCKET:", GCS_BUCKET)
    st.write("Storage client available:", bool(storage_client))
else:
    st.info("GCS not configured or invalid; approved uploads will be skipped until fixed.")

# -----------------------------
# Initialize Claude client and probe models
# -----------------------------
try:
    claude_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    st.success("Initialized Claude client")
except Exception as e:
    st.error("Failed to initialize Claude client.")
    st.exception(e)
    st.stop()

MODEL_CANDIDATES = ["claude-haiku-4-5", "claude-3.11", "claude-3.1", "claude-2", "claude-instant"]
working_model = None
probe_exc = None
for m in MODEL_CANDIDATES:
    try:
        probe_resp = claude_client.messages.create(
            model=m,
            max_tokens=20,
            messages=[{"role": "user", "content": "Ping. Reply exactly: OK"}]
        )
        try:
            probe_text = getattr(probe_resp.content[0], "text", None) or probe_resp.content
        except Exception:
            probe_text = probe_resp
        st.success(f"Claude OK with model: {m}")
        st.write("Probe response:", probe_text)
        working_model = m
        break
    except Exception as e:
        probe_exc = e

if not working_model:
    st.error("Claude connectivity failed for all probed models.")
    st.exception(probe_exc)

# -----------------------------
# Helpers: base64 encode, call Claude, robust parse
# -----------------------------
def encode_file_to_base64(bytes_in: bytes) -> str:
    return base64.b64encode(bytes_in).decode("ascii")

def call_claude_with_base64_file(model: str, b64data: str, filename: str) -> str:
    prompt = f"""
You are a strict JSON extractor. The following is a base64-encoded file named {filename}. Decode it and extract:
- merchant_name (string or null)
- date (ISO 8601 date string YYYY-MM-DD or null)
- total (number or null)
- currency (3-letter code or null)
- reference_number (string or null)

Return a single line containing only valid JSON and nothing else. Use null when unknown.

Base64 file:
{b64data}
"""
    resp = claude_client.messages.create(
        model=model,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    try:
        return getattr(resp.content[0], "text", None) or resp.content
    except Exception:
        return resp

def robust_json_parse(s: str):
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None

# -----------------------------
# File upload UI and review flow
# -----------------------------
uploaded_file = st.file_uploader("Upload a receipt image or PDF", type=["jpg", "jpeg", "png", "pdf"])
if uploaded_file is None:
    st.info("Upload a file to test Claude-only parsing.")
else:
    st.write("File uploaded:", uploaded_file.name)
    uploaded_bytes = uploaded_file.getvalue()
    st.write("File size (bytes):", len(uploaded_bytes))

    if not working_model:
        st.error("No working Claude model available; cannot run extraction.")
    else:
        # Base64 encode (for short tests). For larger setups consider a multimodal endpoint.
        b64 = encode_file_to_base64(uploaded_bytes)
        st.write("Base64 length (chars):", len(b64))
        st.info("Sending base64 payload to Claude for extraction (short tests only).")
        try:
            claude_raw = call_claude_with_base64_file(working_model, b64, uploaded_file.name)
            st.subheader("Claude extraction (raw)")
            st.code(claude_raw)
        except Exception as e:
            st.error("Claude extraction failed.")
            st.exception(e)
            claude_raw = None

    parsed = robust_json_parse(claude_raw) if claude_raw else None
    st.subheader("Parsed (best-effort)")
    if parsed and isinstance(parsed, dict):
        st.json(parsed)
    else:
        st.warning("Could not parse valid JSON from Claude output. Reviewer may still approve or reject using raw text.")

    col1, col2 = st.columns(2)
    approve = col1.button("Approve and store")
    reject = col2.button("Reject (discard)")

    if reject:
        st.info("File discarded (not stored).")
    if approve:
        if storage_client and GCS_BUCKET:
            try:
                bucket = storage_client.get_bucket(GCS_BUCKET)
                # store original file under accepted/<filename>
                blob = bucket.blob(f"accepted/{uploaded_file.name}")
                blob.upload_from_string(uploaded_bytes, content_type=uploaded_file.type)
                # store extracted JSON (best-effort) as sibling file
                parsed_payload = parsed if parsed else {"raw_extraction": claude_raw}
                meta_blob = bucket.blob(f"accepted/{uploaded_file.name}.json")
                meta_blob.upload_from_string(json.dumps(parsed_payload), content_type="application/json")
                # store audit record
                audit = {
                    "approved_by": st.session_state.get("user_id", "manual_test"),
                    "timestamp": int(time.time()),
                    "model": working_model,
                    "file": f"accepted/{uploaded_file.name}"
                }
                audit_blob = bucket.blob(f"accepted/{uploaded_file.name}.audit.json")
                audit_blob.upload_from_string(json.dumps(audit), content_type="application/json")
                st.success(f"Uploaded file and JSON to gs://{GCS_BUCKET}/accepted/{uploaded_file.name}")
            except Exception as e:
                st.error("GCS upload failed.")
                st.exception(e)
        else:
            st.warning("Storage client or GCS_BUCKET not available. To persist approved files, configure GCS credentials in secrets and redeploy.")

    st.info("When parsing quality is acceptable we can switch to a multimodal endpoint or reintroduce OCR for production reliability.")
