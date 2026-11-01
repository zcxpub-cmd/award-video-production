import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile


def module(name):
    p=Path(__file__).resolve().parents[1]/'scripts'/(name+'.py')
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


C=module('content_tools');A=module('archive_tools')


class ContentArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def write(self,name,data):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,ensure_ascii=False));return p
    def manuscript(self):
        return {'project_title':'测试颁奖片','opening':'这是片头。','ending':'这是片尾。','chapters':[{'chapter_id':'C01','title':'示例成果','units':['甲机构','乙机构'],'sentences':[{'id':'C01_S01','text':'器件保持完整。','tts_text':'器件保持完整。','source_refs':[{'document_id':'D01','locator':'body-p-1'}]}]}]}
    def test_docx_roundtrip_and_preserved_boundaries(self):
        src=self.write('manuscript.json',self.manuscript());out=self.root/'export'
        C.export_manuscript(src,out)
        C.ingest(out/'narration.docx',self.root/'ingested.json','D01')
        blocks=C.load(self.root/'ingested.json')['blocks'];texts=[x['text'] for x in blocks]
        self.assertIn('这是片头。',texts);self.assertIn('这是片尾。',texts);self.assertIn('参与单位：甲机构、乙机构',texts)
        self.assertIn('器件保持完整。',texts);self.assertTrue((out/'C01.docx').is_file())
        with self.assertRaises(ValueError):C.export_manuscript(src,out)
    def test_duplicate_sentence_and_path_id_rejected(self):
        d=self.manuscript();d['chapters'][0]['sentences']*=2
        p=self.write('duplicate.json',d)
        with self.assertRaises(ValueError):C.export_manuscript(p,self.root/'bad')
        d=self.manuscript();d['chapters'][0]['chapter_id']='../escape'
        with self.assertRaises(ValueError):C.export_manuscript(self.write('escape.json',d),self.root/'bad2')
    def test_ppt_preserves_slide_order_and_animation_flag(self):
        p=self.root/'slides.pptx'
        with zipfile.ZipFile(p,'w') as z:
            z.writestr('ppt/presentation.xml','<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId r:id="b"/><p:sldId r:id="a"/></p:sldIdLst></p:presentation>')
            z.writestr('ppt/_rels/presentation.xml.rels','<Relationships><Relationship Id="a" Target="slides/slide1.xml"/><Relationship Id="b" Target="slides/slide2.xml"/></Relationships>')
            for i in [1,2]:
                z.writestr(f'ppt/slides/slide{i}.xml',f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:p><a:t>page{i}</a:t></a:p>'+('<p:timing/>' if i==2 else '')+'</p:sld>')
        C.ingest(p,self.root/'slides.json','SLIDES')
        blocks=C.load(self.root/'slides.json')['blocks']
        self.assertEqual(blocks[0]['text'],'page2');self.assertTrue(blocks[0]['animation_present']);self.assertFalse(blocks[1]['animation_present'])
    def test_handoff_coverage_and_local_ai_flag(self):
        src=self.write('manuscript.json',self.manuscript());media=self.root/'image.png';media.write_bytes(b'demo')
        shots=self.write('shots.json',{'shots':[{'asset_id':'A01','source_path':'image.png','sentence_ids':['C01_S01'],'semantic_reason':'展现形态','origin':'submitted animation','local_codex_generated':False}]})
        r=C.handoff(src,shots,self.root/'wall.json')
        self.assertTrue(r['reference_structure_valid']);self.assertEqual(r['semantic_review_status'],'pending')
        self.assertFalse(C.load(self.root/'wall.json')['assets'][0]['display_ai_badge'])
        self.assertEqual(Path(C.load(self.root/'wall.json')['assets'][0]['source_path']),media.resolve())
        shots=self.write('shots2.json',{'shots':[]});r=C.handoff(src,shots,self.root/'wall2.json')
        self.assertFalse(r['reference_structure_valid'])
    def archive(self):
        p=self.root/'source'/'media.bin';p.parent.mkdir();p.write_bytes(b'protected media')
        conf=self.write('source/config.json',{'source_path':'media.bin'})
        plan=self.write('plan.json',{'dependency_review_complete':True,'files':[{'path':str(p),'role':'media'},{'path':str(conf),'role':'configuration'}]})
        dest=self.root/'archive';A.create(plan,dest);return p,conf,dest
    def test_archive_copy_rewrite_and_relocate_without_original(self):
        p,conf,dest=self.archive();out=dest/'restored-config.json'
        A.rewrite_json(dest,conf,out);p.unlink();conf.unlink()
        self.assertTrue(A.verify(dest)['hashes_verified'])
        relocated=self.root/'moved';dest.rename(relocated)
        cfg=A.load(relocated/'restored-config.json')
        self.assertEqual((relocated/cfg['source_path']).read_bytes(),b'protected media')
        self.assertEqual(A.verify(relocated)['editor_reopen_status'],'not_verified')
    def test_archived_configuration_rewrites_after_original_tree_is_gone(self):
        p,conf,dest=self.archive();manifest=A.load(dest/'archive-manifest.json')
        archived_config=manifest['path_mapping'][str(conf.resolve())]
        p.unlink();conf.unlink();p.parent.rmdir()
        relocated=self.root/'relocated-archive';dest.rename(relocated)
        out=relocated/'restored-config.json'
        result=A.rewrite_json(relocated,relocated/archived_config,out)
        self.assertEqual(result['rewritten_paths'],1)
        self.assertEqual((out.parent/A.load(out)['source_path']).read_bytes(),b'protected media')
    def test_archive_preserves_program_executable_mode_and_rejects_bad_mapping(self):
        program=self.root/'program.py';program.write_text('print("demo")\n');program.chmod(0o755)
        plan=self.write('executable-plan.json',{'dependency_review_complete':True,'files':[{'path':str(program)}]})
        dest=self.root/'program-archive';A.create(plan,dest);manifest=A.load(dest/'archive-manifest.json')
        copied=dest/manifest['files'][0]['archive_path']
        self.assertTrue(copied.stat().st_mode & 0o100)
        self.assertNotEqual(copied.stat().st_ino,program.stat().st_ino)
        manifest['path_mapping'][str(program.resolve())]='files/wrong.py'
        (dest/'archive-manifest.json').write_text(json.dumps(manifest))
        self.assertFalse(A.verify(dest)['hashes_verified'])
    def test_recipe_subtitle_dependency_is_relocated_and_unmapped_paths_reported(self):
        subtitle=self.write('source/captions.json',{'subtitles':[{'start':0,'end':1,'text':'demo'}]})
        recipe=self.write('source/edit.json',{'subtitles':'captions.json','source_path':'unlisted.mp4'})
        plan=self.write('subtitle-plan.json',{'dependency_review_complete':True,'files':[{'path':str(subtitle)},{'path':str(recipe)}]})
        dest=self.root/'subtitle-archive';A.create(plan,dest);manifest=A.load(dest/'archive-manifest.json')
        stored=dest/manifest['path_mapping'][str(recipe.resolve())]
        subtitle.unlink();recipe.unlink()
        out=dest/'relinked.json';result=A.rewrite_json(dest,stored,out)
        self.assertEqual(result['rewritten_paths'],1)
        self.assertEqual(A.load(out.parent/A.load(out)['subtitles'])['subtitles'][0]['text'],'demo')
        self.assertFalse(result['explicit_paths_relocated'])
        self.assertEqual(result['unmapped_paths'][0]['value'],'unlisted.mp4')
    def test_archive_refuses_unreviewed_missing_and_symlink(self):
        p=self.write('unreviewed.json',{'files':[]})
        with self.assertRaises(ValueError):A.create(p,self.root/'bad')
        data=self.root/'file';data.write_text('x');link=self.root/'link';link.symlink_to(data)
        p=self.write('symlink.json',{'dependency_review_complete':True,'files':[{'path':'link'}]})
        with self.assertRaises(ValueError):A.create(p,self.root/'bad2')
    def test_tamper_and_escape_detected(self):
        _,_,dest=self.archive();manifest=A.load(dest/'archive-manifest.json')
        (dest/manifest['files'][0]['archive_path']).write_text('tampered')
        self.assertFalse(A.verify(dest)['hashes_verified'])
        with self.assertRaises(ValueError):A.manifest_path(dest,'../outside')
    def test_discover_does_not_claim_complete_or_promote_candidates(self):
        p=self.root/'asset.dat';p.write_bytes(b'x')
        conf=self.write('conf.json',{'source_path':'asset.dat'})
        src=self.write('discover.json',{'files':[],'references':['conf.json']})
        A.discover(src,self.root/'found.json');d=A.load(self.root/'found.json')
        self.assertFalse(d['dependency_review_complete']);self.assertEqual(len(d['files']),1);self.assertEqual(len(d['candidates']),1)
    def test_cleanup_quarantine_restore_and_hash_gate(self):
        original,_,dest=self.archive();old=self.root/'old.bin';old.write_bytes(b'old')
        config=self.write('cleanup.json',{'verified_archives':[str(dest)],'protect':[str(original)],'targets':[str(old),str(original),str(dest)]})
        plan=self.root/'cleanup-plan.json';r=A.cleanup_plan(config,plan)
        self.assertEqual(r['candidates'],1)
        with self.assertRaises(ValueError):A.quarantine(plan,self.root/'wrong','bad-hash')
        q=self.root/'quarantine';A.quarantine(plan,q,A.sha(plan));self.assertFalse(old.exists());self.assertTrue(original.exists())
        A.restore(q);self.assertEqual(old.read_bytes(),b'old')
    def test_purge_only_quarantined_files_and_verified_archive(self):
        _,_,dest=self.archive();old=self.root/'old.bin';old.write_text('old')
        config=self.write('cleanup.json',{'verified_archives':[str(dest)],'targets':[str(old)]})
        plan=self.root/'cleanup-plan.json';A.cleanup_plan(config,plan);q=self.root/'quarantine'
        A.quarantine(plan,q,A.sha(plan));manifest=q/'quarantine-manifest.json'
        receipt=A.purge(q,A.sha(manifest));self.assertEqual(receipt['deleted_files'],1);self.assertTrue(A.verify(dest)['hashes_verified'])
    def cleanup_pair(self):
        _,_,archive=self.archive();folder=self.root/'working';folder.mkdir()
        files=[folder/'first.bin',folder/'second.bin']
        for index,p in enumerate(files):p.write_text(f'old-{index}')
        config=self.write('cleanup-pair.json',{'verified_archives':[str(archive)],'targets':[str(folder)]})
        plan=self.root/'pair-plan.json';A.cleanup_plan(config,plan)
        return files,plan,self.root/'pair-quarantine',archive
    def test_protected_directory_hardlink_alias_is_excluded(self):
        source,_,archive=self.archive();alias=self.root/'alias.bin';os.link(source,alias)
        config=self.write('protected-directory.json',{'verified_archives':[str(archive)],'protect':[str(source.parent)],'targets':[str(alias)]})
        output=self.root/'protected-plan.json';result=A.cleanup_plan(config,output)
        self.assertEqual(result['candidates'],0)
        self.assertEqual(A.load(output)['skipped'][0]['reason'],'hard link to protected file')
    def test_restore_rejects_replaced_parent_symlink_and_dangling_destination(self):
        files,plan,q,_=self.cleanup_pair();A.quarantine(plan,q,A.sha(plan))
        former=files[0].parent;former.rename(self.root/'former-directory')
        outside=self.root/'unrelated';outside.mkdir();former.symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):A.restore(q)
        self.assertEqual(list(outside.iterdir()),[])
        former.unlink();(self.root/'former-directory').rename(former)
        files[0].symlink_to(self.root/'nonexistent-target')
        with self.assertRaises(ValueError):A.restore(q)
        self.assertTrue(files[0].is_symlink());files[0].unlink()
        self.assertEqual(A.restore(q)['restored_files'],2)
    def test_failed_quarantine_retains_full_intent_and_can_restore_after_failed_rollback(self):
        files,plan,q,_=self.cleanup_pair();real=A.move_exclusive;calls=[]
        def fail_after_one(source,dest):
            calls.append((source,dest))
            if len(calls)>1:raise OSError('simulated storage interruption')
            real(source,dest)
        with mock.patch.object(A,'move_exclusive',side_effect=fail_after_one):
            with self.assertRaises(OSError):A.quarantine(plan,q,A.sha(plan))
        data=A.load(q/'quarantine-manifest.json')
        self.assertEqual(len(data['files']),2)
        self.assertEqual(data['operation_status'],'rollback_incomplete')
        with self.assertRaises(ValueError):A.purge(q,A.sha(q/'quarantine-manifest.json'))
        self.assertEqual(A.restore(q)['restored_files'],2)
        self.assertEqual([p.read_text() for p in files],['old-0','old-1'])
    def test_interrupted_restore_resumes_without_overwrite(self):
        files,plan,q,_=self.cleanup_pair();A.quarantine(plan,q,A.sha(plan));real=A.move_exclusive;calls=[]
        def fail_second(source,dest):
            calls.append(source)
            if len(calls)==2:raise OSError('simulated interruption')
            real(source,dest)
        with mock.patch.object(A,'move_exclusive',side_effect=fail_second):
            with self.assertRaises(OSError):A.restore(q)
        self.assertEqual(sum(p.exists() for p in files),1)
        self.assertEqual(A.restore(q)['restored_files'],2)
        self.assertEqual(A.restore(q)['restored_files'],2)
        self.assertEqual([p.read_text() for p in files],['old-0','old-1'])
    def test_purge_interruption_resumes_only_remaining_reviewed_members(self):
        _,plan,q,archive=self.cleanup_pair();A.quarantine(plan,q,A.sha(plan));manifest=q/'quarantine-manifest.json'
        data=A.load(manifest);second=(q/data['files'][1]['quarantine_path']).resolve();real=Path.unlink
        def fail_second(path,*args,**kwargs):
            if path.resolve()==second:raise OSError('simulated delete interruption')
            return real(path,*args,**kwargs)
        with mock.patch.object(Path,'unlink',fail_second):
            with self.assertRaises(OSError):A.purge(q,A.sha(manifest))
        self.assertFalse((q/data['files'][0]['quarantine_path']).exists());self.assertTrue(second.exists())
        self.assertEqual(A.purge(q,A.sha(manifest))['deleted_files'],2)
        self.assertFalse(second.exists());self.assertTrue(A.verify(archive)['hashes_verified'])
    def test_duplicate_quarantine_entries_rejected_before_any_delete(self):
        _,plan,q,_=self.cleanup_pair();A.quarantine(plan,q,A.sha(plan));manifest=q/'quarantine-manifest.json'
        data=A.load(manifest);data['files'].append(data['files'][0]);manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError):A.purge(q,A.sha(manifest))
        self.assertTrue(all((q/row['quarantine_path']).is_file() for row in data['files']))


if __name__=='__main__':unittest.main()
