import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('media_tools', ROOT/'scripts/media_tools.py')
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

class CaptionPagesTests(unittest.TestCase):
    def export(self, text, **options):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            result = M.subtitle_files({'pagination': {'max_columns': 12}, 'subtitles': [dict(start=1,end=11,text=text)], **options},root)
            return result, (root/'subtitles.srt').read_text(), (root/'layers.ass').read_text()

    def test_opt_in_semantic_pages_keep_punctuation_and_intervals(self):
        text = '这是第一句话，随后介绍新的方法。最后我们检查结果！'
        result,srt,ass = self.export(text)
        blocks=srt.strip().split('\n\n')
        self.assertGreater(len(blocks),1)
        self.assertEqual(''.join(b.splitlines()[2] for b in blocks),text)
        self.assertTrue(all(len(b.splitlines())==3 for b in blocks))
        self.assertTrue(all(b.splitlines()[2][0] not in '，。！？；：' for b in blocks))
        self.assertIn('00:00:01,000 -->',blocks[0]);self.assertIn('--> 00:00:11,000',blocks[-1])
        self.assertIn('estimated',result['timing_source'])
        self.assertIn('\\q2',ass)

    def test_titles_and_default_export_are_not_repaginated(self):
        _,srt,ass=self.export('原文。',titles=[dict(start=0,end=2,text='主标题\n副标题')])
        self.assertIn('主标题\\N副标题',ass)
        with tempfile.TemporaryDirectory() as d:
            r=M.subtitle_files({'subtitles':[dict(start=0,end=2,text='第一行\n第二行')]},Path(d))
            self.assertEqual(r['subtitle_count'],1)
            self.assertIn('第一行\n第二行',(Path(d)/'subtitles.srt').read_text())

    def test_latin_terms_not_split_and_oversize_fails_before_files(self):
        _,srt,_=self.export('首先观察 FGF1，再核对结果。')
        self.assertIn('FGF1',srt)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            with self.assertRaises(ValueError):
                M.subtitle_files({'pagination':{'max_columns':8},'subtitles':[dict(start=0,end=1,text='ABCDEFGHIJKLMNOPQRSTUVWXYZ')]},p)
            self.assertEqual(list(p.iterdir()),[])

    def test_too_short_or_bad_config_rejected(self):
        for pagination in [{'max_columns':True},{'max_columns':0},{'unknown':1}]:
            with self.subTest(pagination=pagination), tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):M.subtitle_files({'pagination':pagination},Path(d))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                M.subtitle_files({'pagination':{'max_columns':8},'subtitles':[dict(start=0,end=.01,text='中文测试字幕非常长需要分页进行展示。')]},Path(d))

    def test_half_centisecond_boundary_matches_ass_rounding(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            with self.assertRaisesRegex(ValueError, 'too short'):
                M.subtitle_files({'pagination':{'max_columns':4},'subtitles':[dict(start=.005,end=.02,text='一二三四五六七八')]},p)
            self.assertEqual(list(p.iterdir()),[])
            M.subtitle_files({'pagination':{'max_columns':4},'subtitles':[dict(start=.005,end=.025,text='一二三四五六七八')]},p)
            rows=[line.split(',') for line in (p/'layers.ass').read_text().splitlines() if line.startswith('Dialogue:')]
            self.assertEqual([(row[1],row[2]) for row in rows],[('0:00:00.01','0:00:00.02'),('0:00:00.02','0:00:00.03')])

    def test_ascii_closing_parenthesis_never_starts_exported_page(self):
        text='(一二三)后续'
        _,srt,_=self.export(text,pagination={'max_columns':4})
        pages=[b.splitlines()[2] for b in srt.strip().split('\n\n')]
        self.assertEqual(''.join(pages),text)
        self.assertFalse(any(p.startswith(')') or p.endswith('(') for p in pages))

    def test_technical_term_suffix_stays_with_latin_word(self):
        for term in ['C++','C#','CD4+','FGF1','IL-6']:
            with self.subTest(term=term):
                text='新算法使用'+term+'实现。'
                _,srt,_=self.export(text,pagination={'max_columns':6})
                pages=[b.splitlines()[2] for b in srt.strip().split('\n\n')]
                self.assertEqual(''.join(pages),text)
                self.assertTrue(any(term in p for p in pages))

if __name__=='__main__':unittest.main()
