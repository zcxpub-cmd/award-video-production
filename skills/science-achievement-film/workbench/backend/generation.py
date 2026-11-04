"""One explicit billable request, durable uncertainty, query/download without resubmission."""
import importlib.util
import json
from pathlib import Path
import re
import time
from .domain import DomainError, text
from .media import atomic_json
from .render import Cancelled

path=Path(__file__).resolve().parents[2]/'references/integrations/seedance_http.py'
spec=importlib.util.spec_from_file_location('yingxu_ark_client',path)
client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)


def request_payload(settings,prompt,duration=5,ratio='16:9',resolution='720p'):
    text(prompt,'生成提示词',12000,False)
    if type(duration) is not int or not 4<=duration<=12 or ratio not in {'16:9','9:16','1:1'} or resolution not in {'480p','720p','1080p'}:
        raise DomainError('生成规格无效。')
    if not settings.get('generation_enabled') or not settings.get('generation_model') or not settings.get('credential_ref'):
        raise DomainError('请先配置并启用生成模型与本次账户凭据。')
    payload=dict(model=settings['generation_model'],content=[{'type':'text','text':prompt}],duration=duration,ratio=ratio,resolution=resolution,
                 watermark=True,generate_audio=False)
    client.validate_request(payload)
    return payload


def execute(store,media,job,folder,cancel,progress):
    private=job['_private'];payload=private['generation_payload'];key=store.credential(private['credential_ref'])
    api=client.endpoint(client.API_BASE);current=store.job(job['id']);external=current.get('external_id')
    if not external:
        if private.get('submission_attempted'):
            raise DomainError('此前提交结果未知；请先在服务商对账并绑定原任务ID，不能再次提交。')
        private['submission_attempted']=True
        reserved=store.update_job(job['id'],{'_private':private,'stage':'已登记提交意图，正在提交一次请求','progress':None})
        if reserved['status']!='running' or cancel.is_set():raise Cancelled()
        atomic_json(folder/'generation-journal.json',{'request_sha256':private['request_sha256'],'status':'unknown','external_id':None,'submission_count':1})
        try:
            response=client.send(api,key,json.dumps(payload,ensure_ascii=False).encode())
            external=response.get('id')
            if not isinstance(external,str) or external==key or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',external):raise ValueError()
        except Exception:
            store.update_job(job['id'],{'status':'unknown','stage':'提交结果未知，必须对账原任务','error':'没有再次提交。请在服务商确认原任务ID后继续查询。'})
            return None
        store.record_generation_receipt(job['id'],external)
        atomic_json(folder/'generation-journal.json',{'request_sha256':private['request_sha256'],'status':'submitted','external_id':external,'submission_count':1})
    failures=0;deadline=time.monotonic()+30*60
    while True:
        if cancel.is_set():raise Cancelled()
        try:
            response=client.send(api+'/'+external,key)
            status=response.get('status');failures=0
        except Exception:
            failures+=1
            if failures>=3:
                return {'status':'unknown','stage':'查询暂不可用，原任务ID已保留','error':'请稍后继续查询；不要重新生成。'}
            if cancel.wait(min(15,3*failures)):raise Cancelled()
            continue
        if response.get('id') not in {None,external}:
            return {'status':'unknown','stage':'服务商回执编号不符','error':'已保留原ID，请核对后继续查询。'}
        resolved=response.get('model')
        if resolved and not payload['model'].startswith('ep-') and resolved!=payload['model']:
            return {'status':'unknown','stage':'服务商回执模型不符','error':'原ID已保留，没有重新提交。'}
        if time.monotonic()>=deadline and status in {'queued','running'}:
            return {'status':'unknown','stage':'本轮查询已到时限','error':'服务商仍未完成，稍后继续查询原任务。'}
        if status=='succeeded':break
        if status in {'failed','cancelled','expired'}:
            return {'status':'failed','stage':'服务商任务结束','error':'服务商返回 '+status+'；原任务已保留，没有自动重试。'}
        if status not in {'queued','running'}:
            return {'status':'unknown','stage':'服务商返回未识别状态','error':'请核对原任务，不会重交。'}
        progress('服务商生成中 · '+status,None)
        if cancel.wait(3):raise Cancelled()
    if cancel.is_set():raise Cancelled()
    progress('下载官方结果并登记候选素材',None)
    destination=folder/'generated.mp4'
    if not destination.exists():
        try:
            url=response['content']['video_url']
            if not isinstance(url,str) or key in url:raise ValueError()
            client.download(url,destination)
        except Exception:
            return {'status':'unknown','stage':'结果下载待处理','error':'原任务已成功；下载未完成或主机不在官方白名单，请查询原任务，勿重新提交。'}
    if cancel.is_set():raise Cancelled()
    record=media.prepare(destination,'生成镜头-'+job['id']+'.mp4',job['project_id'],aid='generated-'+job['id'],origin='generated')
    record['metadata']['note']='外部生成候选 · 待内容与授权审核；不自动作为科学证据。'
    # Appending a candidate is commutative; each retry only rechecks CAS, never recontacts generation POST.
    for attempt in range(3):
        if cancel.is_set():raise Cancelled()
        current=store.history(job['project_id'])['present']
        if any(a['id']==record['metadata']['id'] and a.get('sha256')==record['sha256'] for a in current['assets']):
            history=store.history(job['project_id']);break
        try:
            history=store.add_asset(job['project_id'],current['revision'],record,'generation-'+job['id']+'-'+str(attempt),guard_job=job['id'])
            break
        except __import__('backend.domain',fromlist=['Conflict']).Conflict:
            if attempt==2:raise
    result={'asset_id':record['metadata']['id'],'revision':history['present']['revision'],'external_id':external,'resolved_model':resolved,'review_status':'pending','request_sha256':private['request_sha256']}
    atomic_json(folder/'generation-journal.json',{'request_sha256':private['request_sha256'],'status':'downloaded','external_id':external,'submission_count':1,'asset_sha256':record['sha256']})
    return {'status':'succeeded','stage':'生成候选已入素材库，待内容审核','progress':1,'result':result}
