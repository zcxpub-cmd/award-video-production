import importlib.util
import base64
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
def module(name):
    s=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
P=module('public_release');C=module('content_tools')

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'source';self.root.mkdir()
        for name,text in {'README.md':'# Generic video workflow','LICENSE':'MIT','.codex-plugin/plugin.json':'{}','skills/science-achievement-film/SKILL.md':'# Generic workflow'}.items():
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    def tearDown(self):self.temp.cleanup()
    def test_public_zip_omits_private_dev_history_and_reports(self):
        for name in ['development/notes.txt','.git/config','outputs/private.mp4','.env']:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('not for distribution')
        output=self.root.parent/'release.zip';r=P.build(self.root,output)
        self.assertTrue(r['heuristic_scan_passed'])
        with zipfile.ZipFile(output) as z:
            self.assertEqual(len(z.namelist()),4)
            self.assertFalse(any('.git/' in n or 'development/' in n or 'outputs/' in n or '.env' in n for n in z.namelist()))
    def test_private_text_is_rejected_without_echo(self):
        marker='private'+'person'
        (self.root/'README.md').write_text('/'+'Users/'+marker+'/workspace\n'+'api_key = "'+'Z'*24+'"')
        report=P.scan(self.root,[marker])
        self.assertFalse(report['heuristic_scan_passed']);self.assertNotIn(marker,json.dumps(report));self.assertNotIn('Z'*24,json.dumps(report))
        with self.assertRaises(ValueError):P.build(self.root,self.root.parent/'bad.zip',[marker])
    def test_symlinks_and_runtime_files_rejected(self):
        source=self.root/'skills/science-achievement-film'
        (source/'leak.md').symlink_to(self.root/'README.md')
        with self.assertRaises(ValueError):P.scan(self.root)
        (source/'leak.md').unlink();(source/'reviews.json').write_text('{}')
        self.assertFalse(P.scan(self.root)['heuristic_scan_passed'])
    def test_local_or_nonpublishable_edition_refuses_before_creating_archive(self):
        for edition,publishable in [('local',False),('local',True),('public',False)]:
            with self.subTest(edition=edition,publishable=publishable):
                (self.root/'edition.json').write_text(json.dumps({'edition':edition,'publishable':publishable,'version':'1.0.0'}))
                output=self.root.parent/'must-not-exist'/'release.zip'
                with self.assertRaisesRegex(ValueError,'cannot be packaged'):P.build(self.root,output)
                self.assertFalse(output.parent.exists())
                self.assertIn('not_publishable_edition',[x['rule'] for x in P.scan(self.root)['findings']])
    def test_public_marker_documents_and_screenshot_are_packaged(self):
        (self.root/'edition.json').write_text(json.dumps({'edition':'public','publishable':True,'version':'1.0.0'}))
        folder=self.root/'docs/screenshots';folder.mkdir(parents=True)
        (self.root/'docs/features.md').write_text('Generic documented features')
        # A synthetic one-pixel PNG. This does not stand in for visual privacy review.
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6SAAAAABJRU5ErkJggg==')
        (folder/'01-demo.png').write_bytes(png)
        output=self.root.parent/'public.zip';report=P.build(self.root,output)
        self.assertEqual(report['screenshot_visual_review_required'],['docs/screenshots/01-demo.png'])
        self.assertFalse(report['screenshot_pixels_scanned'])
        self.assertTrue(report['human_privacy_review_required'])
        with zipfile.ZipFile(output) as z:
            self.assertIn('award-video-production/edition.json',z.namelist())
            self.assertIn('award-video-production/docs/features.md',z.namelist())
            self.assertEqual(z.read('award-video-production/docs/screenshots/01-demo.png'),png)
    def test_local_configs_fail_even_if_no_personal_text(self):
        for name in ['skills/science-achievement-film/local/runtime-config.json','skills/science-achievement-film/private/defaults.json','docs/private/notes.md','skills/science-achievement-film/references/local-runtime.md']:
            with self.subTest(name=name):
                p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
                report=P.scan(self.root)
                self.assertIn('local_private_configuration',[x['rule'] for x in report['findings']])
                with self.assertRaises(ValueError):P.build(self.root,self.root.parent/'bad.zip')
                p.unlink()
    def test_images_outside_screenshot_directory_and_binary_payloads_rejected(self):
        for name,content,rule in [('docs/private-photo.png',b'\x89PNG\r\n\x1a\n','image_outside_screenshot_directory'),('skills/science-achievement-film/assets/photo.jpg',b'\xff\xd8\xff','image_outside_screenshot_directory'),('docs/screenshots/fake.png',b'not image','invalid_screenshot_signature'),('docs/screenshots/archive.zip',b'PK','unapproved_binary_or_file_type')]:
            with self.subTest(name=name):
                p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
                self.assertIn(rule,[x['rule'] for x in P.scan(self.root)['findings']])
                with self.assertRaises(ValueError):P.build(self.root,self.root.parent/'bad.zip')
                p.unlink()
    def test_jpeg_signature_is_supported_but_not_visual_validation(self):
        p=self.root/'docs/screenshots/shot.jpeg';p.parent.mkdir(parents=True);p.write_bytes(b'\xff\xd8\xff\xe0fixture\xff\xd9')
        r=P.scan(self.root)
        self.assertTrue(r['heuristic_scan_passed'])
        self.assertFalse(r['screenshot_pixels_scanned'])
        self.assertIn('metadata',r['screenshot_check_scope'])
    def test_invalid_edition_marker_cannot_bypass_gate(self):
        marker=self.root/'edition.json'
        for data in [{'edition':'public','publishable':'true'}, {'edition':'unknown','publishable':True}, []]:
            marker.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'Invalid edition'):P.build(self.root,self.root.parent/'bad.zip')
        marker.unlink();marker.symlink_to(self.root/'nonexistent.json')
        with self.assertRaisesRegex(ValueError,'symlink'):P.build(self.root,self.root.parent/'bad.zip')
    def test_manuscript_bridge_keeps_unknowns_and_stable_sentence(self):
        manuscript={'project_title':'Demo','chapters':[{'chapter_id':'C01','title':'示例器件','units':['示例机构'],'sentences':[{'id':'C01_S01','text':'这只是演示。'}]}]}
        p=self.root/'manuscript.json';p.write_text(json.dumps(manuscript));out=self.root/'project.json'
        C.to_project(p,out)
        d=json.loads(out.read_text());self.assertEqual(d['chapters'][0]['narration'][-1]['id'],'C01_S01')
        self.assertEqual([s['role'] for s in d['chapters'][0]['narration']],['title','units','body'])
        self.assertTrue(all(s['voice_duration_s'] is None for s in d['chapters'][0]['narration']))
        self.assertIsNone(d['runtime']['opening_s'])

if __name__=='__main__':unittest.main()
