# Module 1 — Portal Monitoring: Revision Cheat Sheet

## What Module 1 does (one line)
Automatically detects new notices on the university portal, without any manual upload — hands new documents off to Module 2.

## Status at a glance

| Step | Task | Status |
|---|---|---|
| 1 | Fetch portal HTML | ✅ Done |
| 2 | Identify notice HTML structure | ✅ Done |
| 3 | Extract title + PDF URL | ✅ Done |
| 4 | Build structured notice list | ✅ Done |
| 5 | Generate unique notice ID (hash) | ✅ Done |
| 6 | Store in MongoDB | ✅ Done (script written) |
| 7 | Compare old vs new | ✅ Done (script written) |
| 8 | Detect new/modified notices | ✅ Done (via upsert logic) |
| 9 | Manual two-run test | ✅ Done |
| 10 | Add scheduler (every 30 min) | ⬜ Upcoming — last step |

---

## Site investigation — what we learned

| Site tried | Result | Tool needed |
|---|---|---|
| `makautexam.net` | ✅ Real notices, plain `<a>` tags | `requests` + `BeautifulSoup` |
| `www.makautwb.ac.in` (root) | ❌ Only placeholder "Event heading" text | JS-rendered — needs Selenium/API |
| `makautwb.ac.in/page.php?id=340` | ✅ ~187 real notices, server-rendered | `requests` + `BeautifulSoup` |

**Key lesson:** always check "view page source" first — if notice titles/links are visible in raw HTML, you don't need Selenium. Only reach for a headless browser if content is genuinely missing from the raw HTML (confirmed by testing, not assumed).

**Final chosen source:** `https://makautwb.ac.in/page.php?id=340`

---

## Confirmed HTML pattern for our target page

```html
<a class="text-danger" href="datas/users/0-file.pdf">
    <font color="blue">Notice title text</font>
</a>
&nbsp;
<img src="images/new-08-june.gif" border="0">
<br/><br/>
```

- Real notices always have `class="text-danger"` on the `<a>` tag — this is the reliable selector.
- URLs appear in 3 different forms: relative, differently-relative, and already-absolute. Handle all three with `urljoin`.
- No per-notice date exists in the HTML — only a page-level "Last Updated" timestamp at the bottom.
- A "NEW" badge `<img>` sometimes follows a notice — free bonus signal, not required for detection.

---

## Core concepts — quick recall

### `urljoin(base, href)`
Resolves relative/absolute URLs correctly, like a browser would. Avoids manual `if href.startswith("http")` bugs (double slashes, missing prefixes, etc).

```python
urljoin("https://site.com/", "folder/file.pdf")
# → "https://site.com/folder/file.pdf"
```

### `find_next_sibling("img")`
Looks only at the *next tag at the same nesting level* — not the whole document. Used to detect the "NEW" badge image right after a notice link.

### Hashing for unique IDs
```python
hashlib.sha256(url.encode()).hexdigest()
```
- `.encode()` — hash functions need bytes, not strings.
- Same input → same hash, every time (deterministic). This is what makes "have I seen this before?" checks possible.
- Used as `notice_id`, the primary key for detection.

### Idempotency (important concept)
A system is **idempotent** if running it multiple times produces the same end result as running it once. A 30-minute unattended monitor **must** be idempotent, or it silently corrupts data (duplicate inserts) over time.

### Upsert + unique index (how we guarantee idempotency)
```python
notices_collection.create_index("notice_id", unique=True)

result = notices_collection.update_one(
    {"notice_id": notice["notice_id"]},
    {"$setOnInsert": notice},
    upsert=True
)
```
- `upsert=True` → insert if not found, otherwise touch nothing.
- `$setOnInsert` → only writes fields on a **new** insert; existing documents are left untouched (so `detected_at` doesn't get reset every time an old notice is re-scraped).
- The **unique index** is a database-level safety net — even a buggy script physically cannot insert a duplicate `notice_id`.

### Why store timestamps in UTC, not IST
- UTC is unambiguous regardless of server/machine location.
- Convert to IST only when **displaying** to a human, not when storing.
```python
from zoneinfo import ZoneInfo
ist_time = utc_dt.astimezone(ZoneInfo("Asia/Kolkata"))
```
- India = UTC+5:30, no daylight saving, single time zone nationwide.

---

## Full working script (as of now)

```python
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import hashlib
from pymongo import MongoClient
from datetime import datetime, timezone

BASE_URL = "https://makautwb.ac.in/"
NOTICE_PAGE = "https://makautwb.ac.in/page.php?id=340"

MONGO_URI = "mongodb://localhost:27017"
client = MongoClient(MONGO_URI)
db = client["university_assistant"]
notices_collection = db["university_documents"]
notices_collection.create_index("notice_id", unique=True)


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


def store_notice(notice):
    notice["detected_at"] = datetime.now(timezone.utc)
    notice["status"] = "new"

    result = notices_collection.update_one(
        {"notice_id": notice["notice_id"]},
        {"$setOnInsert": notice},
        upsert=True
    )
    return result.upserted_id is not None


def run_monitor_cycle():
    print("Checking university portal...\n")

    scraped_notices = get_makautwb_notices()
    scraped_notices = [add_notice_id(n) for n in scraped_notices]

    new_count = 0
    new_notices = []

    for notice in scraped_notices:
        if store_notice(notice):
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
```

---

## Validation checklist — do this before adding the scheduler

- [ ] `pip install requests beautifulsoup4 lxml pymongo`
- [ ] MongoDB is running (local or Atlas connection string set)
- [ ] Run script once → expect **all notices marked new** (first run, empty DB)
- [ ] Run script again, nothing changed on site → expect **0 new notices**
- [ ] Spot-check 2–3 `notice_id` values are identical across both runs (proves hashing is deterministic)
- [ ] Only after both checks pass → move to Step 10 (scheduler)

---

## What's NOT built yet (don't jump ahead)

- ❌ Scheduler (`APScheduler` / `cron`) — deliberately last, so bugs are visible when run manually first
- ❌ Module 2 (downloading the actual PDF once a notice is flagged new)
- ❌ Any PDF text extraction, chunking, or embeddings — that's Module 3 and 4
- ❌ Selenium / dynamic scraping — only needed if you later decide to also monitor `makautwb.ac.in` root site (JS-rendered), which is a stretch goal, not required for MVP

---

## One-sentence summary for your professor

> "Module 1 uses `requests` and `BeautifulSoup` to scrape the university's notice page, hashes each notice's URL into a unique ID, and stores it in MongoDB using an upsert with a unique index — guaranteeing idempotency so the same notice is never processed twice, even if the monitor runs unattended for weeks."
