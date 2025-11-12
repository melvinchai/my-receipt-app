# claude_parser_app.py
import re
import base64
import io
import json
import streamlit as st
from google.cloud import storage, vision
from google.oauth2 import service_account
from google.api_core.exceptions import GoogleAPIError
import anthropic

# Streamlit UI
st.set_page_config(page_title="Claude Parser", layout="centered")
st.title("Claude Receipt Parser - Traces Enabled")

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
# Helper: sanitize private_key into canonical PEM
# -----------------------------
def sanitize_pem(raw: str) -> str:
    if not isinstance(raw, str):
        raise TypeError("private_key must be a string")
    s = raw.replace("\\n", "\n").strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    start = s.find("-----BEGIN PRIVATE KEY-----")
    end = s.find("-----END PRIVATE KEY-----")
    if start == -1 or end == -1:
        raise ValueError("PEM header/footer not found")
    body = s[start + len("-----BEGIN PRIVATE KEY-----"):end]
    body_lines = []
    for line in body.splitlines():
        cleaned = re.sub(r"[^A-Za-z0-9+/=]", "", line)
        if cleaned:
            body_lines.append(cleaned)
    if not body_lines:
        raise ValueError("PEM body empty after cleaning")
    canonical = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(body_lines) + "\n-----END PRIVATE KEY-----"
    try:
        base64.b64decode("".join(body_lines), validate=True)
    except Exception as e:
        raise ValueError(f"PEM body failed base64 validation: {e}")
    return canonical

# -----------------------------
# Build service account dict from secrets
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

# -----------------------------
# Detailed runtime traces (helpful during debugging)
# -----------------------------
st.header("Runtime traces and credential inspection")

# Print top-level secret keys present
st.write("Secrets keys present:", sorted(list(st.secrets.keys())))
# Print which client_email we will use
sa_email = raw_gcs.get("client_email")
st.write("Service account in secrets (client_email):", sa_email)
st.write("GCS_BUCKET from secrets:", GCS_BUCKET)
st.write("GOOGLE_CLOUD_PROJECT from secrets:", PROJECT_ID)

# Show start and end of cleaned private key (non-sensitive preview)
st.write("private_key head (preview):", cleaned_key[:80])
st.write("private_key tail (preview):", cleaned_key[-80:])

# -----------------------------
# Create credentials and clients
# -----------------------------
try:
    gcs_credentials = service_account.Credentials.from_service_account_info(gcs_info)
    st.success("Built service account credentials object from secrets")
except Exception as exc:
    st.error("Failed to build GCS credentials from service account info.")
    st.exception(exc)
    st.stop()

# Show some attributes of the credentials object
try:
    st.write("Credentials service_account_email:", getattr(gcs_credentials, "service_account_email", None))
    st.write("Credentials project_id:", getattr(gcs_credentials, "project_id", None))
    st.write("Credentials token_uri:", getattr(gcs_credentials, "token_uri", None))
except Exception:
    pass

# Initialize clients and report initialization status
try:
    storage_client = storage.Client(project=PROJECT_ID, credentials=gcs_credentials)
    st.success("Initialized storage client")
except Exception as exc:
    st.error("Failed to initialize storage client.")
    st.exception(exc)
    st.stop()

try:
    vision_client = vision.ImageAnnotatorClient(credentials=gcs_credentials)
    st.success("Initialized vision client")
except Exception as exc:
    st.error("Failed to initialize Vision client.")
    st.exception(exc)
    vision_client = None

try:
    claude_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    st.success("Initialized Claude client")
except Exception as exc:
    st.error("Failed to initialize Claude client.")
    st.exception(exc)
    st.stop()

# -----------------------------
# Model probe (try a short list)
# -----------------------------
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
        st.write("Claude probe response (raw):", probe_text)
        working_model = m
        break
    except Exception as e:
        probe_exc = e

if not working_model:
    st.error("Claude connectivity failed for all probed models.")
    st.exception(probe_exc)

# -----------------------------
# Upload UI and traced GCS operations
# -----------------------------
uploaded_file = st.file_uploader("Upload a receipt image or PDF", type=["jpg", "jpeg", "png", "pdf"])

if uploaded_file is not None:
    st.write("File uploaded:", uploaded_file.name)
    uploaded_bytes = uploaded_file.getvalue()

    # Re-check working model before parsing
    if working_model:
        try:
            resp = claude_client.messages.create(
                model=working_model,
                max_tokens=20,
                messages=[{"role": "user", "content": "Respond with OK"}]
            )
            reply = getattr(resp.content[0], "text", None) or resp.content
            st.write("Claude reply:", reply)
        except Exception as e:
            st.error("Claude call failed.")
            st.exception(e)

    # Defensive GCS: attempt to get bucket with extended trace of the exception
    bucket = None
    try:
        st.write("Attempting storage_client.get_bucket(...) now...")
        bucket = storage_client.get_bucket(GCS_BUCKET)
        st.success("storage_client.get_bucket succeeded")
        st.write("Bucket name returned:", getattr(bucket, "name", None))
        # sample objects
        try:
            blobs = [b.name for b in bucket.list_blobs(max_results=5)]
            st.write("Sample objects:", blobs)
        except Exception as list_exc:
            st.error("bucket.list_blobs failed")
            st.exception(list_exc)
    except Exception as e:
        st.error("GCS bucket access failed on get_bucket.")
        st.exception(e)
        # Attempt to extract helpful pieces from the exception for debugging
        try:
            st.write("Exception type:", type(e).__name__)
            # some google exceptions include .errors or .response
            if hasattr(e, "errors"):
                st.write("e.errors:", e.errors)
            if hasattr(e, "response"):
                st.write("e.response:", getattr(e, "response", None))
            if hasattr(e, "message"):
                st.write("e.message:", getattr(e, "message", None))
        except Exception:
            pass

    # If bucket is available, run the upload using your known-good pattern
    if bucket:
        try:
            st.write("Uploading file using uploads/<filename> path...")
            blob = bucket.blob(f"uploads/{uploaded_file.name}")
            # if we have bytes, use upload_from_string to avoid file-like issues
            blob.upload_from_string(uploaded_bytes, content_type=uploaded_file.type)
            st.success(f"Uploaded file to gs://{GCS_BUCKET}/uploads/{uploaded_file.name}")
        except Exception as up_e:
            st.error("Upload to GCS failed after bucket access succeeded.")
            st.exception(up_e)
    else:
        st.info("Skipping upload because bucket is not accessible. See get_bucket exception details above.")

    # Optional: run OCR + Claude extraction only if you want to exercise parsing locally
    run_parse = st.checkbox("Run OCR + Claude extraction now", value=False)
    if run_parse:
        # Initialize vision client check
        if not vision_client:
            st.error("Vision client not initialized; cannot OCR.")
        else:
            try:
                image = vision.Image(content=uploaded_bytes)
                vresp = vision_client.text_detection(image=image)
                if vresp.error.message:
                    raise GoogleAPIError(vresp.error.message)
                ocr_text = vresp.full_text_annotation.text if vresp.full_text_annotation and vresp.full_text_annotation.text else ""
                st.write("OCR text length:", len(ocr_text))
            except Exception as ocr_exc:
                st.error("OCR failed.")
                st.exception(ocr_exc)
                ocr_text = ""

            if working_model and ocr_text:
                try:
                    prompt = f"""
You are a strict JSON extractor. Given the raw OCR text of a receipt, return a single JSON object with the following keys:
merchant_name, date (YYYY-MM-DD), total (number), currency (3-letter) and reference_number.
Only output valid JSON and nothing else.

OCR:
\"\"\"{ocr_text}\"\"\"
"""
                    cresp = claude_client.messages.create(model=working_model, max_tokens=600,
                                                         messages=[{"role": "user", "content": prompt}])
                    ctext = getattr(cresp.content[0], "text", None) or cresp.content
                    st.subheader("Claude extraction (raw)")
                    st.code(ctext)
                    parsed = None
                    try:
                        parsed = json.loads(ctext)
                    except Exception:
                        m = re.search(r"\{.*\}", ctext, re.S)
                        if m:
                            try:
                                parsed = json.loads(m.group(0))
                            except Exception:
                                parsed = None
                    st.subheader("Parsed extraction")
                    if parsed and isinstance(parsed, dict):
                        st.json(parsed)
                    else:
                        st.warning("Could not parse JSON from Claude output. See raw output above.")
                except Exception as ce:
                    st.error("Claude extraction failed.")
                    st.exception(ce)
