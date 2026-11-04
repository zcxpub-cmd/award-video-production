"""Validated, side-effect-free timeline operations shared by manual and AI editing."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import math
import re
import uuid


class DomainError(ValueError):
    status = 400


class Conflict(DomainError):
    status = 409


class Missing(DomainError):
    status = 404


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex[:16]


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', value):
        raise DomainError('编号格式无效。')
    return value


def text(value, label, maximum=10000, empty=True):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()) or '\x00' in value:
        raise DomainError(f'{label}格式或长度无效。')
    return value


def number(value, label, minimum=0, maximum=3600):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise DomainError(f'{label}超出有效范围。')
    return value


def fields(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise DomainError('操作包含未知或缺少必填字段。')


def duration(project):
    return max((c['start'] + c['length'] for c in project['clips']), default=0)


def default_tracks():
    return [dict(id=i, name=n, kind=k, color=c, muted=False, locked=False) for i, n, k, c in [
        ('T1', '字幕与标题', 'title', 'ochre'), ('V2', '叠加画面', 'video', 'violet'),
        ('V1', '主画面', 'video', 'sage'), ('A1', '旁白', 'audio', 'clay'), ('A2', '音乐与音效', 'audio', 'blue')]]


def new_project(name='未命名故事', mode='manual', aspect='16:9', target=30, project_id=None):
    p = dict(id=project_id or uid(), name=name, brief='', mode=mode, aspect=aspect, fps=25,
             target=target, style='自然纪录片', revision=0, updated=now(), assets=[], tracks=default_tracks(), clips=[])
    validate(p)
    return p


CLIP_FIELDS = {'id', 'track', 'asset', 'name', 'start', 'length', 'sourceIn', 'volume', 'opacity', 'scale', 'text'}
PATCH_FIELDS = CLIP_FIELDS - {'id'}


def validate(p):
    if not isinstance(p, dict):
        raise DomainError('工程格式无效。')
    identifier(p.get('id'))
    text(p.get('name'), '项目名称', 100, False)
    text(p.get('brief', ''), '创作简报', 20000)
    text(p.get('style', ''), '风格', 100)
    if p.get('mode') not in {'manual', 'one-click'} or p.get('aspect') not in {'16:9', '9:16', '1:1'}:
        raise DomainError('工程模式或画幅无效。')
    if p.get('fps') not in {24, 25, 30, 50, 60}:
        raise DomainError('帧率暂不支持。')
    number(p.get('target'), '目标时长', 1, 3600)
    number(p.get('revision'), '修订号', 0, 10**12)
    if not isinstance(p.get('tracks'), list) or not 1 <= len(p['tracks']) <= 24:
        raise DomainError('轨道数量无效。')
    tracks = {}
    for t in p['tracks']:
        identifier(t.get('id'))
        if t['id'] in tracks or t.get('kind') not in {'video', 'title', 'audio'}:
            raise DomainError('轨道编号重复或类型无效。')
        if type(t.get('muted')) is not bool or type(t.get('locked')) is not bool:
            raise DomainError('轨道状态必须是布尔值。')
        text(t.get('name'), '轨道名称', 100)
        tracks[t['id']] = t
    if not isinstance(p.get('assets'), list) or len(p['assets']) > 2000:
        raise DomainError('素材数量无效。')
    assets = {}
    for a in p['assets']:
        identifier(a.get('id'))
        if a['id'] in assets or a.get('kind') not in {'video', 'image', 'audio'}:
            raise DomainError('素材编号重复或类型无效。')
        text(a.get('name'), '素材名称', 500, False)
        number(a.get('duration', 0), '素材时长', 0, 86400)
        assets[a['id']] = a
    if not isinstance(p.get('clips'), list) or len(p['clips']) > 500:
        raise DomainError('片段数量无效。')
    ids = set()
    for c in p['clips']:
        fields(c, CLIP_FIELDS, {'id', 'track', 'name', 'start', 'length', 'sourceIn', 'volume', 'opacity', 'scale'})
        identifier(c['id'])
        if c['id'] in ids:
            raise DomainError('片段编号重复。')
        ids.add(c['id'])
        t = tracks.get(c['track'])
        if not t:
            raise DomainError('片段引用的轨道不存在。')
        text(c['name'], '片段名称', 500)
        number(c['start'], '片段开始')
        number(c['length'], '片段时长', 1 / p['fps'] - 1e-7)
        number(c['sourceIn'], '素材入点', 0, 86400)
        number(c['start'] + c['length'], '片段结束')
        number(c['volume'], '音量', 0, 2)
        number(c['opacity'], '透明度', 0, 1)
        number(c['scale'], '缩放', .1, 2)
        if t['kind'] == 'title':
            if c.get('asset') or not isinstance(c.get('text'), str):
                raise DomainError('标题轨道只接受文字。')
            text(c['text'], '文字', 4000)
        else:
            a = assets.get(c.get('asset'))
            if not a or (a['kind'] == 'audio') != (t['kind'] == 'audio'):
                raise DomainError('素材与轨道类型不匹配。')
            if not a.get('unavailable') and a['kind'] != 'image' and c['sourceIn'] + c['length'] > a['duration'] + .001:
                raise DomainError('修剪范围超过原素材时长。')
    return p


def apply_operations(project, operations):
    if not isinstance(operations, list) or not 1 <= len(operations) <= 100:
        raise DomainError('每次需要1至100项操作。')
    p = deepcopy(project)
    for op in operations:
        if not isinstance(op, dict):
            raise DomainError('操作格式无效。')
        kind = op.get('type')
        by_track = {t['id']: t for t in p['tracks']}
        clip = next((c for c in p['clips'] if c['id'] == op.get('id')), None)
        if kind in {'update', 'delete', 'split'}:
            if not clip:
                raise DomainError('片段不存在。')
            if by_track[clip['track']]['locked']:
                raise DomainError('轨道已锁定，请先解锁。')
        if kind == 'update':
            fields(op, {'type', 'id', 'patch'}, {'id', 'patch'})
            fields(op['patch'], PATCH_FIELDS)
            target = op['patch'].get('track', clip['track'])
            if target in by_track and by_track[target]['locked']:
                raise DomainError('目标轨道已锁定。')
            clip.update(deepcopy(op['patch']))
        elif kind == 'add':
            fields(op, {'type', 'clip'}, {'clip'})
            fields(op['clip'], CLIP_FIELDS)
            if by_track.get(op['clip'].get('track'), {}).get('locked'):
                raise DomainError('目标轨道已锁定。')
            p['clips'].append(deepcopy(op['clip']))
        elif kind == 'delete':
            fields(op, {'type', 'id'}, {'id'})
            p['clips'] = [c for c in p['clips'] if c['id'] != op['id']]
        elif kind == 'split':
            fields(op, {'type', 'id', 'time'}, {'id', 'time'})
            at = number(op['time'], '切分时间')
            left, right = at - clip['start'], clip['start'] + clip['length'] - at
            if min(left, right) < 1 / p['fps'] - 1e-7:
                raise DomainError('切分点必须在片段内部，并保留至少一帧。')
            p['clips'].append(dict(clip, id=uid(), start=at, length=right, sourceIn=clip['sourceIn'] + left,
                                   name=(clip['name'] + ' · 后段')[:500]))
            clip['length'] = left
        elif kind == 'track':
            fields(op, {'type', 'id', 'patch'}, {'id', 'patch'})
            fields(op['patch'], {'muted', 'locked'})
            if op['id'] not in by_track:
                raise DomainError('轨道不存在。')
            by_track[op['id']].update(op['patch'])
        elif kind == 'configure':
            fields(op, {'type', 'patch'}, {'patch'})
            fields(op['patch'], {'name', 'brief', 'mode', 'aspect', 'target', 'style', 'fps'})
            p.update(deepcopy(op['patch']))
        elif kind == 'replace':
            fields(op, {'type', 'clips'}, {'clips'})
            if any(t['locked'] for t in p['tracks']):
                raise DomainError('请先解锁轨道，再重新编排。')
            p['clips'] = deepcopy(op['clips'])
        else:
            raise DomainError('不支持此操作；素材必须通过本地导入接口登记。')
        validate(p)
    p['revision'] = project['revision'] + len(operations)
    p['updated'] = now()
    return p


def arrange(project, sequence=None):
    p = project
    visuals = [a for a in p['assets'] if a['kind'] != 'audio' and not a.get('unavailable')]
    if not visuals:
        raise DomainError('请先导入可用图片或视频。')
    if sequence is not None:
        if not isinstance(sequence, list) or not sequence or len(sequence) > 100:
            raise DomainError('AI镜头序列无效。')
        lookup = {a['id']: a for a in visuals}
        selected = []
        for item in sequence:
            fields(item, {'asset_id', 'reason'}, {'asset_id'})
            if item['asset_id'] not in lookup:
                raise DomainError('AI引用了不存在或不可用的素材。')
            selected.append(lookup[item['asset_id']])
        visuals = selected
    fps, target_frames = p['fps'], round(p['target'] * p['fps'])
    if len(visuals)>target_frames:raise DomainError('目标时长不足以容纳所选镜头，请减少素材或延长时长。')
    share = target_frames / len(visuals)
    lengths = [max(1, min(math.floor(share), math.floor(a['duration'] * fps)) if a['kind'] != 'image' else math.floor(share)) for a in visuals]
    stills = [i for i, a in enumerate(visuals) if a['kind'] == 'image']
    extra = max(0, target_frames - sum(lengths))
    if stills:
        for rank, i in enumerate(stills):
            lengths[i] += extra // len(stills) + (rank < extra % len(stills))
    clips, position = [], 0
    common = dict(sourceIn=0, volume=1, opacity=1, scale=1)
    for a, count in zip(visuals, lengths):
        length = count / fps
        clips.append(dict(common, id=uid(), track='V1', asset=a['id'], name=a['name'], start=position, length=length))
        position += length
    clips.append(dict(common, id=uid(), track='T1', name='片名', text=p['name'], start=0, length=min(3, position)))
    music = next((a for a in p['assets'] if a['kind'] == 'audio' and not a.get('unavailable')), None)
    if music:
        clips.append(dict(common, id=uid(), track='A2', asset=music['id'], name=music['name'], start=0,
                          length=min(position, music['duration']), volume=.25))
    validate(dict(p, clips=clips))
    return clips
