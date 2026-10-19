"""Phase 5 offline regression tests. No real MongoDB, Pinecone, Ollama or Groq.
Run from backend/: python3 test_phase5.py
"""
import importlib.util
import io
import os
import pathlib
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

BACKEND = pathlib.Path(__file__).resolve().parent
os.environ["MONGO_URI"] = "mongodb://unit-test.invalid"
os.environ["PINECONE_API_KEY"] = "fake-pinecone"
os.environ["LLM_PROVIDER"] = "ollama"


class Result:
    def __init__(self, upserted_id=None, matched_count=0, modified_count=0):
        self.upserted_id = upserted_id
        self.matched_count = matched_count
        self.modified_count = modified_count


class Cursor:
    def __init__(self, items):
        self.items = list(items)
    def sort(self, specs):
        for key, order in reversed(specs):
            self.items.sort(key=lambda r: r.get(key) or datetime.min.replace(tzinfo=timezone.utc),
                            reverse=order < 0)
        return self
    def limit(self, n):
        self.items = self.items[:n]
        return self
    def __iter__(self):
        return iter(self.items)


class FakeCollection:
    def __init__(self):
        self.records = []
        self._next = 1
    def create_index(self, *args, **kwargs):
        return "notice_id_1"
    def insert(self, record):
        rec = dict(record)
        rec.setdefault("_id", self._next)
        self._next += 1
        self.records.append(rec)
        return rec
    def match(self, rec, criteria):
        for k, v in criteria.items():
            if k == "$or":
                if not any(self.match(rec, cond) for cond in v):
                    return False
            elif isinstance(v, dict):
                actual = rec.get(k)
                for op, cmp in v.items():
                    if op == "$lt":
                        if actual is None or not actual < cmp: return False
                    elif op == "$lte":
                        if actual is None or not actual <= cmp: return False
                    elif op == "$exists":
                        if (k in rec) != cmp: return False
                    elif op == "$type":
                        if cmp == "string" and not isinstance(actual,str): return False
                        if cmp == "object" and not isinstance(actual,dict): return False
                    elif op == "$ne":
                        if actual == cmp: return False
                    else:
                        raise NotImplementedError(op)
            elif rec.get(k) != v:
                return False
        return True
    @staticmethod
    def apply(rec, updates, is_insert=False):
        # Match MongoDB's path-conflict rule, including for non-insert upserts.
        seen = set()
        for operator in ("$set", "$setOnInsert", "$inc", "$unset"):
            for key in updates.get(operator, {}):
                if key in seen:
                    raise ValueError(f"Updating the path '{key}' would create a conflict")
                seen.add(key)
        for k,v in updates.get("$set",{}).items(): rec[k]=v
        if is_insert:
            for k,v in updates.get("$setOnInsert",{}).items(): rec.setdefault(k,v)
        for k,v in updates.get("$inc",{}).items(): rec[k]=rec.get(k,0)+v
        for k in updates.get("$unset",{}): rec.pop(k,None)
    def update_one(self, criteria, updates, upsert=False):
        for rec in self.records:
            if self.match(rec, criteria):
                self.apply(rec,updates)
                return Result(matched_count=1, modified_count=1)
        if not upsert: return Result()
        rec={k:v for k,v in criteria.items() if not k.startswith('$')}
        self.apply(rec,updates,is_insert=True)
        self.insert(rec)
        return Result(upserted_id=rec.get("_id") or self.records[-1]["_id"])
    def find_one_and_update(self, query, updates, sort=None, return_document=None):
        candidates=[r for r in self.records if self.match(r,query)]
        if sort:
            candidates=list(Cursor(candidates).sort(sort))
        if not candidates: return None
        rec=candidates[0]
        self.apply(rec,updates)
        return dict(rec)
    def find(self, query):
        return Cursor([r for r in self.records if self.match(r,query)])


DB=FakeCollection()
class Client:
    def __init__(self,*a,**kw): pass
    def __getitem__(self, key): return self
    def close(self): pass
    def create_index(self,*a,**kw): return DB.create_index(*a,**kw)
    def __getattr__(self, k):
        return getattr(DB,k)


# Replace only third-party integrations needed to import actual source.
pymongo=types.ModuleType('pymongo')
pymongo.MongoClient=Client
pymongo.ReturnDocument=types.SimpleNamespace(AFTER=1)
sys.modules['pymongo']=pymongo

class Chain:
    def __init__(self,*a,**kw): pass
    def __or__(self,other): return self
    def invoke(self,*a,**kw): return {}

langchain_ollama=types.ModuleType('langchain_ollama')
langchain_ollama.ChatOllama=Chain
sys.modules['langchain_ollama']=langchain_ollama

fake_ocr=types.ModuleType('ocr')
fake_ocr.extract_pdf_text=lambda p: "Academic notice issued by university"
fake_ocr.ocr_extract_pdf=lambda p: "Scanned notice text"
sys.modules['ocr']=fake_ocr
fake_prompt=types.ModuleType('prompt')
fake_prompt.notice_extraction_prompt=Chain()
fake_prompt.parser=Chain()
sys.modules['prompt']=fake_prompt
fake_schema=types.ModuleType('schema')
class Schema:
    @classmethod
    def model_validate(cls, data):
        return types.SimpleNamespace(model_dump=lambda: data)
fake_schema.NoticeSchema=Schema
sys.modules['schema']=fake_schema

fake_pinecone=types.ModuleType('pinecone')
class Index:
    def __init__(self):
        self.upserts=[]
        self.fail=False
    def upsert_records(self,namespace,records):
        if self.fail: raise RuntimeError('Pinecone unavailable')
        self.upserts.append((namespace,records))
INDEX=Index()
class Pinecone:
    def __init__(self,api_key): pass
    def Index(self,name): return INDEX
fake_pinecone.Pinecone=Pinecone
sys.modules['pinecone']=fake_pinecone


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,str(path))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

scraper=load('phase5_scraper',BACKEND/'Module1'/'scrapper.py')
processor=load('phase5_module2',BACKEND/'Module2'/'main.py')
indexer=load('phase5_module3',BACKEND/'Module3'/'main.py')
sync=load('phase5_sync',BACKEND/'scheduler'/'sync_notices.py')


class Phase5Tests(unittest.TestCase):
    def setUp(self):
        DB.records.clear()
        DB._next=1
        INDEX.upserts.clear()
        INDEX.fail=False

    def test_01_scraper_parses_and_deduplicates(self):
        html='''<a class="text-danger" href="/datas/users/test.pdf">Notice A</a>
        <a class="text-danger" href="/datas/users/test.pdf">Notice A</a>
        <a class="text-danger" href="https://evil.example/bad.pdf">Outside</a>
        <a class="text-danger" href="/datas/users/test2.pdf">Notice B</a>'''
        with patch.object(scraper.requests,'get',return_value=types.SimpleNamespace(
            text=html,raise_for_status=lambda:None)):
            notices=scraper.get_makautwb_notices()
        self.assertEqual(len(notices),2)
        self.assertTrue(all(x['url'].startswith('https://makautwb.ac.in/') for x in notices))

    def test_02_upsert_skips_existing_and_preserves_status(self):
        notice={'title':'Admission','url':'https://makautwb.ac.in/datas/users/admission.pdf',
                'flagged_new_on_site':True}
        self.assertTrue(scraper.store_notice(notice))
        DB.records[0]['status']='processed'
        self.assertFalse(scraper.store_notice({**notice,'flagged_new_on_site':False}))
        self.assertEqual(len(DB.records),1)
        self.assertIn('last_seen_at', DB.records[0])
        self.assertTrue(DB.records[0]['flagged_new_on_site'] is False)
        self.assertEqual(DB.records[0]['status'],'processed')
        self.assertFalse(DB.records[0]['flagged_new_on_site'])

    def test_03_detect_updated_pdf_content_without_new_url(self):
        notice=DB.insert({'status':'processed','notice_id':'x','url':'https://makautwb.ac.in/datas/users/a.pdf',
                           'pdf_sha256':'old', 'detected_at':datetime.now(timezone.utc)})
        with patch.object(scraper,'_pdf_digest',return_value='new'):
            report=scraper.recheck_existing_pdf_versions(limit=1)
        self.assertEqual(report['changed'],1)
        self.assertEqual(notice['status'],'new')
        self.assertFalse(notice['pinecone_indexed'])
        self.assertEqual(notice['processing_attempts'],0)

    def test_04_unchanged_pdf_not_reprocessed(self):
        notice=DB.insert({'status':'processed','notice_id':'x','url':'https://makautwb.ac.in/datas/users/a.pdf',
                           'pdf_sha256':'same','detected_at':datetime.now(timezone.utc)})
        with patch.object(scraper,'_pdf_digest',return_value='same'):
            report=scraper.recheck_existing_pdf_versions(limit=1)
        self.assertEqual(report['changed'],0)
        self.assertEqual(notice['status'],'processed')

    def test_05_pdf_processing_and_indexing_full_handoff(self):
        notice=DB.insert({'status':'new','notice_id':'id-55','title':'Test Notice',
                          'url':'https://makautwb.ac.in/datas/users/a.pdf','processing_attempts':0})
        structured={'title':'Test Notice', 'summary':'Admissions opening','notice_type':'Admission',
                    'important_dates':{'start_date':'01-10-2026','last_date':'30-10-2026'},
                    'key_points':['Apply online']}
        def fake_download(url,path):
            pathlib.Path(path).write_bytes(b'%PDF-1.7\nTest file')
        with patch.object(processor,'download_pdf',side_effect=fake_download),\
             patch.object(processor,'extract_structured_data',return_value=structured):
            report=processor.process_new_notices(limit=1)
        self.assertEqual(report['processed'],1)
        self.assertEqual(notice['status'],'processed')
        self.assertEqual(notice['pdf_sha256'],__import__('hashlib').sha256(b'%PDF-1.7\nTest file').hexdigest())
        self.assertFalse(notice['pinecone_indexed'])
        indexer.index_one_notice(notice)
        self.assertTrue(notice['pinecone_indexed'])
        self.assertEqual(INDEX.upserts[0][0],'notices')
        self.assertEqual(INDEX.upserts[0][1][0]['id'],'id-55')

    def test_06_transient_failure_retry_is_bounded(self):
        notice=DB.insert({'status':'new','notice_id':'id','title':'N',
                          'url':'https://makautwb.ac.in/datas/users/a.pdf','processing_attempts':0})
        with patch.object(processor,'download_pdf',side_effect=RuntimeError('provider timeout')):
            report=processor.process_new_notices(limit=2)
        self.assertEqual(report['failed'],1)
        self.assertEqual(notice['status'],'failed')
        self.assertEqual(notice['processing_attempts'],1)
        self.assertGreater(notice['next_retry_at'],datetime.now(timezone.utc))
        with patch.object(processor,'download_pdf',side_effect=RuntimeError('provider timeout')):
            next_report=processor.process_new_notices(limit=2)
        self.assertEqual(next_report['selected'],0)

    def test_07_invalid_pdf_retry_then_quarantine(self):
        notice=DB.insert({'status':'new','notice_id':'id','title':'N',
                          'url':'https://makautwb.ac.in/datas/users/a.pdf','processing_attempts':0})
        with patch.object(processor,'download_pdf',side_effect=processor.InvalidPDFError('not a PDF')):
            first=processor.process_new_notices(limit=1)
        self.assertEqual(first['failed'],1)
        self.assertEqual(notice['status'],'failed')
        # After exhausting configured attempts, quarantine instead of retrying forever.
        notice['status']='new'
        notice['processing_attempts']=processor.MAX_ATTEMPTS-1
        with patch.object(processor,'download_pdf',side_effect=processor.InvalidPDFError('not a PDF')):
            last=processor.process_new_notices(limit=1)
        self.assertEqual(last['invalid'],1)
        self.assertEqual(notice['status'],'invalid')

    def test_08_long_doc_held_for_review_by_default(self):
        notice=DB.insert({'status':'new','notice_id':'long','title':'N',
                          'url':'https://makautwb.ac.in/datas/users/a.pdf','processing_attempts':0})
        def download(_,path): pathlib.Path(path).write_bytes(b'%PDF-sample')
        with patch.object(processor,'download_pdf',side_effect=download),\
             patch.object(processor,'_extract_notice_text',return_value='x'*8000),\
             patch.object(processor,'process_long_notice',return_value=({'title':'N','key_points':[]},[{}])):
            report=processor.process_new_notices(limit=1)
        self.assertEqual(report['review_required'],1)
        self.assertEqual(notice['status'],'review_required')
        self.assertFalse(notice['pinecone_indexed'])

    def test_09_index_failure_does_not_claim_success(self):
        notice=DB.insert({'_id':9,'status':'processed','notice_id':'abc', 'url':'https://makautwb.ac.in/n.pdf',
                          'pinecone_indexed':False, 'structured_data':{'title':'N', 'summary':'A summary'}})
        INDEX.fail=True
        with self.assertRaisesRegex(RuntimeError,'Pinecone unavailable'):
            indexer.index_one_notice(notice)
        self.assertFalse(notice['pinecone_indexed'])

    def test_10_pipeline_call_order_and_empty_run(self):
        calls=[]
        def stage(name,result):
            def wrapper(*a,**kw): calls.append(name); return result
            return wrapper
        report=sync.run_sync(
            scrape_fn=stage('scrape',{'seen':10,'new':0,'existing':10}),
            recheck_fn=stage('recheck',{'checked':2,'changed':0,'errors':0}),
            process_fn=stage('extract',{'selected':0,'processed':0,'failed':0}),
            index_fn=stage('index',(0,0)))
        self.assertEqual(calls,['scrape','recheck','extract','index'])
        self.assertEqual(report['indexed'],0)

    def test_11_pipeline_reports_failed_index(self):
        with self.assertRaisesRegex(RuntimeError,'indexing'):
            sync.run_sync(
                scrape_fn=lambda:{'seen':0,'new':0},
                recheck_fn=lambda **kw:{'checked':0},
                process_fn=lambda **kw:{'failed':0},
                index_fn=lambda **kw:(0,1))

    def test_12_workflow_schedule_and_cloud_secrets(self):
        workflow=(BACKEND.parent/'.github'/'workflows'/'notice_sync.yml').read_text()
        self.assertIn('17 */3 * * *',workflow)
        self.assertIn('workflow_dispatch',workflow)
        self.assertIn('LLM_PROVIDER: groq',workflow)
        self.assertIn('secrets.GROQ_API_KEY',workflow)
        self.assertIn('python backend/scheduler/sync_notices.py',workflow)


if __name__=='__main__':
    unittest.main(verbosity=2)
