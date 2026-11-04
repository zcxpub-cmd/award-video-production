"""Durable local task workers. A generation POST is never retried implicitly."""
from copy import deepcopy
import json
from pathlib import Path
import queue
import re
import threading
import traceback
from . import generation
from .domain import Conflict, DomainError, arrange, duration, identifier, now, number, text
from .media import atomic_json
from .render import Cancelled, Renderer
from .store import TERMINAL, fingerprint


class Jobs:
    def __init__(self,store,media,agent,start=True):
        self.store,self.media,self.agent=store,media,agent
        self.renderer=Renderer(media);self.root=store.root/'jobs';self.root.mkdir(exist_ok=True)
        self.queues={k:queue.Queue() for k in ['render','ai','generation']}
        self.cancel_events={};self.processes={};self.connections={};self.lock=threading.RLock();self.stopping=threading.Event();self.threads=[]
        for job in store.unfinished_jobs():
            if job['kind']=='generation' and job.get('external_id'):
                store.update_job(job['id'],{'status':'queued','stage':'服务重启，继续查询原任务'})
                self.enqueue(job)
            elif job['status']=='queued':self.enqueue(job)
            else:store.update_job(job['id'],{'status':'interrupted','stage':'服务曾中断，结果未确认','error':'原工程与任务记录已保留；本地任务可重新发起，生成任务先对账。'})
        if start:
            for kind in self.queues:
                thread=threading.Thread(target=self.worker,args=(kind,),daemon=True,name='yingxu-'+kind);self.threads.append(thread);thread.start()

    def category(self,kind):return 'generation' if kind=='generation' else 'ai' if kind in {'ai-edit','observe'} else 'render'

    def enqueue(self,job):
        self.queues[self.category(job['kind'])].put(job['id'])

    def submit(self,pid,kind,request_id,expected,options):
        if type(expected) is not int or expected<0:raise DomainError('发起任务需要明确工程修订。')
        p=self.store.history(pid)['present'];settings=self.store.private_settings()
        private={'snapshot':deepcopy(p),'records':self.store.project_records(p),'execution_revision':settings['execution_revision'],'model':settings['ollama_model'],'options':deepcopy(options)}
        if (kind=='observe' or kind=='auto' and options.get('use_ai') and options.get('analyze_assets')) and not settings['vision_enabled']:
            raise DomainError('本地画面观察已关闭，请先在执行设置中开启，或关闭一键制作的画面观察。')
        if kind=='generation':
            if options.get('approve_billable') is not True or options.get('approve_text_transfer') is not True:
                raise DomainError('需要明确批准本次一次收费请求与提示词外传。')
            payload=generation.request_payload(settings,options.get('prompt'),options.get('duration',5),p['aspect'],options.get('resolution','720p'))
            private.update(generation_payload=payload,credential_ref=settings['credential_ref'],request_sha256=fingerprint(payload),submission_attempted=False)
        elif kind=='ai-edit':
            text(options.get('instruction'),'剪辑指令',8000,False)
            private['recent_messages']=[{'role':m['role'],'text':m['text'][:500]} for m in self.store.messages(pid)[-6:]]
        elif kind=='observe':
            if options.get('asset_id') not in private['records']:raise DomainError('素材尚未关联。')
        elif kind=='auto':
            selected=options.get('asset_ids')
            if selected is not None:
                if not isinstance(selected,list) or not 1<=len(selected)<=100:raise DomainError('请选择1至100份可用素材。')
                for aid in selected:identifier(aid)
                if len(set(selected))!=len(selected) or not set(selected)<=set(private['records']):raise DomainError('所选素材不可用或重复。')
            if 'target' in options:number(options['target'],'目标时长',1,3600)
            if 'brief' in options:text(options['brief'],'创作简报',8000)
        elif kind not in {'render','auto'}:raise DomainError('任务类型无效。')
        job,created=self.store.create_job(pid,kind,request_id,dict(expected=expected,options=options),private,expected)
        if created:
            if kind=='ai-edit':self.store.add_message(pid,'user',options['instruction'],job['id'])
            self.enqueue(job)
        return self.store.public_job(job)

    def _set_process(self,jid,process):
        with self.lock:
            if process is None:self.processes.pop(jid,None)
            else:self.processes[jid]=process

    def _set_connection(self,jid,response):
        with self.lock:
            if response is None:self.connections.pop(jid,None)
            else:self.connections[jid]=response

    def cancel(self,jid):
        job=self.store.job(jid)
        if job['status'] in TERMINAL:return self.store.public_job(job)
        event=self.cancel_events.setdefault(jid,threading.Event());event.set()
        stage='已取消，工程与源文件保留'
        if job['kind']=='generation':stage='本地停止跟进；服务商任务可能仍执行和计费，可继续查询原ID'
        job=self.store.update_job(jid,{'status':'cancelled','stage':stage,'progress':None})
        with self.lock:proc=self.processes.get(jid);response=self.connections.get(jid)
        if proc is not None and proc.poll() is None:
            try:proc.terminate()
            except OSError:pass
        if response is not None:threading.Thread(target=response.close,daemon=True).start()
        return self.store.public_job(job)

    def worker(self,category):
        q=self.queues[category]
        while not self.stopping.is_set():
            try:jid=q.get(timeout=.3)
            except queue.Empty:continue
            try:self.run(jid)
            finally:q.task_done()

    def run(self,jid):
        job=self.store.job(jid)
        if job['status']!='queued':return
        cancel=self.cancel_events.setdefault(jid,threading.Event())
        folder=self.root/jid;folder.mkdir(exist_ok=True)
        self.store.update_job(jid,{'status':'running','stage':'准备输入','started_at':now()})
        last=[0.0]
        def progress(stage,value):
            if cancel.is_set():raise Cancelled()
            self.store.update_job(jid,{'stage':stage,'progress':value})
        def connection(response):self._set_connection(jid,response)
        def process(p):self._set_process(jid,p)
        def chunk(content):
            if cancel.is_set():raise Cancelled()
            import time
            if time.monotonic()-last[0]>.4:
                match=re.search(r'"summary"\s*:\s*"((?:\\.|[^"\\])*)',content)
                self.store.update_job(jid,{'progress':None,'output_characters':len(content),'partial_summary':match.group(1)[:600] if match else ''})
                last[0]=time.monotonic()
        try:
            private=job['_private'];p=private['snapshot'];records=private['records'];options=private['options']
            if self.store.private_settings()['execution_revision']!=private['execution_revision'] and job['kind']!='render' and not (job['kind']=='generation' and job.get('external_id')):
                raise Conflict('模型或执行设置已改变，请基于当前设置重新发起。')
            if job['kind']=='render':
                progress('冻结工程与源文件校验',.03)
                result=self.renderer.render(p,records,folder,options,cancel,progress,process)
                patch={'status':'succeeded','stage':'成片已导出，技术解码通过','progress':1,'result':result}
            elif job['kind']=='observe':
                progress('本地模型观察抽样画面',None)
                aid=options['asset_id'];result=self.agent.observe(records[aid],self.media,private['model'],cancel,connection)
                self.store.save_observation(p['id'],aid,records[aid]['sha256'],result,guard_job=jid)
                atomic_json(folder/'observation.json',result)
                patch={'status':'succeeded','stage':'抽样观察已保存，仍需内容审核','progress':1,'result':result}
            elif job['kind']=='ai-edit':
                progress('本地模型正在规划剪辑操作',None)
                proposal,metrics=self.agent.edit(p,options['instruction'],options.get('selected'),options.get('playhead',0),private['model'],cancel,chunk,connection,recent_messages=private.get('recent_messages',()))
                result=dict(proposal,metrics=metrics,base_revision=p['revision'],execution_revision=private['execution_revision'])
                atomic_json(folder/'proposal.json',result)
                if cancel.is_set():raise Cancelled()
                if not result['operations'] and result['history_action']=='none':
                    patch={'status':'needs_attention','stage':'AI需要进一步说明','progress':None,'result':result,'error':proposal['summary']}
                    self.store.add_message(p['id'],'assistant',proposal['summary'],jid)
                elif options.get('auto_apply'):
                    history=self._apply_result(job,result)
                    result['applied_revision']=history['present']['revision']
                    patch={'status':'succeeded','stage':'AI修改已应用，可撤销','progress':1,'result':result}
                    self.store.add_message(p['id'],'assistant',proposal['summary'],jid)
                else:patch={'status':'awaiting_confirmation','stage':'修改建议已准备，请确认后应用','progress':1,'result':result}
            elif job['kind']=='auto':
                choices=options.get('asset_ids')
                source=deepcopy(p)
                if choices is not None:
                    available={a['id']:a for a in p['assets']}
                    source['assets']=[available[aid] for aid in choices]
                source['target']=options.get('target',p['target']);source['brief']=options.get('brief',p['brief'])
                if not any(a['kind']!='audio' and a['id'] in records for a in source['assets']):raise DomainError('请至少选择一份可用画面素材。')
                observations={a['id']:records[a['id']]['analysis'] for a in source['assets'] if a['id'] in records and records[a['id']].get('analysis')}
                summary='按所选素材顺序编排。';sequence=None
                if options.get('use_ai'):
                    if options.get('analyze_assets'):
                        candidates=[a for a in source['assets'] if a['kind']!='audio' and a['id'] in records]
                        if len(candidates)>12:raise DomainError('本次自动观察最多12份素材；请先分批观察或关闭逐项观察。')
                        for i,a in enumerate(candidates):
                            progress(f'观察素材 {i+1}/{len(candidates)}',None)
                            record=records[a['id']]
                            if not observations.get(a['id']):
                                result=self.agent.observe(record,self.media,private['model'],cancel,connection)
                                observations[a['id']]=result;self.store.save_observation(p['id'],a['id'],a['sha256'],result,guard_job=jid)
                    progress('本地导演规划镜头顺序',None)
                    plan,metrics=self.agent.plan(source,observations,private['model'],cancel,chunk,connection)
                    sequence=plan['sequence'];summary=plan['summary']
                    atomic_json(folder/'director-plan.json',dict(plan,metrics=metrics,observations=observations))
                clips=arrange(source,sequence)
                actual=duration({'clips':clips})
                if actual<source['target']-1/p['fps']:summary+=f' 可用画面不足：目标{source["target"]:.2f}秒，实际{actual:.2f}秒。'
                if any(t['muted'] for t in p['tracks'] if t['id']=='V1'):raise DomainError('主画面轨道已静音，请先启用后再一键制作。')
                if self.store.private_settings()['execution_revision']!=private['execution_revision']:
                    raise Conflict('执行设置已变化，本次方案没有覆盖工程。')
                edits=[{'type':'replace','clips':clips}]
                config={key:source[key] for key in ('target','brief') if source[key]!=p[key]}
                if config:edits.insert(0,{'type':'configure','patch':config})
                history=self.store.edit(p['id'],p['revision'],edits,'auto-'+jid,guard_job=jid,execution=private['execution_revision'])
                p=history['present'];private['render_snapshot']=p;self.store.update_job(jid,{'_private':private,'render_revision':p['revision']})
                progress('时间线编排完成，开始真实渲染',.06)
                result=self.renderer.render(p,records,folder,options,cancel,progress,process)
                result['summary']=summary
                patch={'status':'succeeded','stage':'一键制作完成，成片等待观看与听审','progress':1,'result':result}
            else:
                patch=generation.execute(self.store,self.media,job,folder,cancel,progress)
                if patch is None:return
            if cancel.is_set():raise Cancelled()
            self.store.update_job(jid,patch)
        except Cancelled:
            self.store.update_job(jid,{'status':'cancelled','stage':'本地任务已停止；工程与已有输出保留','progress':None})
        except DomainError as e:
            self.store.update_job(jid,{'status':'needs_attention' if isinstance(e,Conflict) else 'failed','stage':'需要处理后继续','error':str(e),'progress':None})
        except Exception as e:
            (folder/'failure.log').write_text(''.join(traceback.format_tb(e.__traceback__))+'\n'+type(e).__name__,encoding='utf8')
            self.store.update_job(jid,{'status':'failed','stage':'任务未完成，输入与日志已保留','error':'内部处理失败（'+type(e).__name__+'），没有伪造输出。','progress':None})
        finally:
            self._set_process(jid,None);self._set_connection(jid,None)

    def _apply_result(self,job,result):
        if self.store.private_settings()['execution_revision']!=result['execution_revision']:
            raise Conflict('模型设置已变化，请重新生成建议。')
        pid=job['project_id'];revision=result['base_revision']
        if result['history_action'] in {'undo','redo'}:
            return self.store.move_history(pid,revision,result['history_action'],'apply-'+job['id'],guard_job=job['id'],execution=result['execution_revision'])
        return self.store.edit(pid,revision,result['operations'],'apply-'+job['id'],guard_job=job['id'],execution=result['execution_revision'])

    def apply_ai(self,jid):
        job=self.store.job(jid)
        if job['kind']!='ai-edit':raise DomainError('此任务不是剪辑建议。')
        if job['status']=='succeeded':return self.store.history(job['project_id'])
        if job['status']!='awaiting_confirmation':raise Conflict('此建议当前不可应用。')
        h=self._apply_result(job,job['result']);result=job['result']|{'applied_revision':h['present']['revision']}
        self.store.update_job(jid,{'status':'succeeded','stage':'建议已应用，可撤销','result':result})
        self.store.add_message(job['project_id'],'assistant',result['summary'],jid)
        return h

    def resume_generation(self,jid,external_id=None):
        job=self.store.job(jid)
        if job['kind']!='generation' or job['status'] not in {'unknown','interrupted','cancelled'}:
            raise DomainError('仅可继续查询已停止的生成任务。')
        actual=job.get('external_id')
        if external_id:
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',external_id):raise DomainError('原任务ID格式无效。')
            if actual and actual!=external_id:raise Conflict('不能替换已有服务商任务ID。')
            actual=external_id
        if not actual:raise DomainError('先在服务商对账，填入原任务ID；不能盲目重发。')
        self.cancel_events[jid]=threading.Event()
        updated=self.store.update_job(jid,{'status':'queued','external_id':actual,'stage':'继续查询原任务，不重新提交','error':None},allow_terminal=True)
        self.enqueue(updated);return self.store.public_job(updated)

    def shutdown(self):
        self.stopping.set()
        with self.lock:
            for jid,event in self.cancel_events.items():
                if self.store.job(jid)['status'] in {'running','submitted'}:
                    self.store.update_job(jid,{'status':'interrupted','stage':'服务停止，输入与任务ID已保留'})
                event.set()
            for proc in self.processes.values():
                if proc.poll() is None:
                    try:proc.terminate()
                    except OSError:pass

        for response in list(self.connections.values()):
            threading.Thread(target=response.close,daemon=True).start()
        for thread in self.threads:thread.join(timeout=8)
