import importlib.util
from pathlib import Path
p=Path(__file__).parent
spec=importlib.util.spec_from_file_location('phase_evidence',p/'Module4'/'evidence.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
wb='0b671a4732db6587b97e58699b2a2eea05f24886be72aa3e2570dc4cad132b14'
jeca='36ad02612535c0d46e28e19041abfddf3cc440e9ec07ce332141c886352fc93c'
records=[{'notice_id':wb,'title':'WBJEEB 2nd Round Notice','url':'https://makautwb.ac.in/datas/users/0-wbjee_2nd_2526.pdf','structured_data':{'title':'Document verification and admission reporting for WBJEEB-2025 allotted students','issue_date':'08-09-2025','target_audience':'students allotted through WBJEEB-2025 (2nd round)','action_required':'Report to Haringhata Main Campus between 9-11 September 2025 (12:00-16:00) for document verification and admission, carrying all required original documents and photocopies.'}},{'notice_id':jeca,'title':'JECA Counselling Notice','url':'https://makautwb.ac.in/datas/users/0-wbjeca_2025.pdf','structured_data':{'title':'Admission Reporting Schedule for JECA-2025 Counselling','issue_date':'11-12-2025','key_points':['First round reporting: 17-21 Dec 2025.','Second round reporting: 23-26 Dec 2025.']}}]
q='What are the reporting dates and times for WBJEEB-2025 second-round document verification?'
filtered=mod.filter_explicit_notice_scope(q,records)
assert len(filtered)==1 and filtered[0]['notice_id']==wb,filtered
context,refs,byid=mod.build_evidence_bundle(filtered,q,lambda records,question:'',lambda *args,**kwargs:[])
ref_a=next(k for k,v in refs.items() if 'target_audience:' in v['text'])
ref_b=next(k for k,v in refs.items() if 'action_required:' in v['text'])
claim={'text':'Students allotted through WBJEEB-2025 (2nd round) report to Haringhata Main Campus between 9-11 September 2025 (12:00-16:00) for document verification and admission.','notice_ids':[wb],'evidence_refs':[ref_a,ref_b]}
assert len(mod.validate_claims([claim],refs,byid,debug=True))==1
assert not mod.validate_claims([{**claim,'text':'Students must report on 30 September 2025.'}],refs,byid)
assert not mod.validate_claims([{**claim,'evidence_refs':['FAKE']}],refs,byid)
assert not mod.validate_claims([{**claim,'notice_ids':[jeca]}],refs,byid)
print('PASS: exact WBJEEB topic selection, valid cited answer, fabricated date/ID rejection')
