"""Deterministic contracts and actual local media integration; no paid services."""
from copy import deepcopy
import io
import json
import math
from pathlib import Path
import struct
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave
import zipfile
from PIL import Image
from fastapi.testclient import TestClient
from .agents import LocalAgent
from .domain import Conflict, DomainError, apply_operations, arrange, new_project, validate
from .jobs import Jobs
from .media import Media, atomic_json
from .render import Renderer
from .server import create_app
from .store import Store


class FakeAgent:
    def health(self):return {'available':True,'models':['qwen2.5vl:7b'],'provider':'TEST DOUBLE'}
    def edit(self,p,instruction,selected,playhead,model,cancel,on_chunk,on_connection,recent_messages=()):
        return {'summary':'仅测试夹具：修改标题','history_action':'none','operations':[{'type':'update','id':'clip','patch':{'length':2}}]}, {'provider':'test-double'}


def simple_project():
    p=new_project('测试工程',project_id='test-project')
    p['assets']=[dict(id='image',name='red.png',kind='image',duration=0,url='',origin='demo')]
    p['clips']=[dict(id='clip',track='V1',asset='image',name='画面',start=0,length=3,sourceIn=0,volume=1,opacity=1,scale=1)]
    return p


class DomainTests(unittest.TestCase):
    def test_atomic_batch(self):
        p=simple_project();before=deepcopy(p)
        with self.assertRaises(DomainError):apply_operations(p,[{'type':'delete','id':'clip'},{'type':'delete','id':'missing'}])
        self.assertEqual(p,before)

    def test_reject_free_code_and_reference_paths(self):
        for op in [{'type':'shell','command':'anything'},{'type':'update','id':'clip','patch':{'path':'/private/file'}},{'type':'import','asset':{}}]:
            with self.assertRaises(DomainError):apply_operations(simple_project(),[op])

    def test_invalid_values(self):
        for patch_value in [{'start':-1},{'length':0},{'volume':3},{'opacity':float('nan')},{'track':'A1'}]:
            with self.subTest(patch=patch_value),self.assertRaises(DomainError):apply_operations(simple_project(),[{'type':'update','id':'clip','patch':patch_value}])

    def test_source_bound_and_lock(self):
        p=simple_project();p['assets'][0].update(kind='video',duration=3)
        with self.assertRaises(DomainError):apply_operations(p,[{'type':'update','id':'clip','patch':{'sourceIn':1}}])
        p['tracks'][2]['locked']=True
        with self.assertRaises(DomainError):apply_operations(p,[{'type':'delete','id':'clip'}])

    def test_split_preserves_source(self):
        p=apply_operations(simple_project(),[{'type':'split','id':'clip','time':1}])
        self.assertEqual([c['length'] for c in p['clips']],[1,2]);self.assertEqual(p['clips'][1]['sourceIn'],1)

    def test_arrange_meets_image_duration(self):
        p=simple_project();p['target']=17
        clips=arrange(p);self.assertEqual(clips[0]['length'],17);validate(dict(p,clips=clips))

    def test_arrange_rejects_hallucinated_id(self):
        with self.assertRaises(DomainError):arrange(simple_project(),[{'asset_id':'not-provided','reason':'invented'}])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.store.create(simple_project())
    def tearDown(self):self.temp.cleanup()

    def test_idempotent_and_no_rollback_on_replay(self):
        a=[{'type':'update','id':'clip','patch':{'start':1}}]
        self.store.edit('test-project',0,a,'request-1')
        self.store.edit('test-project',1,[{'type':'update','id':'clip','patch':{'length':2}}],'request-2')
        replay=self.store.edit('test-project',0,a,'request-1')
        self.assertTrue(replay['deduplicated']);self.assertEqual(replay['present']['revision'],2);self.assertEqual(replay['present']['clips'][0]['length'],2)

    def test_same_id_different_payload_fails(self):
        self.store.edit('test-project',0,[{'type':'delete','id':'clip'}],'one')
        with self.assertRaises(Conflict):self.store.edit('test-project',0,[{'type':'track','id':'A1','patch':{'muted':True}}],'one')

    def test_stale_revision_rejected(self):
        self.store.edit('test-project',0,[{'type':'update','id':'clip','patch':{'start':1}}],'one')
        with self.assertRaises(Conflict):self.store.edit('test-project',0,[{'type':'delete','id':'clip'}],'two')

    def test_restart_and_undo_redo(self):
        self.store.edit('test-project',0,[{'type':'delete','id':'clip'}],'one')
        reopened=Store(self.temp.name);self.assertEqual(reopened.history('test-project')['present']['clips'],[])
        h=reopened.move_history('test-project',1,'undo','undo-1');self.assertEqual(len(h['present']['clips']),1)
        h=reopened.move_history('test-project',2,'redo','redo-1');self.assertEqual(len(h['present']['clips']),0);self.assertEqual(h['present']['revision'],3)

    def test_theme_does_not_invalidate_model_but_aba_does(self):
        s=self.store.update_settings(0,{'theme':'light'});self.assertEqual(s['execution_revision'],0)
        s=self.store.update_settings(1,{'ollama_model':'other'});self.assertEqual(s['execution_revision'],1)
        s=self.store.update_settings(2,{'ollama_model':'qwen2.5vl:7b'});self.assertEqual(s['execution_revision'],2)

    def test_public_settings_never_return_key(self):
        self.store.update_settings(0,{'generation_key':'unit-secret-key-123456789','generation_enabled':True,'generation_model':'unit-model'})
        public=json.dumps(self.store.public_settings());self.assertNotIn('unit-secret',public);self.assertNotIn('credential_ref',public)

    def test_cancelled_job_cannot_commit(self):
        j,_=self.store.create_job('test-project','ai-edit','job-req',{}, {'snapshot':simple_project()})
        self.store.update_job(j['id'],{'status':'cancelled'})
        with self.assertRaises(Conflict):self.store.edit('test-project',0,[{'type':'delete','id':'clip'}],'apply',guard_job=j['id'])

    def test_model_revision_checked_in_write_transaction(self):
        self.store.update_settings(0,{'ollama_model':'other'})
        with self.assertRaises(Conflict):self.store.edit('test-project',0,[{'type':'delete','id':'clip'}],'apply',execution=0)

    def test_job_deduplication_before_revision_check(self):
        j,_=self.store.create_job('test-project','render','r',{'base':0},{'snapshot':simple_project()},0)
        self.store.edit('test-project',0,[{'type':'delete','id':'clip'}],'edit')
        again,created=self.store.create_job('test-project','render','r',{'base':0},{'snapshot':simple_project()},0)
        self.assertFalse(created);self.assertEqual(j['id'],again['id'])

    def test_unknown_directory_is_not_reinitialized(self):
        other=Path(self.temp.name)/'unknown';other.mkdir();(other/'important.txt').write_text('preserve')
        with self.assertRaises(DomainError):Store(other)
        self.assertEqual((other/'important.txt').read_text(),'preserve')


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=create_app(self.temp.name,workers=False,agent=FakeAgent(),seed=False)
        self.client=TestClient(self.app,base_url='http://127.0.0.1:8787')
        boot=self.client.get('/api/bootstrap');self.token=boot.json()['token'];self.headers={'X-Yingxu-Token':self.token,'Origin':'http://127.0.0.1:8787'}
        self.app.state.store.create(simple_project())
    def tearDown(self):self.client.close();self.temp.cleanup()

    def test_cross_origin_and_host_rejected(self):
        self.assertEqual(self.client.get('/api/bootstrap',headers={'Origin':'https://external.invalid'}).status_code,403)
        self.assertEqual(self.client.get('/api/bootstrap',headers={'Host':'evil.invalid'}).status_code,403)

    def test_write_requires_header_and_session(self):
        self.assertEqual(self.client.post('/api/projects',json={'name':'bad'}).status_code,403)
        self.client.cookies.clear()
        self.assertEqual(self.client.post('/api/projects',json={'name':'bad'},headers=self.headers).status_code,403)

    def test_manual_api_edit_persists(self):
        r=self.client.post('/api/projects/test-project/edit',headers=self.headers,json={'expected_revision':0,'request_id':'one','operations':[{'type':'update','id':'clip','patch':{'start':1}}]})
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['present']['revision'],1)

    def test_upload_and_range_are_real_and_persist(self):
        image=Image.new('RGB',(64,32),(220,50,30));out=io.BytesIO();image.save(out,'PNG')
        r=self.client.post('/api/projects/test-project/assets?expected_revision=0&request_id=upload-1',headers=self.headers,files={'file':('actual.png',out.getvalue(),'image/png')})
        self.assertEqual(r.status_code,200,r.text)
        a=r.json()['present']['assets'][-1];self.assertEqual(a['width'],64)
        response=self.client.get(a['url'],headers={'Range':'bytes=0-7'})
        self.assertEqual(response.status_code,206);self.assertEqual(response.content,b'\x89PNG\r\n\x1a\n')
        restarted=create_app(self.temp.name,workers=False,agent=FakeAgent(),seed=False)
        client=TestClient(restarted,base_url='http://127.0.0.1:8787');client.get('/api/bootstrap')
        self.assertEqual(client.get(a['url']).status_code,200);client.close()

    def test_path_traversal_archive_refused(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('../outside.txt','no');z.writestr('portable-project.json','{}')
        r=self.client.post('/api/import-project',headers=self.headers,files={'file':('unsafe.zip',out.getvalue(),'application/zip')})
        self.assertEqual(r.status_code,400);self.assertFalse((Path(self.temp.name).parent/'outside.txt').exists())

    def test_unapproved_paid_task_cannot_start(self):
        r=self.client.post('/api/projects/test-project/jobs',headers=self.headers,json={'kind':'generation','expected_revision':0,'request_id':'gen','options':{'prompt':'unit test'}})
        self.assertEqual(r.status_code,400);self.assertEqual(self.app.state.store.jobs(),[])

    def test_private_payload_not_in_job_response(self):
        r=self.client.post('/api/projects/test-project/jobs',headers=self.headers,json={'kind':'render','expected_revision':0,'request_id':'render1','options':{}})
        self.assertEqual(r.status_code,200);self.assertNotIn('_private',r.json())
        self.assertNotIn('credential_ref',r.text)

    def test_vision_toggle_blocks_observation_before_job_creation(self):
        self.app.state.store.update_settings(0,{'vision_enabled':False})
        r=self.client.post('/api/projects/test-project/jobs',headers=self.headers,json={'kind':'observe','expected_revision':0,'request_id':'off','options':{'asset_id':'image'}})
        self.assertEqual(r.status_code,400);self.assertIn('画面观察已关闭',r.json()['detail']);self.assertFalse(self.app.state.store.jobs())

    def test_runtime_data_dir_is_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            first=create_app(directory,agent=FakeAgent(),seed=False)
            with TestClient(first,base_url='http://127.0.0.1:8787'):
                with self.assertRaises(DomainError):create_app(directory,agent=FakeAgent(),seed=False)
            with TestClient(create_app(directory,agent=FakeAgent(),seed=False),base_url='http://127.0.0.1:8787') as restarted:
                self.assertEqual(restarted.get('/api/health').status_code,200)


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.store.create(simple_project())
        self.media=Media(self.temp.name);self.jobs=Jobs(self.store,self.media,FakeAgent(),start=False)
        self.store.update_settings(0,{'generation_key':'unit-key-not-real-12345','generation_model':'unit-model','generation_enabled':True})
        self.options={'prompt':'Synthetic unit test, never sent to a real provider','approve_billable':True,'approve_text_transfer':True}
    def tearDown(self):self.temp.cleanup()

    def test_ambiguous_post_is_recorded_once_and_never_resubmitted(self):
        j=self.jobs.submit('test-project','generation','gen-one',0,self.options)
        with patch('backend.generation.client.send',side_effect=TimeoutError()) as send:
            self.jobs.run(j['id']);self.jobs.run(j['id']);self.assertEqual(send.call_count,1)
        stored=self.store.job(j['id']);self.assertEqual(stored['status'],'unknown');self.assertTrue(stored['_private']['submission_attempted'])
        with self.assertRaises(DomainError):self.jobs.resume_generation(j['id'])
        with self.assertRaises(Conflict):self.jobs.submit('test-project','generation','gen-two',0,self.options)

    def test_credential_and_signed_urls_not_in_public_job(self):
        j=self.jobs.submit('test-project','generation','gen-one',0,self.options)
        self.assertNotIn('unit-key',json.dumps(j));self.assertNotIn('_private',j)

    def test_local_cancel_blocks_generation_before_post(self):
        j=self.jobs.submit('test-project','generation','gen-one',0,self.options);self.jobs.cancel(j['id'])
        with patch('backend.generation.client.send') as send:self.jobs.run(j['id']);send.assert_not_called()

    def test_inflight_receipt_survives_cancel_and_resumes_by_get_only(self):
        job=self.jobs.submit('test-project','generation','gen-one',0,self.options)
        jid=job['id']
        def send(url,key,payload=None):
            if payload:
                self.jobs.cancel(jid)
                return {'id':'remote-fixture-id'}
            self.assertTrue(url.endswith('/remote-fixture-id'))
            return {'status':'succeeded','model':'unit-model','content':{'video_url':'https://fixture.invalid/result.mp4'}}
        sample=Path(__file__).resolve().parents[2]/'assets/wall/cover/ocean.mp4'
        with patch('backend.generation.client.send',side_effect=send) as sent,patch('backend.generation.client.download',side_effect=lambda _url,target:shutil.copyfile(sample,target)):
            self.jobs.run(jid)
            cancelled=self.store.job(jid);self.assertEqual(cancelled['status'],'cancelled');self.assertEqual(cancelled['external_id'],'remote-fixture-id')
            self.jobs.resume_generation(jid);self.jobs.run(jid)
            self.assertEqual(sent.call_count,2);self.assertEqual(len(sent.call_args_list[1].args),2)
        self.assertEqual(self.store.job(jid)['status'],'succeeded')
        self.assertEqual(self.store.history('test-project')['present']['assets'][-1]['origin'],'generated')


class RenderIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();root=Path(cls.temp.name);cls.store=Store(root);cls.media=Media(root)
        red=root/'red.png';blue=root/'blue.png';Image.new('RGB',(320,180),(210,20,20)).save(red);Image.new('RGB',(320,180),(20,30,220)).save(blue)
        tone=root/'tone.wav';rate=16000
        with wave.open(str(tone),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate)
            f.writeframes(b''.join(struct.pack('<h',int(3000*math.sin(2*math.pi*440*i/rate))) for i in range(rate*2)))
        p=new_project('实际渲染测试',project_id='actual-render',target=2);cls.records={}
        for aid,path in [('red',red),('blue',blue),('tone',tone)]:
            record=cls.media.prepare(path,path.name,p['id'],aid);cls.records[aid]=record;p['assets'].append(record['metadata'])
        base=dict(sourceIn=0,volume=1,opacity=1,scale=1)
        p['clips']=[dict(base,id='base',track='V1',asset='red',name='底图',start=0,length=2),dict(base,id='overlay',track='V2',asset='blue',name='叠加',start=.6,length=.8,scale=.4),dict(base,id='title',track='T1',name='片名',text='影序验证',start=.3,length=1.2),dict(base,id='audio',track='A2',asset='tone',name='声音',start=.5,length=.8,volume=.5)]
        cls.project=p;cls.folder=root/'result'
        cls.result=Renderer(cls.media).render(p,cls.records,cls.folder,{'resolution':'720p','format':'mov'},threading.Event(),lambda *args:None)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def frame(self,t):
        raw=self.media.run([self.media.ffmpeg,'-hide_banner','-v','error','-ss',str(t),'-i',str(self.folder/'film.mp4'),'-frames:v','1','-f','image2pipe','-vcodec','png','pipe:1'])
        return Image.open(io.BytesIO(raw)).convert('RGB')

    def test_actual_output_decodes_and_has_expected_dimensions(self):
        self.assertTrue(self.result['qc']['full_decode_passed']);self.assertAlmostEqual(self.result['duration'],2,places=2)
        self.assertEqual((self.result['qc']['width'],self.result['qc']['height']),(1280,720))

    def test_mov_delivers_pcm_and_matching_picture(self):
        info=self.media.probe(self.folder/'film.mov')
        codecs={s['codec_type']:s['codec_name'] for s in info['streams']}
        self.assertEqual(codecs,{'video':'h264','audio':'pcm_s24le'});self.assertIn('film.mov',self.result['files'])
        self.assertAlmostEqual(float(info['format']['duration']),2,places=2)

    def test_overlay_only_exists_in_its_time_range(self):
        before=self.frame(.1).getpixel((640,360));during=self.frame(.9).getpixel((640,360));after=self.frame(1.8).getpixel((640,360))
        self.assertGreater(before[0],before[2]*3);self.assertGreater(during[2],during[0]*3);self.assertGreater(after[0],after[2]*3)

    def test_chinese_title_produces_visible_text_pixels(self):
        image=self.frame(.9);pixels=list(image.crop((350,330,930,450)).get_flattened_data())
        self.assertGreater(sum(r>200 and g>200 and b>180 for r,g,b in pixels),100)

    def test_audio_is_delayed_and_mixed(self):
        raw=self.media.run([self.media.ffmpeg,'-v','error','-i',str(self.folder/'film.mp4'),'-vn','-ac','1','-ar','8000','-f','s16le','pipe:1'])
        from array import array
        values=array('h');values.frombytes(raw)
        rms=lambda a,b:math.sqrt(sum(v*v for v in values[int(a*8000):int(b*8000)])/max(1,int((b-a)*8000)))
        self.assertGreater(rms(.7,.9),300);self.assertLess(rms(.05,.2),5);self.assertLess(rms(1.6,1.8),5)

    def test_delivery_package_contains_media_and_relative_project(self):
        with zipfile.ZipFile(self.folder/'delivery.zip') as z:
            self.assertIsNone(z.testzip());data=json.loads(z.read('portable-project.json'))
            self.assertTrue(all(a['url'].startswith('media/') for a in data['project']['assets']))
            self.assertIn('subtitles.srt',z.namelist());self.assertIn('timeline.edl',z.namelist())


if __name__=='__main__':unittest.main(verbosity=2)
