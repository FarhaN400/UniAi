import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import hashlib
from pymongo import MongoClient 
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://makautwb.ac.in/"
NOTICE_PAGE = "https://makautwb.ac.in/page.php?id=340"

# --- MongoDB connection ---
# Local MongoDB (default):
MONGO_URI = os.getenv("MONGO_URI")

client = MongoClient(MONGO_URI)
db = client["university_assistant"]
notices_collection = db["university_documents"]

# Ensure notice_id is unique — MongoDB itself will now refuse duplicate inserts
notices_collection.create_index("notice_id", unique=True)

# --- Step 1-5: extraction  ---

def get_makautwb_notices():
    resp = requests.get(NOTICE_PAGE, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    notices = []
    for a in soup.select("a.text-danger[href]"):
        title = a.get_text(strip=True)
        href = a["href"]
        full_url = urljoin(BASE_URL, href)

        is_new = False
        next_img = a.find_next_sibling("img")
        if next_img and "new-08-june" in next_img.get("src", ""):
            is_new = True

        notices.append({
            "title": title,
            "url": full_url,
            "flagged_new_on_site": is_new
        })

    return notices


def add_notice_id(notice):
    notice["notice_id"] = hashlib.sha256(notice["url"].encode()).hexdigest()
    return notice


# --- Step 6: store in MongoDB ---

def store_notice(notice):
    """
    Upsert = insert if new, do nothing if already exists (matched by notice_id).
    Returns True if this was a genuinely NEW notice, False if it already existed.
    """
    notice["detected_at"] = datetime.now(timezone.utc)
    notice["status"] = "new"

    result = notices_collection.update_one(
        {"notice_id": notice["notice_id"]},   # match condition
        {"$setOnInsert": notice},              # only applied if inserting, not if updating
        upsert=True
    )

    # If a new document was inserted, MongoDB gives us its upserted_id.
    # If the document already existed, upserted_id is None.
    return result.upserted_id is not None


# --- Step 7: compare + report ---

def run_monitor_cycle():
    print("Checking university portal...\n")

    scraped_notices = get_makautwb_notices()
    scraped_notices = [add_notice_id(n) for n in scraped_notices]

    new_count = 0
    new_notices = []

    for notice in scraped_notices:
        is_new = store_notice(notice)
        if is_new:
            new_count += 1
            new_notices.append(notice)

    total_found = len(scraped_notices)
    existing_count = total_found - new_count

    print(f"Found {total_found} notices on the page.")
    print(f"Existing notices: {existing_count}")
    print(f"New notices: {new_count}\n")

    if new_notices:
        print("NEW:")
        for n in new_notices:
            print(f"- {n['title']}")
            print(f"  {n['url']}")
    else:
        print("No new notices this run.")


if __name__ == "__main__":
    run_monitor_cycle()