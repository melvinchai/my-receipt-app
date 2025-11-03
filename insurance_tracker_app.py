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
st.title("📁 Insurance Document Tracker")
st.caption(f"Logged in as: `{tag_id}`")

category = "Car"
subtag = st.text_input("Enter vehicle number (e.g. XYZ123)", placeholder="e.g. XYZ123")
uploaded_file = st.file_uploader("Upload insurance letter (image or PDF)", type=["jpg", "jpeg", "png"])
submit = st.button("📤 Upload & Parse")

# --- OCR + Parser ---
def extract_fields_from_text(text):
    fields = {}
    policy_match = re.search(r"Policy\s*No[:\s]*([A-Z0-9]+)", text)
    start_match = re.search(r"from\s*(\d{1,2}\s*\w+\s*\d{4})", text, re.IGNORECASE)
    end_match = re.search(r"to\s*(\d{1,2}\s*\w+\s*\d{4})", text, re.IGNORECASE)
    vehicle_match = re.search(r"Vehicle\s*No[:\s]*([A-Z0-9]+)", text)

    if policy_match:
        fields["policy_no"] = policy_match.group(1)
    if start_match:
        fields["start"] = str(datetime.strptime(start_match.group(1), "%d %b %Y").date())
    if end_match:
        fields["end"] = str(datetime.strptime(end_match.group(1), "%d %b %Y").date())
    if vehicle_match:
        fields["vehicle_no"] = vehicle_match.group(1)

    return fields

# --- Save + Parse ---
if submit and uploaded_file and subtag:
    folder_path = os.path.join(base_folder, category, subtag)
    os.makedirs(folder_path, exist_ok=True)

    file_path = os.path.join(folder_path, uploaded_file.name)
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    image = Image.open(uploaded_file)
    text = pytesseract.image_to_string(image)
    fields = extract_fields_from_text(text)

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
        "vehicle_no": fields.get("vehicle_no", subtag),
        "reminder_set": True
    }

    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    st.success(f"✅ Document saved and parsed for `{subtag}`")
    st.write("**Extracted Fields:**")
    st.json(metadata["insurance"])

elif submit and not uploaded_file:
    st.error("Please upload a document.")
elif submit and not subtag:
    st.error("Please enter a vehicle number.")
