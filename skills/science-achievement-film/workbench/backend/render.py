"""Multi-track FFmpeg rendering from a frozen, validated project snapshot."""
from __future__ import annotations
import csv
import json
import math
from pathlib import Path
import subprocess
import threading
import zipfile
from .domain import DomainError, duration, validate
from .media import atomic_json, sha256


class Cancelled(Exception):
    pass


def stamp(seconds):
    ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def ass_stamp(seconds):
    cs=round(seconds*100);h,cs=divmod(cs,360000);m,cs=divmod(cs,6000);s,cs=divmod(cs,100)
    return f'{h}:{m:02}:{s:02}.{cs:02}'


def subtitle_exports(project, folder, width, height):
    by_track={t['id']:t for t in project['tracks']}
    titles=sorted((c for c in project['clips'] if by_track[c['track']]['kind']=='title' and not by_track[c['track']]['muted']),key=lambda c:c['start'])
    srt=[];dialogues=[]
    for i,c in enumerate(titles):
        content=c['text'].replace('\r','').replace('\x00','')
        srt.extend([str(i+1),f"{stamp(c['start'])} --> {stamp(c['start']+c['length'])}",content,''])
        safe=content.replace('\\','\\\\').replace('{','\\{').replace('}','\\}').replace('\n','\\N')
        y=round(height*(.6 if c['name']=='片名' else .88))
        override='{\\an2\\pos('+str(width//2)+','+str(y)+')}'
        dialogues.append(f"Dialogue: {i},{ass_stamp(c['start'])},{ass_stamp(c['start']+c['length'])},Default,,0,0,0,,{override}{safe}")
    (folder/'subtitles.srt').write_text('\n'.join(srt),encoding='utf8')
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,PingFang SC,{round(width*.024)},&H00F3F3F3,&H000000FF,&H40000000,&H80000000,0,0,0,0,100,100,0,0,1,1,1,2,60,60,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    (folder/'subtitles.ass').write_text(header+'\n'.join(dialogues)+'\n',encoding='utf8')


class Renderer:
    def __init__(self, media):
        self.media=media

    def dimensions(self, project, resolution):
        if resolution not in {'720p','1080p','2160p'}:
            raise DomainError('输出分辨率不支持。')
        short={'720p':720,'1080p':1080,'2160p':2160}[resolution]
        if project['aspect']=='9:16':return short,short*16//9
        if project['aspect']=='1:1':return short,short
        return short*16//9,short

    def build(self, project, records, folder, options):
        validate(project)
        if options.get("format","mp4") not in {"mp4","mov"}:raise DomainError("输出格式不支持。")
        total=duration(project)
        if total<=0:
            raise DomainError('时间线为空，无法导出。')
        if len(project['clips'])>150:
            raise DomainError('本机首版单次渲染支持最多150个片段，请先分项导出。')
        w,h=self.dimensions(project,options.get('resolution','1080p'));fps=project['fps']
        total=round(total*fps)/fps
        tracks={t['id']:t for t in project['tracks']}
        selected=[c for c in project['clips'] if not tracks[c['track']]['muted']]
        for c in selected:
            if tracks[c['track']]['kind']!='title':
                r=records.get(c.get('asset'))
                if not r:raise DomainError('时间线含未关联的媒体，请先修复素材引用。')
                p=self.media.path(r['path'])
                if p.stat().st_size!=r['size'] or sha256(p)!=r['sha256']:
                    raise DomainError('源素材与登记校验值不符，已停止渲染。')
        args=[self.media.ffmpeg,'-hide_banner','-nostdin','-v','warning','-n','-filter_complex_threads','1',
              '-f','lavfi','-i',f'color=c=black:s={w}x{h}:r={fps}:d={total}']
        filters=[];current='0:v';audios=[];index=1
        visuals=[c for c in selected if tracks[c['track']]['kind']=='video']
        visuals.sort(key=lambda c:list(tracks).index(c['track']),reverse=True)
        for c in visuals:
            r=records[c['asset']];a=r['metadata'];path=self.media.path(r.get('normalized_path') or r['path'])
            if a['kind']=='image':args+=['-loop','1','-framerate',str(fps),'-t',str(c['length'])]
            else:args+=['-ss',str(c['sourceIn']),'-t',str(c['length'])]
            args+=self.media.input_args(path)
            cw=max(2,round(w*c['scale']/2)*2);ch=max(2,round(h*c['scale']/2)*2)
            label=f'v{index}';output=f'base{index}'
            filters.append(f'[{index}:v]setpts=PTS-STARTPTS+{c["start"]}/TB,fps={fps},scale={cw}:{ch}:force_original_aspect_ratio=decrease,pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=rgba,colorchannelmixer=aa={c["opacity"]}[{label}]')
            filters.append(f"[{current}][{label}]overlay=x=(main_w-overlay_w)/2:y=(main_h-overlay_h)/2:eof_action=pass:repeatlast=0:enable='gte(t,{c['start']})*lt(t,{c['start']+c['length']})'[{output}]")
            current=output
            if a.get('hasAudio') and c['volume']>0:
                al=f'a{index}'
                filters.append(f'[{index}:a]atrim=duration={c["length"]},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,volume={c["volume"]},adelay={round(c["start"]*1000)}:all=1[{al}]')
                audios.append(al)
            index+=1
        for c in (x for x in selected if tracks[x['track']]['kind']=='audio'):
            r=records[c['asset']];args+=['-ss',str(c['sourceIn']),'-t',str(c['length']),*self.media.input_args(self.media.path(r['path']))]
            al=f'a{index}'
            filters.append(f'[{index}:a]atrim=duration={c["length"]},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,volume={c["volume"]},adelay={round(c["start"]*1000)}:all=1[{al}]')
            audios.append(al);index+=1
        title_clips=[c for c in selected if tracks[c['track']]['kind']=='title']
        if title_clips and not self.media.font:
            raise DomainError('未找到中文字体，请配置YINGXU_FONT。')
        for i,c in enumerate(title_clips):
            name=f'title_{i:03}.txt';(folder/name).write_text(c['text'],encoding='utf8')
            size=max(12,round(w*(.05 if c['name']=='片名' else .024)*c['scale']))
            font=self.media.font.replace('\\','\\\\').replace(':','\\:').replace("'","\\'")
            previous=[x for x in title_clips[:i] if x['name']!='片名']
            terms='+'.join(f'gte(t,{x["start"]})*lt(t,{x["start"]+x["length"]})' for x in previous) or '0'
            y='h*0.6-text_h' if c['name']=='片名' else f'h*(0.88-0.12*({terms}))-text_h'
            label=f'text{i}'
            filters.append(f"[{current}]drawtext=fontfile='{font}':textfile={name}:expansion=none:fontsize={size}:fontcolor=0xf7f3dd@{c['opacity']}:shadowcolor=black@0.6:shadowx=1:shadowy=2:x=(w-text_w)/2:y='{y}':enable='gte(t,{c['start']})*lt(t,{c['start']+c['length']})'[{label}]")
            current=label
        if audios:
            joined=''.join(f'[{x}]' for x in audios)
            filters.append(f'{joined}amix=inputs={len(audios)}:duration=longest:dropout_transition=0:normalize=0,alimiter=limit=0.95,apad,atrim=duration={total}[mixed]')
        else:
            filters.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={total}[mixed]')
        filters.append(f'[{current}]format=yuv420p[video]')
        output=folder/'film.mp4'
        mov=options.get('format')=='mov'
        if mov:filters.append('[mixed]asplit=2[previewaudio][pcmaudio]')
        args+=['-filter_complex',';'.join(filters),'-map','[video]','-map','[previewaudio]' if mov else '[mixed]','-t',str(total),'-r',str(fps),
               '-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ar','48000',
               '-movflags','+faststart','-progress','pipe:1','-nostats',str(output)]
        if mov:args+=['-map','[pcmaudio]','-t',str(total),'-c:a','pcm_s24le',str(folder/'mix.wav')]
        return args,dict(duration=total,width=w,height=h,fps=fps,output=output)

    def render(self, project, records, folder, options, cancel, progress, process_callback=lambda p:None):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        args,plan=self.build(project,records,folder,options)
        if cancel.is_set():raise Cancelled()
        atomic_json(folder/'project.json',dict(schema_version=1,project=project,source_revision=project['revision']))
        atomic_json(folder/'render-plan.json',{'revision':project['revision'],'dimensions':[plan['width'],plan['height']], 'duration':plan['duration'],'source_hashes':{a:r['sha256'] for a,r in records.items()}})
        with (folder/'ffmpeg.log').open('wb') as log:
            proc=subprocess.Popen(args,cwd=folder,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=log,text=True)
            process_callback(proc)
            try:
                for line in proc.stdout:
                    if cancel.is_set():
                        proc.terminate();raise Cancelled()
                    if line.startswith('out_time_us='):
                        try:progress('渲染画面与声音',.1+min(.79,max(0,float(line.split('=',1)[1])/1e6/plan['duration']*.79)))
                        except ValueError:pass
                code=proc.wait()
                if cancel.is_set():raise Cancelled()
                if code:raise DomainError('视频渲染失败；原素材和工程已保留，可查看本地任务日志。')
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:proc.wait(5)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()
                proc.stdout.close()
                process_callback(None)
        progress('完整解码与输出检查',.92)
        self.check_output(plan['output'],cancel,process_callback)
        info=self.media.probe(plan['output'])
        actual=float(info['format']['duration'])
        video=next(s for s in info['streams'] if s['codec_type']=='video')
        if abs(actual-plan['duration'])>max(.15,2/plan['fps']) or (video['width'],video['height'])!=(plan['width'],plan['height']):
            raise DomainError('输出时长或画布与冻结工程不符。')
        if options.get('format')=='mov':
            progress('输出MOV与PCM声音',.94)
            mov=folder/'film.mov'
            self.run_cancellable([self.media.ffmpeg,'-hide_banner','-nostdin','-v','error','-n',*self.media.input_args(plan['output']),*self.media.input_args(folder/'mix.wav'),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','copy','-movflags','+faststart',str(mov)],cancel,process_callback,folder/'mov.log')
            self.check_output(mov,cancel,process_callback)
            (folder/'mix.wav').unlink()
        subtitle_exports(project,folder,plan['width'],plan['height'])
        with (folder/'cutlist.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f);writer.writerow(['clip_id','track','asset_id','name','timeline_start','length','source_in','text'])
            for c in project['clips']:writer.writerow([c['id'],c['track'],c.get('asset',''),c['name'],c['start'],c['length'],c['sourceIn'],c.get('text','')])
        # EDL is a main-video interchange; multi-layer/graphics remain in full JSON and media package.
        self.write_edl(project,folder,records)
        qc=dict(full_decode_passed=True,expected_duration=plan['duration'],actual_duration=actual,width=plan['width'],height=plan['height'],
                source_revision=project['revision'],sha256=sha256(plan['output']),semantic_acceptance=False,player_acceptance=False,listening_acceptance=False,
                limits=['技术解码不替代科学核验、实际播放、听审或用户接受。','EDL只交接主画面；完整多层结构保存于工程JSON。'])
        atomic_json(folder/'qc.json',qc)
        if options.get('chapters'):
            cuts=sorted({0.0,*[float(c['start']) for c in project['clips'] if c.get('text') and c['start']<plan['duration']],plan['duration']})
            for i,(start,end) in enumerate(zip(cuts,cuts[1:])):
                if cancel.is_set():raise Cancelled()
                if end-start<1/project['fps']:continue
                target=folder/f'chapter-{i+1:02}.mp4'
                self.run_cancellable([self.media.ffmpeg,'-hide_banner','-nostdin','-v','error','-n','-ss',str(start),*self.media.input_args(plan['output']),'-t',str(end-start),'-c:v','libx264','-preset','fast','-crf','20','-c:a','aac','-movflags','+faststart',str(target)],cancel,process_callback,folder/'chapters.log')
                self.check_output(target,cancel,process_callback)
        progress('整理工程交接包',.98)
        with zipfile.ZipFile(folder/'delivery.zip','x',zipfile.ZIP_DEFLATED) as archive:
            for name in ['project.json','subtitles.srt','subtitles.ass','cutlist.csv','timeline.edl','qc.json']:
                archive.write(folder/name,name)
            portable=__import__('copy').deepcopy(project)
            for a in portable['assets']:
                record=records.get(a['id'])
                if record:
                    src=self.media.path(record['path']);rel=f'media/{a["id"]}{src.suffix}'
                    archive.write(src,rel);a['url']=rel;a['poster']=None
                else:a['url']=''
            archive.writestr('portable-project.json',json.dumps({'schema_version':1,'project':portable,'note':'导入影序时重新注册媒体；EDL仅覆盖主画面。'},ensure_ascii=False,indent=2))
        files=[p.name for p in folder.iterdir() if p.suffix in {'.mp4','.mov','.json','.srt','.ass','.csv','.edl','.zip'} and p.name!='render-plan.json']
        return dict(files=sorted(files),qc=qc,duration=actual,revision=project['revision'])

    def run_cancellable(self,args,cancel,callback,log_path):
        with Path(log_path).open('ab') as log:
            proc=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
            callback(proc)
            try:
                while proc.poll() is None:
                    if cancel.wait(.1):proc.terminate();raise Cancelled()
                if cancel.is_set():raise Cancelled()
                if proc.returncode:raise DomainError('媒体完整解码或分项导出失败。')
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:proc.wait(5)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()
                callback(None)

    def check_output(self,path,cancel,callback):
        self.run_cancellable([self.media.ffmpeg,'-hide_banner','-nostdin','-v','error',*self.media.input_args(path),'-f','null','-'],cancel,callback,Path(path).with_suffix('.decode.log'))

    def write_edl(self,p,folder,records):
        fps=p['fps']
        def tc(sec):
            frames=round(sec*fps);s,ff=divmod(frames,fps);m,ss=divmod(s,60);hh,mm=divmod(m,60)
            return f'{hh:02}:{mm:02}:{ss:02}:{ff:02}'
        lines=['TITLE: YINGXU MAIN VIDEO','FCM: NON-DROP FRAME','']
        for i,c in enumerate(sorted((c for c in p['clips'] if c['track']=='V1'),key=lambda c:c['start']),1):
            lines.append(f'{i:03}  AX       V     C        {tc(c["sourceIn"])} {tc(c["sourceIn"]+c["length"])} {tc(c["start"])} {tc(c["start"]+c["length"])}')
            lines.append('* FROM CLIP NAME: '+c['name'].replace('\n',' '))
            lines.append('* YINGXU ASSET ID: '+c.get('asset',''))
            lines.append('')
        (folder/'timeline.edl').write_text('\n'.join(lines),encoding='utf8')
