import { useCallback, useEffect, useRef, useState } from 'react'
import { api, activeTask, type Bootstrap, type RuntimeSettings, type Task, type Workspace } from './api'
import { commit, type Edit, type History, type Project } from './editor'

export function useWorkspace(notify:(s:string)=>void){
 const [workspace,setWorkspace]=useState<Workspace|null>(null),[models,setModels]=useState<Bootstrap['models']>({available:false,models:[],provider:'Ollama · 本机'}),[runtime,setRuntime]=useState<Bootstrap['runtime']|null>(null),[error,setError]=useState(''),[saving,setSaving]=useState(0),[jobs,setJobs]=useState<Task[]>([])
 const ref=useRef<Workspace|null>(null),pending=useRef(new Set<Promise<unknown>>()),epoch=useRef(0),lastJobs=useRef(new Map<string,string>()),loading=useRef<Promise<void>|null>(null)
 const changeQueue = useRef(Promise.resolve())
 const install=(w:Workspace)=>{ref.current=w;setWorkspace(w)}
 const updateHistory=useCallback((id:string,h:History)=>{const previous=ref.current;if(!previous)return;const existing=previous.projects[id];if(existing&&existing.present.revision>h.present.revision)return;install({...previous,projects:{...previous.projects,[id]:h}})},[])
 const refresh=useCallback(async(id?:string)=>{const pid=id||ref.current?.current;if(!pid)return;const h=await api.project(pid);updateHistory(pid,h);return h},[updateHistory])
 const load=useCallback(()=>{
  if(loading.current)return loading.current
  loading.current=(async()=>{setError('')
  try{
   const boot=await api.bootstrap();let w:Workspace=boot
   if(boot.migration_available){
    try{const old=JSON.parse(localStorage.getItem('yingxu.interface-prototype.v1')||'null');if(old?.projects&&Object.keys(old.projects).length)w=await api.migrate(old)}
    catch(e){notify('旧浏览器工程迁移未完成，原备份保留：'+(e as Error).message)}
   }
   install(w);setModels(boot.models);setRuntime(boot.runtime)
  }catch(e){setError((e as Error).message)}
 })().finally(()=>{loading.current=null});return loading.current
 },[])
 useEffect(()=>{void load()},[load])
 const track=async<T,>(promise:Promise<T>):Promise<T>=>{
  pending.current.add(promise);setSaving(s=>s+1)
  try{return await promise}finally{pending.current.delete(promise);setSaving(s=>Math.max(0,s-1))}
 }
 const flush=async()=>{await Promise.allSettled([...pending.current])}
 const queueChange=<T,>(operation:()=>Promise<T>)=>{
  const result=changeQueue.current.then(operation)
  changeQueue.current=result.then(()=>{},()=>{})
  return track(result)
 }
 const edit=async(operations:Edit[])=>{
  const pid=ref.current?.current
  if(!pid)throw Error('工程尚未连接。')
  return queueChange(async()=>{
   const history=ref.current?.projects[pid]
   if(!history)throw Error('工程尚未连接。')
   commit(history,operations)
   try{updateHistory(pid,await api.edit(pid,history.present.revision,operations))}
   catch(error){await refresh(pid).catch(()=>{});throw error}
  })
 }
 const moveHistory=async(direction:'undo'|'redo')=>{
  const pid=ref.current?.current
  if(!pid)return
  try{
   await queueChange(async()=>updateHistory(pid,await api.history(pid,ref.current!.projects[pid].present.revision,direction)))
  }catch(e){await refresh(pid).catch(()=>{});notify((e as Error).message)}
 }
 const select=async(id:string)=>{try{await flush();const h=await api.select(id);const w=ref.current!;install({...w,current:id,projects:{...w.projects,[id]:h}})}catch(e){notify((e as Error).message)}}
 const create=async(p:Project)=>{const h=await track(api.create(p));const w=ref.current!;install({...w,current:h.present.id,projects:{...w.projects,[h.present.id]:h}});return h.present}
 const upload=async(file:File,relink?:string,pid=ref.current?.current)=>{
  if(!pid)throw Error('工程尚未连接。')
  return queueChange(async()=>{
   const h=await api.upload(pid,ref.current!.projects[pid].present.revision,file,relink)
   updateHistory(pid,h)
   return h
  })
 }
 const importProject=async(file:File)=>{await flush();const h=await track(api.importProject(file)),w=ref.current!;install({...w,current:h.present.id,projects:{...w.projects,[h.present.id]:h}});return h.present}
 const settings=async(patch:Partial<RuntimeSettings>&{generation_key?:string;clear_generation_key?:boolean})=>{
  const w=ref.current!;try{const result=await track(api.saveSettings(w.settings.revision,patch));const current=ref.current!;if(result.revision>=current.settings.revision)install({...current,settings:result})}
  catch(e){const current=await api.settings().catch(()=>null);if(current)install({...ref.current!,settings:current.settings});notify((e as Error).message);throw e}
 }
 const refreshModels=async()=>{const r=await api.settings();setModels(r.models);install({...ref.current!,settings:r.settings});return r}
 const start=async(kind:Task['kind'],options:Record<string,unknown>)=>{await flush();const w=ref.current!;const task=await api.start(w.current,w.projects[w.current].present.revision,kind,options);setJobs(j=>[task,...j.filter(x=>x.id!==task.id)]);return task}
 const applyAI=async(id:string)=>{const h=await api.apply(id);updateHistory(h.present.id,h);const task=await api.task(id);setJobs(j=>j.map(x=>x.id===id?task:x));return h}
 const cancel=async(id:string)=>{const result=await api.cancel(id);setJobs(j=>j.map(x=>x.id===id?result:x));return result}
 const query=async(id:string,external?:string)=>{const result=await api.query(id,external);setJobs(j=>j.map(x=>x.id===id?result:x));return result}
 const currentId=workspace?.current
 useEffect(()=>{
  if(!currentId)return
  const stamp=++epoch.current;let stopped=false;let timer:ReturnType<typeof setTimeout>
  const poll=async()=>{
   try{const rows=await api.tasks(currentId);if(stopped||stamp!==epoch.current)return
    setJobs(rows)
    for(const task of rows){const previous=lastJobs.current.get(task.id);lastJobs.current.set(task.id,task.status);if(previous&&previous!==task.status&&!activeTask(task))void refresh(currentId).catch(()=>{})}
   }catch{/* A task polling failure never resubmits a task. */}
   if(!stopped)timer=setTimeout(poll,900)
  };setJobs([]);void poll();return()=>{stopped=true;clearTimeout(timer)}
 },[currentId,refresh])
 return {workspace,models,runtime,error,saving,jobs,load,edit,moveHistory,select,create,upload,importProject,settings,refreshModels,start,applyAI,cancel,query,refresh}
}
