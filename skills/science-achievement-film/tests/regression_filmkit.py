import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import wave

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'filmkit.py'
spec = importlib.util.spec_from_file_location('filmkit', SCRIPT)
filmkit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(filmkit)
ROOT = Path(tempfile.mkdtemp(prefix='science-filmkit-')).resolve()
results = []

def record(name, callback):
    try:
        details = callback()
        results.append({'name': name, 'passed': True, 'details': details})
    except Exception as exc:
        results.append({'name': name, 'passed': False, 'error': repr(exc)})

def cli(*args):
    result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True, timeout=30)
    return result

def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)

def load(path):
    return json.loads(Path(path).read_text())

project_dir = ROOT / '中文路径 项目'
result = cli('init', project_dir, '--chapters', 2, '--max-seconds', 600, '--fps', 25)
project_path = project_dir / 'project.json'
record('init_unicode_and_stable_ids', lambda: (
    assert_true(result.returncode == 0, result.stderr),
    assert_true([item['id'] for item in load(project_path)['chapters']] == ['C01', 'C02'], 'wrong IDs'),
    {'path': str(project_path), 'returncode': result.returncode})[-1])
before = project_path.read_bytes()
result = cli('init', project_dir, '--chapters', 3)
record('init_refuses_overwrite', lambda: (
    assert_true(result.returncode == 1, 'should refuse overwrite'),
    assert_true(project_path.read_bytes() == before, 'project changed'),
    {'returncode': result.returncode, 'unchanged': True})[-1])
result = cli('check', project_path, '--out', ROOT / 'template-report.json')
report = load(ROOT / 'template-report.json')
record('template_unknown_durations_do_not_pass', lambda: (
    assert_true(result.returncode == 2, result.stderr),
    assert_true(report['runtime']['total_s'] is None, 'null counted as zero'),
    assert_true(any(f['code'] == 'duration_unknown_or_invalid' for f in report['findings']), 'missing duration finding'),
    {'status': report['status'], 'total_s': report['runtime']['total_s']})[-1])

wav = project_dir / '录音.wav'
with wave.open(str(wav), 'wb') as audio:
    audio.setnchannels(1)
    audio.setsampwidth(2)
    audio.setframerate(8000)
    audio.writeframes(b'\0\0' * 16000)
png = project_dir / '图片.png'
png.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j6ZkAAAAASUVORK5CYII='))
frozen = project_dir / 'approved.txt'
frozen.write_text('approved opening v1', encoding='utf-8')
project = load(project_path)
project['title'] = '测试片'
project['runtime'].update(opening_s=3, intro_music_standalone_s=2, ending_s=3, global_wait_s=0)
project['chapters'] = project['chapters'][:1]
chapter = project['chapters'][0]
chapter['narration'] = chapter['narration'][:1]
chapter['speak_units'] = False
chapter.update(title='深海观测系统', units=['示例单位'], protected_terms=['深海观测系统'],
               transition_duration_s=2, transition_overlap_s=1, picture_extension_s=1, wait_s=0)
line = chapter['narration'][0]
line.update(narration_display='深海观测系统', narration_tts='深海观测系统', voice_duration_s=2,
            voice_duration_basis='measured_audio', voice_path='录音.wav',
            tts_segments=[{'start': 0, 'end': 6}], subtitle_cues=[{'start': 0, 'end': 6}])
chapter['picture_plan'] = [{'sentence_ids': ['C01-S01'], 'source': '图片.png', 'in_s': 0, 'out_s': 4}]
project['approved'] = [{'id': 'OPENING', 'path': 'approved.txt', 'sha256': hashlib.sha256(frozen.read_bytes()).hexdigest()}]

counter = 0

def run_check(value):
    global counter
    counter += 1
    path = project_dir / f'case-{counter}.json'
    path.write_text(json.dumps(value, ensure_ascii=False))
    out = ROOT / f'case-{counter}-report.json'
    result = cli('check', path, '--out', out)
    return result, load(out)

def has(report, code):
    return any(f['code'] == code for f in report['findings'])

result, report = run_check(project)
record('measured_runtime_overlap_once', lambda: (
    assert_true(result.returncode == 0, result.stderr),
    assert_true(report['runtime']['total_s'] == 12, str(report['runtime'])),
    assert_true(report['status'] == 'needs_review' and report['human_acceptance'] == 'not_verified', 'false acceptance'),
    {'total_s': report['runtime']['total_s'], 'status': report['status']})[-1])

missing = copy.deepcopy(project)
missing['chapters'][0]['narration'][0]['voice_duration_s'] = None
result, report = run_check(missing)
record('missing_measured_voice_blocks_total', lambda: (
    assert_true(result.returncode == 2 and report['runtime']['total_s'] is None, 'missing voice was accepted'),
    {'total_s': report['runtime']['total_s']})[-1])

estimated = copy.deepcopy(project)
estimated['chapters'][0]['narration'][0]['voice_duration_basis'] = 'estimated_chars'
result, report = run_check(estimated)
record('estimated_voice_not_counted', lambda: (
    assert_true(has(report, 'voice_unmeasured') and report['runtime']['total_s'] is None, 'estimate accepted'),
    {'total_s': report['runtime']['total_s']})[-1])

repeated = copy.deepcopy(project)
repeated['chapters'][0]['picture_plan'].append({'sentence_ids': ['C01-S01'], 'source': '图片.png', 'in_s': 2, 'out_s': 5})
result, report = run_check(repeated)
record('repeated_source_interval_flagged', lambda: (
    assert_true(has(report, 'source_interval_reused'), 'reuse unreported'),
    {'code': 'source_interval_reused', 'status': report['status']})[-1])

split = copy.deepcopy(project)
split['chapters'][0]['narration'][0]['tts_segments'] = [{'start': 0, 'end': 2}, {'start': 2, 'end': 6}]
result, report = run_check(split)
record('explicit_tts_boundary_splits_protected_term', lambda: (
    assert_true(result.returncode == 2 and has(report, 'protected_term_split'), 'explicit split unreported'),
    {'code': 'protected_term_split'})[-1])

variant = copy.deepcopy(project)
variant['chapters'][0]['narration'][0]['narration_tts'] = '深海观察系统'
result, report = run_check(variant)
record('wording_variant_not_falsely_inferred_split', lambda: (
    assert_true(has(report, 'protected_term_not_located') and not has(report, 'protected_term_split'), 'naive split inference'),
    {'code': 'protected_term_not_located'})[-1])

accelerated = copy.deepcopy(project)
accelerated['chapters'][0]['narration'][0]['playback_rate'] = 1.1
result, report = run_check(accelerated)
record('speedup_rejected', lambda: (
    assert_true(result.returncode == 2 and has(report, 'speed_change_forbidden'), 'speedup accepted'),
    {'code': 'speed_change_forbidden'})[-1])

invalid_overlap = copy.deepcopy(project)
invalid_overlap['chapters'][0]['transition_overlap_s'] = 3
result, report = run_check(invalid_overlap)
record('invalid_overlap_rejected', lambda: (
    assert_true(result.returncode == 2 and has(report, 'overlap_exceeds_blocks') and report['runtime']['total_s'] is None, 'overlap accepted'),
    {'code': 'overlap_exceeds_blocks'})[-1])

frozen.write_text('unauthorized changed version', encoding='utf-8')
changed = copy.deepcopy(project)
changed['revision_queue'] = [{'component_id': 'OPENING', 'reason': 'request to revise'}]
result, report = run_check(changed)
record('frozen_hash_change_not_waived_by_queue', lambda: (
    assert_true(result.returncode == 2 and has(report, 'frozen_component_changed') and has(report, 'revision_pending'), 'changed frozen content accepted'),
    {'code': 'frozen_component_changed'})[-1])
frozen.write_text('approved opening v1', encoding='utf-8')

badref = copy.deepcopy(project)
badref['chapters'][0]['picture_plan'][0]['sentence_ids'] = ['C99-S99']
result, report = run_check(badref)
record('unknown_shot_binding_rejected', lambda: (
    assert_true(has(report, 'unknown_sentence_reference') and has(report, 'sentence_without_picture'), 'unknown ref accepted'),
    {'code': 'unknown_sentence_reference'})[-1])

assets = ROOT / '素材扫描'
assets.mkdir()
shutil.copyfile(wav, assets / '中文.wav')
(assets / '坏视频.mov').write_text('not a video')
(assets / '.离线.mov.icloud').write_text('placeholder token')
(assets / '符号链接').symlink_to(project_dir, target_is_directory=True)
result = cli('inventory', assets, '--out', ROOT / 'metadata.json')
report = load(ROOT / 'metadata.json')
record('metadata_inventory_no_availability_overclaim', lambda: (
    assert_true(result.returncode == 0, result.stderr),
    assert_true(report['counts'] == {'placeholder': 1, 'decode_unverified': 2} or report['counts'] == {'decode_unverified': 2, 'placeholder': 1}, str(report['counts'])),
    assert_true(any(issue['status'] == 'symlink_skipped' for issue in report['issues']), 'symlink followed'),
    assert_true(all(item['availability'] != 'available' and not item['decode_verified'] for item in report['files']), 'stat marked usable'),
    {'counts': report['counts'], 'symlink_skipped': True})[-1])

if shutil.which('ffprobe'):
    result = cli('inventory', assets, '--out', ROOT / 'probe.json', '--probe')
    report = load(ROOT / 'probe.json')
    record('real_ffprobe_good_audio_bad_video_placeholder', lambda: (
        assert_true(result.returncode == 0, result.stderr),
        assert_true(report['counts'].get('probe_ok') == 1 and report['counts'].get('read_error') == 1 and report['counts'].get('placeholder') == 1, str(report['counts'])),
        assert_true(all(not item['decode_verified'] for item in report['files']), 'probe marked decoding'),
        {'counts': report['counts']})[-1])
else:
    results.append({'name': 'real_ffprobe_good_audio_bad_video_placeholder', 'passed': None, 'skipped': 'ffprobe unavailable'})

flagdir = ROOT / 'flag-simulation'
flagdir.mkdir()
(flagdir / '云端.wav').write_text('must not read')
real_scandir = os.scandir
class Entry:
    def __init__(self, entry):
        self.entry, self.path = entry, entry.path
    def stat(self, follow_symlinks=False):
        info = self.entry.stat(follow_symlinks=follow_symlinks)
        return SimpleNamespace(st_mode=info.st_mode, st_flags=0x40000000, st_size=info.st_size, st_mtime_ns=info.st_mtime_ns)
class Listing:
    def __init__(self, path):
        self.context = real_scandir(path)
    def __enter__(self):
        return [Entry(entry) for entry in self.context.__enter__()]
    def __exit__(self, *args):
        return self.context.__exit__(*args)
def placeholder_test():
    out = ROOT / 'flag-report.json'
    with patch.object(filmkit.os, 'scandir', Listing), patch.object(filmkit.subprocess, 'run', side_effect=AssertionError('placeholder was probed')):
        filmkit.inventory(SimpleNamespace(source=str(flagdir), out=str(out), probe=True, timeout=1))
    report = load(out)
    assert_true(report['counts'] == {'placeholder': 1}, str(report['counts']))
    assert_true(filmkit.dataless(SimpleNamespace(st_flags=0x40000000)), 'flag ignored')
    assert_true(not filmkit.dataless(SimpleNamespace()), 'cross-platform fallback broken')
    return {'counts': report['counts'], 'subprocess_calls': 0, 'simulation': 'st_flags UF_DATALESS injected; no real cloud download attempted'}
record('simulated_uf_dataless_never_probed', placeholder_test)

def missing_ffprobe_test():
    out = ROOT / 'no-ffprobe.json'
    with patch.object(filmkit.shutil, 'which', return_value=None):
        filmkit.inventory(SimpleNamespace(source=str(wav), out=str(out), probe=True, timeout=1))
    entry = load(out)['files'][0]
    assert_true(entry['status'] == 'decode_unverified' and entry['probe_error'] == 'ffprobe_unavailable', 'tool absence misreported')
    return {'status': entry['status'], 'probe_error': entry['probe_error']}
record('ffprobe_unavailable_is_unverified', missing_ffprobe_test)

def timeout_test():
    out = ROOT / 'timeout.json'
    with patch.object(filmkit.shutil, 'which', return_value='/fake/ffprobe'), patch.object(filmkit.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['ffprobe'], 1)):
        filmkit.inventory(SimpleNamespace(source=str(wav), out=str(out), probe=True, timeout=1))
    entry = load(out)['files'][0]
    assert_true(entry['status'] == 'read_error', 'timeout swallowed')
    return {'status': entry['status']}
record('ffprobe_timeout_reported', timeout_test)

safe_project = project_dir / 'safe-project.json'
safe_project.write_text(json.dumps(project, ensure_ascii=False))
source_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in [safe_project, wav, png, frozen]}
result = cli('check', safe_project, '--out', ROOT / 'read-only-report.json')
record('check_preserves_all_inputs', lambda: (
    assert_true(result.returncode == 0, result.stderr),
    assert_true(source_hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in [safe_project, wav, png, frozen]}, 'input changed'),
    {'files_unchanged': len(source_hashes)})[-1])
result = cli('check', safe_project, '--out', safe_project)
record('report_cannot_overwrite_project', lambda: (
    assert_true(result.returncode == 1 and hashlib.sha256(safe_project.read_bytes()).hexdigest() == source_hashes[str(safe_project)], 'project overwritten'),
    {'returncode': result.returncode, 'unchanged': True})[-1])

title_auto = copy.deepcopy(project)
title_auto['chapters'][0]['protected_terms'] = []
title_auto['chapters'][0]['narration'][0]['subtitle_cues'] = [{'start': 0, 'end': 3}, {'start': 3, 'end': 6}]
result, report = run_check(title_auto)
record('title_automatically_protected_from_subtitle_split', lambda: (
    assert_true(result.returncode == 2 and has(report, 'protected_term_split'), 'title not protected'),
    {'code': 'protected_term_split'})[-1])

touching = copy.deepcopy(project)
touching['chapters'][0]['picture_plan'].append({'kind': 'bridge', 'purpose': 'scene transition', 'source': '图片.png', 'in_s': 4, 'out_s': 5})
result, report = run_check(touching)
record('touching_source_intervals_not_reuse', lambda: (
    assert_true(not has(report, 'source_interval_reused'), 'adjacent intervals falsely overlap'),
    {'no_false_overlap': True})[-1])

frozen_json = project_dir / 'frozen-data.json'
frozen_json.write_text('{"approved": true}')
invalid_snapshot = copy.deepcopy(project)
invalid_snapshot['approved'] = [{'id': 'JSON', 'path': 'frozen-data.json', 'sha256': 'invalid'}]
invalid_path = project_dir / 'invalid-snapshot-project.json'
invalid_path.write_text(json.dumps(invalid_snapshot, ensure_ascii=False))
original_frozen_json = frozen_json.read_bytes()
result = cli('check', invalid_path, '--out', frozen_json)
record('report_cannot_overwrite_invalid_snapshot_source', lambda: (
    assert_true(result.returncode == 1 and frozen_json.read_bytes() == original_frozen_json, 'invalid digest bypassed output protection'),
    {'unchanged': True})[-1])

screen_only = copy.deepcopy(project)
chapter = screen_only['chapters'][0]
chapter.update(speak_title=False, speak_units=False, protected_terms=[])
line = chapter['narration'][0]
line.update(role='body', narration_display='科研人员完成了深海试验。', narration_tts='科研人员完成了深海试验。')
line['tts_segments'] = [{'start': 0, 'end': len(line['narration_tts'])}]
line['subtitle_cues'] = [{'start': 0, 'end': len(line['narration_display'])}]
result, report = run_check(screen_only)
record('screen_only_title_and_units_need_no_fake_tts', lambda: (
    assert_true(result.returncode == 0 and report['runtime']['total_s'] == 12, str(report['findings'])),
    assert_true(not has(report, 'title_sentence_count') and not has(report, 'units_sentence_missing'), 'screen-only fields forced to speak'),
    assert_true(not has(report, 'protected_term_not_located'), 'unspoken title sought in body audio'),
    {'status': report['status'], 'total_s': report['runtime']['total_s'], 'spoken_entries': 1})[-1])

all_visual = copy.deepcopy(screen_only)
chapter = all_visual['chapters'][0]
chapter['narration'] = []
chapter['transition_overlap_s'] = 0
chapter['picture_plan'] = [{'kind': 'bridge', 'purpose': '纯画面展示标题和单位，无口播', 'source': '图片.png', 'in_s': 0, 'out_s': 3}]
result, report = run_check(all_visual)
record('explicit_empty_spoken_list_no_silent_record_required', lambda: (
    assert_true(result.returncode == 0 and report['runtime']['total_s'] == 11, str(report['findings'])),
    {'total_s': report['runtime']['total_s'], 'spoken_entries': 0})[-1])

units_required = copy.deepcopy(project)
units_required['chapters'][0]['speak_units'] = True
result, report = run_check(units_required)
record('spoken_units_require_units_role', lambda: (
    assert_true(result.returncode == 2 and has(report, 'units_sentence_missing'), 'spoken units missing not reported'),
    {'code': 'units_sentence_missing'})[-1])

units_line = copy.deepcopy(units_required['chapters'][0]['narration'][0])
units_line.update(id='C01-S02', role='units', narration_display='示例单位', narration_tts='示例单位', voice_duration_s=2)
units_line['tts_segments'] = [{'start': 0, 'end': 4}]
units_line['subtitle_cues'] = [{'start': 0, 'end': 4}]
units_required['chapters'][0]['narration'].append(units_line)
units_required['chapters'][0]['picture_plan'][0]['sentence_ids'].append('C01-S02')
result, report = run_check(units_required)
record('actual_units_voice_counted', lambda: (
    assert_true(result.returncode == 0 and report['runtime']['total_s'] == 14, str(report['findings'])),
    {'total_s': report['runtime']['total_s']})[-1])

legacy = copy.deepcopy(project)
for key in ['speak_title', 'speak_units', 'protect_title_as_phrase']:
    legacy['chapters'][0].pop(key, None)
result, report = run_check(legacy)
record('legacy_missing_switches_preserve_title_only_contract', lambda: (
    assert_true(result.returncode == 0 and report['runtime']['total_s'] == 12, str(report['findings'])),
    {'legacy_title_default': True, 'legacy_units_default': False})[-1])

pause = copy.deepcopy(project)
chapter = pause['chapters'][0]
chapter.update(title='高精度卫星观测系统', protect_title_as_phrase=False, protected_terms=['高精度', '观测系统'])
line = chapter['narration'][0]
line.update(narration_display=chapter['title'], narration_tts=chapter['title'])
line['tts_segments'] = [{'start': 0, 'end': 5}, {'start': 5, 'end': 9}]
line['subtitle_cues'] = [{'start': 0, 'end': 9}]
result, report = run_check(pause)
record('explicit_title_pause_after_satellite_allowed', lambda: (
    assert_true(result.returncode == 0 and has(report, 'title_phrase_protection_overridden') and not has(report, 'protected_term_split'), str(report['findings'])),
    {'status': report['status'], 'explicit_pause_after_character': 5})[-1])

protected_pause = copy.deepcopy(pause)
protected_pause['chapters'][0]['protected_terms'].append('卫星观测系统')
result, report = run_check(protected_pause)
record('title_pause_override_does_not_disable_explicit_terms', lambda: (
    assert_true(result.returncode == 2 and has(report, 'protected_term_split'), 'explicit protected term bypassed'),
    {'code': 'protected_term_split'})[-1])

zero_voice = copy.deepcopy(project)
zero_voice['chapters'][0]['narration'][0]['voice_duration_s'] = 0
result, report = run_check(zero_voice)
record('nonempty_spoken_text_cannot_use_zero_second_measurement', lambda: (
    assert_true(result.returncode == 2 and has(report, 'voice_duration_nonpositive') and report['runtime']['total_s'] is None, 'zero-second spoken entry accepted'),
    {'code': 'voice_duration_nonpositive', 'total_s': report['runtime']['total_s']})[-1])

artifact = {'script': str(SCRIPT), 'test_root': str(ROOT), 'tests': results,
            'passed': sum(item['passed'] is True for item in results),
            'failed': sum(item['passed'] is False for item in results),
            'skipped': sum(item['passed'] is None for item in results),
            'scope': 'Only synthetic temporary files. No existing production media modified.'}
(ROOT / 'test-report.json').write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
print(json.dumps({k: artifact[k] for k in ['test_root', 'passed', 'failed', 'skipped']}, ensure_ascii=False))
for item in results:
    if item['passed'] is False:
        print(json.dumps(item, ensure_ascii=False))
sys.exit(1 if artifact['failed'] else 0)
