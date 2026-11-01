#!/usr/bin/env python3
"""Local, non-destructive ffmpeg utilities. See references/local-media-tools.md."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


class MediaError(ValueError):
    pass


def number(value, name, minimum=0, maximum=86400, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MediaError(f"{name} must be a number")
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise MediaError(f"{name} must be between {minimum} and {maximum}")
    if integer and int(value) != value:
        raise MediaError(f"{name} must be an integer")
    return int(value) if integer else float(value)


def keys(obj, allowed, label):
    if not isinstance(obj, dict):
        raise MediaError(f"{label} must be an object")
    unknown = set(obj) - set(allowed)
    if unknown:
        raise MediaError(f"Unknown {label} fields: {', '.join(sorted(unknown))}")


def boolean(value, name):
    if not isinstance(value, bool):
        raise MediaError(f"{name} must be true or false")
    return value


def local_file(value, base=None):
    if not isinstance(value, str) or not value or '\x00' in value or '://' in value:
        raise MediaError("Input must be a local file path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    path = path.resolve()
    if not path.is_file():
        raise MediaError(f"File not found: {path}")
    return path


def read_json(path):
    if path.stat().st_size > 8_000_000:
        raise MediaError("JSON input exceeds 8 MB")
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise MediaError(f"Invalid UTF-8 JSON: {path.name}: {exc}") from exc


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class Runner:
    def __init__(self, ffmpeg='ffmpeg', ffprobe='ffprobe'):
        self.ffmpeg = shutil.which(ffmpeg)
        self.ffprobe = shutil.which(ffprobe)
        if not self.ffmpeg or not self.ffprobe:
            raise MediaError("Required executables missing: ffmpeg and ffprobe (no automatic installation)")
        self.calls = []
        self._filters = None

    def run(self, args, cwd=None):
        # File-backed logs bound Python memory even during full-decode QC.
        started = time.monotonic()
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            proc = subprocess.run([str(a) for a in args], cwd=cwd, stdin=subprocess.DEVNULL,
                                  stdout=out, stderr=err, check=False)
            out.seek(0, 2)
            size = out.tell()
            if size > 16_000_000:
                raise MediaError("Unexpected command output exceeds 16 MB")
            out.seek(0)
            stdout = out.read().decode('utf-8', errors='replace')
            err.seek(0, 2)
            err.seek(max(0, err.tell() - 32000))
            stderr = err.read().decode('utf-8', errors='replace')
        self.calls.append({'argv': [str(a) for a in args], 'cwd': str(cwd) if cwd else None,
                           'returncode': proc.returncode, 'elapsed_s': round(time.monotonic() - started, 3),
                           'stderr_tail': stderr[-4000:]})
        if proc.returncode:
            raise MediaError(f"{Path(args[0]).name} exited {proc.returncode}: {stderr[-3000:]}")
        return stdout, stderr

    def ff(self, args, cwd=None):
        return self.run([self.ffmpeg, '-hide_banner', '-nostdin', '-n', *args], cwd)

    def require(self, *names):
        if self._filters is None:
            stdout, _ = self.run([self.ffmpeg, '-hide_banner', '-filters'])
            self._filters = set(re.findall(r'^\s*[TSC.]{2,3}\s+(\w+)\s', stdout, re.M))
        missing = set(names) - self._filters
        if missing:
            raise MediaError(f"Selected ffmpeg lacks filters: {', '.join(sorted(missing))}; select a capable build with --ffmpeg")

    def probe(self, path):
        # Do not return arbitrary embedded metadata/tags or environment values.
        stdout, _ = self.run([self.ffprobe, '-v', 'error', '-protocol_whitelist', 'file,pipe',
                              '-show_entries', 'format=duration,size,format_name:stream=index,codec_type,codec_name,width,height,pix_fmt,avg_frame_rate,r_frame_rate,sample_aspect_ratio,display_aspect_ratio,sample_rate,channels,duration:stream_side_data=rotation',
                              '-of', 'json', str(path)])
        info = json.loads(stdout)
        if not info.get('streams'):
            raise MediaError(f"No decodable streams in {path}")
        return info


def input_args(path):
    # Reject HTTP/HLS/network references even if supplied inside a local playlist.
    return ['-protocol_whitelist', 'file,pipe', '-i', str(path)]


def stream(info, kind):
    return next((x for x in info.get('streams', []) if x.get('codec_type') == kind), None)


def duration(info):
    try:
        value = float(info.get('format', {}).get('duration', 0))
    except (ValueError, TypeError):
        value = 0
    if value <= 0 or not math.isfinite(value):
        raise MediaError("Media has no finite positive duration")
    return value


def check_range(info, start, end):
    number(start, 'in')
    number(end, 'out', minimum=0.001)
    if end <= start or end > duration(info) + 0.025:
        raise MediaError(f"Invalid source interval {start}..{end}; duration={duration(info):.3f}")


def video_params(canvas):
    keys(canvas, ['width', 'height', 'fps', 'background'], 'canvas')
    width = number(canvas.get('width', 1920), 'canvas.width', 16, 7680, True)
    height = number(canvas.get('height', 1080), 'canvas.height', 16, 7680, True)
    fps = number(canvas.get('fps', 25), 'canvas.fps', 1, 120)
    if width % 2 or height % 2:
        raise MediaError('Canvas width and height must be even for yuv420p')
    bg = canvas.get('background', 'black')
    if not isinstance(bg, str) or not re.fullmatch(r'(black|white|#[0-9a-fA-F]{6})', bg):
        raise MediaError('background must be black, white or #RRGGBB')
    return width, height, fps, bg


def fit_filter(w, h, fps, bg='black'):
    # reset_sar normalizes non-square source pixels without distorting display ratio.
    return (f'scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2:reset_sar=1,'
            f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={bg},setsar=1,fps={fps},format=yuv420p')


def timestamp(value, ass=False):
    multiplier = 100 if ass else 1000
    ticks = int(math.floor(value * multiplier + 0.5))
    seconds, frac = divmod(ticks, multiplier)
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f'{hours}:{minute:02d}:{sec:02d}.{frac:02d}' if ass else f'{hours:02d}:{minute:02d}:{sec:02d},{frac:03d}'


def subtitle_files(spec, folder, timeline_duration=None):
    keys(spec, ['width', 'height', 'font', 'font_size', 'subtitles', 'titles'], 'subtitle document')
    w = number(spec.get('width', 1920), 'width', 16, 7680, True)
    h = number(spec.get('height', 1080), 'height', 16, 7680, True)
    font = spec.get('font', 'PingFang SC')
    if not isinstance(font, str) or not font.strip() or any(c in font for c in ',\n\r{}\\'):
        raise MediaError('Invalid font family')
    font_size = number(spec.get('font_size', 48), 'font_size', 8, 400)
    events, srt = [], []
    for kind in ['subtitles', 'titles']:
        items = spec.get(kind, [])
        if not isinstance(items, list) or len(items) > 10000:
            raise MediaError(f'{kind} must be a list of at most 10000 items')
        for item in items:
            keys(item, ['start', 'end', 'text', 'x', 'y', 'font_size'], kind)
            a = number(item.get('start'), f'{kind}.start')
            b = number(item.get('end'), f'{kind}.end', .01)
            if b <= a or (timeline_duration is not None and b > timeline_duration + .01):
                raise MediaError('Subtitle/title interval must be positive and within timeline')
            content = item.get('text')
            if not isinstance(content, str) or not content.strip() or len(content) > 10000 or '\x00' in content:
                raise MediaError('Subtitle text must be nonempty text, at most 10000 characters')
            content = content.replace('\r\n', '\n').replace('\r', '\n')
            if kind == 'subtitles':
                srt.append((a, b, content))
            # Prevent user text being interpreted as ASS override syntax.
            safe = content.replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\n', '\\N')
            style = 'Title' if kind == 'titles' else 'Subtitle'
            override = ''
            if 'x' in item or 'y' in item:
                x = number(item.get('x', w / 2), 'x', 0, w)
                y = number(item.get('y', h / 2), 'y', 0, h)
                override += f'\\an5\\pos({x:g},{y:g})'
            if 'font_size' in item:
                size = number(item['font_size'], 'font_size', 8, 400)
                override += f'\\fs{size:g}'
            if override:
                safe = '{' + override + '}' + safe
            events.append((a, f'Dialogue: {1 if kind == "titles" else 0},{timestamp(a, True)},{timestamp(b, True)},{style},,0,0,0,,{safe}'))
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Subtitle,{font},{font_size:g},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,60,60,50,1
Style: Title,{font},{font_size * 1.5:g},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,5,80,80,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    ass_path, srt_path = folder / 'layers.ass', folder / 'subtitles.srt'
    ass_path.write_text(header + '\n'.join(line for _, line in sorted(events)) + '\n', encoding='utf-8')
    srt_path.write_text('\n\n'.join(f'{i}\n{timestamp(a)} --> {timestamp(b)}\n{txt}'
                                  for i, (a, b, txt) in enumerate(sorted(srt), 1)) + '\n', encoding='utf-8')
    return {'subtitle_count': len(srt), 'title_count': len(events) - len(srt),
            'timing_source': 'user-provided measured intervals; no speech alignment performed'}


def intervals(items, limit, name):
    if not isinstance(items, list) or len(items) > 1000:
        raise MediaError(f'{name} must be a list of at most 1000 [start,end] pairs')
    result = []
    for span in items:
        if not isinstance(span, list) or len(span) != 2:
            raise MediaError(f'{name} requires [start,end] pairs')
        a, b = number(span[0], name, 0, limit), number(span[1], name, 0, limit)
        if b <= a:
            raise MediaError(f'{name}: end must exceed start')
        result.append((a, b))
    return result


def volume_spans(items, level):
    # Sample-evaluated gain: intervals refer to the output timeline, not packets.
    return ''.join(f",aeval=exprs='val(ch)*if(gte(t,{a})*lt(t,{b}),{level},1)':c=same" for a, b in items)


def make_audio(runner, spec, base, folder, length=None):
    keys(spec, ['duration', 'tracks', 'mute', 'keep_clip_audio'], 'audio recipe')
    keep_source = boolean(spec.get('keep_clip_audio', False), 'keep_clip_audio')
    if length is None and keep_source:
        raise MediaError('keep_clip_audio=true is only valid inside a render recipe')
    total = number(spec.get('duration', length), 'audio.duration', .02)
    if length is not None and abs(total - length) > .01:
        raise MediaError('Embedded audio duration must equal video timeline')
    tracks = spec.get('tracks', [])
    if not isinstance(tracks, list) or not tracks or len(tracks) > 100:
        raise MediaError('audio.tracks requires 1..100 explicit tracks')
    args, filters, labels, summary = [], [], [], []
    for index, item in enumerate(tracks):
        keys(item, ['path', 'in', 'duration', 'at', 'volume', 'loop', 'fade_in', 'fade_out', 'duck', 'role'], 'audio track')
        path = local_file(item.get('path'), base)
        info = runner.probe(path)
        if not stream(info, 'audio'):
            raise MediaError(f'No audio stream: {path}')
        a = number(item.get('in', 0), 'track.in')
        length = number(item.get('duration'), 'track.duration', .02, total)
        at = number(item.get('at', 0), 'track.at', 0, total)
        gain = number(item.get('volume', 1), 'track.volume', 0, 8)
        loop = boolean(item.get('loop', False), 'track.loop')
        if at + length > total + .001:
            raise MediaError('Audio track exceeds timeline duration')
        if a >= duration(info) or (not loop and a + length > duration(info) + .025):
            raise MediaError('Audio track exceeds source; use explicit loop=true for BGM')
        role = item.get('role', 'effect')
        if role not in ['narration', 'bgm', 'effect']:
            raise MediaError('Audio role must be narration, bgm or effect')
        if loop:
            args += ['-stream_loop', '-1']
        args += ['-ss', str(a), '-t', str(length), *input_args(path)]
        chain = f'[{index}:a:0]atrim=duration={length},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,volume={gain}'
        for name in ['fade_in', 'fade_out']:
            value = number(item.get(name, 0), name, 0, length)
            if value:
                chain += f',afade=t={"in" if name == "fade_in" else "out"}:st={0 if name == "fade_in" else length - value}:d={value}'
        chain += f',adelay={round(at * 48000)}S:all=1,apad,atrim=duration={total}'
        duck = item.get('duck')
        if duck is not None:
            keys(duck, ['volume', 'intervals'], 'duck')
            level = number(duck.get('volume', .2), 'duck.volume', 0, 1)
            chain += volume_spans(intervals(duck.get('intervals', []), total, 'duck.intervals'), level)
        labels.append(f'[a{index}]')
        filters.append(chain + labels[-1])
        summary.append({'path': str(path), 'at': at, 'duration': length, 'role': role, 'loop': loop, 'volume': gain})
    mix = ''.join(labels) + f'amix=inputs={len(labels)}:duration=longest:normalize=0'
    mix += volume_spans(intervals(spec.get('mute', []), total, 'mute'), 0)
    # A limiter bounds peaks after explicit gains without stretching the timeline.
    mix += f',alimiter=limit=0.95:level=0:latency=1,apad,atrim=duration={total}[mix]'
    filters.append(mix)
    output = folder / 'mix.wav'
    runner.ff([*args, '-filter_complex', ';'.join(filters), '-map', '[mix]', '-c:a', 'pcm_s24le', str(output)])
    return output, {'duration_s': total, 'tracks': summary, 'mute': spec.get('mute', []),
                    'duck_method': 'explicit output-timeline gain intervals; no automatic speech detector',
                    'mute_precision': 'sample-evaluated output timeline; limiter delay compensated'}


def make_render(runner, spec, base, folder):
    keys(spec, ['version', 'canvas', 'clips', 'subtitles', 'audio', 'chapters'], 'edit recipe')
    if number(spec.get('version', 1), 'version', 1, 1, True) != 1:
        raise MediaError('Only edit recipe version 1 is supported')
    w, h, fps, bg = video_params(spec.get('canvas', {}))
    clips = spec.get('clips')
    if not isinstance(clips, list) or not clips or len(clips) > 500:
        raise MediaError('clips must contain 1..500 entries')
    segments, timeline, position = [], [], 0
    for index, clip in enumerate(clips):
        keys(clip, ['path', 'kind', 'in', 'out', 'duration', 'audio', 'volume', 'fade_in', 'fade_out', 'chapter_id'], 'clip')
        path = local_file(clip.get('path'), base)
        info = runner.probe(path)
        if not stream(info, 'video'):
            raise MediaError(f'No video/image stream: {path}')
        kind = clip.get('kind', 'video')
        if kind not in ['video', 'image']:
            raise MediaError('clip.kind must be video or image')
        if kind == 'image':
            if 'in' in clip or 'out' in clip:
                raise MediaError('Image clips use duration, not in/out')
            if info.get('format', {}).get('format_name') not in ['image2', 'png_pipe', 'jpeg_pipe', 'webp_pipe', 'bmp_pipe', 'tiff_pipe']:
                raise MediaError('kind=image requires a supported still image, not a movie')
            length = number(clip.get('duration'), 'clip.duration', .04)
            args = ['-loop', '1', '-framerate', str(fps), '-t', str(length), *input_args(path)]
            source_in = 0
        else:
            if 'duration' in clip:
                raise MediaError('Video clips use measured in/out, not duration')
            source_in = number(clip.get('in', 0), 'clip.in')
            source_out = number(clip.get('out'), 'clip.out', .04)
            check_range(info, source_in, source_out)
            length = source_out - source_in
            args = ['-ss', str(source_in), '-t', str(length), *input_args(path)]
        # Represent each clip by an explicit whole number of output frames.
        frames = round(length * fps)
        if frames < 1:
            raise MediaError('Clip is shorter than one output frame')
        actual = frames / fps
        has_audio = boolean(clip.get('audio', True), 'clip.audio') and stream(info, 'audio') is not None and kind == 'video'
        gain = number(clip.get('volume', 1), 'clip.volume', 0, 8)
        chapter_id = clip.get('chapter_id')
        if chapter_id is not None and (not isinstance(chapter_id, str) or not chapter_id.strip() or len(chapter_id) > 120):
            raise MediaError('clip.chapter_id must be nonempty text of at most 120 characters')
        if not has_audio:
            args += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
        video = f'[0:v:0]setpts=PTS-STARTPTS,{fit_filter(w, h, fps, bg)},tpad=stop_mode=clone:stop_duration=1,trim=end_frame={frames}'
        audio_index = 0 if has_audio else 1
        audio = f'[{audio_index}:a:0]asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,volume={gain},apad,atrim=duration={actual}'
        for fade in ['fade_in', 'fade_out']:
            value = number(clip.get(fade, 0), fade, 0, actual)
            if value:
                typ, start = ('in', 0) if fade == 'fade_in' else ('out', actual - value)
                video += f',fade=t={typ}:st={start}:d={value}'
                audio += f',afade=t={typ}:st={start}:d={value}'
        # PCM intermediates avoid repeated AAC priming/padding at every splice.
        segment = folder / f'segment_{index:04d}.mov'
        runner.ff([*args, '-filter_complex', video + '[v];' + audio + '[a]', '-map', '[v]', '-map', '[a]',
                   '-t', str(actual), '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
                   '-c:a', 'pcm_s24le', '-video_track_timescale', '90000', str(segment)])
        segments.append(segment)
        timeline.append({'path': str(path), 'source_in_s': source_in, 'start_s': position,
                         'end_s': position + actual, 'requested_duration_s': length, 'frames': frames,
                         'chapter_id': clip.get('chapter_id')})
        position += actual
    concat_file = folder / 'segments.txt'
    concat_file.write_text(''.join(f"file '{p.name}'\n" for p in segments), encoding='utf-8')
    joined = folder / 'joined.mov'
    runner.ff(['-f', 'concat', '-safe', '1', '-i', concat_file.name, '-c', 'copy', '-t', str(position), str(joined)], cwd=folder)
    args, maps, vf, af, sidecars = [*input_args(joined)], ['-map', '0:v:0'], [], [], []
    if 'subtitles' in spec:
        runner.require('ass')
        subpath = local_file(spec['subtitles'], base)
        subtitle_spec = read_json(subpath)
        if subtitle_spec.get('width', w) != w or subtitle_spec.get('height', h) != h:
            raise MediaError('Subtitle canvas must match render canvas')
        subtitle_spec = dict(subtitle_spec, width=w, height=h)
        subtitle_files(subtitle_spec, folder, position)
        vf.append('ass=filename=layers.ass')
        sidecars = ['layers.ass', 'subtitles.srt']
    if 'audio' in spec:
        spec_audio = spec['audio']
        mixed, audio_report = make_audio(runner, spec_audio, base, folder, position)
        args += input_args(mixed)
        if boolean(spec_audio.get('keep_clip_audio', False), 'keep_clip_audio'):
            af.append('[0:a:0][1:a:0]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95:level=0:latency=1[a]')
            maps += ['-map', '[a]']
        else:
            maps += ['-map', '1:a:0']
    else:
        maps += ['-map', '0:a:0']
        audio_report = None
    if vf:
        args += ['-vf', ','.join(vf)]
    if af:
        args += ['-filter_complex', ';'.join(af)]
    result = folder / 'film.mp4'
    runner.ff([*args, *maps, '-t', str(position), '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
               '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(result)], cwd=folder)
    chapters = spec.get('chapters', [])
    if not isinstance(chapters, list) or len(chapters) > 500:
        raise MediaError('chapters must be a list with at most 500 entries')
    chapter_outputs = []
    for chapter in chapters:
        keys(chapter, ['id', 'start', 'end'], 'chapter')
        name = chapter.get('id')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', name) or name in chapter_outputs:
            raise MediaError('Chapter IDs must be unique safe ASCII identifiers')
        start = number(chapter.get('start'), 'chapter.start', 0, position)
        end = number(chapter.get('end'), 'chapter.end', 0, position)
        if end <= start:
            raise MediaError('chapter.end must exceed start')
        runner.ff(['-ss', str(start), '-t', str(end - start), *input_args(result), '-map', '0:v:0', '-map', '0:a:0',
                   '-c:v', 'libx264', '-crf', '18', '-c:a', 'aac', '-movflags', '+faststart', str(folder / f'{name}.mp4')])
        chapter_outputs.append(name)
    return {'duration_s': position, 'canvas': {'width': w, 'height': h, 'fps': fps}, 'timeline': timeline,
            'audio': audio_report, 'chapters': chapter_outputs, 'sidecars': sidecars,
            'fit': 'display-aspect-preserving fit with padding; no crop',
            'semantic_acceptance': False}, ['film.mp4', *sidecars, *(f'{x}.mp4' for x in chapter_outputs)]


def do_frames(runner, args, folder):
    source = local_file(args.input)
    info = runner.probe(source)
    if not stream(info, 'video'):
        raise MediaError('frames requires a video stream')
    every = number(args.every, 'every', .04, 3600)
    count = number(args.count, 'count', 1, 500, True)
    width = number(args.width, 'width', 16, 4096, True)
    columns = number(args.columns, 'columns', 1, 20, True)
    video = stream(info, 'video')
    if video.get('width', 0) <= 0 or video.get('height', 0) <= 0:
        raise MediaError('Video stream has invalid dimensions')
    sar = video.get('sample_aspect_ratio', '1:1')
    try:
        n, d = [float(x) for x in sar.split(':')]
        aspect = video['width'] * n / (video['height'] * d)
        rotation = next((abs(x.get('rotation', 0)) for x in video.get('side_data_list', []) if 'rotation' in x), 0)
        if rotation % 180:
            aspect = 1 / aspect
        estimated_height = width / aspect
    except (ValueError, TypeError, ZeroDivisionError, KeyError):
        estimated_height = width * video['height'] / video['width']
    if (width + 4) * (estimated_height + 4) * columns * math.ceil(count / columns) > 80_000_000:
        raise MediaError('Contact sheet would exceed 80 megapixels; reduce width or count')
    runner.ff([*input_args(source), '-vf', f'fps=1/{every},scale={width}:-2:reset_sar=1', '-frames:v', str(count), str(folder / 'frame_%04d.jpg')])
    files = sorted(folder.glob('frame_*.jpg'))
    if not files:
        raise MediaError('No frames extracted')
    rows = math.ceil(len(files) / columns)
    runner.ff(['-framerate', '1', '-i', str(folder / 'frame_%04d.jpg'), '-vf', f'tile={columns}x{rows}:nb_frames={len(files)}:padding=4:margin=4',
               '-frames:v', '1', str(folder / 'contact-sheet.jpg')])
    return {'input': str(source), 'frames': len(files), 'sample_interval_s': every,
            'sample_note': 'ffmpeg fps resampling; representative intervals, not frame-accurate timestamps or full viewing',
            'files': [x.name for x in files], 'contact_sheet': 'contact-sheet.jpg'}


def do_candidates(runner, args, folder):
    threshold = number(args.scene_threshold, 'scene-threshold', 0, 1)
    fps = number(args.sample_fps, 'sample-fps', .01, 10)
    cap = number(args.max_samples, 'max-samples', 2, 2000, True)
    near = number(args.near_mae, 'near-mae', 0, 255)
    files, groups, samples = [], {}, []
    for index, name in enumerate(args.inputs):
        path = local_file(name)
        info = runner.probe(path)
        digest = sha256(path)
        groups.setdefault(digest, []).append(str(path))
        entry = {'path': str(path), 'sha256': digest, 'scene_cut_candidates_s': [], 'sampled_frame_repeats': [], 'adjacent_near_candidates': []}
        if stream(info, 'video'):
            # metadata print is stored separately so long source logs cannot truncate cuts.
            scene_file = folder / f'scenes_{index}.txt'
            runner.ff([*input_args(path), '-an', '-vf', f"select='gt(scene,{threshold})',metadata=print:file={scene_file.name}", '-f', 'null', '-'], cwd=folder)
            with scene_file.open(encoding='utf-8') as handle:
                for line in handle:
                    match = re.search(r'pts_time:([0-9.]+)', line)
                    if match:
                        entry['scene_cut_candidates_s'].append(float(match.group(1)))
            raw = folder / f'sample_{index}.gray'
            runner.ff([*input_args(path), '-an', '-vf', f'fps={fps},scale=32:32,format=gray', '-frames:v', str(cap), '-pix_fmt', 'gray', '-f', 'rawvideo', str(raw)])
            data = raw.read_bytes()
            seen, previous = {}, None
            for j in range(len(data) // 1024):
                pixels = data[j * 1024:(j + 1) * 1024]
                pix_hash = hashlib.sha256(pixels).hexdigest()
                current = {'path': str(path), 'sample_index': j, 'grid_time_s': j / fps, 'sha256': pix_hash}
                if pix_hash in seen:
                    entry['sampled_frame_repeats'].append({'first_sample': seen[pix_hash], 'repeat_sample': j, 'grid_time_s': j / fps})
                else:
                    seen[pix_hash] = j
                if previous is not None:
                    mae = sum(abs(a - b) for a, b in zip(previous, pixels)) / 1024
                    if 0 < mae <= near:
                        entry['adjacent_near_candidates'].append({'samples': [j - 1, j], 'mean_absolute_error_0_255': round(mae, 4)})
                samples.append(current)
                previous = pixels
            entry['sample_count'] = len(data) // 1024
            entry['sample_limit_reached'] = len(data) // 1024 == cap
        files.append(entry)
    return {'files': files, 'exact_file_duplicate_groups': [v for v in groups.values() if len(v) > 1],
            'sample_fps': fps, 'scene_threshold': threshold, 'near_mae_threshold_0_255': near,
            'sample_frame_hashes': samples,
            'limitations': ['Only full-file SHA-256 groups establish byte-identical assets.',
                             'Frame repeats hash normalized 32x32 grayscale samples, not full-resolution originals.',
                             'Near comparisons are adjacent samples only; MAE is an image metric, not semantic identity.',
                             'Scene cuts and all sampled repeats are review candidates; fades/static scientific diagrams can trigger them.',
                             'grid_time_s is the fps sampling grid, not an original-frame timestamp.'],
            'semantic_acceptance': False}


def do_qc(runner, args, folder):
    path = local_file(args.input)
    info = runner.probe(path)
    black_min = number(args.black_min, 'black-min', .01, 3600)
    freeze_min = number(args.freeze_min, 'freeze-min', .01, 3600)
    filters = []
    if stream(info, 'video'):
        runner.require('blackdetect', 'freezedetect')
        # Emit metadata to a file, preserving every interval even on long films.
        filters = [f'blackdetect=d={black_min}:pix_th=0.10', f'freezedetect=n=-60dB:d={freeze_min}', 'metadata=print:file=qc-events.txt']
    command = ['-v', 'info', '-xerror', '-err_detect', 'explode', *input_args(path), '-map', '0:v?', '-map', '0:a?']
    if filters:
        command += ['-vf', ','.join(filters)]
    runner.ff([*command, '-f', 'null', '-'], cwd=folder)
    events = []
    event_path = folder / 'qc-events.txt'
    if event_path.exists():
        with event_path.open(encoding='utf-8') as handle:
            for line in handle:
                if line.startswith('lavfi.black') or line.startswith('lavfi.freezedetect'):
                    key, _, value = line.strip().partition('=')
                    events.append({'metric': key, 'value': value})
    return {'input': str(path), 'sha256': sha256(path), 'parameters': info, 'full_decode_passed': True,
            'black_min_s': black_min, 'freeze_min_s': freeze_min, 'candidate_events': events,
            'limits': ['Only technical decode and signal candidates were checked.',
                       'Static titles can trigger freeze detection; designed fades can trigger black detection.',
                       'No scientific meaning, label integrity, subtitle readability, lip sync, listening or playback acceptance is asserted.'],
            'semantic_acceptance': False, 'player_acceptance': False}


def validate_destination(path):
    if path.exists() or path.is_symlink():
        raise MediaError(f'Refusing to overwrite existing output: {path}')
    if not path.parent.is_dir():
        raise MediaError(f'Output parent directory does not exist: {path.parent}')


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ffmpeg', default='ffmpeg', help='ffmpeg executable or local absolute path')
    p.add_argument('--ffprobe', default='ffprobe', help='ffprobe executable or local absolute path')
    sub = p.add_subparsers(dest='command', required=True)
    probe = sub.add_parser('probe', help='Read stream/format parameters; not decode acceptance')
    probe.add_argument('input')
    probe.add_argument('--output', required=True, help='New JSON report path')
    frames = sub.add_parser('frames', help='Extract sampled JPG frames and ffmpeg contact sheet')
    frames.add_argument('input')
    frames.add_argument('--output', required=True, help='New output directory')
    frames.add_argument('--every', type=float, default=2)
    frames.add_argument('--count', type=int, default=48)
    frames.add_argument('--width', type=int, default=320)
    frames.add_argument('--columns', type=int, default=4)
    candidates = sub.add_parser('candidates', help='Scene cuts, file hashes and sampled duplicate candidates')
    candidates.add_argument('inputs', nargs='+')
    candidates.add_argument('--output', required=True, help='New JSON report path')
    candidates.add_argument('--scene-threshold', type=float, default=.3)
    candidates.add_argument('--sample-fps', type=float, default=1)
    candidates.add_argument('--max-samples', type=int, default=600)
    candidates.add_argument('--near-mae', type=float, default=3)
    for command, desc in [('subtitles', 'Generate editable SRT and ASS from measured JSON intervals'),
                          ('render', 'Render explicit recipe, subtitles and chapter slices'),
                          ('audio', 'Build timeline audio from explicit placements, gain, duck and mute')]:
        item = sub.add_parser(command, help=desc)
        item.add_argument('recipe')
        item.add_argument('--output', required=True, help='New output directory (render/audio/subtitles package)')
    qc = sub.add_parser('qc', help='Full decode; black/freeze candidates; no semantic/player acceptance')
    qc.add_argument('input')
    qc.add_argument('--output', required=True, help='New JSON report path')
    qc.add_argument('--black-min', type=float, default=.2)
    qc.add_argument('--freeze-min', type=float, default=1)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    output = Path(args.output).expanduser().absolute()
    runner = None
    try:
        validate_destination(output)
        # Directory lock avoids replacing a concurrently created output package.
        lock = output.with_name(output.name + '.media-tools.lock')
        lock.mkdir()
    except (OSError, MediaError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    try:
        with tempfile.TemporaryDirectory(prefix='.media-tools-', dir=output.parent) as tmp:
            folder = Path(tmp)
            runner = Runner(args.ffmpeg, args.ffprobe) if args.command != 'subtitles' else None
            if args.command == 'probe':
                source = local_file(args.input)
                result = {'input': str(source), 'sha256': sha256(source), 'parameters': runner.probe(source), 'full_decode_passed': False}
            elif args.command == 'frames':
                result = do_frames(runner, args, folder)
            elif args.command == 'candidates':
                result = do_candidates(runner, args, folder)
            elif args.command == 'qc':
                result = do_qc(runner, args, folder)
            else:
                recipe = local_file(args.recipe)
                spec = read_json(recipe)
                if args.command == 'subtitles':
                    result = subtitle_files(spec, folder)
                elif args.command == 'audio':
                    _, result = make_audio(runner, spec, recipe.parent, folder)
                else:
                    result, keep = make_render(runner, spec, recipe.parent, folder)
                    for item in sorted(folder.iterdir(), key=lambda x: x.name == 'report.json'):
                        if item.name not in keep:
                            item.unlink()
                result['recipe'] = str(recipe)
                result['recipe_sha256'] = sha256(recipe)
            report = {'tool': 'science-achievement-film/media_tools', 'schema_version': 1,
                      'command': args.command, 'status': 'success', 'result': result,
                      'calls': runner.calls if runner else [],
                      'acceptance_note': 'Local processing only; human scientific, audio and player review remain required.'}
            if args.command in ['probe', 'candidates', 'qc']:
                staged = folder / 'report.json'
                dump(staged, report)
                os.link(staged, output)  # Atomic publish with no overwrite.
            else:
                report['outputs'] = [{'file': x.name, 'size': x.stat().st_size, 'sha256': sha256(x)}
                                     for x in sorted(folder.iterdir()) if x.is_file()]
                dump(folder / 'report.json', report)
                validate_destination(output)
                # mkdir is exclusive; populate only after all work succeeded.
                output.mkdir()
                try:
                    for item in folder.iterdir():
                        os.link(item, output / item.name)
                except Exception:
                    shutil.rmtree(output)
                    raise
        print(json.dumps({'status': 'success', 'output': str(output)}, ensure_ascii=False))
        return 0
    except (OSError, MediaError, KeyError, TypeError) as exc:
        # Never publish a nominal output on failure. Failure audit has its own name.
        failure = output.with_name(output.name + '.failed.json')
        error = {'tool': 'science-achievement-film/media_tools', 'status': 'failed', 'command': args.command,
                 'error': str(exc), 'calls': runner.calls if runner else []}
        try:
            with failure.open('x', encoding='utf-8') as handle:
                json.dump(error, handle, ensure_ascii=False, indent=2)
                handle.write('\n')
        except OSError:
            pass
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    finally:
        lock.rmdir()


if __name__ == '__main__':
    raise SystemExit(main())
