import streamlit as st
import os
import json
import re
from datetime import datetime, timezone
from PIL import Image
import pytesseract

# --- Token-based access ---
token_map = {f"{i:02}": f"{i:02}" for i in range(1, 100)}
upload_token = st.query_params.get("token", "")
tag_id = token_map.get(upload_token)
if not tag_id:
    st.error("❌ Invalid or missing upload token.")
    st.stop()

now = datetime.now(timezone.utc)
base_folder = f"data/{tag_id}/"

# --- UI ---
st.title("📸 Smart Insurance Parser")
st.caption(f"Logged in as: `{tag_id}`")
uploaded_file = st.file_uploader("Upload insurance photo (JPG/PNG)", type=["jpg", "jpeg", "png"])
submit = st.button("📤 Upload & Parse")

# --- OCR + Smart Field Extraction ---
def extract_fields(text):
    fields = {}

    # Policy number
    policy_match = re.search(r"Policy\s*(?:Number|No)?[:\s]*([A-Z0-9\-]+)", text, re.IGNORECASE)
    if policy_match:
        fields["policy_no"] = policy_match.group(1)

    # Coverage dates
    date_range = re.search(r"Period\s*of\s*Insurance[:\s]*(\d{1,2}\s*\w+\s*\d{4})\s*to\s*(\d{1,2}\s*\w+\s*\d{4})", text, re.IGNORECASE)
    if date_range:
        try:
            fields["start"] = str(datetime.strptime(date_range.group(1), "%d %B %Y").date())
            fields["end"] = str(datetime.strptime(date_range.group(2), "%d %B %Y").date())
        except:
            fields["start"] = date_range.group(1)
            fields["end"] = date_range.group(2)

    # Vehicle make/model
    vehicle_match = re.search(r"(?:Make\s*and\s*Model|Vehicle)\s*[:\s]*(.+?)\n", text, re.IGNORECASE)
    if vehicle_match:
        fields["vehicle"] = vehicle_match.group(1).strip()

    # Plate number (e.g. ZZY123)
    plate_match = re.search(r"\b[A-Z]{2,3}\d{3,4}\b", text)
    if plate_match:
        fields["plate_no"] = plate_match.group(0)

    # Insurer detection
    if "Coles Car Insurance" in text:
        fields["insurer"] = "Coles"
    elif "AAMI" in text:
        fields["insurer"] = "AAMI"
    else:
        insurer_match = re.search(r"Insurer\s*[:\s]*(.+?)\n", text, re.IGNORECASE)
        if insurer_match:
            fields["insurer"] = insurer_match.group(1).strip()

    return fields

# --- Save + Parse ---
if submit and uploaded_file:
    image = Image.open(uploaded_file)
    text = pytesseract.image_to_string(image)
    fields = extract_fields(text)

    vehicle_id = fields.get("plate_no", fields.get("vehicle", "UnknownVehicle")).replace(" ", "_")
    folder_path = os.path.join(base_folder, "Car", vehicle_id)
    os.makedirs(folder_path, exist_ok=True)

    file_path = os.path.join(folder_path, uploaded_file.name)
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    metadata_path = os.path.join(folder_path, "metadata.json")
    if os.path.exists(metadata_path):
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
    else:
        metadata = {}

    metadata["insurance"] = {
        "policy_no": fields.get("policy_no", "Unknown"),
        "start": fields.get("start", "Unknown"),
        "end": fields.get("end", "Unknown"),
        "vehicle": fields.get("vehicle", "Unknown"),
        "plate_no": fields.get("plate_no", "Unknown"),
        "insurer": fields.get("insurer", "Unknown"),
        "reminder_set": True
    }

    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    st.success(f"✅ Parsed and saved for `{vehicle_id}`")
    st.write("**Extracted Fields:**")
    st.json(metadata["insurance"])

elif submit and not uploaded_file:
    st.error("Please upload a photo of the insurance document.")
