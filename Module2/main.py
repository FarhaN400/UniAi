import os
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient
from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace
from ocr import ocr_extract_pdf
from prompt import notice_extraction_prompt as prompt, parser

load_dotenv()

# --- 1. MongoDB Connection ---
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["university_assistant"]
collection = db["university_documents"]

# --- 2. Existing LLM Chain ---
llm = HuggingFaceEndpoint(
    repo_id='openai/gpt-oss-120b',
    task="text-generation"
)
model = ChatHuggingFace(llm=llm)
chain = prompt | model | parser

# --- Helper: Download PDF to a temporary path ---
def download_pdf(url, save_path="temp_notice.pdf"):
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    with open(save_path, "wb") as f:
        f.write(response.content)
    return save_path

# --- Step 8 & 9: Batch Processing Pipeline with Safe Error Handling ---
def process_new_notices(limit=None):
    """
    Finds all notices with status == 'new', downloads and OCRs each PDF,
    extracts structured data via LLM, and updates MongoDB.
    Errors on any notice are caught safely so the rest of the batch continues.
    """
    query = {"status": "new"}
    cursor = collection.find(query)
    if limit:
        cursor = cursor.limit(limit)

    new_notices = list(cursor)
    total = len(new_notices)

    if total == 0:
        print("No notices with status 'new' found in MongoDB. Everything is up to date!")
        return

    print("=" * 55)
    print(f" Starting Batch Pipeline: {total} new notice(s) to process")
    print("=" * 55)

    success_count = 0
    failed_count = 0

    for index, notice in enumerate(new_notices, start=1):
        notice_id = notice.get("notice_id")
        title = notice.get("title", "Untitled Notice")
        pdf_url = notice.get("url")

        print(f"\n[{index}/{total}] Processing: {title[:70]}...")
        print(f"  Notice ID : {notice_id}")
        print(f"  URL       : {pdf_url}")

        temp_pdf_path = f"temp_{notice_id[:8]}.pdf"

        # Step 9: Individual notice error handling (one failure does NOT stop the batch)
        try:
            # Step 2: Download PDF
            download_pdf(pdf_url, temp_pdf_path)
            file_size_kb = os.path.getsize(temp_pdf_path) / 1024
            print(f"  -> Downloaded ({file_size_kb:.1f} KB)")

            # Step 3: OCR Extraction
            docs = ocr_extract_pdf(temp_pdf_path)
            if not docs or not docs.strip():
                raise ValueError("OCR extracted empty text from PDF")
            print(f"  -> OCR completed ({len(docs)} characters)")

            # Step 4: LLM Structured Extraction
            structured_data = chain.invoke({"text": docs})
            print(f"  -> LLM structured extraction successful")

            # Step 6 & 7: Update document in MongoDB and mark status='processed'
            collection.update_one(
                {"notice_id": notice_id},
                {
                    "$set": {
                        "raw_text": docs,
                        "structured_data": structured_data,
                        "status": "processed",
                        "processed_at": datetime.now(timezone.utc)
                    }
                }
            )

            success_count += 1
            print(f"  -> SUCCESS: Status changed to 'processed'.")

        except Exception as error:
            failed_count += 1
            print(f"  -> ERROR: Failed to process notice.")
            print(f"     Reason: {error}")
            print(f"     Status remains 'new' (will not be marked 'processed').")

        finally:
            # Step 9: Guarantee temporary PDF deletion from disk
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)

    print("\n" + "=" * 55)
    print(" Batch Pipeline Summary")
    print(f" Total Checked : {total}")
    print(f" Succeeded     : {success_count} (marked 'processed')")
    print(f" Failed        : {failed_count} (remain 'new')")
    print("=" * 55)


if __name__ == "__main__":
    process_new_notices()