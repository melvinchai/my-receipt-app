import os
import io
import re
import json
import traceback
from decimal import Decimal, ROUND_HALF_UP

import streamlit as st
import pandas as pd
from PIL import Image, ImageOps

# Google Vision SDK
from google.cloud import vision

# ---------- Streamlit page setup ----------
st.set_page_config(page_title="Google Vision OCR", layout="centered")
st.title("🧠 Audit‑grade Receipt Parser (Google Vision OCR)")

# ---------- Vision client init via Streamlit secrets ----------
def init_vision_client():
    try:
        # Expect st.secrets["gcs"] to contain a full service account JSON
        sa_info = dict(st.secrets["gcs"])
        key_path = "/tmp/vision_key.json"
        with open(key_path, "w") as f:
            json.dump(sa_info, f)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = key_path
        client = vision.ImageAnnotatorClient()
        st.success("✅ Vision API client initialized")
        return client
    except Exception as e:
        st.error("❌ Failed to initialize Vision client")
        st.caption("Check that [gcs] secrets exist and the private_key is properly escaped.")
        st.exception(e)
        st.stop()

client = init_vision_client()

# ---------- File upload ----------
uploaded_file = st.file_uploader("Upload a receipt (JPG, PNG, PDF)", type=["jpg", "jpeg", "png", "pdf"])
if not uploaded_file:
    st.info("Upload a receipt to begin.")
    st.stop()

# Read file bytes
file_bytes = uploaded_file.read()
file_ext = uploaded_file.name.lower().split(".")[-1]

# Display image preview (first page for PDF)
if file_ext in ["jpg", "jpeg", "png"]:
    img = Image.open(io.BytesIO(file_bytes))
    img = ImageOps.exif_transpose(img)
    st.image(img, caption="Uploaded Image", use_column_width=True)
    image = vision.Image(content=file_bytes)
elif file_ext == "pdf":
    st.info("📄 PDF uploaded — Vision will process the first page in this view")
    image = vision.Image(content=file_bytes)
else:
    st.error("Unsupported file type")
    st.stop()

# ---------- OCR call ----------
try:
    response = client.document_text_detection(image=image)
    if response.error.message:
        raise RuntimeError(response.error.message)
except Exception as e:
    st.error("❌ OCR request failed")
    st.exception(e)
    st.stop()

full_text = response.full_text_annotation.text or ""
if not full_text.strip():
    st.warning("OCR returned empty text. Please try a clearer image.")
    st.stop()

# ---------- Helpers ----------
def D(x):
    """Safe Decimal conversion from string; returns None if invalid."""
    try:
        return Decimal(str(x).strip())
    except Exception:
        return None

def money_str(d):
    if d is None:
        return ""
    return f"{d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"

def clean_money_token(tok):
    # Remove currency symbols, commas, and stray text like "RM"
    tok = tok.replace("RM", "").replace(",", "").strip()
    # Accept forms like 120, 120.00, .50
    m = re.search(r"-?\d+(?:\.\d+)?", tok)
    return m.group(0) if m else tok

def normalize_token(tok):
    return tok.strip()

def split_full_text_lines(text):
    # Keep line breaks from OCR; strip trailing spaces
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines

def tokenize_line(line):
    # Split by whitespace while preserving tokens like x1, @, =
    return [normalize_token(t) for t in re.split(r"\s+", line) if t]

def looks_like_qty_price_row(tokens):
    # Heuristic: contains qty marker (x or X followed by digits) AND '@' AND '='
    has_qty = any(re.match(r"(?i)^x\d+$", t) for t in tokens)
    has_at = "@" in tokens
    has_eq = "=" in tokens
    # Allow minor variations (e.g., x 1 or x-1)
    if not has_qty:
        # Separate x and number
        try:
            for i, t in enumerate(tokens[:-1]):
                if t.lower() == "x" and re.match(r"^\d+$", tokens[i+1]):
                    has_qty = True
                    break
        except Exception:
            pass
    return has_qty and has_at and has_eq

def parse_item_from_combined_tokens(tokens):
    """
    Combined tokens: [code, desc..., xQTY, @, UNIT, =, TOTAL]
    """
    try:
        code = tokens[0]
        # Find indices
        qty_idx = None
        at_idx = None
        eq_idx = None

        for i, t in enumerate(tokens):
            if qty_idx is None and re.match(r"(?i)^x\d+$", t):
                qty_idx = i
            if at_idx is None and t == "@":
                at_idx = i
            if eq_idx is None and t == "=":
                eq_idx = i

        # Handle variant "x 1"
        if qty_idx is None:
            for i in range(len(tokens) - 1):
                if tokens[i].lower() == "x" and re.match(r"^\d+$", tokens[i+1]):
                    qty_idx = i

        if any(idx is None for idx in [qty_idx, at_idx, eq_idx]):
            raise ValueError("Missing qty/@/= markers")

        # Description spans after code up to qty marker
        desc_tokens = tokens[1:qty_idx]
        description = " ".join(desc_tokens).strip()

        # Quantity
        qty_token = tokens[qty_idx]
        quantity = None
        mqty = re.search(r"(?i)^x(\d+)$", qty_token)
        if mqty:
            quantity = mqty.group(1)
        else:
            # "x 1" form
            if tokens[qty_idx].lower() == "x" and re.match(r"^\d+$", tokens[qty_idx+1]):
                quantity = tokens[qty_idx+1]

        # Unit price and line total
        unit_price = clean_money_token(tokens[at_idx + 1]) if at_idx + 1 < len(tokens) else ""
        line_total = clean_money_token(tokens[eq_idx + 1]) if eq_idx + 1 < len(tokens) else ""

        return {
            "code": {"value": code, "source": "OCR"},
            "description": {"value": description, "source": "OCR"},
            "quantity": {"value": quantity or "", "source": "OCR"},
            "unit_price": {"value": unit_price, "source": "OCR"},
            "line_total": {"value": line_total, "source": "OCR"},
        }
    except Exception:
        return None

def parse_items_from_lines(lines):
    """
    Merge pairs of lines where the second line contains qty/price ('x', '@', '=').
    """
    items = []
    i = 0
    raw_rows = []
    while i < len(lines):
        line = lines[i]
        tokens = tokenize_line(line)
        # Look ahead for qty/price line
        if i + 1 < len(lines):
            next_tokens = tokenize_line(lines[i + 1])
        else:
            next_tokens = []

        if looks_like_qty_price_row(next_tokens):
            combined = tokens + next_tokens
            parsed = parse_item_from_combined_tokens(combined)
            if parsed:
                items.append(parsed)
                raw_rows.append({"row_1": line, "row_2": lines[i + 1]})
                i += 2
                continue

        # Fallback: single-line item (rare)
        parsed = parse_item_from_combined_tokens(tokens)
        if parsed:
            items.append(parsed)
            raw_rows.append({"row_1": line})
        else:
            raw_rows.append({"row_1": line})
        i += 1
    return items, raw_rows

# ---------- Merchant & totals extraction (regex heuristics) ----------
def extract_invoice_number(text):
    # Examples: BPP01/915522, INV-1234, 12345678
    patterns = [
        r"[A-Z]{2,}\d{2,}/\d{3,}",         # e.g., BPP01/915522
        r"INV[-\s]?\d{3,}",               # e.g., INV-12345
        r"\b\d{6,}\b",                    # long numeric sequences
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return None

def extract_date(text):
    # Try multiple date formats: DD/MM/YYYY, YYYY-MM-DD, DD-MM-YYYY
    patterns = [
        r"\b\d{2}/\d{2}/\d{4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{2}-\d{2}-\d{4}\b",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return None

def extract_payment_method_and_amount(text):
    # Payment methods seen on local receipts: VISA, MASTERCARD, HLB, FPX, CASH
    method_pattern = r"(MASTERCARD|MASTERONLINE|VISA|HLB|FPX|CASH|DEBIT|CREDIT)"
    amount_pattern = r"RM\s*\d+(?:\.\d+)?"
    # Heuristic: search near the bottom
    lines = split_full_text_lines(text)
    for ln in reversed(lines[-20:]):
        mth = re.search(method_pattern, ln, flags=re.IGNORECASE)
        amt = re.search(amount_pattern, ln, flags=re.IGNORECASE)
        if mth and amt:
            method = mth.group(1).upper()
            amount = clean_money_token(amt.group(0))
            return method, amount
    # Fallback: find any RM amount near bottom
    for ln in reversed(lines[-20:]):
        amt = re.search(amount_pattern, ln, flags=re.IGNORECASE)
        if amt:
            return None, clean_money_token(amt.group(0))
    return None, None

def extract_subtotal_tax_total(text):
    """
    Extract OCR 'Subtotal', 'Tax', 'Total/Grand Total' lines and numeric values.
    """
    def find_last(patterns):
        lines = split_full_text_lines(text)
        for ln in reversed(lines):
            for p in patterns:
                m = re.search(p, ln, flags=re.IGNORECASE)
                if m:
                    # capture amount anywhere in line (prefer 'RM')
                    amt = re.search(r"RM?\s*\-?\d+(?:\.\d+)?", ln, flags=re.IGNORECASE)
                    if amt:
                        return clean_money_token(amt.group(0))
        return None

    subtotal = find_last([r"subtotal", r"sub total"])
    tax = find_last([r"tax", r"sst", r"gst"])
    grand = find_last([r"grand total", r"total\s*$", r"total amount"])
    return subtotal, tax, grand

# ---------- Build JSON + compute totals ----------
lines = split_full_text_lines(full_text)
items, raw_rows = parse_items_from_lines(lines)

# Compute totals from items
computed_subtotal = None
if items:
    sum_total = Decimal("0.00")
    for it in items:
        lt = D(it["line_total"]["value"])
        if lt is not None:
            sum_total += lt
    computed_subtotal = sum_total

ocr_subtotal, ocr_tax, ocr_grand = extract_subtotal_tax_total(full_text)
payment_method, payment_amount = extract_payment_method_and_amount(full_text)

computed_tax = D(ocr_tax) if ocr_tax else Decimal("0.00")
computed_grand = None
if computed_subtotal is not None:
    computed_grand = (computed_subtotal + (computed_tax or Decimal("0.00"))).quantize(Decimal("0.01"))

# Rounding reconciliation: payment vs subtotal/grand
rounding_diff = None
if payment_amount and (computed_subtotal is not None):
    pa = D(payment_amount)
    if pa is not None:
        # Prefer comparing payment to OCR grand total if present, else computed grand/subtotal
        base_total = D(ocr_grand) or computed_grand or computed_subtotal
        if base_total is not None:
            rounding_diff = (pa - base_total).quantize(Decimal("0.01"))

# Validation flags with tolerance
TOL = Decimal("0.05")
subtotal_match = None
grand_match = None
payment_match = None

if ocr_subtotal and computed_subtotal is not None:
    subtotal_match = abs(D(ocr_subtotal) - computed_subtotal) <= TOL
if ocr_grand and computed_grand is not None:
    grand_match = abs(D(ocr_grand) - computed_grand) <= TOL
if payment_amount and computed_grand is not None:
    payment_match = abs(D(payment_amount) - computed_grand) <= TOL

# Merchant info (basic heuristics)
merchant_name = None
# Try first lines heuristics for merchant/store name (often in top 5 lines)
for ln in lines[:5]:
    if re.search(r"(watson|store|mart|sdn bhd|berhad|bhd|pharmacy)", ln, flags=re.IGNORECASE):
        merchant_name = ln
        break

merchant_info = {
    "name": {"value": merchant_name, "source": "OCR"},
    "address": {"value": None, "source": "OCR"},  # Address extraction can be added with patterns
    "date": {"value": extract_date(full_text), "source": "OCR"},
    "invoice_number": {"value": extract_invoice_number(full_text), "source": "OCR"},
    "payment_method": {"value": payment_method, "source": "OCR"},
}

# Structured JSON payload
structured = {
    "filename": uploaded_file.name,
    "merchant": merchant_info,
    "items": items,
    "totals": {
        "computed": {
            "subtotal": {"value": money_str(computed_subtotal) if computed_subtotal is not None else None, "source": "COMPUTED"},
            "tax": {"value": money_str(computed_tax) if computed_tax is not None else None, "source": "COMPUTED"},
            "grand_total": {"value": money_str(computed_grand) if computed_grand is not None else None, "source": "COMPUTED"},
        },
        "ocr": {
            "subtotal": {"value": ocr_subtotal, "source": "OCR"},
            "tax": {"value": ocr_tax, "source": "OCR"},
            "grand_total": {"value": ocr_grand, "source": "OCR"},
        },
        "payment": {
            "method": {"value": payment_method, "source": "OCR"},
            "amount_charged": {"value": payment_amount, "source": "OCR"},
        },
        "validation": {
            "tolerance": {"value": str(TOL), "source": "APP"},
            "subtotal_match": {"value": subtotal_match, "source": "APP"},
            "grand_total_match": {"value": grand_match, "source": "APP"},
            "payment_vs_grand_match": {"value": payment_match, "source": "APP"},
            "rounding_difference": {"value": money_str(rounding_diff) if rounding_diff is not None else None, "source": "APP"},
        },
        "raw_rows": raw_rows,  # for audit, not displayed to humans
    },
    "ocr_text": full_text,  # raw OCR text for audit
}

# ---------- Human-friendly display ----------
st.subheader("🏬 Merchant information")
for k in ["name", "date", "invoice_number", "payment_method"]:
    val = structured["merchant"][k]["value"]
    st.text(f"{k.replace('_',' ').title()}: {val if val else ''}")

# Line items table (pretty)
def items_to_dataframe(items):
    rows = []
    for it in items:
        rows.append({
            "Code": it.get("code", {}).get("value"),
            "Description": it.get("description", {}).get("value"),
            "Quantity": it.get("quantity", {}).get("value"),
            "Unit Price": it.get("unit_price", {}).get("value"),
            "Line Total": it.get("line_total", {}).get("value"),
        })
    return pd.DataFrame(rows)

df = items_to_dataframe(structured["items"])
st.subheader("🧾 Line items")
if len(df) == 0:
    st.warning("No line items parsed. Review the raw OCR text or adjust parsing heuristics.")
else:
    st.table(df)

# Totals with verification badges
st.subheader("💰 Totals")
computed = structured["totals"]["computed"]
ocr = structured["totals"]["ocr"]
payment = structured["totals"]["payment"]
valid = structured["totals"]["validation"]

def badge(label, ok):
    if ok is None:
        st.markdown(f"- **{label}:** Unknown")
        return
    color = "green" if ok else "red"
    status = "Verified" if ok else "Mismatch"
    st.markdown(f"- **{label}:** <span style='color:{color}'>{status}</span>", unsafe_allow_html=True)

st.text(f"Subtotal (computed): RM {computed['subtotal']['value'] or ''}")
st.text(f"Tax (computed): RM {computed['tax']['value'] or ''}")
st.text(f"Grand total (computed): RM {computed['grand_total']['value'] or ''}")
st.text(f"Subtotal (OCR): RM {ocr['subtotal']['value'] or ''}")
st.text(f"Grand total (OCR): RM {ocr['grand_total']['value'] or ''}")
st.text(f"Amount charged: RM {payment['amount_charged']['value'] or ''} ({payment['method']['value'] or ''})")

badge("Subtotal match", valid["subtotal_match"]["value"])
badge("Grand total match", valid["grand_total_match"]["value"])
badge("Payment vs grand match", valid["payment_vs_grand_match"]["value"])
st.text(f"Rounding difference: RM {valid['rounding_difference']['value'] or '0.00'} (tolerance ±{valid['tolerance']['value']})")

# ---------- Audit downloads ----------
st.subheader("📂 Audit downloads")
st.download_button(
    "Download raw OCR text",
    data=structured["ocr_text"],
    file_name="ocr_raw.txt",
    mime="text/plain"
)
st.download_button(
    "Download structured JSON",
    data=json.dumps(structured, indent=2),
    file_name="vision_receipt.json",
    mime="application/json"
)
st.download_button(
    "Download original receipt",
    data=file_bytes,
    file_name=uploaded_file.name,
    mime="application/pdf" if file_ext == "pdf" else f"image/{file_ext}"
)

# Optional: expandable audit of raw rows
with st.expander("🔎 Raw OCR rows (for audit)"):
    for i, rr in enumerate(structured["totals"]["raw_rows"], start=1):
        if "row_2" in rr:
            st.text(f"Row {i}a: {rr['row_1']}")
            st.text(f"Row {i}b: {rr['row_2']}")
        else:
            st.text(f"Row {i}: {rr['row_1']}")

# ---------- Error footer ----------
st.caption("This app preserves raw OCR, structured JSON, and the original image/PDF for audit-grade traceability. "
           "Computed totals are authoritative; OCR totals are retained for comparison and reconciliation.")
