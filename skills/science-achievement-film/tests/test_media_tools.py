"""Meaningful local ffmpeg regression and short-film integration checks (no network)."""
import array
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'media_tools.py'
spec = importlib.util.spec_from_file_location('media_tools', SCRIPT)
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)
FULL = '/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg'
FFMPEG = os.environ.get('MEDIA_TEST_FFMPEG', FULL if Path(FULL).exists() else shutil.which('ffmpeg') or '')
FFPROBE = os.environ.get('MEDIA_TEST_FFPROBE', shutil.which('ffprobe') or '')


class SchemaTests(unittest.TestCase):
    def test_nonfinite_boolean_unknown_fields_rejected(self):
        for value in [float('nan'), float('inf'), True, '1', -1]:
            with self.assertRaises(media.MediaError):
                media.number(value, 'value')
        with self.assertRaises(media.MediaError):
            media.keys({'unknown': 1}, ['known'], 'recipe')
        with self.assertRaises(media.MediaError):
            media.video_params({'width': 161})

    def test_measured_subtitles_and_editable_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            result = media.subtitle_files({'subtitles': [{'start': .125, 'end': 1.5, 'text': '中文\n第二行{\\pos(0,0)}'}],
                                          'titles': [{'start': 0, 'end': 2, 'text': '章标题', 'x': 800, 'y': 120}]}, target, 2)
            self.assertEqual(result['title_count'], 1)
            srt = (target / 'subtitles.srt').read_text()
            ass = (target / 'layers.ass').read_text()
            self.assertIn('00:00:00,125 --> 00:00:01,500', srt)
            self.assertIn('\\an5\\pos(800,120)', ass)
            self.assertIn('｛＼pos(0,0)｝', ass)
            self.assertNotIn('章标题', srt)
            with self.assertRaises(media.MediaError):
                media.subtitle_files({'subtitles': [{'start': 1, 'end': .5, 'text': 'invalid'}]}, target)


@unittest.skipUnless(FFMPEG and FFPROBE, 'Local ffmpeg/ffprobe required')
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='science-film-media-test-')
        cls.work = Path(cls.tmp.name)
        cls.source = cls.work / "source '中文'.mp4"
        cls.still = cls.work / 'portrait.png'
        cls.tone = cls.work / 'tone.wav'
        cls.run_ff(['-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=10:d=2',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(cls.source)])
        cls.run_ff(['-f', 'lavfi', '-i', 'color=c=lime:s=60x120:d=0.1', '-frames:v', '1', str(cls.still)])
        cls.run_ff(['-f', 'lavfi', '-i', 'sine=frequency=700:sample_rate=48000:duration=1', '-c:a', 'pcm_s16le', str(cls.tone)])
        cls.original = {p: media.sha256(p) for p in [cls.source, cls.still, cls.tone]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def run_ff(cls, args, binary=False):
        proc = subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-n', *args],
                              capture_output=True, check=False)
        if proc.returncode:
            raise AssertionError(proc.stderr.decode(errors='replace'))
        return proc.stdout if binary else proc.stdout.decode(errors='replace')

    def cli(self, args, ok=True):
        proc = subprocess.run([sys.executable, str(SCRIPT), '--ffmpeg', FFMPEG, '--ffprobe', FFPROBE, *map(str, args)],
                              capture_output=True, text=True, cwd=self.work)
        if ok:
            self.assertEqual(proc.returncode, 0, proc.stderr)
        else:
            self.assertNotEqual(proc.returncode, 0)
        return proc

    def json_file(self, name, spec):
        path = self.work / name
        path.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
        return path

    def test_audio_explicit_gaps_duck_and_mute_preserve_duration(self):
        recipe = self.json_file('audio.json', {'duration': 2, 'tracks': [
            {'path': self.tone.name, 'duration': 1, 'at': .3, 'volume': .8,
             'duck': {'volume': .2, 'intervals': [[.65, .9]]}}], 'mute': [[1.05, 1.2]]})
        output = self.work / 'audio-package'
        self.cli(['audio', recipe, '--output', output])
        raw = self.run_ff(['-i', str(output / 'mix.wav'), '-ac', '1', '-f', 's16le', '-'], binary=True)
        data = array.array('h', raw)
        def power(a, b):
            values = data[int(a * 48000):int(b * 48000)]
            return sum(x * x for x in values) / len(values)
        self.assertAlmostEqual(len(data) / 48000, 2, places=3)
        self.assertEqual(power(.05, .2), 0, 'Explicit narration lead interval must remain silent')
        self.assertGreater(power(.4, .55), 10000)
        self.assertLess(power(.72, .82), power(.4, .55) * .08, 'Duck must lower the specified interval')
        self.assertEqual(power(1.09, 1.15), 0, 'Mute must preserve duration while zeroing the requested interior')
        self.assertGreater(power(1.24, 1.28), 10000)

    def test_all_commands_short_film_fit_subtitles_chapters_and_qc(self):
        subtitle = self.json_file('captions.json', {'width': 160, 'height': 90, 'font_size': 10,
            'subtitles': [{'start': .2, 'end': .7, 'text': '实测时间字幕'}],
            'titles': [{'start': 0, 'end': .6, 'text': '第一章', 'x': 80, 'y': 20, 'font_size': 14}]})
        recipe = self.json_file('edit.json', {'version': 1, 'canvas': {'width': 160, 'height': 90, 'fps': 10},
            'clips': [{'path': self.source.name, 'in': 0, 'out': 1.2, 'fade_in': .1, 'fade_out': .1},
                      {'path': self.still.name, 'kind': 'image', 'duration': 1}],
            'subtitles': subtitle.name,
            'audio': {'tracks': [{'path': self.tone.name, 'in': 0, 'duration': 2.2, 'loop': True,
                                 'at': 0, 'volume': .1, 'role': 'bgm', 'fade_out': .1},
                                {'path': self.tone.name, 'duration': .7, 'at': .3, 'role': 'narration'}],
                      'mute': [[1.4, 1.6]], 'keep_clip_audio': False},
            'chapters': [{'id': 'C01', 'start': 0, 'end': 1.2}, {'id': 'C02', 'start': 1.2, 'end': 2.2}]})
        output = self.work / 'film-package'
        self.cli(['render', recipe, '--output', output])
        report = json.loads((output / 'report.json').read_text())
        self.assertEqual(report['status'], 'success')
        self.assertEqual(report['result']['chapters'], ['C01', 'C02'])
        self.assertAlmostEqual(report['result']['duration_s'], 2.2)
        self.assertTrue((output / 'layers.ass').is_file())
        self.assertEqual({x.name for x in output.iterdir()}, {'report.json', 'film.mp4', 'C01.mp4', 'C02.mp4', 'layers.ass', 'subtitles.srt'})
        # Inspect actual decoded portrait pixels: green center, padded black edges.
        raw = self.run_ff(['-ss', '1.9', '-i', str(output / 'film.mp4'), '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], binary=True)
        pixel = lambda x, y: raw[(y * 160 + x) * 3:(y * 160 + x) * 3 + 3]
        self.assertLess(max(pixel(10, 45)), 20)
        self.assertGreater(pixel(80, 45)[1], 200)
        self.assertLess(max(pixel(150, 45)), 20)
        # 60:120 remains 1:2 inside the 160:90 canvas, within codec edge rounding.
        green = [x for x in range(160) if pixel(x, 45)[1] > 180]
        self.assertTrue(42 <= len(green) <= 47, len(green))
        self.cli(['probe', output / 'film.mp4', '--output', self.work / 'probe.json'])
        probe = json.loads((self.work / 'probe.json').read_text())
        self.assertFalse(probe['result']['full_decode_passed'])
        self.assertAlmostEqual(float(probe['result']['parameters']['format']['duration']), 2.2, delta=.15)
        self.cli(['frames', output / 'film.mp4', '--every', '.5', '--count', 4, '--width', 80,
                  '--columns', 2, '--output', self.work / 'frames-package'])
        self.assertTrue((self.work / 'frames-package' / 'contact-sheet.jpg').is_file())
        duplicate = self.work / 'duplicate.mp4'
        shutil.copy2(self.source, duplicate)
        self.cli(['candidates', self.source, duplicate, output / 'film.mp4', '--max-samples', 10, '--sample-fps', 2,
                  '--output', self.work / 'candidates.json'])
        candidate = json.loads((self.work / 'candidates.json').read_text())['result']
        self.assertEqual(len(candidate['exact_file_duplicate_groups']), 1)
        self.assertTrue(candidate['files'][0]['sampled_frame_repeats'])
        self.assertTrue(any(.9 < t < 1.4 for t in candidate['files'][2]['scene_cut_candidates_s']),
                        'The abrupt landscape-to-portrait cut should be proposed for review')
        self.cli(['subtitles', subtitle, '--output', self.work / 'captions-package'])
        self.cli(['qc', output / 'film.mp4', '--freeze-min', '.4', '--output', self.work / 'qc.json'])
        qc = json.loads((self.work / 'qc.json').read_text())['result']
        self.assertTrue(qc['full_decode_passed'])
        self.assertFalse(qc['player_acceptance'])
        self.assertTrue(any('freeze' in x['metric'] for x in qc['candidate_events']))
        black = self.work / 'black.mp4'
        self.run_ff(['-f', 'lavfi', '-i', 'color=c=black:s=160x90:r=10:d=0.8', '-c:v', 'libx264', str(black)])
        self.cli(['qc', black, '--output', self.work / 'black-qc.json'])
        black_qc = json.loads((self.work / 'black-qc.json').read_text())['result']
        self.assertTrue(any('black_start' in x['metric'] for x in black_qc['candidate_events']))
        for source, digest in self.original.items():
            self.assertEqual(media.sha256(source), digest, 'Original inputs must remain unchanged')

    def test_invalid_recipe_no_fake_success_and_existing_input_never_overwritten(self):
        recipe = self.json_file('bad.json', {'version': 1, 'clips': [{'path': self.source.name, 'in': 2, 'out': 1}]})
        output = self.work / 'must-not-exist'
        self.cli(['render', recipe, '--output', output], ok=False)
        self.assertFalse(output.exists())
        audit = json.loads((self.work / 'must-not-exist.failed.json').read_text())
        self.assertEqual(audit['status'], 'failed')
        before = media.sha256(self.source)
        self.cli(['probe', self.source, '--output', self.source], ok=False)
        self.assertEqual(media.sha256(self.source), before)


if __name__ == '__main__':
    unittest.main()
