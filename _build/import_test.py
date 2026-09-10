"""import_test.py <cartridge> <course name> [canvas_cartridge_importer|common_cartridge_importer] [--new-quizzes]
Creates a scratch course on optimaoaoteam, imports the cartridge, prints issues + quiz question counts."""
import json,re,urllib.request,urllib.parse,time,os,uuid,sys
path,name=sys.argv[1],sys.argv[2]
mtype=sys.argv[3] if len(sys.argv)>3 and not sys.argv[3].startswith('--') else 'canvas_cartridge_importer'
newq='--new-quizzes' in sys.argv
tok=None
for line in open(r"C:/Users/JessicaDrexel/OneDrive - OptimaEd/Academic Design & Curriculum/Access tokens.txt",encoding='utf-8',errors='ignore'):
    m=re.search(r'\b([0-9]+~[A-Za-z0-9]+)',line)
    if m: tok=m.group(1)
HOST='https://optimaoaoteam.instructure.com/api/v1/'; H={'Authorization':'Bearer '+tok}
def call(path,method='GET',data=None,**q):
    url=(path if path.startswith('http') else HOST+path)+('?'+urllib.parse.urlencode(q,doseq=True) if q else '')
    body=None; hdr=dict(H)
    if data is not None: body=json.dumps(data).encode(); hdr['Content-Type']='application/json'
    try:
        with urllib.request.urlopen(urllib.request.Request(url,data=body,method=method,headers=hdr)) as r: return json.load(r)
    except urllib.error.HTTPError as e: return {'error':e.code,'body':e.read().decode()[:300]}
c=call('accounts/self/courses','POST',{'course':{'name':name,'course_code':'KIT-TEST'}}); cid=c.get('id'); print('scratch course',cid,c.get('name') or c)
size=os.path.getsize(path)
payload={'migration_type':mtype,'pre_attachment':{'name':os.path.basename(path),'size':size,'content_type':'application/zip'}}
if newq: payload['settings']={'import_quizzes_next':True}
m=call(f'courses/{cid}/content_migrations','POST',payload); print('migration',m.get('id'),mtype,'new-quizzes' if newq else '', '' if m.get('id') else m)
pa=m['pre_attachment']; b=uuid.uuid4().hex; parts=[]
for k,v in pa['upload_params'].items(): parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{os.path.basename(path)}"\r\nContent-Type: application/zip\r\n\r\n'.encode()+open(path,'rb').read()+b'\r\n'); parts.append(f'--{b}--\r\n'.encode())
class NR(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**k): return None
try: r=urllib.request.build_opener(NR).open(urllib.request.Request(pa['upload_url'],data=b''.join(parts),method='POST',headers={'Content-Type':f'multipart/form-data; boundary={b}'})); print('upload',r.status)
except urllib.error.HTTPError as e:
    print('upload',e.code)
    if e.code in (301,302,303) and e.headers.get('Location'):
        with urllib.request.urlopen(urllib.request.Request(e.headers['Location'],headers=H)) as r2: print('confirm',r2.status)
for i in range(120):
    st=call(f'courses/{cid}/content_migrations/{m["id"]}'); ws=st.get('workflow_state')
    if ws in ('completed','failed'): break
    time.sleep(5)
print('migration state',ws,'after ~%ds'%(i*5))
iss=call(f'courses/{cid}/content_migrations/{m["id"]}/migration_issues',per_page=100); print('issues',len(iss) if isinstance(iss,list) else iss)
for i in (iss if isinstance(iss,list) else [])[:40]: print(' -',i.get('issue_type'),(i.get('description') or '')[:250])
qs=call(f'courses/{cid}/quizzes',per_page=100)
if isinstance(qs,list):
    from collections import Counter
    print('quizzes imported',len(qs),'| by type:',dict(Counter(q['quiz_type'] for q in qs)))
    print('surveys:',[(q['title'][:28],q['question_count']) for q in qs if q['quiz_type'] in ('survey','graded_survey')])
    print('graded empty:',[(q['title'][:28]) for q in qs if q['quiz_type']=='assignment' and not q['question_count']])
    print('total questions',sum(q['question_count'] or 0 for q in qs))
asg=call(f'courses/{cid}/assignments',per_page=100)
if isinstance(asg,list):
    print('assignments',len(asg),'| external-tool (New Quizzes):',sum(1 for a in asg if 'external_tool' in (a.get('submission_types') or [])))
    dated=[a for a in asg if a.get('due_at') or a.get('unlock_at') or a.get('lock_at')]
    print('assignments with dates:',len(dated))
    for a in dated[:6]: print('   %-44s due=%s unlock=%s lock=%s pts=%s pub=%s'%(a['name'][:44],a.get('due_at'),a.get('unlock_at'),a.get('lock_at'),a.get('points_possible'),a.get('published')))
    unpub=[a['name'][:40] for a in asg if not a.get('published')]
    print('unpublished assignments:',len(unpub),unpub[:4])
course=call(f'courses/{cid}')
groups=call(f'courses/{cid}/assignment_groups',per_page=50)
if isinstance(groups,list):
    print('weighted:',course.get('apply_assignment_group_weights'),'| groups:',[(g['name'],g.get('group_weight')) for g in groups])
mods=call(f'courses/{cid}/modules',per_page=50)
if isinstance(mods,list): print('modules:',[(m['name'][:30],m.get('published'),m.get('unlock_at')) for m in mods])
