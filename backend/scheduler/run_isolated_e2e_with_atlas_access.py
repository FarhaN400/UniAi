"""Run the Phase 5 isolated test behind temporary Atlas IP authorization.

Does NOT execute the normal production notice sync; all notice records and
Pinecone vectors written by the called test use temporary locations.
"""
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

from run_with_atlas_access import (
    API, EXPIRY_MINUTES, already_authorized, api_call,
    oauth_token, runner_public_ipv4, wait_for_mongo,
)


def main():
    project = os.getenv('ATLAS_PROJECT_ID', '')
    client_id = os.getenv('ATLAS_CLIENT_ID', '')
    client_secret = os.getenv('ATLAS_CLIENT_SECRET', '')
    mongo_uri = os.getenv('MONGO_URI', '')

    if not re.fullmatch(r'[a-f0-9]{24}', project):
        print('FAIL: ATLAS_PROJECT_ID repository variable missing or invalid', flush=True)
        return 1
    if not all((client_id, client_secret, mongo_uri)):
        print('FAIL: Missing Atlas credentials or MongoDB URI', flush=True)
        return 1

    access_list_url = API + f'/api/atlas/v2/groups/{project}/accessList'
    created_by_this_job = False
    token = None
    ip = None
    exit_code = 1
    try:
        token = oauth_token(client_id, client_secret)
        print('PASS: Atlas OAuth authentication', flush=True)
        ip = runner_public_ipv4()
        print('PASS: GitHub runner public IPv4 discovered', flush=True)
        entries = api_call(
            access_list_url + '?itemsPerPage=500', token=token,
        ).get('results', [])
        if already_authorized(entries, ip):
            print('INFO: GitHub runner IP already permitted; not adding or removing it', flush=True)
        else:
            expires = (datetime.now(timezone.utc) + timedelta(
                minutes=EXPIRY_MINUTES
            )).strftime('%Y-%m-%dT%H:%M:%SZ')
            api_call(
                access_list_url,
                method='POST',
                token=token,
                data=[{
                    'ipAddress': ip,
                    'comment': 'UniAI GitHub Actions isolated Phase 5 E2E test',
                    'deleteAfterDate': expires,
                }],
            )
            created_by_this_job = True
            print('PASS: Temporary Atlas IP authorization created', flush=True)

        wait_for_mongo(mongo_uri)
        print('[Phase5] Starting ISOLATED cloud E2E ingestion test...', flush=True)
        exit_code = subprocess.call([
            sys.executable,
            'backend/scheduler/phase5_isolated_e2e_test.py',
        ])
        if exit_code:
            print(f'FAIL: Isolated test exited with code {exit_code}', flush=True)
    except urllib.error.HTTPError as exc:
        print(f'FAIL: Atlas API HTTP {exc.code}', file=sys.stderr, flush=True)
        exit_code = 1
    except Exception as exc:
        print(f'FAIL: Isolated test setup ({type(exc).__name__}): {exc}',
              file=sys.stderr, flush=True)
        exit_code = 1
    finally:
        if created_by_this_job and token and ip:
            try:
                api_call(
                    access_list_url + '/' + urllib.parse.quote(ip, safe=''),
                    method='DELETE', token=token,
                )
                print('PASS: Temporary GitHub runner IP removed', flush=True)
            except Exception as exc:
                print('WARNING: Atlas runner IP cleanup failed; it should expire '
                      f'within {EXPIRY_MINUTES} minutes '
                      f'({type(exc).__name__})', file=sys.stderr, flush=True)
                exit_code = 1
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
