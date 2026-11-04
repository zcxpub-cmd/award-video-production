export type Page = 'projects' | 'assets' | 'editor' | 'prompts' | 'agents' | 'exports' | 'settings'
export type Asset = { id:string; name:string; kind:'video'|'image'|'audio'; url:string; poster?:string; duration:number; width?:number; height?:number; origin:'demo'|'local'|'generated'; note:string; sha256?:string; hasAudio?:boolean; unavailable?:boolean; waveform?:number[]; waveform_coverage_seconds?:number; analysis?:{description?:string;uncertainties?:string;sampled_frame_times?:number[];full_viewing?:boolean;audio_reviewed?:boolean} }
export type Track = {id:string; name:string; kind:'video'|'title'|'audio'; color:string; muted:boolean; locked:boolean}
export type Clip = {id:string; track:string; asset?:string; name:string; start:number; length:number; sourceIn:number; volume:number; opacity:number; scale:number; text?:string}
export type Project = {id:string; name:string; brief:string; mode:'one-click'|'manual'; aspect:'16:9'|'9:16'|'1:1'; fps:number; target:number; style:string; revision:number; updated:string; assets:Asset[]; tracks:Track[]; clips:Clip[]}
export type History = {present:Project; past:Project[]; future:Project[]}
export type Edit = {type:'update';id:string;patch:Partial<Clip>} | {type:'add';clip:Clip} | {type:'delete';id:string} | {type:'split';id:string;time:number} | {type:'track';id:string;patch:Partial<Pick<Track,'muted'|'locked'>>} | {type:'configure';patch:Partial<Pick<Project,'name'|'brief'|'mode'|'aspect'|'target'|'style'|'fps'>>} | {type:'import';asset:Asset} | {type:'replace';clips:Clip[]}

export const uid = () => crypto.randomUUID().slice(0,8)
export const duration = (p:Project) => Math.max(0,...p.clips.map(c=>c.start+c.length))
export const time = (s:number) => `${Math.floor(s/60).toString().padStart(2,'0')}:${Math.floor(s%60).toString().padStart(2,'0')}`
export const precise = (s:number,fps=25) => {const frames=Math.floor(s*fps+1e-6);return `${time(Math.floor(frames/fps))}:${(frames%fps).toString().padStart(2,'0')}`}
export const tracks = ():Track[] => [
  {id:'T1',name:'字幕与标题',kind:'title',color:'ochre',muted:false,locked:false},
  {id:'V2',name:'叠加画面',kind:'video',color:'violet',muted:false,locked:false},
  {id:'V1',name:'主画面',kind:'video',color:'sage',muted:false,locked:false},
  {id:'A1',name:'旁白',kind:'audio',color:'clay',muted:false,locked:false},
  {id:'A2',name:'音乐与音效',kind:'audio',color:'blue',muted:false,locked:false},
]
export const sampleAssets:Asset[] = [
 {id:'mountain-still',name:'雪山的第一束光.webp',kind:'image',url:'/cover/mountain.webp',duration:0,width:1672,height:941,origin:'demo',note:'图序自产虚构视觉素材 · 原型示例'},
 {id:'ocean-motion',name:'潮汐与呼吸.mp4',kind:'video',url:'/cover/ocean.mp4',poster:'/cover/ocean.webp',duration:4.541667,width:1280,height:720,origin:'demo',note:'图序自产循环短片 · 原型示例'},
 {id:'ocean-still',name:'海面的留白.webp',kind:'image',url:'/cover/ocean.webp',duration:0,width:1672,height:941,origin:'demo',note:'图序自产虚构视觉素材 · 原型示例'},
 {id:'dna-motion',name:'生命的微观秩序.mp4',kind:'video',url:'/cover/dna.mp4',poster:'/cover/dna.webp',duration:4.541667,width:1280,height:720,origin:'demo',note:'图序自产循环短片 · 原型示例'},
 {id:'dna-still',name:'微观结构.webp',kind:'image',url:'/cover/dna.webp',duration:0,width:1672,height:941,origin:'demo',note:'图序自产虚构视觉素材，不作科学证据'},
 {id:'studio-tone',name:'低音量和弦试音.wav',kind:'audio',url:'/cover/studio-tone.wav',duration:16,origin:'demo',note:'程序合成测试音 · 非配乐质量样本'},
]
const baseClip = {sourceIn:0,volume:1,opacity:1,scale:1}
export function demoProject():Project {
 const clips:Clip[] = [
  {id:'shot-01',track:'V1',asset:'mountain-still',name:'雪山 · 序章',start:0,length:6,...baseClip},
  {id:'shot-02',track:'V1',asset:'ocean-motion',name:'潮汐 · 呼吸',start:6,length:4,...baseClip},
  {id:'shot-03',track:'V1',asset:'ocean-still',name:'海面 · 留白',start:10,length:6,...baseClip},
  {id:'shot-04',track:'V1',asset:'dna-motion',name:'生命 · 微观',start:16,length:4,...baseClip},
  {id:'shot-05',track:'V1',asset:'mountain-still',name:'群山 · 尾声',start:20,length:4,...baseClip},
  {id:'overlay-01',track:'V2',asset:'dna-still',name:'结构叠加',start:12,length:4,...baseClip,scale:.4,opacity:.85},
  {id:'title-01',track:'T1',name:'片名',start:0,length:4,...baseClip,text:'山 海 之 间'},
  {id:'title-02',track:'T1',name:'章节字幕',start:8,length:4,...baseClip,text:'万物，自有节奏。'},
  {id:'title-03',track:'T1',name:'尾声',start:20,length:4,...baseClip,text:'让故事，连接脉动。'},
  {id:'music-01',track:'A2',asset:'studio-tone',name:'低音量和弦试音',start:0,length:16,...baseClip,volume:.28},
 ]
 return {id:'project-demo',name:'山海之间',brief:'一支关于自然、生命与时间的短片。以群山开场，让潮汐接续呼吸，在微观与宏观之间找到叙事的节奏。',mode:'manual',aspect:'16:9',fps:25,target:24,style:'自然纪录片',revision:0,updated:new Date().toISOString(),assets:structuredClone(sampleAssets),tracks:tracks(),clips}
}
export function createProject(name:string,mode:Project['mode'],aspect:Project['aspect'],target:number):Project {
 return {...demoProject(),id:uid(),name:name.trim()||'未命名故事',mode,aspect,target,brief:'',clips:[]}
}
export function validate(p:Project) {
 if (!p.name.trim() || p.name.length>100) throw Error('项目名称需要为 1–100 个字符。')
 const ids = new Set<string>()
 for (const c of p.clips) {
  if (ids.has(c.id)) throw Error('片段编号重复。'); ids.add(c.id)
  const track=p.tracks.find(t=>t.id===c.track), asset=p.assets.find(a=>a.id===c.asset)
  if (!track) throw Error('轨道不存在。')
  for(const n of [c.start,c.length,c.sourceIn,c.volume,c.opacity,c.scale]) if(!Number.isFinite(n)) throw Error('时间与参数必须是有效数字。')
  if(c.start<0 || c.length<1/p.fps-1e-6 || c.sourceIn<0 || c.start+c.length>3600) throw Error('片段需要至少一帧，且位于一小时以内。')
  if(c.volume<0||c.volume>2||c.opacity<0||c.opacity>1||c.scale<.1||c.scale>2) throw Error('音量、透明度或缩放超出范围。')
  if(track.kind==='title') {if(c.asset||typeof c.text!=='string')throw Error('标题轨道需要文字片段。')}
  else {
   if(!asset || (track.kind==='audio'?asset.kind!=='audio':asset.kind==='audio')) throw Error('素材类型与轨道不匹配。')
   if(asset.kind!=='image'&&c.sourceIn+c.length>asset.duration+1e-4) throw Error('修剪范围超出了原素材时长。')
  }
 }
}
export function edit(p:Project, op:Edit):Project {
 const n=structuredClone(p)
 const clip='id'in op?n.clips.find(c=>c.id===op.id):undefined
 if(['update','delete','split'].includes(op.type)) {
  if(!clip)throw Error('片段不存在。')
  if(n.tracks.find(t=>t.id===clip.track)?.locked)throw Error('此轨道已锁定。')
 }
 switch(op.type) {
  case 'update': if(n.tracks.find(t=>t.id===op.patch.track)?.locked)throw Error('目标轨道已锁定。');Object.assign(clip!,op.patch,{id:clip!.id});break
  case 'add': if(n.tracks.find(t=>t.id===op.clip.track)?.locked)throw Error('目标轨道已锁定。');n.clips.push(structuredClone(op.clip));break
  case 'delete':n.clips=n.clips.filter(c=>c.id!==op.id);break
  case 'split': {
   const left=op.time-clip!.start,right=clip!.length-left
   if(left<1/p.fps || right<1/p.fps) throw Error('切分位置需要位于片段内部。')
   n.clips.push({...clip!,id:uid(),start:op.time,length:right,sourceIn:clip!.sourceIn+left,name:clip!.name+' · 后段'})
   clip!.length=left;break
  }
  case 'track':Object.assign(n.tracks.find(t=>t.id===op.id)!,op.patch);break
  case 'configure':Object.assign(n,op.patch);break
  case 'import':n.assets.push(op.asset);break
  case 'replace':if(n.tracks.some(t=>t.locked))throw Error('请先解锁轨道，再重新编排。');n.clips=structuredClone(op.clips);break
 }
 validate(n);n.revision=p.revision+1;n.updated=new Date().toISOString();return n
}
export function commit(h:History, operations:Edit[]):History {
 const next=operations.reduce(edit,h.present)
 return {present:next,past:[...h.past,h.present].slice(-40),future:[]}
}
export function undo(h:History):History {
 if(!h.past.length)return h
 const present={...h.past.at(-1)!,revision:h.present.revision+1,updated:new Date().toISOString()}
 return {present,past:h.past.slice(0,-1),future:[h.present,...h.future].slice(0,40)}
}
export function redo(h:History):History {
 if(!h.future.length)return h
 return {present:{...h.future[0],revision:h.present.revision+1,updated:new Date().toISOString()},past:[...h.past,h.present].slice(-40),future:h.future.slice(1)}
}
export function autoArrange(p:Project):Clip[] {
 const visuals=p.assets.filter(a=>a.kind!=='audio')
 if(!visuals.length)throw Error('请先加入图片或视频素材。')
 const result:Clip[]=[];const share=p.target/visuals.length;let position=0
 for(const a of visuals){
  const length=Math.floor(Math.min(a.kind==='image'?share:a.duration,share)*p.fps)/p.fps
  if(length<1/p.fps)continue
  result.push({...baseClip,id:uid(),track:'V1',asset:a.id,name:a.name,start:position,length});position+=length
 }
 const stills=result.filter(c=>p.assets.find(a=>a.id===c.asset)?.kind==='image')
 const remaining=Math.max(0,Math.round((p.target-position)*p.fps))
 if(stills.length&&remaining){stills.forEach((c,i)=>c.length+=(Math.floor(remaining/stills.length)+(i<remaining%stills.length?1:0))/p.fps);position=0;for(const c of result){c.start=position;position+=c.length}}
 result.push({...baseClip,id:uid(),track:'T1',name:'片名',text:p.name,start:0,length:Math.min(3,position)})
 const music=p.assets.find(a=>a.kind==='audio')
 if(music)result.push({...baseClip,id:uid(),track:'A2',asset:music.id,name:music.name,start:0,length:Math.min(position,music.duration),volume:.25})
 return result
}
export function demoInstruction(text:string,p:Project,selected:string|null):{operations:Edit[];summary:string} {
 const chosen=p.clips.find(c=>c.id===selected)
 if(/片头.*(?:缩短|改|调整|设置).*?(\d+(?:\.\d+)?)\s*秒/.test(text)) {
  const seconds=Number(text.match(/(\d+(?:\.\d+)?)\s*秒/)![1]); const first=p.clips.filter(c=>c.track==='V1').sort((a,b)=>a.start-b.start)[0]
  if(!first)throw Error('主画面轨道中还没有片头。')
  return {operations:[{type:'update',id:first.id,patch:{length:seconds}}],summary:`将片头时长改为 ${seconds} 秒；后续镜头位置保留。`}
 }
 if(/音乐.*?(\d+)\s*%/.test(text)) {
  const volume=Number(text.match(/(\d+)\s*%/)![1])/100
  const clips=p.clips.filter(c=>c.track==='A2');if(!clips.length)throw Error('音乐轨道中还没有片段。')
  return {operations:clips.map(c=>({type:'update',id:c.id,patch:{volume}})),summary:`将音乐轨道中的片段音量改为 ${Math.round(volume*100)}%。`}
 }
 if(/添加(?:标题|字幕)[：:\s]*(.+)/.test(text)) {
  const title=text.match(/添加(?:标题|字幕)[：:\s]*(.+)/)![1]
  return {operations:[{type:'add',clip:{...baseClip,id:uid(),track:'T1',name:'新字幕',text:title,start:0,length:Math.min(4,duration(p)||4)}}],summary:`在开头加入文字「${title}」，持续 4 秒。`}
 }
 if(/(?:选中|当前).*?(?:移到|移动到).*?(\d+(?:\.\d+)?)\s*秒/.test(text)) {
  if(!chosen)throw Error('请先选择一个片段。')
  const start=Number(text.match(/(\d+(?:\.\d+)?)\s*秒/)![1])
  return {operations:[{type:'update',id:chosen.id,patch:{start}}],summary:`将「${chosen.name}」移到 ${start} 秒。`}
 }
 if(/删除.*(?:选中|当前)/.test(text)) {
  if(!chosen)throw Error('请先选择一个片段。')
  return {operations:[{type:'delete',id:chosen.id}],summary:`删除「${chosen.name}」。原素材保留。`}
 }
 throw Error('原型支持下方示例指令，以及“将选中片段移到10秒”“删除选中片段”。正式版将接入模型理解更多表达。')
}
