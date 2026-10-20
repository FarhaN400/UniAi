"""Isolated Phase 5 full-pipeline test. Run from backend/ after copying to scheduler/."""
import os
import sys
import time
import uuid
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))
os.environ['LLM_PROVIDER'] = 'groq'
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / 'Module2'))

TARGET_URL = ('https://makautwb.ac.in/datas/users/'
              '0-in-house%20b.%20tech%20decentralize%20notice%202026.pdf')


def main():
    for key in ('MONGO_URI', 'GROQ_API_KEY', 'PINECONE_API_KEY'):
        if not os.environ.get(key):
            raise RuntimeError(f'{key} missing in environment')

    from Module1 import scrapper as scraper
    from Module2 import main as extractor
    from Module3 import main as indexer

    suffix = uuid.uuid4().hex[:12]
    database_name = f'uniai_phase5_e2e_{suffix}'
    namespace = f'phase5-e2e-{suffix}'
    assert database_name != 'university_assistant' and namespace != 'notices'
    test_collection = scraper.client[database_name]['notices']
    original = (scraper.notices_collection, extractor.collection,
                indexer.notices_collection, indexer.NAMESPACE)
    notice_id = None
    cleanup_errors = []

    try:
        test_collection.create_index('notice_id', unique=True)
        scraper.notices_collection = test_collection
        extractor.collection = test_collection
        indexer.notices_collection = test_collection
        indexer.NAMESPACE = namespace

        print('--- PHASE 5 ISOLATED FULL PIPELINE TEST ---', flush=True)
        print('Staging MongoDB:', database_name, flush=True)
        print('Staging Pinecone namespace:', namespace, flush=True)

        print('\n1. Scrape MAKAUT and insert one notice in staging...', flush=True)
        candidates = scraper.get_makautwb_notices()
        notice = next((n for n in candidates if n['url'] == TARGET_URL), None)
        if notice is None:
            raise RuntimeError('Expected official test PDF not present on MAKAUT page')
        assert scraper.store_notice(notice), 'New notice not inserted into staging'
        assert not scraper.store_notice(notice), 'Duplicate notice was inserted'
        row = test_collection.find_one({'url': TARGET_URL})
        assert row and row['status'] == 'new'
        notice_id = row['notice_id']
        print('PASS: Scraper -> MongoDB staging, duplicate detection', flush=True)

        print('\n2. Process PDF and extract structured data using Groq...', flush=True)
        summary = extractor.process_new_notices(limit=1)
        assert summary['selected'] == 1 and summary['processed'] == 1, summary
        row = test_collection.find_one({'notice_id': notice_id})
        assert row['status'] == 'processed' and row.get('raw_text') and row.get('pdf_sha256')
        dates = (row.get('structured_data') or {}).get('important_dates') or {}
        assert dates.get('last_date') == '27-10-2026', dates
        print('PASS: PDF -> extraction -> Groq -> structured JSON -> MongoDB', flush=True)

        print('\n3. Index in an isolated Pinecone namespace...', flush=True)
        indexed, failed = indexer.index_all_processed_notices(limit=1)
        assert (indexed, failed) == (1, 0), (indexed, failed)
        assert test_collection.find_one({'notice_id': notice_id})['pinecone_indexed'] is True
        for _ in range(10):
            response = indexer.index.fetch(ids=[notice_id], namespace=namespace)
            if notice_id in (response.vectors or {}):
                print('PASS: Pinecone vector upserted and fetched from staging', flush=True)
                break
            time.sleep(2)
        else:
            raise RuntimeError('New vector was not fetchable from test namespace')

        print('\nPASS: COMPLETE ISOLATED E2E INGESTION', flush=True)
    finally:
        print('\n--- TEST CLEANUP ---', flush=True)
        if notice_id:
            try:
                indexer.index.delete(ids=[notice_id], namespace=namespace)
                print('PASS: Temporary Pinecone vector deletion requested', flush=True)
            except Exception as exc:
                cleanup_errors.append('Pinecone ' + type(exc).__name__)
                print('WARNING: Pinecone cleanup failed:', type(exc).__name__, flush=True)
        try:
            scraper.client.drop_database(database_name)
            print('PASS: Temporary MongoDB database deleted', flush=True)
        except Exception as exc:
            cleanup_errors.append('MongoDB ' + type(exc).__name__)
            print('WARNING: MongoDB cleanup failed:', type(exc).__name__, flush=True)
        scraper.notices_collection, extractor.collection, \
            indexer.notices_collection, indexer.NAMESPACE = original
        if cleanup_errors and sys.exc_info()[0] is None:
            raise RuntimeError('Test cleanup incomplete: ' + ', '.join(cleanup_errors))


if __name__ == '__main__':
    main()
