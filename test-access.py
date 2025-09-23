from google.cloud import documentai_v1beta3 as documentai
from google.api_core.client_options import ClientOptions
import pandas as pd
import os

# --- Configuration ---
project_id = "malaysia-receipt-saas"
location = "us"
processor_id = "8fb44aee4495bb0f"
file_path = "MengKee.jpg"
mime_type = "image/jpeg"

# --- Set credential path programmatically ---
credential_path = "/home/melvinchia8/gcs-mount/malaysia-receipt-saas-3cb987586941.json"
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credential_path

# --- Verify authentication ---
if not os.path.exists(credential_path):
    print(f"❌ Credential file not found at: {credential_path}")
    exit()
else:
    print(f"✅ Using credentials from: {credential_path}")

def process_receipt():
    client_options = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    client = documentai.DocumentProcessorServiceClient(client_options=client_options)

    processor_path = f"projects/{project_id}/locations/{location}/processors/{processor_id}"

    try:
        with open(file_path, "rb") as image:
            image_content = image.read()
    except FileNotFoundError:
        print(f"❌ File not found at {file_path}")
        return

    raw_document = documentai.RawDocument(content=image_content, mime_type=mime_type)
    request = documentai.ProcessRequest(name=processor_path, raw_document=raw_document)

    try:
        result = client.process_document(request=request)
        document = result.document
        print("✅ Document processed successfully.\n")
    except Exception as e:
        print(f"❌ Error during processing: {e}")
        return

    # --- Print full extracted text ---
    print("📄 Full Extracted Text:\n")
    print(document.text)

    # --- Format entities into a table ---
    print("\n📊 Extracted Entities Table:\n")
    rows = []
    for entity in document.entities:
        text_value = entity.text_anchor.content or entity.mention_text
        confidence = f"{entity.confidence:.1%}"
        normalized = (
            entity.normalized_value.text
            if entity.normalized_value and entity.normalized_value.text
            else str(entity.normalized_value.date_value)
            if entity.normalized_value and hasattr(entity.normalized_value, "date_value")
            else "N/A"
        )
        rows.append({
            "Type": entity.type_,
            "Value": text_value,
            "Confidence": confidence,
            "Normalized": normalized
        })

    df = pd.DataFrame(rows)
    print(df.to_string(index=False))

if __name__ == "__main__":
    process_receipt()
