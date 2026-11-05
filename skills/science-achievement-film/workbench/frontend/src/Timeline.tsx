import { tr } from './i18n'
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { ArrowRight, ArrowUUpLeft, ArrowUUpRight, ArrowUp, CaretDown, CaretRight, Check, Circle, Copy, Export, FilmStrip, ImageSquare, Lock, LockOpen, MagnifyingGlass, Minus, MusicNotes, Pause, Play, Plus, Robot, Scissors, SkipBack, SkipForward, SlidersHorizontal, Sparkle, SpeakerHigh, SpeakerSlash, TextT, Trash, UploadSimple, VideoCamera, X } from '@phosphor-icons/react'
import { duration, precise, time, uid, type Asset, type Clip, type Edit, type History, type Project } from './editor'
import { Button, Empty, Tag } from './ui'
import { api, activeTask, type Task } from './api'
type Props={project:Project;history:History;onEdit:(ops:Edit[])=>Promise<void>;onUndo:()=>void;onRedo:()=>void;notify:(s:string)=>void;onUpload:()=>void;onExport:()=>void;initialPrompt:string;clearPrompt:()=>void;confirmAI:boolean;jobs:Task[];modelName:string;modelAvailable:boolean;onAI:(instruction:string,selected:string|null,playhead:number)=>Promise<Task>;onApplyAI:(id:string)=>Promise<unknown>;onCancelTask:(id:string)=>Promise<unknown>}
type Message={id:string;role:'assistant'|'user';text:string;changes?:number}
export default function Timeline({project,history,onEdit,onUndo,onRedo,notify,onUpload,onExport,initialPrompt,clearPrompt,confirmAI,jobs,modelName,modelAvailable,onAI,onApplyAI,onCancelTask}:Props) {
 const [selected,setSelected]=useState<string|null>('shot-01'),[position,setPosition]=useState(1.2),[playing,setPlaying]=useState(false),[zoom,setZoom]=useState(27),[snap,setSnap]=useState(true),[tab,setTab]=useState<'chat'|'properties'>('chat'),[mediaTab,setMediaTab]=useState('all'),[query,setQuery]=useState(''),[busy,setBusy]=useState(false),[ghost,setGhost]=useState<Clip|null>(null)
 const [messages,setMessages]=useState<Message[]>([])
 const aiJobs=jobs.filter(j=>j.project_id===project.id&&j.kind==='ai-edit'),running=aiJobs.find(activeTask),proposal=aiJobs.find(j=>j.status==='awaiting_confirmation'),working=busy||!!running
 const latestAI=aiJobs[0],applied=aiJobs.find(j=>j.status==='succeeded'&&j.result?.applied_revision===project.revision)
 const updatedIds=new Set(applied?.result?.operations?.flatMap(op=>op.type==='add'?[op.clip.id]:'id' in op?[op.id]:[])||[])
 const messageStamp=aiJobs.map(j=>j.id+':'+j.status).join('|')
 useEffect(()=>{let live=true;api.messages(project.id).then(rows=>{if(live)setMessages(rows)}).catch(e=>notify(e.message));return()=>{live=false}},[project.id,messageStamp])
 const end=duration(project),selectedClip=project.clips.find(c=>c.id===selected),revision=useRef(project.revision),cleanupDrag=useRef<(()=>void)|null>(null),chatScroll=useRef<HTMLDivElement>(null)
 const clipDisplay=(c:Clip)=>ghost?.id===c.id?ghost:c
 useEffect(()=>{revision.current=project.revision},[project.revision])
 useEffect(()=>{if(initialPrompt){setQuery(initialPrompt.slice(0,6000));clearPrompt();setTab('chat');if(initialPrompt.length>6000)notify(tr("正文较长，对话草稿已放入前 6,000 字；完整正文仍可在灵感库复制。"))}},[initialPrompt])
 useEffect(()=>{chatScroll.current?.scrollTo({top:chatScroll.current.scrollHeight,behavior:'smooth'})},[messages,working,proposal])
 useEffect(()=>()=>{cleanupDrag.current?.()},[])
 useEffect(()=>{
  if(!playing)return
  const initial=performance.now(),from=position;let frame=0
  const tick=(now:number)=>{const next=from+(now-initial)/1000;if(next>=end){setPosition(end);setPlaying(false);return}setPosition(next);frame=requestAnimationFrame(tick)}
  frame=requestAnimationFrame(tick);return()=>cancelAnimationFrame(frame)
 },[playing,end])
 const seek=(value:number)=>{setPlaying(false);setPosition(Math.max(0,Math.min(value,Math.max(end,project.target))))}
 const safeEdit=async(ops:Edit[])=>{try{await onEdit(ops);return true}catch{return false}}
 const split=async()=>{const clip=selectedClip||project.clips.find(c=>c.track==='V1'&&position>c.start&&position<c.start+c.length);if(!clip){notify(tr("先选择片段，并把播放头放在片段内部。"));return}if(await safeEdit([{type:'split',id:clip.id,time:Math.round(position*project.fps)/project.fps}]))notify(tr("片段已切分，源内入点同步保留。"))}
 const remove=async()=>{if(!selectedClip){notify(tr("先选择一个片段。"));return}if(await safeEdit([{type:'delete',id:selectedClip.id}]))setSelected(null)}
 useEffect(()=>{const key=(e:KeyboardEvent)=>{if((e.target as HTMLElement)?.closest('input,textarea,select,button,a,[contenteditable],[role=dialog]'))return;if(e.code==='Space'){e.preventDefault();if(end){if(position>=end)setPosition(0);setPlaying(p=>!p)}}if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='z'){e.preventDefault();e.shiftKey?onRedo():onUndo()}if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();remove()}if(e.key.toLowerCase()==='s'&&!e.metaKey&&!e.ctrlKey)split()};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key)},[selectedClip,position,end,onUndo,onRedo])
 const addAsset=async(asset:Asset)=>{
  if(!asset.url){notify(tr("此素材需要重新导入后替换。"));return}
  const id=uid();const track=asset.kind==='audio'?'A1':'V1';const start=asset.kind==='audio'?position:end
  if(await safeEdit([{type:'add',clip:{id,track,asset:asset.id,name:asset.name,start:Math.round(start*project.fps)/project.fps,length:asset.kind==='image'?4:Math.min(4,asset.duration),sourceIn:0,volume:asset.kind==='audio'?.6:1,opacity:1,scale:1}}])){setSelected(id);notify(tr("素材已加入时间线。"))}
 }
 const addTitle=async()=>{const id=uid();if(await safeEdit([{type:'add',clip:{id,track:'T1',name:'新标题',text:'写下你的故事',start:Math.round(position*project.fps)/project.fps,length:3,sourceIn:0,volume:1,opacity:1,scale:1}}])){setSelected(id);setTab('properties')}}
 const beginDrag=(event:ReactPointerEvent,clip:Clip,kind:'move'|'left'|'right')=>{
  event.stopPropagation();if(event.button!==0)return;setSelected(clip.id)
  if(project.tracks.find(t=>t.id===clip.track)?.locked){notify(tr("轨道已锁定，请先解锁。"));return}
  const initialX=event.clientX;let next=clip,moved=false
  const media=project.assets.find(a=>a.id===clip.asset)
  const quantize=(v:number)=>Math.round(v*project.fps)/project.fps
  const snapped=(v:number)=>{if(!snap)return quantize(v);const edges=[0,...project.clips.filter(c=>c.id!==clip.id).flatMap(c=>[c.start,c.start+c.length])];const near=edges.find(x=>Math.abs(x-v)<7/zoom);return quantize(near??v)}
  const move=(e:PointerEvent)=>{
   const delta=quantize((e.clientX-initialX)/zoom);if(Math.abs(e.clientX-initialX)<3&&!moved)return;moved=true
   if(kind==='move'){
    const target=(document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-track]') as HTMLElement)?.dataset.track
    const targetTrack=project.tracks.find(t=>t.id===target),from=project.tracks.find(t=>t.id===clip.track)
    const track=targetTrack&&!targetTrack.locked&&targetTrack.kind===from?.kind?target!:clip.track
    next={...clip,start:Math.max(0,snapped(clip.start+delta)),track}
   }else if(kind==='left'){
    const minimum=media&&media.kind!=='image'?Math.max(0,clip.start-clip.sourceIn):0
    const start=Math.min(clip.start+clip.length-1/project.fps,Math.max(minimum,snapped(clip.start+delta)))
    next={...clip,start,length:quantize(clip.length+clip.start-start),sourceIn:media&&media.kind!=='image'?quantize(clip.sourceIn+start-clip.start):0}
   }else{
    const limit=media&&media.kind!=='image'?media.duration-clip.sourceIn:3600-clip.start
    next={...clip,length:quantize(Math.max(1/project.fps,Math.min(Math.floor((limit+1e-7)*project.fps)/project.fps,snapped(clip.start+clip.length+delta)-clip.start)))}
   }
   setGhost(next)
  }
  const stop=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',stop);window.removeEventListener('pointercancel',cancel);document.body.classList.remove('is-dragging');cleanupDrag.current=null;setGhost(null);if(moved)safeEdit([{type:'update',id:clip.id,patch:{start:next.start,length:next.length,sourceIn:next.sourceIn,track:next.track}}])}
  const cancel=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',stop);window.removeEventListener('pointercancel',cancel);document.body.classList.remove('is-dragging');cleanupDrag.current=null;setGhost(null)}
  cleanupDrag.current=cancel;document.body.classList.add('is-dragging');window.addEventListener('pointermove',move);window.addEventListener('pointerup',stop);window.addEventListener('pointercancel',cancel)
 }
 const send=async(text=query)=>{
  if(!text.trim()||working)return
  const input=text.trim();setBusy(true)
  try{await onAI(input,selected,position);setQuery('');const rows=await api.messages(project.id);setMessages(rows)}
  catch(e){notify((e as Error).message)}finally{setBusy(false)}
 }
 const acceptProposal=async(task:Task)=>{try{await onApplyAI(task.id);notify(tr("AI修改已保存，可随时撤销。"))}catch(e){notify((e as Error).message)}}
 const canvasSeconds=Math.max(28,end+4,Math.min(120,project.target+4)),pixels=canvasSeconds*zoom
 const active=project.clips.filter(c=>position>=c.start&&position<c.start+c.length&&!project.tracks.find(t=>t.id===c.track)?.muted)
 const videoClips=active.filter(c=>project.tracks.find(t=>t.id===c.track)?.kind==='video').sort((a,b)=>project.tracks.findIndex(t=>t.id===b.track)-project.tracks.findIndex(t=>t.id===a.track))
 const titleClips=active.filter(c=>project.tracks.find(t=>t.id===c.track)?.kind==='title')
 return <div className="editor-workspace">
  <div className="editor-heading"><div><FilmStrip size={21}/><div><strong>{project.id==='project-demo'?tr(project.name):project.name}</strong><span>{project.aspect} <i>·</i> {project.fps} fps <i>·</i> {tr("修订")} {project.revision}</span></div><Tag>{project.mode==='manual'?tr("人工设置"):tr("一键编排")}</Tag></div><div><button className="quiet-button" onClick={()=>safeEdit([{type:'configure',patch:{mode:project.mode==='manual'?'one-click':'manual'}}])}><SlidersHorizontal size={16}/>{tr("切换模式")}</button><Button onClick={onExport}><Export size={17}/>{tr("导出")}</Button></div></div>
  <div className="editor-top"><aside className="editor-media"><div className="panel-heading"><h3>{tr("项目素材")}</h3><button className="icon-button" title={tr("导入素材")} onClick={onUpload}><Plus size={17}/></button></div><div className="media-tabs">{[['all',tr("全部")],['image',tr("图片")],['video',tr("视频")],['audio',tr("声音")]].map(([id,label])=><button key={id} className={mediaTab===id?'active':''} onClick={()=>setMediaTab(id)}>{tr(label)}</button>)}</div><div className="mini-assets">{project.assets.filter(a=>mediaTab==='all'||a.kind===mediaTab).map(a=><button key={a.id} onClick={()=>addAsset(a)} title={tr("点击加入时间线")}><div>{!a.url?<span className="missing-asset">{tr("请重新导入")}</span>:a.kind==='audio'?<MusicNotes size={23}/>:a.poster||a.kind==='image'?<img src={a.poster||a.url} alt=""/>:a.url?<video src={a.url} muted preload="metadata"/>:<ImageSquare size={23}/>}<span><Plus size={14}/></span></div><strong>{tr(a.name)}</strong><small>{a.kind==='image'?tr("静态画面"):time(a.duration)}</small></button>)}</div><button className="media-import" onClick={onUpload}><UploadSimple size={18}/>{tr("导入本地素材")}</button><div className="editor-material-note">{tr("示例素材不作内容证据。")}<br/>{tr("点击素材即可加入时间线。")}</div></aside>
   <section className="preview-panel"><div className="panel-heading"><div><span className="tiny-dot"/>{tr("画面预览")}</div><span>{project.aspect}<CaretDown size={12}/></span></div><div className="preview-stage"><div className={`preview-canvas aspect-${project.aspect.replace(':','-')}`}>
    {!videoClips.length&&<div className="preview-empty"><FilmStrip size={30}/><span>{tr("此处暂无画面")}</span></div>}
    {videoClips.map(c=><MediaLayer key={c.id} clip={c} asset={project.assets.find(a=>a.id===c.asset)} position={position} playing={playing}/>)}
    {titleClips.map((c,i)=><div key={c.id} className={`preview-title ${c.name===tr("片名")?'main-title':''}`} style={{opacity:c.opacity,bottom:`${12+i*12}%`,transform:`translateX(-50%) scale(${c.scale})`}}>{c.text}</div>)}
    <div className="preview-safe-frame"/>
   </div></div><div className="preview-controls"><span className="preview-time">{precise(position,project.fps)}<i> / </i>{precise(end,project.fps)}</span><div><button className="icon-button" aria-label={tr("回到开头")} onClick={()=>seek(0)}><SkipBack size={17} weight="fill"/></button><button className="preview-play" aria-label={playing?tr("暂停预览"):tr("播放预览")} onClick={()=>{if(position>=end)setPosition(0);if(end)setPlaying(p=>!p)}}>{playing?<Pause size={19} weight="fill"/>:<Play size={19} weight="fill"/>}</button><button className="icon-button" aria-label={tr("跳到结尾")} onClick={()=>seek(end)}><SkipForward size={17} weight="fill"/></button></div><span className="preview-quality">{tr("适应窗口")} <span>HD</span></span></div><div className="preview-foot"><span className="status-dot"/>{tr("本地媒体预览")}<small>{tr("空格播放 / 暂停")}</small></div>
   {active.filter(c=>project.tracks.find(t=>t.id===c.track)?.kind==='audio').map(c=><AudioLayer key={c.id} clip={c} asset={project.assets.find(a=>a.id===c.asset)} position={position} playing={playing}/>)}
   </section>
   <aside className="assistant-panel"><div className="assistant-tabs"><button className={tab==='chat'?'active':''} onClick={()=>setTab('chat')}><Sparkle size={16}/>{tr("AI 剪辑对话")}</button><button className={tab==='properties'?'active':''} onClick={()=>setTab('properties')}><SlidersHorizontal size={16}/>{tr("片段属性")}</button></div>
    {tab==='chat'?<><div className="assistant-identity"><div className="assistant-icon"><Sparkle size={21}/></div><div><strong>{tr("你的剪辑搭档")}</strong><span><i/> {modelAvailable?modelName:tr("本地模型未就绪")}</span></div><Tag>{tr("本地 AI")}</Tag></div><div className="chat-messages" ref={chatScroll}>{!messages.length&&<p className="chat-intro">{tr("描述你想改变的节奏、画面或声音。本地模型会读取当前时间线，提出可撤销的修改。")}</p>}{messages.map(m=><div key={m.id} className={`chat-message ${m.role}`}>{m.role==='assistant'&&<span className="chat-avatar"><Sparkle size={14}/></span>}<div><p>{m.text}</p>{m.changes&&<span className="change-chip"><Check size={12}/>{m.changes} {tr("项可撤销修改")}<button onClick={onUndo}>{tr("撤销")}</button></span>}</div></div>)}{working&&<div className="chat-task"><div className="chat-thinking"><span/><span/><span/>{running?.stage||tr("正在登记任务…")}</div>{running?.partial_summary&&<p>{running.partial_summary}</p>}{running&&<button className="text-link" onClick={()=>void onCancelTask(running.id).catch(e=>notify(e.message))}>{tr("停止本次推理")}</button>}</div>}{proposal&&<div className="proposal"><strong>{tr("待确认的修改 · 修订")} {proposal.result?.base_revision}</strong><p>{proposal.result?.summary}</p>{proposal.result?.operations?.length?<ul className="proposal-operations">{proposal.result.operations.map((op,i)=><li key={i}>{describe(op,project)}</li>)}</ul>:null}{proposal.result?.base_revision!==project.revision&&<p>{tr("时间线已更新，请放弃旧建议并重新发送。")}</p>}<div className="proposal-actions"><Button secondary onClick={()=>void onCancelTask(proposal.id).catch(e=>notify(e.message))}>{tr("放弃建议")}</Button><Button disabled={proposal.result?.base_revision!==project.revision} onClick={()=>void acceptProposal(proposal)}>{tr("应用到时间线")}<Check size={14}/></Button></div></div>}{latestAI?.error&&!working&&<div className="chat-task-error" role="status">{tr(latestAI.error)}</div>}</div><div className="chat-quick"><p>{tr("试着对我说")}</p>{[tr("片头缩短到3秒"),tr("音乐音量改成20%"),tr("添加字幕：让故事，连接脉动。")].map(s=><button key={s} onClick={()=>send(s)} disabled={working||!modelAvailable}>{s}<ArrowRight size={12}/></button>)}</div><form className="chat-composer" onSubmit={e=>{e.preventDefault();send()}}><textarea aria-label={tr("剪辑对话")} placeholder={tr("描述你想调整的片段…")} value={query} maxLength={6000} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();send()}}}/><div><span>{tr("可随时手动接管")}</span><button type="submit" disabled={working||!modelAvailable||!query.trim()} aria-label={tr("发送剪辑指令")}><ArrowUp size={17}/></button></div></form><p className="chat-disclaimer">{confirmAI?tr("模型建议经确认后应用。"):tr("模型修改通过校验后自动应用，可撤销。")} {tr("手动编辑始终可用。")}</p></>:<Inspector clip={selectedClip} project={project} onEdit={safeEdit} onRemove={remove}/>}
   </aside>
  </div>
  <section className="timeline-panel"><div className="timeline-toolbar"><div><button className="icon-button" title={tr("撤销 ⌘Z")} aria-label={tr("撤销")} disabled={!history.past.length} onClick={onUndo}><ArrowUUpLeft size={18}/></button><button className="icon-button" title={tr("重做 ⇧⌘Z")} aria-label={tr("重做")} disabled={!history.future.length} onClick={onRedo}><ArrowUUpRight size={18}/></button><i/><button className="quiet-button" onClick={split} title={tr("在播放头切分 S")}><Scissors size={17}/><span>{tr("切分")}</span></button><button className="icon-button" aria-label={tr("删除选中片段")} onClick={remove} disabled={!selectedClip}><Trash size={17}/></button><i/><button className="quiet-button" aria-label={tr("添加文字")} title={tr("添加文字")} onClick={addTitle}><TextT size={17}/><span>{tr("添加文字")}</span></button><button className={`snap-button ${snap?'active':''}`} onClick={()=>setSnap(!snap)}>{tr("吸附")}<span>{snap?tr("开"):tr("关")}</span></button></div><div className="timeline-zoom"><span>{precise(position,project.fps)}</span><Minus size={13}/><input aria-label={tr("时间线缩放")} type="range" min={14} max={60} value={zoom} onChange={e=>setZoom(Number(e.target.value))}/><Plus size={13}/></div></div>
   <div className="timeline-scroll"><div className="timeline-board" style={{width:pixels+115}}><div className="ruler"><span className="ruler-label">{tr("轨道 / TRACKS")}</span><div className="ruler-time" style={{width:pixels}} onPointerDown={e=>{const rect=e.currentTarget.getBoundingClientRect();seek((e.clientX-rect.left)/zoom)}}>{Array.from({length:Math.ceil(canvasSeconds/2)},(_,i)=><span key={i} style={{left:i*2*zoom}}>{time(i*2)}</span>)}</div></div>
    {project.tracks.map(t=><div className={`track-row ${t.kind} ${t.locked?'locked':''}`} key={t.id} data-track={t.id}><div className="track-label"><div><span className={`track-code ${t.color}`}>{t.id}</span><strong>{tr(t.name)}</strong></div><div><button className="icon-button" title={t.muted?tr("取消静音"):tr("静音轨道")} aria-label={`${t.muted?tr("取消静音"):tr("静音")}${tr(t.name)}`} onClick={()=>safeEdit([{type:'track',id:t.id,patch:{muted:!t.muted}}])}>{t.muted?<SpeakerSlash size={13}/>:<SpeakerHigh size={13}/>}</button><button className="icon-button" title={t.locked?tr("解锁轨道"):tr("锁定轨道")} aria-label={`${t.locked?tr("解锁"):tr("锁定")}${tr(t.name)}`} onClick={()=>safeEdit([{type:'track',id:t.id,patch:{locked:!t.locked}}])}>{t.locked?<Lock size={13} weight="fill"/>:<LockOpen size={13}/>}</button></div></div><div className="track-lane" style={{width:pixels,backgroundSize:`${zoom*2}px 100%`}} onDoubleClick={e=>{if(e.target===e.currentTarget){const r=e.currentTarget.getBoundingClientRect();seek((e.clientX-r.left)/zoom)}}}>
     {project.clips.map(clipDisplay).filter(c=>c.track===t.id).map(c=>{const asset=project.assets.find(a=>a.id===c.asset);return <div key={c.id} role="button" tabIndex={0} aria-label={tr("片段 {0}", c.name)} aria-pressed={selected===c.id} className={`timeline-clip ${t.color} ${selected===c.id?'selected':''} ${ghost?.id===c.id?'dragging':''} ${t.muted?'muted':''} ${updatedIds.has(c.id)?'ai-edited':''}`} style={{left:c.start*zoom,width:Math.max(c.length*zoom,8)}} onPointerDown={e=>beginDrag(e,c,'move')} onDoubleClick={()=>{setSelected(c.id);setTab('properties')}} onKeyDown={e=>{if(e.key==='Enter'){setSelected(c.id);setTab('properties')}}}>
      <span className="trim-handle left" onPointerDown={e=>beginDrag(e,c,'left')} aria-hidden="true"/>{t.kind==='video'&&(asset?.poster||asset?.kind==='image')&&<div className="clip-thumbs" style={{backgroundImage:`url("${asset.poster||asset.url}")`}}/>}<div className="clip-name">{t.kind==='title'?<TextT size={12}/>:t.kind==='audio'?<MusicNotes size={12}/>:<FilmStrip size={12}/>}<span>{t.kind==='title'?c.text:tr(c.name)}</span></div>{t.kind==='audio'&&<div className="clip-wave" title={tr("从原音频分析的振幅包络；不代表听审")}>{Array.from({length:Math.max(5,Math.min(100,Math.floor(c.length*zoom/4)))},(_,i)=><i key={i} style={{height:`${Math.max(3,100*(asset?.waveform?.[Math.min((asset.waveform?.length||1)-1,Math.floor((c.sourceIn+i/Math.max(5,Math.min(100,Math.floor(c.length*zoom/4)))*c.length)/Math.max(asset?.duration||1,1)*(asset?.waveform?.length||1)))]||0))}%`}}/>)}</div>}<span className="trim-handle right" onPointerDown={e=>beginDrag(e,c,'right')} aria-hidden="true"/>
     </div>})}{!project.clips.some(c=>clipDisplay(c).track===t.id)&&<span className="empty-track-label">{t.kind==='audio'?tr("从素材区添加声音到这里"):t.kind==='title'?tr("添加标题或字幕"):tr("添加叠加画面")}</span>}</div></div>)}
    <div className="playhead" style={{left:115+position*zoom}}><button aria-label={tr("播放头")} onPointerDown={e=>{e.preventDefault();const x=e.clientX,from=position;setPlaying(false);const move=(ev:PointerEvent)=>setPosition(Math.max(0,Math.min(canvasSeconds,from+(ev.clientX-x)/zoom)));const stop=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',stop)};window.addEventListener('pointermove',move);window.addEventListener('pointerup',stop)}}/></div><div className="end-marker" style={{left:115+end*zoom}}/>
   </div></div><footer className="timeline-footer"><span>{project.tracks.length} {tr("条轨道")} <i>·</i> {project.clips.length} {tr("个片段")} <i>·</i> {tr("总长")} {time(end)}</span><span>{ghost?tr("移动中 {0}", precise(ghost.start,project.fps)):tr("拖动片段移动 · 拖动两端修剪 · 双击打开属性")}</span><span>{applied?tr("AI修改已应用 · 可撤销"):tr("本机工程持久保存")}</span></footer></section>
 </div>
}

function MediaLayer({clip,asset,position,playing}:{clip:Clip;asset?:Asset;position:number;playing:boolean}) {
 const ref=useRef<HTMLVideoElement>(null)
 useEffect(()=>{const v=ref.current;if(!v)return;const target=clip.sourceIn+position-clip.start;if(Number.isFinite(v.duration)&&Math.abs(v.currentTime-target)>(playing?.22:.015))v.currentTime=Math.min(target,Math.max(0,v.duration-.01));v.volume=Math.min(1,clip.volume);if(playing&&v.paused)void v.play().catch(()=>{});if(!playing&&!v.paused)v.pause()},[position,playing,clip])
 const style={opacity:clip.opacity,width:`${clip.scale*100}%`,height:`${clip.scale*100}%`}
 if(!asset?.url)return <div className="media-layer missing-asset" style={style}>{tr("此素材需重新关联")}</div>
 return asset.kind==='image'?<img className="media-layer" src={asset.url} alt={tr(asset.name)} style={style}/>:<video className="media-layer" ref={ref} src={asset.url} poster={asset.poster} playsInline preload="auto" style={style}/>
}
function AudioLayer({clip,asset,position,playing}:{clip:Clip;asset?:Asset;position:number;playing:boolean}) {
 const ref=useRef<HTMLAudioElement>(null)
 useEffect(()=>{const a=ref.current;if(!a)return;const target=clip.sourceIn+position-clip.start;if(Number.isFinite(a.duration)&&Math.abs(a.currentTime-target)>(playing?.22:.015))a.currentTime=Math.min(target,Math.max(0,a.duration-.01));a.volume=Math.min(1,clip.volume);if(playing&&a.paused)void a.play().catch(()=>{});if(!playing&&!a.paused)a.pause()},[position,playing,clip])
 return asset?.url?<audio ref={ref} src={asset.url} preload="auto"/>:null
}
function ClipNumberField({ label, value, step, onSave }: {
 label: string; value: number; step: number; onSave: (value: number) => Promise<boolean>
}) {
 const format = (n: number) => String(Number(n.toFixed(3)))
 const [draft, setDraft] = useState(() => format(value))
 const focused = useRef(false)
 const saved = useRef(value)
 saved.current = value
 useEffect(() => {
  if (!focused.current) setDraft(format(value))
 }, [value])

 return <label className="field">{tr(label)}<input aria-label={tr(label)} type="number" step={step} min={0}
  value={draft}
  onFocus={() => { focused.current = true }}
  onChange={event => setDraft(event.currentTarget.value)}
  onBlur={async event => {
   focused.current = false
   const next = event.currentTarget.valueAsNumber
   if (!Number.isFinite(next)) {
    setDraft(format(saved.current))
    return
   }
   if (next === saved.current) return
   const applied = await onSave(next)
   if (!applied && !focused.current) setDraft(format(saved.current))
  }}
  onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur() }}
 /></label>
}

function Inspector({clip,project,onEdit,onRemove}:{clip?:Clip;project:Project;onEdit:(ops:Edit[])=>Promise<boolean>;onRemove:()=>void}) {
 if(!clip)return <Empty title={tr("选择一个片段")} detail={tr("点击时间线片段，在这里调整时间、声音与画面。")}/>
 const track=project.tracks.find(t=>t.id===clip.track),asset=project.assets.find(a=>a.id===clip.asset)
 const numeric = (label: string, key: 'start' | 'length' | 'sourceIn' | 'scale' | 'opacity' | 'volume', step = .04) => (
  <ClipNumberField key={clip.id + '-' + key} label={tr(label)} value={clip[key]} step={step}
   onSave={value => onEdit([{ type: 'update', id: clip.id, patch: { [key]: value } }])} />
 )
 return <div className="inspector"><div className="inspector-name"><span className={`track-code ${track?.color}`}>{clip.track}</span><h3>{tr(clip.name)}</h3></div><p className="field-hint">{tr("离开输入框后保存。修改可撤销。")}</p><div className="property-section"><h4>{tr("时间与位置")}</h4><div className="form-row">{numeric(tr("开始时间 / 秒"),'start')}{numeric(tr("片段时长 / 秒"),'length')}</div>{asset?.kind!=='image'&&asset&&numeric(tr("源素材入点 / 秒"),'sourceIn')}</div>{track?.kind==='title'?<div className="property-section"><h4>{tr("文字内容")}</h4><textarea aria-label={tr("片段文字")} key={`${clip.id}-${project.revision}`} defaultValue={clip.text} onBlur={e=>{if(e.target.value!==clip.text)onEdit([{type:'update',id:clip.id,patch:{text:e.target.value}}])}}/></div>:null}{track?.kind==='video'&&<div className="property-section"><h4>{tr("画面")}</h4><div className="form-row">{numeric(tr("缩放比例"),'scale',.05)}{numeric(tr("透明度"),'opacity',.05)}</div></div>}{asset&&asset.kind!=='image'&&<div className="property-section"><h4>{tr("声音")}</h4>{numeric(tr("音量 / 1 为原始音量"),'volume',.05)}</div>}<div className="property-section"><h4>{tr("素材与来源")}</h4><p>{asset?.name||tr("独立文字层")}</p>{asset&&<label className="field">{tr("替换素材")}<select value={clip.asset} onChange={e=>{const a=project.assets.find(x=>x.id===e.target.value)!;onEdit([{type:'update',id:clip.id,patch:{asset:a.id,sourceIn:0,length:a.kind==='image'?clip.length:Math.min(clip.length,a.duration)}}])}}>{project.assets.filter(a=>(track?.kind==='audio'?a.kind==='audio':a.kind!=='audio')).map(a=><option key={a.id} value={a.id}>{tr(a.name)}{!a.url?tr("（需重新导入）"):''}</option>)}</select></label>}<p className="field-hint">{asset?.note||tr("文字与底图保持独立，可随时修改。")}</p></div><button className="danger-button" onClick={onRemove}><Trash size={16}/>{tr("删除此片段")}</button></div>
}

function describe(op:Edit,project:Project){
 if(op.type==='add')return tr("添加 {0} · {1} · {2}秒", op.clip.name, op.clip.track, op.clip.length)
 if('id' in op){const name=project.clips.find(c=>c.id===op.id)?.name||project.tracks.find(t=>t.id===op.id)?.name||op.id
  if(op.type==='update'){const labels:Record<string,string>={start:'开始',length:'时长',sourceIn:'源入点',volume:'音量',opacity:'透明度',scale:'缩放',text:'文字',track:'轨道'};return `${name}：${Object.entries(op.patch).map(([k,v])=>`${tr(labels[k]||k)} → ${v}${['start','length','sourceIn'].includes(k)?tr("秒"):''}`).join(', ')}`}
  if(op.type==='delete')return tr("删除 {0}", name)
  if(op.type==='split')return tr("在 {0} 秒切分 {1}", op.time, name)
  if(op.type==='track')return `${name}：${op.patch.muted!==undefined?(op.patch.muted?tr("静音"):tr("启用声音")):''}${op.patch.locked!==undefined?(op.patch.locked?tr(" 锁定"):tr(" 解锁")):''}`
 }
 return tr("更新工程")
}
