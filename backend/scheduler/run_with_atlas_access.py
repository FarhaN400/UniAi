"""Run UniAI sync with temporary MongoDB Atlas IP access.

Requires:
  ATLAS_CLIENT_ID, ATLAS_CLIENT_SECRET, ATLAS_PROJECT_ID, MONGO_URI

Runs:
  python backend/scheduler/run_with_atlas_access.py

Only removes a database network entry if this job created it.
Temporary entries automatically expire after 60 minutes.
"""
import base64
import ipaddress
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

API = "https://cloud.mongodb.com"
ACCEPT = "application/vnd.atlas.2025-03-12+json"
EXPIRY_MINUTES = 60
PING_ATTEMPTS = 6
PING_WAIT_SECONDS = 10


def api_call(url, *, method="GET", token, data=None):
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": ACCEPT,
        "User-Agent": "UniAI-Notice-Sync",
    }
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}


def oauth_token(client_id, secret):
    credentials = base64.b64encode((client_id + ":" + secret).encode()).decode()
    request = urllib.request.Request(
        API + "/api/oauth/token",
        data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
        headers={
            "Authorization": "Basic " + credentials,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["access_token"]


def runner_public_ipv4():
    req = urllib.request.Request(
        "https://api.ipify.org?format=json",
        headers={"User-Agent": "UniAI-Notice-Sync"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        ip = ipaddress.IPv4Address(json.load(response)["ip"])
    if not ip.is_global:
        raise ValueError("Runner does not have a globally routable IPv4 address")
    return str(ip)


def already_authorized(entries, ip):
    address = ipaddress.ip_address(ip)
    for entry in entries:
        try:
            value = entry.get("cidrBlock") or entry.get("ipAddress")
            if value and address in ipaddress.ip_network(value, strict=False):
                return True
        except ValueError:
            continue
    return False


def wait_for_mongo(mongo_uri):
    for attempt in range(1, PING_ATTEMPTS + 1):
        try:
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=12000)
            try:
                client.admin.command("ping")
            finally:
                client.close()
            print("PASS: MongoDB connectivity from GitHub runner", flush=True)
            return
        except Exception as exc:
            print(f"Atlas network propagation {attempt}/{PING_ATTEMPTS}: "
                  f"{type(exc).__name__}", flush=True)
            if attempt == PING_ATTEMPTS:
                raise RuntimeError("MongoDB ping failed after retries") from None
            time.sleep(PING_WAIT_SECONDS)


def main():
    project = os.getenv("ATLAS_PROJECT_ID", "")
    client_id = os.getenv("ATLAS_CLIENT_ID", "")
    secret = os.getenv("ATLAS_CLIENT_SECRET", "")
    mongo_uri = os.getenv("MONGO_URI", "")

    if not re.fullmatch(r"[a-f0-9]{24}", project):
        print("FAIL: ATLAS_PROJECT_ID repository variable is missing or invalid")
        return 1
    if not all([client_id, secret, mongo_uri]):
        print("FAIL: Missing Atlas or MongoDB GitHub secret")
        return 1

    created = False
    token = None
    ip = None
    url = API + f"/api/atlas/v2/groups/{project}/accessList"
    result_code = 1

    try:
        token = oauth_token(client_id, secret)
        print("PASS: Atlas OAuth authentication", flush=True)
        ip = runner_public_ipv4()
        print("PASS: Runner public IPv4 discovered", flush=True)

        entries = api_call(url + "?itemsPerPage=500", token=token).get("results", [])
        if already_authorized(entries, ip):
            print("INFO: Runner IP already permitted; not creating an entry", flush=True)
        else:
            expires = (datetime.now(timezone.utc) + timedelta(
                minutes=EXPIRY_MINUTES
            )).strftime("%Y-%m-%dT%H:%M:%SZ")
            api_call(
                url, method="POST", token=token,
                data=[{
                    "ipAddress": ip,
                    "comment": "UniAI GitHub Actions temporary scheduler access",
                    "deleteAfterDate": expires,
                }],
            )
            created = True
            print("PASS: Temporary Atlas IP authorization created", flush=True)

        wait_for_mongo(mongo_uri)
        print("[Phase5] Starting cloud notice sync...", flush=True)
        result_code = subprocess.call(
            [sys.executable, "backend/scheduler/sync_notices.py"]
        )
        if result_code:
            print(f"[Phase5] Scheduler exited with code {result_code}", flush=True)
    except urllib.error.HTTPError as exc:
        print(f"FAIL: Atlas API returned HTTP {exc.code}", file=sys.stderr, flush=True)
        result_code = 1
    except Exception as exc:
        print(f"FAIL: Cloud sync setup ({type(exc).__name__}): {exc}",
              file=sys.stderr, flush=True)
        result_code = 1
    finally:
        if created and token and ip:
            try:
                encoded_ip = urllib.parse.quote(ip, safe="")
                api_call(url + "/" + encoded_ip, method="DELETE", token=token)
                print("PASS: Temporary runner IP removed", flush=True)
            except Exception as exc:
                print(f"WARNING: IP cleanup failed ({type(exc).__name__}); "
                      f"Atlas should expire this entry within {EXPIRY_MINUTES} minutes",
                      file=sys.stderr, flush=True)
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
