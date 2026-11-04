"""Local media registration. No network inputs and no mutable source overwrite."""
from __future__ import annotations
from array import array
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from PIL import Image, ImageOps
from .domain import DomainError, identifier, uid

ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}
MEDIA_EXT = IMAGE_EXT | {'.mp4', '.mov', '.m4v', '.mkv', '.webm', '.avi', '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.aif', '.aiff'}
FORMATS = 'mov,matroska,webm,mp3,wav,flac,aiff,ogg,avi,image2,png_pipe,jpeg_pipe,webp_pipe,bmp_pipe,tiff_pipe,gif,apng,aac'


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uid() + '.tmp')
    with temporary.open('x', encoding='utf8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


class Media:
    def __init__(self, data_root):
        self.root = Path(data_root).resolve()
        self.media_dir = self.root / 'media'
        self.media_dir.mkdir(parents=True, exist_ok=True)
        full = Path('/opt/homebrew/opt/ffmpeg-full/bin')
        self.ffmpeg = os.environ.get('YINGXU_FFMPEG') or (str(full/'ffmpeg') if (full/'ffmpeg').is_file() else shutil.which('ffmpeg'))
        self.ffprobe = os.environ.get('YINGXU_FFPROBE') or (str(full/'ffprobe') if (full/'ffprobe').is_file() else shutil.which('ffprobe'))
        self.font = next((str(p) for p in map(Path, [os.environ.get('YINGXU_FONT', ''), '/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/STHeiti Light.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', str(Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts/msyh.ttc')]) if p.is_file()), None)

    def run(self, argv, timeout=120):
        try:
            p = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise DomainError('媒体工具不可用或执行超时：' + type(e).__name__) from None
        if p.returncode:
            raise DomainError('媒体读取或处理失败；请检查文件格式和解码能力。')
        return p.stdout

    def input_args(self, path):
        return ['-protocol_whitelist', 'file,pipe', '-format_whitelist', FORMATS, '-i', str(path)]

    def probe(self, path):
        if not self.ffprobe:
            raise DomainError('未找到 ffprobe。')
        data = self.run([self.ffprobe, '-v', 'error', '-protocol_whitelist', 'file,pipe', '-format_whitelist', FORMATS,
                         '-show_entries', 'format=duration,size,format_name:stream=codec_type,codec_name,width,height,duration,sample_rate,channels:stream_side_data=rotation', '-of', 'json', str(path)], 60)
        try:
            info = json.loads(data)
            if not info.get('streams'):
                raise ValueError()
            return info
        except ValueError:
            raise DomainError('未读取到有效媒体流。') from None

    def public_metadata(self, pid, aid, digest, name, kind, info, origin='local'):
        v = next((s for s in info.get('streams', []) if s['codec_type'] == 'video'), {})
        seconds = 0 if kind == 'image' else float(info.get('format', {}).get('duration') or v.get('duration') or 0)
        if not math.isfinite(seconds) or (kind != 'image' and not 0 < seconds <= 86400):
            raise DomainError('未获得有效时长，或源文件超过24小时。')
        prefix = f'/api/projects/{pid}/assets/{aid}/{digest}'
        return dict(id=aid, name=name[:500], kind=kind, url=prefix+'/media', poster=prefix+'/thumbnail' if kind != 'audio' else None,
                    duration=seconds, width=v.get('width'), height=v.get('height'), origin=origin, sha256=digest,
                    codec=v.get('codec_name'), hasAudio=any(s['codec_type']=='audio' for s in info.get('streams', [])),
                    note='保存在本机影序工程目录；原文件保持不变。', unavailable=False)

    def prepare(self, source, name, pid, aid=None, origin='local'):
        identifier(pid)
        aid = identifier(aid or uid())
        source, ext = Path(source), Path(name).suffix.lower()
        if ext not in MEDIA_EXT:
            raise DomainError('请导入支持的图片、视频或音频文件。')
        if not source.is_file() or source.is_symlink() or source.stat().st_size == 0 or source.stat().st_size > 2 * 1024**3:
            raise DomainError('媒体文件为空、过大或不可读取。')
        info = self.probe(source)
        if ext in IMAGE_EXT:
            try:
                with Image.open(source) as image:
                    if image.width * image.height > 100_000_000:
                        raise DomainError('图片超过一亿像素，请先缩小。')
                    image.verify()
            except (OSError, ValueError, Image.DecompressionBombError):
                raise DomainError('图片格式无效或尺寸过大。') from None
            kind = 'image'
        else:
            kind = 'video' if any(s['codec_type']=='video' for s in info['streams']) else 'audio'
        digest = sha256(source)
        folder = self.media_dir/pid
        folder.mkdir(exist_ok=True)
        target = folder/f'{aid}-{digest[:20]}{ext}'
        if not target.exists():
            temporary = target.with_suffix(target.suffix+'.part')
            with source.open('rb') as src, temporary.open('xb') as out:
                shutil.copyfileobj(src, out, 1024*1024)
                out.flush()
                os.fsync(out.fileno())
            os.link(temporary, target)
            temporary.unlink()
            if os.name != 'nt':
                target.chmod(0o400)
        metadata = self.public_metadata(pid, aid, digest, name, kind, info, origin)
        thumb = target.with_suffix(target.suffix+'.jpg')
        if not thumb.exists() and kind != 'audio':
            if kind == 'image':
                with Image.open(target) as image:
                    image = ImageOps.exif_transpose(image).convert('RGB')
                    image.thumbnail((720, 405))
                    image.save(thumb, 'JPEG', quality=86)
            else:
                self.run([self.ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-n', *self.input_args(target),
                          '-frames:v', '1', '-vf', 'scale=720:-2', '-q:v', '3', str(thumb)], 60)
        if kind == 'audio':
            try:
                raw = self.run([self.ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', *self.input_args(target),
                                '-t', '3600', '-vn', '-ac', '1', '-ar', '2000', '-f', 's16le', 'pipe:1'], 180)
                samples = array('h'); samples.frombytes(raw[:len(raw)//2*2])
                step = max(1, math.ceil(len(samples)/256))
                peaks = [math.sqrt(sum(x*x for x in samples[i:i+step])/max(1,len(samples[i:i+step])))/32768 for i in range(0,len(samples),step)]
                maximum = max(peaks, default=0)
                metadata['waveform'] = [round(v/maximum,4) if maximum else 0 for v in peaks]
                metadata['waveformDuration'] = min(3600, metadata['duration'])
            except DomainError:
                metadata['waveform'] = []
        record = dict(metadata=metadata, path=str(target.relative_to(self.root)), thumbnail=str(thumb.relative_to(self.root)) if thumb.exists() else None,
                      size=target.stat().st_size, sha256=digest, probe=info)
        return record

    def path(self, relative):
        p = self.root / relative
        if not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(self.root):
            raise DomainError('工程媒体文件缺失，请重新关联。')
        return p

    def frame(self, record, second=0):
        path = self.path(record['path'])
        if record['metadata']['kind'] == 'image':
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image).convert('RGB'); image.thumbnail((1024,1024))
                import io
                out=io.BytesIO(); image.save(out,'JPEG',quality=85); return out.getvalue()
        return self.run([self.ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-ss', str(second), *self.input_args(path),
                         '-frames:v', '1', '-vf', 'scale=1024:-2', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1'], 60)

    def health(self):
        filters = ''
        if self.ffmpeg:
            try:
                filters = self.run([self.ffmpeg,'-hide_banner','-filters'],10).decode(errors='replace')
            except DomainError:
                pass
        required = ['overlay','drawtext','amix','scale','pad']
        return dict(ffmpeg=bool(self.ffmpeg and Path(self.ffmpeg).is_file()), ffprobe=bool(self.ffprobe and Path(self.ffprobe).is_file()),
                    filters={name:bool(re.search(r'\s'+name+r'\s',filters)) for name in required}, chineseFont=bool(self.font))
