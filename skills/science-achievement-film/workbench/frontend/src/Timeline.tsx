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
 useEffect(()=>{if(initialPrompt){setQuery(initialPrompt.slice(0,6000));clearPrompt();setTab('chat');if(initialPrompt.length>6000)notify('正文较长，对话草稿已放入前 6,000 字；完整正文仍可在灵感库复制。')}},[initialPrompt])
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
 const split=async()=>{const clip=selectedClip||project.clips.find(c=>c.track==='V1'&&position>c.start&&position<c.start+c.length);if(!clip){notify('先选择片段，并把播放头放在片段内部。');return}if(await safeEdit([{type:'split',id:clip.id,time:Math.round(position*project.fps)/project.fps}]))notify('片段已切分，源内入点同步保留。')}
 const remove=async()=>{if(!selectedClip){notify('先选择一个片段。');return}if(await safeEdit([{type:'delete',id:selectedClip.id}]))setSelected(null)}
 useEffect(()=>{const key=(e:KeyboardEvent)=>{if((e.target as HTMLElement)?.closest('input,textarea,select,button,a,[contenteditable],[role=dialog]'))return;if(e.code==='Space'){e.preventDefault();if(end){if(position>=end)setPosition(0);setPlaying(p=>!p)}}if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='z'){e.preventDefault();e.shiftKey?onRedo():onUndo()}if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();remove()}if(e.key.toLowerCase()==='s'&&!e.metaKey&&!e.ctrlKey)split()};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key)},[selectedClip,position,end,onUndo,onRedo])
 const addAsset=async(asset:Asset)=>{
  if(!asset.url){notify('此素材需要重新导入后替换。');return}
  const id=uid();const track=asset.kind==='audio'?'A1':'V1';const start=asset.kind==='audio'?position:end
  if(await safeEdit([{type:'add',clip:{id,track,asset:asset.id,name:asset.name,start:Math.round(start*project.fps)/project.fps,length:asset.kind==='image'?4:Math.min(4,asset.duration),sourceIn:0,volume:asset.kind==='audio'?.6:1,opacity:1,scale:1}}])){setSelected(id);notify('素材已加入时间线。')}
 }
 const addTitle=async()=>{const id=uid();if(await safeEdit([{type:'add',clip:{id,track:'T1',name:'新标题',text:'写下你的故事',start:Math.round(position*project.fps)/project.fps,length:3,sourceIn:0,volume:1,opacity:1,scale:1}}])){setSelected(id);setTab('properties')}}
 const beginDrag=(event:ReactPointerEvent,clip:Clip,kind:'move'|'left'|'right')=>{
  event.stopPropagation();if(event.button!==0)return;setSelected(clip.id)
  if(project.tracks.find(t=>t.id===clip.track)?.locked){notify('轨道已锁定，请先解锁。');return}
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
 const acceptProposal=async(task:Task)=>{try{await onApplyAI(task.id);notify('AI修改已保存，可随时撤销。')}catch(e){notify((e as Error).message)}}
 const canvasSeconds=Math.max(28,end+4,Math.min(120,project.target+4)),pixels=canvasSeconds*zoom
 const active=project.clips.filter(c=>position>=c.start&&position<c.start+c.length&&!project.tracks.find(t=>t.id===c.track)?.muted)
 const videoClips=active.filter(c=>project.tracks.find(t=>t.id===c.track)?.kind==='video').sort((a,b)=>project.tracks.findIndex(t=>t.id===b.track)-project.tracks.findIndex(t=>t.id===a.track))
 const titleClips=active.filter(c=>project.tracks.find(t=>t.id===c.track)?.kind==='title')
 return <div className="editor-workspace">
  <div className="editor-heading"><div><FilmStrip size={21}/><div><strong>{project.name}</strong><span>{project.aspect} <i>·</i> {project.fps} fps <i>·</i> 修订 {project.revision}</span></div><Tag>{project.mode==='manual'?'人工设置':'一键编排'}</Tag></div><div><button className="quiet-button" onClick={()=>safeEdit([{type:'configure',patch:{mode:project.mode==='manual'?'one-click':'manual'}}])}><SlidersHorizontal size={16}/>切换模式</button><Button onClick={onExport}><Export size={17}/>导出</Button></div></div>
  <div className="editor-top"><aside className="editor-media"><div className="panel-heading"><h3>项目素材</h3><button className="icon-button" title="导入素材" onClick={onUpload}><Plus size={17}/></button></div><div className="media-tabs">{[['all','全部'],['image','图片'],['video','视频'],['audio','声音']].map(([id,label])=><button key={id} className={mediaTab===id?'active':''} onClick={()=>setMediaTab(id)}>{label}</button>)}</div><div className="mini-assets">{project.assets.filter(a=>mediaTab==='all'||a.kind===mediaTab).map(a=><button key={a.id} onClick={()=>addAsset(a)} title="点击加入时间线"><div>{!a.url?<span className="missing-asset">请重新导入</span>:a.kind==='audio'?<MusicNotes size={23}/>:a.poster||a.kind==='image'?<img src={a.poster||a.url} alt=""/>:a.url?<video src={a.url} muted preload="metadata"/>:<ImageSquare size={23}/>}<span><Plus size={14}/></span></div><strong>{a.name}</strong><small>{a.kind==='image'?'静态画面':time(a.duration)}</small></button>)}</div><button className="media-import" onClick={onUpload}><UploadSimple size={18}/>导入本地素材</button><div className="editor-material-note">示例素材不作内容证据。<br/>点击素材即可加入时间线。</div></aside>
   <section className="preview-panel"><div className="panel-heading"><div><span className="tiny-dot"/>画面预览</div><span>{project.aspect}<CaretDown size={12}/></span></div><div className="preview-stage"><div className={`preview-canvas aspect-${project.aspect.replace(':','-')}`}>
    {!videoClips.length&&<div className="preview-empty"><FilmStrip size={30}/><span>此处暂无画面</span></div>}
    {videoClips.map(c=><MediaLayer key={c.id} clip={c} asset={project.assets.find(a=>a.id===c.asset)} position={position} playing={playing}/>)}
    {titleClips.map((c,i)=><div key={c.id} className={`preview-title ${c.name==='片名'?'main-title':''}`} style={{opacity:c.opacity,bottom:`${12+i*12}%`,transform:`translateX(-50%) scale(${c.scale})`}}>{c.text}</div>)}
    <div className="preview-safe-frame"/>
   </div></div><div className="preview-controls"><span className="preview-time">{precise(position,project.fps)}<i> / </i>{precise(end,project.fps)}</span><div><button className="icon-button" aria-label="回到开头" onClick={()=>seek(0)}><SkipBack size={17} weight="fill"/></button><button className="preview-play" aria-label={playing?'暂停预览':'播放预览'} onClick={()=>{if(position>=end)setPosition(0);if(end)setPlaying(p=>!p)}}>{playing?<Pause size={19} weight="fill"/>:<Play size={19} weight="fill"/>}</button><button className="icon-button" aria-label="跳到结尾" onClick={()=>seek(end)}><SkipForward size={17} weight="fill"/></button></div><span className="preview-quality">适应窗口 <span>HD</span></span></div><div className="preview-foot"><span className="status-dot"/>本地媒体预览<small>空格播放 / 暂停</small></div>
   {active.filter(c=>project.tracks.find(t=>t.id===c.track)?.kind==='audio').map(c=><AudioLayer key={c.id} clip={c} asset={project.assets.find(a=>a.id===c.asset)} position={position} playing={playing}/>)}
   </section>
   <aside className="assistant-panel"><div className="assistant-tabs"><button className={tab==='chat'?'active':''} onClick={()=>setTab('chat')}><Sparkle size={16}/>AI 剪辑对话</button><button className={tab==='properties'?'active':''} onClick={()=>setTab('properties')}><SlidersHorizontal size={16}/>片段属性</button></div>
    {tab==='chat'?<><div className="assistant-identity"><div className="assistant-icon"><Sparkle size={21}/></div><div><strong>你的剪辑搭档</strong><span><i/> {modelAvailable?modelName:'本地模型未就绪'}</span></div><Tag>本地 AI</Tag></div><div className="chat-messages" ref={chatScroll}>{!messages.length&&<p className="chat-intro">描述你想改变的节奏、画面或声音。本地模型会读取当前时间线，提出可撤销的修改。</p>}{messages.map(m=><div key={m.id} className={`chat-message ${m.role}`}>{m.role==='assistant'&&<span className="chat-avatar"><Sparkle size={14}/></span>}<div><p>{m.text}</p>{m.changes&&<span className="change-chip"><Check size={12}/>{m.changes} 项可撤销修改<button onClick={onUndo}>撤销</button></span>}</div></div>)}{working&&<div className="chat-task"><div className="chat-thinking"><span/><span/><span/>{running?.stage||'正在登记任务…'}</div>{running?.partial_summary&&<p>{running.partial_summary}</p>}{running&&<button className="text-link" onClick={()=>void onCancelTask(running.id).catch(e=>notify(e.message))}>停止本次推理</button>}</div>}{proposal&&<div className="proposal"><strong>待确认的修改 · 修订 {proposal.result?.base_revision}</strong><p>{proposal.result?.summary}</p>{proposal.result?.operations?.length?<ul className="proposal-operations">{proposal.result.operations.map((op,i)=><li key={i}>{describe(op,project)}</li>)}</ul>:null}{proposal.result?.base_revision!==project.revision&&<p>时间线已更新，请放弃旧建议并重新发送。</p>}<div className="proposal-actions"><Button secondary onClick={()=>void onCancelTask(proposal.id).catch(e=>notify(e.message))}>放弃建议</Button><Button disabled={proposal.result?.base_revision!==project.revision} onClick={()=>void acceptProposal(proposal)}>应用到时间线<Check size={14}/></Button></div></div>}{latestAI?.error&&!working&&<div className="chat-task-error" role="status">{latestAI.error}</div>}</div><div className="chat-quick"><p>试着对我说</p>{['片头缩短到3秒','音乐音量改成20%','添加字幕：让故事，连接脉动。'].map(s=><button key={s} onClick={()=>send(s)} disabled={working||!modelAvailable}>{s}<ArrowRight size={12}/></button>)}</div><form className="chat-composer" onSubmit={e=>{e.preventDefault();send()}}><textarea aria-label="剪辑对话" placeholder="描述你想调整的片段…" value={query} maxLength={6000} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();send()}}}/><div><span>可随时手动接管</span><button type="submit" disabled={working||!modelAvailable||!query.trim()} aria-label="发送剪辑指令"><ArrowUp size={17}/></button></div></form><p className="chat-disclaimer">{confirmAI?'模型建议经确认后应用。':'模型修改通过校验后自动应用，可撤销。'} 手动编辑始终可用。</p></>:<Inspector clip={selectedClip} project={project} onEdit={safeEdit} onRemove={remove}/>}
   </aside>
  </div>
  <section className="timeline-panel"><div className="timeline-toolbar"><div><button className="icon-button" title="撤销 ⌘Z" aria-label="撤销" disabled={!history.past.length} onClick={onUndo}><ArrowUUpLeft size={18}/></button><button className="icon-button" title="重做 ⇧⌘Z" aria-label="重做" disabled={!history.future.length} onClick={onRedo}><ArrowUUpRight size={18}/></button><i/><button className="quiet-button" onClick={split} title="在播放头切分 S"><Scissors size={17}/><span>切分</span></button><button className="icon-button" aria-label="删除选中片段" onClick={remove} disabled={!selectedClip}><Trash size={17}/></button><i/><button className="quiet-button" aria-label="添加文字" title="添加文字" onClick={addTitle}><TextT size={17}/><span>添加文字</span></button><button className={`snap-button ${snap?'active':''}`} onClick={()=>setSnap(!snap)}>吸附<span>{snap?'开':'关'}</span></button></div><div className="timeline-zoom"><span>{precise(position,project.fps)}</span><Minus size={13}/><input aria-label="时间线缩放" type="range" min={14} max={60} value={zoom} onChange={e=>setZoom(Number(e.target.value))}/><Plus size={13}/></div></div>
   <div className="timeline-scroll"><div className="timeline-board" style={{width:pixels+115}}><div className="ruler"><span className="ruler-label">轨道 / TRACKS</span><div className="ruler-time" style={{width:pixels}} onPointerDown={e=>{const rect=e.currentTarget.getBoundingClientRect();seek((e.clientX-rect.left)/zoom)}}>{Array.from({length:Math.ceil(canvasSeconds/2)},(_,i)=><span key={i} style={{left:i*2*zoom}}>{time(i*2)}</span>)}</div></div>
    {project.tracks.map(t=><div className={`track-row ${t.kind} ${t.locked?'locked':''}`} key={t.id} data-track={t.id}><div className="track-label"><div><span className={`track-code ${t.color}`}>{t.id}</span><strong>{t.name}</strong></div><div><button className="icon-button" title={t.muted?'取消静音':'静音轨道'} aria-label={`${t.muted?'取消静音':'静音'}${t.name}`} onClick={()=>safeEdit([{type:'track',id:t.id,patch:{muted:!t.muted}}])}>{t.muted?<SpeakerSlash size={13}/>:<SpeakerHigh size={13}/>}</button><button className="icon-button" title={t.locked?'解锁轨道':'锁定轨道'} aria-label={`${t.locked?'解锁':'锁定'}${t.name}`} onClick={()=>safeEdit([{type:'track',id:t.id,patch:{locked:!t.locked}}])}>{t.locked?<Lock size={13} weight="fill"/>:<LockOpen size={13}/>}</button></div></div><div className="track-lane" style={{width:pixels,backgroundSize:`${zoom*2}px 100%`}} onDoubleClick={e=>{if(e.target===e.currentTarget){const r=e.currentTarget.getBoundingClientRect();seek((e.clientX-r.left)/zoom)}}}>
     {project.clips.map(clipDisplay).filter(c=>c.track===t.id).map(c=>{const asset=project.assets.find(a=>a.id===c.asset);return <div key={c.id} role="button" tabIndex={0} aria-label={`片段 ${c.name}`} aria-pressed={selected===c.id} className={`timeline-clip ${t.color} ${selected===c.id?'selected':''} ${ghost?.id===c.id?'dragging':''} ${t.muted?'muted':''} ${updatedIds.has(c.id)?'ai-edited':''}`} style={{left:c.start*zoom,width:Math.max(c.length*zoom,8)}} onPointerDown={e=>beginDrag(e,c,'move')} onDoubleClick={()=>{setSelected(c.id);setTab('properties')}} onKeyDown={e=>{if(e.key==='Enter'){setSelected(c.id);setTab('properties')}}}>
      <span className="trim-handle left" onPointerDown={e=>beginDrag(e,c,'left')} aria-hidden="true"/>{t.kind==='video'&&(asset?.poster||asset?.kind==='image')&&<div className="clip-thumbs" style={{backgroundImage:`url("${asset.poster||asset.url}")`}}/>}<div className="clip-name">{t.kind==='title'?<TextT size={12}/>:t.kind==='audio'?<MusicNotes size={12}/>:<FilmStrip size={12}/>}<span>{t.kind==='title'?c.text:c.name}</span></div>{t.kind==='audio'&&<div className="clip-wave" title="从原音频分析的振幅包络；不代表听审">{Array.from({length:Math.max(5,Math.min(100,Math.floor(c.length*zoom/4)))},(_,i)=><i key={i} style={{height:`${Math.max(3,100*(asset?.waveform?.[Math.min((asset.waveform?.length||1)-1,Math.floor((c.sourceIn+i/Math.max(5,Math.min(100,Math.floor(c.length*zoom/4)))*c.length)/Math.max(asset?.duration||1,1)*(asset?.waveform?.length||1)))]||0))}%`}}/>)}</div>}<span className="trim-handle right" onPointerDown={e=>beginDrag(e,c,'right')} aria-hidden="true"/>
     </div>})}{!project.clips.some(c=>clipDisplay(c).track===t.id)&&<span className="empty-track-label">{t.kind==='audio'?'从素材区添加声音到这里':t.kind==='title'?'添加标题或字幕':'添加叠加画面'}</span>}</div></div>)}
    <div className="playhead" style={{left:115+position*zoom}}><button aria-label="播放头" onPointerDown={e=>{e.preventDefault();const x=e.clientX,from=position;setPlaying(false);const move=(ev:PointerEvent)=>setPosition(Math.max(0,Math.min(canvasSeconds,from+(ev.clientX-x)/zoom)));const stop=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',stop)};window.addEventListener('pointermove',move);window.addEventListener('pointerup',stop)}}/></div><div className="end-marker" style={{left:115+end*zoom}}/>
   </div></div><footer className="timeline-footer"><span>{project.tracks.length} 条轨道 <i>·</i> {project.clips.length} 个片段 <i>·</i> 总长 {time(end)}</span><span>{ghost?`移动中 ${precise(ghost.start,project.fps)}`:'拖动片段移动 · 拖动两端修剪 · 双击打开属性'}</span><span>{applied?'AI修改已应用 · 可撤销':'本机工程持久保存'}</span></footer></section>
 </div>
}

function MediaLayer({clip,asset,position,playing}:{clip:Clip;asset?:Asset;position:number;playing:boolean}) {
 const ref=useRef<HTMLVideoElement>(null)
 useEffect(()=>{const v=ref.current;if(!v)return;const target=clip.sourceIn+position-clip.start;if(Number.isFinite(v.duration)&&Math.abs(v.currentTime-target)>(playing?.22:.015))v.currentTime=Math.min(target,Math.max(0,v.duration-.01));v.volume=Math.min(1,clip.volume);if(playing&&v.paused)void v.play().catch(()=>{});if(!playing&&!v.paused)v.pause()},[position,playing,clip])
 const style={opacity:clip.opacity,width:`${clip.scale*100}%`,height:`${clip.scale*100}%`}
 if(!asset?.url)return <div className="media-layer missing-asset" style={style}>此素材需重新关联</div>
 return asset.kind==='image'?<img className="media-layer" src={asset.url} alt={asset.name} style={style}/>:<video className="media-layer" ref={ref} src={asset.url} poster={asset.poster} playsInline preload="auto" style={style}/>
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

 return <label className="field">{label}<input aria-label={label} type="number" step={step} min={0}
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
 if(!clip)return <Empty title="选择一个片段" detail="点击时间线片段，在这里调整时间、声音与画面。"/>
 const track=project.tracks.find(t=>t.id===clip.track),asset=project.assets.find(a=>a.id===clip.asset)
 const numeric = (label: string, key: 'start' | 'length' | 'sourceIn' | 'scale' | 'opacity' | 'volume', step = .04) => (
  <ClipNumberField key={clip.id + '-' + key} label={label} value={clip[key]} step={step}
   onSave={value => onEdit([{ type: 'update', id: clip.id, patch: { [key]: value } }])} />
 )
 return <div className="inspector"><div className="inspector-name"><span className={`track-code ${track?.color}`}>{clip.track}</span><h3>{clip.name}</h3></div><p className="field-hint">离开输入框后保存。修改可撤销。</p><div className="property-section"><h4>时间与位置</h4><div className="form-row">{numeric('开始时间 / 秒','start')}{numeric('片段时长 / 秒','length')}</div>{asset?.kind!=='image'&&asset&&numeric('源素材入点 / 秒','sourceIn')}</div>{track?.kind==='title'?<div className="property-section"><h4>文字内容</h4><textarea aria-label="片段文字" key={`${clip.id}-${project.revision}`} defaultValue={clip.text} onBlur={e=>{if(e.target.value!==clip.text)onEdit([{type:'update',id:clip.id,patch:{text:e.target.value}}])}}/></div>:null}{track?.kind==='video'&&<div className="property-section"><h4>画面</h4><div className="form-row">{numeric('缩放比例','scale',.05)}{numeric('透明度','opacity',.05)}</div></div>}{asset&&asset.kind!=='image'&&<div className="property-section"><h4>声音</h4>{numeric('音量 / 1 为原始音量','volume',.05)}</div>}<div className="property-section"><h4>素材与来源</h4><p>{asset?.name||'独立文字层'}</p>{asset&&<label className="field">替换素材<select value={clip.asset} onChange={e=>{const a=project.assets.find(x=>x.id===e.target.value)!;onEdit([{type:'update',id:clip.id,patch:{asset:a.id,sourceIn:0,length:a.kind==='image'?clip.length:Math.min(clip.length,a.duration)}}])}}>{project.assets.filter(a=>(track?.kind==='audio'?a.kind==='audio':a.kind!=='audio')).map(a=><option key={a.id} value={a.id}>{a.name}{!a.url?'（需重新导入）':''}</option>)}</select></label>}<p className="field-hint">{asset?.note||'文字与底图保持独立，可随时修改。'}</p></div><button className="danger-button" onClick={onRemove}><Trash size={16}/>删除此片段</button></div>
}

function describe(op:Edit,project:Project){
 if(op.type==='add')return `添加 ${op.clip.name} · ${op.clip.track} · ${op.clip.length}秒`
 if('id' in op){const name=project.clips.find(c=>c.id===op.id)?.name||project.tracks.find(t=>t.id===op.id)?.name||op.id
  if(op.type==='update'){const labels:Record<string,string>={start:'开始',length:'时长',sourceIn:'源入点',volume:'音量',opacity:'透明度',scale:'缩放',text:'文字',track:'轨道'};return `${name}：${Object.entries(op.patch).map(([k,v])=>`${labels[k]||k} → ${v}${['start','length','sourceIn'].includes(k)?'秒':''}`).join('，')}`}
  if(op.type==='delete')return `删除 ${name}`
  if(op.type==='split')return `在 ${op.time} 秒切分 ${name}`
  if(op.type==='track')return `${name}：${op.patch.muted!==undefined?(op.patch.muted?'静音':'启用声音'):''}${op.patch.locked!==undefined?(op.patch.locked?' 锁定':' 解锁'):''}`
 }
 return '更新工程'
}
