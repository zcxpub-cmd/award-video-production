"""Transactional local projects, immutable media versions, jobs and idempotency."""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from .domain import Conflict, DomainError, Missing, apply_operations, identifier, new_project, now, text, uid, validate


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


DEFAULT_SETTINGS = dict(revision=0, execution_revision=0, theme='dark', appearanceVersion=2, motion=True, confirmAI=True,
                        ollama_model='qwen2.5vl:7b', vision_enabled=True, generation_enabled=False,
                        generation_model='', generation_max_requests=1, credential_ref=None)
TERMINAL = {'succeeded', 'failed', 'cancelled', 'interrupted', 'needs_attention', 'unknown'}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *exc):
        try:return super().__exit__(*exc)
        finally:self.close()


class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        marker = self.root/'.yingxu-runtime'
        if not marker.exists() and any(self.root.iterdir()):
            raise DomainError('数据目录不是影序运行目录，已停止以保护现有文件。')
        if not marker.exists():
            marker.write_text('yingxu-local-runtime-schema-1\n')
        elif marker.read_text().strip() != 'yingxu-local-runtime-schema-1':
            raise DomainError('数据目录版本未知。')
        self.root.chmod(0o700)
        self.db = self.root/'yingxu.sqlite3'
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, state TEXT NOT NULL, past TEXT NOT NULL, future TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS media(project_id TEXT, id TEXT, sha TEXT, record TEXT NOT NULL, PRIMARY KEY(project_id,id,sha));
                CREATE TABLE IF NOT EXISTS requests(project_id TEXT, id TEXT, hash TEXT NOT NULL, revision INTEGER NOT NULL, PRIMARY KEY(project_id,id));
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, request_id TEXT NOT NULL, hash TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(project_id,request_id));
                CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS credentials(id TEXT PRIMARY KEY, secret TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, project_id TEXT, action TEXT, detail TEXT, previous_hash TEXT, hash TEXT);
            ''')
            if not db.execute("SELECT 1 FROM meta WHERE key='settings'").fetchone():
                self._setmeta(db, 'settings', DEFAULT_SETTINGS)
        self.db.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.db, timeout=20, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=20000')
        return db

    @contextmanager
    def transaction(self):
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            yield db

    def _getmeta(self, db, key, default=None):
        row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row['value']) if row else deepcopy(default)

    def _setmeta(self, db, key, value):
        db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, encode(value)))

    def meta(self, key, default=None):
        with self.connect() as db:
            return self._getmeta(db, key, default)

    def set_meta(self, key, value):
        with self.transaction() as db:
            self._setmeta(db, key, value)

    def _audit(self, db, pid, action, detail):
        row = db.execute('SELECT hash FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
        previous = row['hash'] if row else '0'*64
        entry = dict(at=now(), project_id=pid, action=action, detail=detail, previous_hash=previous)
        db.execute('INSERT INTO audit(at,project_id,action,detail,previous_hash,hash) VALUES(?,?,?,?,?,?)',
                   (entry['at'], pid, action, encode(detail), previous, fingerprint(entry)))

    def _history(self, db, pid):
        row = db.execute('SELECT * FROM projects WHERE id=?', (identifier(pid),)).fetchone()
        if not row:
            raise Missing('工程不存在。')
        return {k: json.loads(row[v]) for k, v in [('present','state'),('past','past'),('future','future')]}

    def history(self, pid):
        with self.connect() as db:
            return self._history(db, pid)

    def workspace(self):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM projects').fetchall()
            projects = {r['id']:dict(present=json.loads(r['state']),past=json.loads(r['past']),future=json.loads(r['future'])) for r in rows}
            current = self._getmeta(db, 'current')
            return dict(projects=projects, current=current if current in projects else next(iter(projects), ''),
                        settings=self.public_settings(db), migration_available=not self._getmeta(db,'legacy_migrated',False))

    def select(self, pid):
        self.history(pid)
        self.set_meta('current', pid)

    def _write(self, db, history):
        p = history['present']
        db.execute('INSERT OR REPLACE INTO projects VALUES(?,?,?,?)', (p['id'],encode(p),encode(history['past'][-40:]),encode(history['future'][:40])))

    def create(self, project, records=()):
        validate(project)
        with self.transaction() as db:
            if db.execute('SELECT 1 FROM projects WHERE id=?',(project['id'],)).fetchone():
                raise Conflict('工程编号已存在。')
            for record in records:
                self._register(db, project['id'], record)
            self._write(db, dict(present=project, past=[], future=[]))
            self._setmeta(db, 'current', project['id'])
            self._audit(db, project['id'], 'create', {'revision':project['revision']})
        return self.history(project['id'])

    def _repeat(self, db, pid, request_id, payload):
        identifier(request_id)
        digest = fingerprint(payload)
        row = db.execute('SELECT * FROM requests WHERE project_id=? AND id=?',(pid,request_id)).fetchone()
        if row and row['hash'] != digest:
            raise Conflict('请求编号已用于不同操作。')
        return bool(row), digest

    def _commit(self, db, history, next_project, request_id, digest, action):
        pid = next_project['id']
        self._write(db, dict(present=next_project,past=[*history['past'],history['present']][-40:],future=[]))
        db.execute('INSERT INTO requests VALUES(?,?,?,?)',(pid,request_id,digest,next_project['revision']))
        self._audit(db,pid,action,{'revision':next_project['revision'],'request_id':request_id})

    def _guard_job(self,db,jid,execution=None):
        if jid:
            row=db.execute('SELECT data FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row or json.loads(row['data'])['status'] not in {'running','awaiting_confirmation'}:
                raise Conflict('任务已停止，旧结果不能再写入工程。')
        if execution is not None and self._getmeta(db,'settings',DEFAULT_SETTINGS)['execution_revision']!=execution:
            raise Conflict('执行设置已改变，旧结果不能再应用。')

    def edit(self, pid, expected, operations, request_id, guard_job=None, execution=None):
        with self.transaction() as db:
            repeated, digest = self._repeat(db,pid,request_id,dict(expected=expected,operations=operations))
            h = self._history(db,pid)
            if repeated:
                return dict(h, deduplicated=True)
            self._guard_job(db,guard_job,execution)
            if h['present']['revision'] != expected:
                raise Conflict('工程已更新，请刷新后基于新版本操作。')
            p = apply_operations(h['present'],operations)
            self._commit(db,h,p,request_id,digest,'edit')
            return self._history(db,pid)

    def move_history(self, pid, expected, direction, request_id, guard_job=None, execution=None):
        if direction not in {'undo','redo'}:
            raise DomainError('历史方向无效。')
        with self.transaction() as db:
            repeated,digest=self._repeat(db,pid,request_id,dict(expected=expected,direction=direction))
            h=self._history(db,pid)
            if repeated:
                return dict(h,deduplicated=True)
            self._guard_job(db,guard_job,execution)
            if h['present']['revision']!=expected:
                raise Conflict('工程已更新，不能使用旧的撤销/重做请求。')
            if not h['past' if direction=='undo' else 'future']:
                return h
            current=h['present']
            if direction=='undo':
                p=deepcopy(h['past'][-1]); past=h['past'][:-1]; future=[current,*h['future']][:40]
            else:
                p=deepcopy(h['future'][0]); past=[*h['past'],current][-40:]; future=h['future'][1:]
            p['revision']=current['revision']+1;p['updated']=now();validate(p)
            self._write(db,dict(present=p,past=past,future=future))
            db.execute('INSERT INTO requests VALUES(?,?,?,?)',(pid,request_id,digest,p['revision']))
            self._audit(db,pid,direction,{'revision':p['revision']})
            return self._history(db,pid)

    def _register(self, db, pid, record):
        a=record['metadata']
        db.execute('INSERT OR IGNORE INTO media VALUES(?,?,?,?)',(pid,a['id'],a['sha256'],encode(record)))

    def add_asset(self, pid, expected, record, request_id, relink=False, guard_job=None):
        a=record['metadata']
        with self.transaction() as db:
            repeated,digest=self._repeat(db,pid,request_id,dict(expected=expected,asset=a['id'],sha=a['sha256'],relink=relink))
            h=self._history(db,pid)
            if repeated:return dict(h,deduplicated=True)
            self._guard_job(db,guard_job)
            if h['present']['revision']!=expected:
                raise Conflict('工程已更新，文件已保留但尚未加入工程，请重新导入。')
            p=deepcopy(h['present'])
            duplicate=next((x for x in p['assets'] if x.get('sha256')==a['sha256'] and not x.get('unavailable')),None)
            if duplicate and not relink:
                return dict(h,deduplicated=True,existing_asset=duplicate['id'])
            self._register(db,pid,record)
            if relink:
                old=next((x for x in p['assets'] if x['id']==a['id']),None)
                if not old:raise Missing('待关联素材不存在。')
                p['assets']=[a if x['id']==a['id'] else x for x in p['assets']]
            else:
                p['assets'].append(a)
            p['revision']+=1;p['updated']=now();validate(p)
            self._commit(db,h,p,request_id,digest,'relink' if relink else 'import')
            return self._history(db,pid)

    def media(self, pid, aid, sha):
        identifier(pid);identifier(aid)
        if not isinstance(sha,str) or not __import__('re').fullmatch('[0-9a-f]{64}',sha):raise Missing('媒体版本不存在。')
        with self.connect() as db:
            row=db.execute('SELECT record FROM media WHERE project_id=? AND id=? AND sha=?',(pid,aid,sha)).fetchone()
            if not row:raise Missing('媒体版本不存在。')
            return json.loads(row['record'])

    def project_records(self, project):
        records={}
        for a in project['assets']:
            if a.get('unavailable') or not a.get('sha256'):
                continue
            records[a['id']]=self.media(project['id'],a['id'],a['sha256'])
        return records

    def migrate(self, histories, settings=None, records=()):
        if not isinstance(histories,dict) or len(histories)>100:raise DomainError('旧工程备份格式无效。')
        for h in histories.values():
            validate(h['present'])
            for p in [*h.get('past',[]),*h.get('future',[])]:validate(p)
        with self.transaction() as db:
            if self._getmeta(db,'legacy_migrated',False):return self.workspace()
            if db.execute('SELECT 1 FROM jobs LIMIT 1').fetchone():raise Conflict('已有运行任务，不能覆盖为旧浏览器工程。')
            for h in histories.values():
                row=db.execute('SELECT state FROM projects WHERE id=?',(h['present']['id'],)).fetchone()
                if row and json.loads(row['state'])['revision']!=0:raise Conflict('已有正式修改，旧工程迁移已停止。')
                self._write(db,dict(present=h['present'],past=h.get('past',[])[-40:],future=h.get('future',[])[:40]))
            for pid,record in records:self._register(db,pid,record)
            if settings:
                s=self._getmeta(db,'settings',DEFAULT_SETTINGS)
                for key in ['theme','motion','confirmAI']:
                    if key in settings:s[key]=settings[key]
                s['appearanceVersion']=2;self._setmeta(db,'settings',s)
            self._setmeta(db,'legacy_migrated',True)
            self._audit(db,'workspace','migrate',{'projects':len(histories)})
        return self.workspace()

    def public_settings(self, db=None):
        if db is None:
            with self.connect() as connection:return self.public_settings(connection)
        s=self._getmeta(db,'settings',DEFAULT_SETTINGS)
        return {k:v for k,v in s.items() if k!='credential_ref'}|{'generation_has_key':bool(s.get('credential_ref'))}

    def private_settings(self):return self.meta('settings',DEFAULT_SETTINGS)

    def update_settings(self, expected, patch):
        allowed={'theme','motion','confirmAI','ollama_model','vision_enabled','generation_enabled','generation_model','generation_max_requests','generation_key','clear_generation_key'}
        if not isinstance(patch,dict) or set(patch)-allowed:raise DomainError('设置包含未知字段。')
        if 'theme' in patch and patch['theme'] not in {'dark','light'}:raise DomainError('风格无效。')
        for key in ['motion','confirmAI','vision_enabled','generation_enabled','clear_generation_key']:
            if key in patch and type(patch[key]) is not bool:raise DomainError('开关设置无效。')
        for key in ['ollama_model','generation_model']:
            if key in patch:text(patch[key],'模型名称',200,empty=key=='generation_model')
        if 'generation_max_requests' in patch and (type(patch['generation_max_requests']) is not int or not 1<=patch['generation_max_requests']<=3):raise DomainError('生成上限需要为1至3次。')
        with self.transaction() as db:
            s=self._getmeta(db,'settings',DEFAULT_SETTINGS)
            if s['revision']!=expected:raise Conflict('设置已更新，请重新载入。')
            execution=any(k in patch and patch[k]!=s.get(k) for k in ['ollama_model','vision_enabled','generation_enabled','generation_model','generation_max_requests'])
            if patch.get('generation_key'):
                key=text(patch['generation_key'],'API密钥',1000,False)
                if '\n' in key or '\r' in key or len(key)<10:raise DomainError('API密钥格式无效。')
                ref=uid();db.execute('INSERT INTO credentials VALUES(?,?)',(ref,key));s['credential_ref']=ref;execution=True
            if patch.get('clear_generation_key'):s['credential_ref']=None;execution=True
            s.update({k:v for k,v in patch.items() if k not in {'generation_key','clear_generation_key'}})
            s['revision']+=1;s['execution_revision']+=int(execution)
            self._setmeta(db,'settings',s)
            self._audit(db,'settings','update',{'revision':s['revision'],'execution_revision':s['execution_revision']})
            return self.public_settings(db)

    def credential(self, ref):
        with self.connect() as db:
            row=db.execute('SELECT secret FROM credentials WHERE id=?',(ref,)).fetchone()
            if not row:raise DomainError('生成凭据不可用。')
            return row['secret']

    def add_message(self, pid, role, content, task=None):
        item=dict(id=uid(),role=role,text=content[:20000],task=task,created_at=now())
        with self.transaction() as db:db.execute('INSERT INTO messages VALUES(?,?,?)',(item['id'],pid,encode(item)))
        return item

    def messages(self, pid):
        with self.connect() as db:
            rows=db.execute('SELECT data FROM messages WHERE project_id=? ORDER BY rowid DESC LIMIT 100',(pid,)).fetchall()
            return [json.loads(r['data']) for r in reversed(rows)]

    def create_job(self, pid, kind, request_id, payload, private, expected=None):
        identifier(request_id);self.history(pid)
        digest=fingerprint(dict(kind=kind,payload=payload))
        with self.transaction() as db:
            row=db.execute('SELECT data,hash FROM jobs WHERE project_id=? AND request_id=?',(pid,request_id)).fetchone()
            if row:
                if row['hash']!=digest:raise Conflict('任务编号已用于不同请求。')
                return json.loads(row['data']),False
            if expected is not None and self._history(db,pid)['present']['revision']!=expected:
                raise Conflict('工程已更新，任务尚未提交，请重新确认当前版本。')
            if kind=='generation' and private.get('request_sha256'):
                duplicate=db.execute("""SELECT 1 FROM jobs WHERE project_id=?
                    AND json_extract(data,'$.kind')='generation'
                    AND json_extract(data,'$._private.request_sha256')=?
                    AND (json_extract(data,'$.status') IN ('queued','running','submitted','unknown','interrupted')
                      OR (json_extract(data,'$.status') IN ('cancelled','needs_attention')
                       AND json_extract(data,'$._private.submission_attempted')=1)) LIMIT 1""",
                    (pid,private['request_sha256'])).fetchone()
                if duplicate:raise Conflict('同一生成请求还有未对账的任务，请先查询原任务。')
            job=dict(id=uid(),project_id=pid,kind=kind,status='queued',stage='等待执行',progress=0,created_at=now(),updated_at=now(),
                     input_revision=private.get('snapshot',{}).get('revision'),result=None,error=None,external_id=None,request_id=request_id,_private=private)
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(job['id'],pid,request_id,digest,encode(job)))
            self._audit(db,pid,'job_queued',{'job_id':job['id'],'kind':kind})
            return job,True

    def job(self, jid):
        identifier(jid)
        with self.connect() as db:
            row=db.execute('SELECT data FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row:raise Missing('任务不存在。')
            return json.loads(row['data'])

    def jobs(self, pid=None):
        with self.connect() as db:
            rows=db.execute('SELECT data FROM jobs'+(' WHERE project_id=?' if pid else '')+' ORDER BY rowid DESC LIMIT 200',(pid,) if pid else ()).fetchall()
            return [json.loads(r['data']) for r in rows]

    def update_job(self, jid, patch, allow_terminal=False):
        with self.transaction() as db:
            row=db.execute('SELECT data FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row:raise Missing('任务不存在。')
            job=json.loads(row['data'])
            if job['status'] in TERMINAL and not allow_terminal:return job
            job.update(patch);job['updated_at']=now()
            db.execute('UPDATE jobs SET data=? WHERE id=?',(encode(job),jid))
            return job

    def record_generation_receipt(self,jid,external):
        with self.transaction() as db:
            row=db.execute('SELECT data FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row:raise Missing('任务不存在。')
            job=json.loads(row['data'])
            if job.get('external_id') not in {None,external}:raise Conflict('原服务商任务ID已登记。')
            job.update(external_id=external,updated_at=now())
            if job['status']=='running':job['stage']='生成已提交，正在查询原任务'
            db.execute('UPDATE jobs SET data=? WHERE id=?',(encode(job),jid))
            return job

    def public_job(self, job):
        return {k:v for k,v in job.items() if not k.startswith('_')}

    def save_observation(self,pid,aid,sha,observation,guard_job=None):
        with self.transaction() as db:
            self._guard_job(db,guard_job)
            row=db.execute('SELECT record FROM media WHERE project_id=? AND id=? AND sha=?',(pid,aid,sha)).fetchone()
            if not row:raise Missing('素材版本不存在。')
            record=json.loads(row['record']);record['analysis']=observation
            db.execute('UPDATE media SET record=? WHERE project_id=? AND id=? AND sha=?',(encode(record),pid,aid,sha))

    def unfinished_jobs(self):
        with self.connect() as db:
            rows=db.execute("SELECT data FROM jobs WHERE json_extract(data,'$.status') IN ('queued','running','submitted') OR (json_extract(data,'$.kind')='generation' AND json_extract(data,'$.status')='interrupted' AND json_extract(data,'$.external_id') IS NOT NULL)").fetchall()
            return [json.loads(r['data']) for r in rows]

    def unresolved_generation(self,pid,request_hash):
        with self.connect() as db:
            rows=db.execute("SELECT data FROM jobs WHERE project_id=? AND json_extract(data,'$.kind')='generation' AND json_extract(data,'$._private.request_sha256')=? AND json_extract(data,'$.status') NOT IN ('succeeded','failed')",(pid,request_hash)).fetchall()
            return [json.loads(r['data']) for r in rows]
