"""Single-user loopback production API and built frontend."""
from __future__ import annotations
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from hashlib import sha256
import threading
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import tempfile
import zipfile
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .agents import LocalAgent
from .domain import Conflict, DomainError, Missing, identifier, new_project, now, uid, validate
from .jobs import Jobs
from .media import Media, ROOT, atomic_json
from .store import Store
from runtime_lock import lock_file

COVER = ROOT.parent / 'assets/wall/cover'
DATA = ROOT / 'data'
IDENTITY = 'yingxu-community-workbench'
VERSION = '1.4.1'
COOKIE = 'yingxu-community-session'

def sample_path(name):
    return DATA / name if name == 'studio-tone.wav' else COVER / name

DEMO_FILES={'mountain-still':'mountain.webp','ocean-motion':'ocean.mp4','ocean-still':'ocean.webp','dna-motion':'dna.mp4','dna-still':'dna.webp','studio-tone':'studio-tone.wav'}


def create_app(data_root, workers=True, agent=None, seed=True):
    store=Store(data_root);media=Media(store.root);agent=agent or LocalAgent()
    process_lock=None
    if workers:
        process_lock=(store.root/'.runtime.lock').open('a+b')
        try:lock_file(process_lock)
        except OSError:
            process_lock.close();raise DomainError('此数据目录已有影序服务运行，请使用原服务。') from None
    migration_lock=threading.RLock()
    if seed and not store.workspace()['projects']:
        p=json.loads((ROOT/'data/seed-project.json').read_text())
        records=[];assets=[]
        for a in p['assets']:
            record=media.prepare(sample_path(DEMO_FILES[a['id']]),a['name'],p['id'],a['id'],'demo')
            records.append(record);assets.append(record['metadata'])
        p['assets']=assets;store.create(p,records)
    manager=Jobs(store,media,agent,start=workers)
    token=secrets.token_urlsafe(32)
    incoming=store.root/'incoming';incoming.mkdir(exist_ok=True)

    @asynccontextmanager
    async def lifespan(app):
        yield
        manager.shutdown()
        if process_lock and not any(thread.is_alive() for thread in manager.threads):process_lock.close()

    app=FastAPI(title='影序开源工作台',version=VERSION,docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.store=store;app.state.media=media;app.state.jobs=manager;app.state.token=token

    @app.middleware('http')
    async def local_access(request:Request,call_next):
        host=request.headers.get('host','')
        hostname=host.split(':')[0]
        if hostname not in {'127.0.0.1','localhost'}:
            return JSONResponse({'detail':'仅支持本机回环访问。'},status_code=403)
        origin=request.headers.get('origin')
        if origin and origin!='http://'+host:
            return JSONResponse({'detail':'跨来源请求已拒绝。'},status_code=403)
        if request.headers.get('sec-fetch-site')=='cross-site':
            return JSONResponse({'detail':'跨站请求已拒绝。'},status_code=403)
        if request.url.path.startswith('/api/') and request.url.path not in {'/api/bootstrap','/api/health'}:
            cookie=request.cookies.get(COOKIE,'')
            header=request.headers.get('x-yingxu-token','')
            if not secrets.compare_digest(cookie,token):return JSONResponse({'detail':'本地会话已更新，请重新连接。'},status_code=403)
            if request.method not in {'GET','HEAD'} and not secrets.compare_digest(header,token):
                return JSONResponse({'detail':'缺少有效的本地写入令牌。'},status_code=403)
        if request.method in {'POST','PUT','PATCH'}:
            size=request.headers.get('content-length')
            limit=2*1024**3 if '/assets' in request.url.path or request.url.path=='/api/import-project' else 8*1024**2
            try:
                if size is None:return JSONResponse({'detail':'需要明确请求长度。'},status_code=411)
                if int(size)>limit:return JSONResponse({'detail':'请求超过本机导入上限。'},status_code=413)
            except ValueError:return JSONResponse({'detail':'请求长度无效。'},status_code=400)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Cross-Origin-Resource-Policy']='same-origin'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request,exc):return JSONResponse({'detail':str(exc)},status_code=exc.status)

    @app.exception_handler(ValueError)
    async def value_error(request,exc):return JSONResponse({'detail':'请求中存在无效数据，工程没有被该请求覆盖。'},status_code=400)

    def enrich(history):
        h=deepcopy(history)
        for a in h['present']['assets']:
            if a.get('sha256') and not a.get('unavailable'):
                try:
                    record=store.media(h['present']['id'],a['id'],a['sha256'])
                    if record.get('analysis'):a['analysis']=record['analysis']
                    if not media.path(record['path']).exists():a.update(url='',unavailable=True)
                except DomainError:a.update(url='',unavailable=True,note='工程媒体缺失，请重新关联。')
        return h

    def workspace():
        w=store.workspace();w['projects']={pid:enrich(h) for pid,h in w['projects'].items()}
        return w

    def normalize_legacy(histories):
        if not isinstance(histories,dict) or len(histories)>100:raise DomainError('旧工程备份格式无效。')
        histories=deepcopy(histories);records=[];cache={}
        for pid,h in histories.items():
            identifier(pid)
            if not isinstance(h,dict) or 'present' not in h or any(not isinstance(h.get(k,[]),list) or len(h.get(k,[]))>40 for k in ('past','future')):raise DomainError('旧工程历史格式无效。')
            for p in [h['present'],*h.get('past',[]),*h.get('future',[])]:
                if not isinstance(p,dict) or p.get('id')!=pid:raise DomainError('旧工程编号不一致。')
                for i,a in enumerate(p.get('assets',[])):
                    if a.get('id') in DEMO_FILES and a.get('origin')=='demo':
                        key=(pid,a['id'])
                        if key not in cache:
                            record=media.prepare(sample_path(DEMO_FILES[a['id']]),a['name'],pid,a['id'],'demo');cache[key]=record
                            records.append((pid,record))
                        p['assets'][i]=cache[key]['metadata']
                    else:
                        a.update(url='',poster=None,unavailable=True,note='来自旧浏览器工程；请重新关联本机原文件。')
                        a.pop('sha256',None)
                validate(p)
        return histories,records

    @app.get('/api/health')
    def health():
        return dict(identity=IDENTITY,version=VERSION,workspace=sha256(os.fsencode(store.root)).hexdigest(),media=media.health(),agent=agent.health())

    @app.get('/api/bootstrap')
    def bootstrap():
        response=JSONResponse(dict(workspace(),token=token,runtime={'identity':IDENTITY,'version':VERSION,'data_directory':str(store.root)},models=agent.health(),media=media.health()))
        response.set_cookie(COOKIE,token,httponly=True,samesite='strict',path='/')
        response.headers['Cache-Control']='no-store'
        return response

    @app.post('/api/migrate')
    def migrate(body:dict):
        with migration_lock:
            if store.meta('legacy_migrated',False):return workspace()
            histories,records=normalize_legacy(body.get('projects',{}))
            settings=body.get('settings',{})
            if settings.get('theme') not in {'dark','light'} or settings.get('appearanceVersion')!=2:settings['theme']='dark'
            for key in ['motion','confirmAI']:
                if key in settings and type(settings[key]) is not bool:raise DomainError('旧偏好格式无效。')
            backup=store.root/'legacy-browser-backup.json'
            if not backup.exists():atomic_json(backup,body)
            result=store.migrate(histories,settings,records)
            if body.get('current') in result['projects']:store.select(body['current'])
            return workspace()

    @app.get('/api/workspace')
    def get_workspace():return workspace()

    @app.post('/api/projects')
    def create_project(body:dict):
        p=new_project(body.get('name','未命名故事'),body.get('mode','manual'),body.get('aspect','16:9'),body.get('target',30))
        records=[]
        if body.get('use_samples'):
            template=json.loads((ROOT/'data/seed-project.json').read_text())
            for a in template['assets']:
                record=media.prepare(sample_path(DEMO_FILES[a['id']]),a['name'],p['id'],a['id'],'demo')
                records.append(record);p['assets'].append(record['metadata'])
        return enrich(store.create(p,records))

    @app.get('/api/projects/{pid}')
    def get_project(pid:str):return enrich(store.history(pid))

    @app.post('/api/projects/{pid}/select')
    def select(pid:str):store.select(pid);return enrich(store.history(pid))

    @app.post('/api/projects/{pid}/edit')
    def edit(pid:str,body:dict):return enrich(store.edit(pid,body.get('expected_revision'),body.get('operations'),body.get('request_id')))

    @app.post('/api/projects/{pid}/history')
    def history(pid:str,body:dict):return enrich(store.move_history(pid,body.get('expected_revision'),body.get('direction'),body.get('request_id')))

    def save_upload(upload):
        ext=Path(upload.filename or '').suffix.lower()
        fd,path=tempfile.mkstemp(prefix='upload-',suffix=ext,dir=incoming)
        count=0
        try:
            with os.fdopen(fd,'wb') as out:
                while chunk:=upload.file.read(1024*1024):
                    count+=len(chunk)
                    if count>2*1024**3:raise DomainError('文件超过2GiB导入上限。')
                    out.write(chunk)
            if count==0:raise DomainError('上传文件为空。')
            return Path(path)
        except Exception:
            Path(path).unlink(missing_ok=True);raise

    @app.post('/api/projects/{pid}/assets')
    def upload_asset(pid:str,request:Request,file:UploadFile=File(...)):
        if not all(k in request.query_params for k in ['expected_revision','request_id']):raise DomainError('缺少素材登记版本或请求编号。')
        expected=int(request.query_params['expected_revision']);rid=request.query_params['request_id']
        relink=request.query_params.get('relink')
        aid=relink or request.query_params.get('asset_id')
        if aid:identifier(aid)
        store.history(pid);temp=save_upload(file)
        try:
            record=media.prepare(temp,Path(file.filename or 'media').name,pid,aid)
            return enrich(store.add_asset(pid,expected,record,rid,relink=bool(relink)))
        finally:temp.unlink(missing_ok=True)

    @app.api_route('/api/projects/{pid}/assets/{aid}/{sha}/{role}',methods=['GET','HEAD'])
    def media_file(pid:str,aid:str,sha:str,role:str):
        record=store.media(pid,aid,sha)
        if role=='media':relative=record['path']
        elif role=='thumbnail' and record.get('thumbnail'):relative=record['thumbnail']
        else:raise Missing('媒体角色不存在。')
        return FileResponse(media.path(relative),headers={'Cache-Control':'private, max-age=86400, immutable','ETag':'"'+sha+'"'})

    @app.get('/api/settings')
    def settings():return dict(settings=store.public_settings(),models=agent.health(),media=media.health())

    @app.put('/api/settings')
    def put_settings(body:dict):return store.update_settings(body.get('expected_revision'),body.get('patch'))

    @app.get('/api/projects/{pid}/messages')
    def messages(pid:str):store.history(pid);return store.messages(pid)

    @app.get('/api/projects/{pid}/jobs')
    def project_jobs(pid:str):store.history(pid);return [store.public_job(j) for j in store.jobs(pid)]

    @app.post('/api/projects/{pid}/jobs')
    def start_job(pid:str,body:dict):
        kind=body.get('kind');options=body.get('options',{})
        if not isinstance(options,dict):raise DomainError('任务选项无效。')
        return manager.submit(pid,kind,body.get('request_id'),body.get('expected_revision'),options)

    @app.get('/api/jobs/{jid}')
    def get_job(jid:str):return store.public_job(store.job(jid))

    @app.post('/api/jobs/{jid}/cancel')
    def cancel_job(jid:str):return manager.cancel(jid)

    @app.post('/api/jobs/{jid}/apply')
    def apply_job(jid:str):return enrich(manager.apply_ai(jid))

    @app.post('/api/jobs/{jid}/query-original')
    def resume_job(jid:str,body:dict):return manager.resume_generation(jid,body.get('external_id'))

    @app.api_route('/api/jobs/{jid}/files/{filename}',methods=['GET','HEAD'])
    def job_file(jid:str,filename:str):
        job=store.job(jid)
        if job['status']!='succeeded' or not job.get('result') or filename not in job['result'].get('files',[]):raise Missing('已完成输出不存在。')
        path=manager.root/jid/filename
        if not path.is_file() or path.is_symlink() or path.parent!=manager.root/jid:raise Missing('输出文件缺失。')
        download=None if filename.endswith('.mp4') else filename
        return FileResponse(path,filename=download,headers={'Cache-Control':'private, no-store'})

    @app.get('/api/projects/{pid}/project.json')
    def project_json(pid:str):
        p=store.history(pid)['present']
        return JSONResponse({'schema_version':1,'project':p,'media_included':False},headers={'Content-Disposition':'attachment; filename="yingxu-project.json"'})

    @app.post('/api/import-project')
    def import_project(file:UploadFile=File(...)):
        temporary=save_upload(file)
        extracted=[]
        try:
            archive=zipfile.ZipFile(temporary) if zipfile.is_zipfile(temporary) else None
            if archive:
                if len(archive.infolist())>5000 or sum(i.file_size for i in archive.infolist())>4*1024**3:raise DomainError('工程包超出本机导入限制。')
                for item in archive.infolist():
                    name=PurePosixPath(item.filename)
                    if name.is_absolute() or '..' in name.parts or '\\' in item.filename or (item.external_attr>>16)&0o170000==0o120000:raise DomainError('工程包含不安全路径。')
                manifest=next((n for n in ['portable-project.json','project.json'] if n in archive.namelist()),None)
                if not manifest or archive.getinfo(manifest).file_size>8*1024**2:raise DomainError('工程包缺少有效清单。')
                data=json.loads(archive.read(manifest))
            else:
                if temporary.stat().st_size>8*1024**2:raise DomainError('工程JSON过大。')
                data=json.loads(temporary.read_text())
            p=deepcopy(data['project']);p['id']=uid();p['revision']=0;p['updated']=now();p['name']=(p['name']+' · 导入')[:100]
            records=[]
            for i,a in enumerate(p['assets']):
                relative=a.get('url','')
                if archive and relative in archive.namelist() and PurePosixPath(relative).parts[:1]==('media',):
                    info=archive.getinfo(relative)
                    if info.file_size>2*1024**3:raise DomainError('包内单素材超过2GiB。')
                    target=incoming/(uid()+Path(relative).suffix)
                    extracted.append(target)
                    with archive.open(relative) as src,target.open('xb') as out:shutil.copyfileobj(src,out,1024*1024)
                    record=media.prepare(target,a['name'],p['id'],a['id'],a.get('origin','local'))
                    records.append(record);p['assets'][i]=record['metadata']
                else:
                    a.update(url='',poster=None,unavailable=True,note='工程仅含引用，请重新关联原素材。');a.pop('sha256',None)
            validate(p)
            return enrich(store.create(p,records))
        except (zipfile.BadZipFile,KeyError,UnicodeError,json.JSONDecodeError):
            raise DomainError('工程包或JSON格式无效。') from None
        finally:
            if 'archive' in locals() and archive:archive.close()
            temporary.unlink(missing_ok=True)
            for p in extracted:p.unlink(missing_ok=True)

    @app.get('/cover/studio-tone.wav')
    def sample_tone():
        return FileResponse(sample_path('studio-tone.wav'), media_type='audio/wav')

    app.mount('/cover', StaticFiles(directory=COVER), name='cover')
    dist=ROOT/'frontend/dist-runtime'
    if dist.exists():app.mount('/',StaticFiles(directory=dist,html=True),name='workspace')
    return app
