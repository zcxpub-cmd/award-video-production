import type { Edit, History, Project } from './editor'
export type RuntimeSettings={revision:number;execution_revision:number;theme:'dark'|'light';appearanceVersion?:2;motion:boolean;confirmAI:boolean;ollama_model:string;vision_enabled:boolean;generation_enabled:boolean;generation_model:string;generation_max_requests:number;generation_has_key:boolean}
export type Workspace={current:string;projects:Record<string,History>;settings:RuntimeSettings;migration_available?:boolean}
export type ModelHealth={available:boolean;models:string[];provider:string;error?:string}
export type Task={id:string;project_id:string;kind:'render'|'auto'|'ai-edit'|'observe'|'generation';status:string;stage:string;progress:number|null;created_at:string;updated_at:string;input_revision:number;external_id?:string;error?:string;partial_summary?:string;output_characters?:number;result?:{duration?:number;files?:string[];qc?:Record<string,unknown>;revision?:number;summary?:string;operations?:Edit[];history_action?:'none'|'undo'|'redo';base_revision?:number;applied_revision?:number;metrics?:Record<string,unknown>;asset_id?:string}}
export type Bootstrap=Workspace&{token:string;models:ModelHealth;media:Record<string,unknown>;runtime:{identity:string;version:string;data_directory:string}}
export class ApiError extends Error{status:number;constructor(message:string,status:number){super(message);this.status=status}}
let token=''
const requestId=()=>crypto.randomUUID()
async function request<T>(path:string,method='GET',body?:unknown):Promise<T>{
 const isForm=body instanceof FormData
 let response:Response
 try{response=await fetch('/api'+path,{method,credentials:'same-origin',headers:{...(method!=='GET'?{'X-Yingxu-Token':token}:{}),...(!isForm&&body!==undefined?{'Content-Type':'application/json'}:{})},body:body===undefined?undefined:isForm?body:JSON.stringify(body)})}
 catch{throw new ApiError('本地服务连接中断。请恢复连接后查询当前工程和原任务，不要盲目重复提交。',0)}
 if(!response.headers.get('content-type')?.includes('application/json'))throw new ApiError('当前端口未连接影序正式后端，请使用开源版启动器启动工作台。',response.status)
 const data=await response.json()
 if(!response.ok)throw new ApiError(typeof data.detail==='string'?data.detail:'请求未完成，请检查输入与本地服务。',response.status)
 return data as T
}
export const activeTask=(task:Task)=>['queued','running','submitted'].includes(task.status)
export const api={
 async bootstrap(){const b=await request<Bootstrap>('/bootstrap');token=b.token;return b},
 workspace:()=>request<Workspace>('/workspace'),
 migrate:(body:unknown)=>request<Workspace>('/migrate','POST',body),
 project:(id:string)=>request<History>('/projects/'+id),
 select:(id:string)=>request<History>('/projects/'+id+'/select','POST',{}),
 create:(project:Project)=>request<History>('/projects','POST',{name:project.name,mode:project.mode,aspect:project.aspect,target:project.target,use_samples:project.assets.length>0}),
 edit:(id:string,revision:number,operations:Edit[])=>request<History>('/projects/'+id+'/edit','POST',{expected_revision:revision,request_id:requestId(),operations}),
 history:(id:string,revision:number,direction:'undo'|'redo')=>request<History>('/projects/'+id+'/history','POST',{expected_revision:revision,request_id:requestId(),direction}),
 upload:(id:string,revision:number,file:File,relink?:string)=>{const body=new FormData();body.append('file',file);const params=new URLSearchParams({expected_revision:String(revision),request_id:requestId(),asset_id:requestId()});if(relink)params.set('relink',relink);return request<History>('/projects/'+id+'/assets?'+params,'POST',body)},
 importProject:(file:File)=>{const body=new FormData();body.append('file',file);return request<History>('/import-project','POST',body)},
 settings:()=>request<{settings:RuntimeSettings;models:ModelHealth;media:Record<string,unknown>}>('/settings'),
 saveSettings:(revision:number,patch:Partial<RuntimeSettings>&{generation_key?:string;clear_generation_key?:boolean})=>request<RuntimeSettings>('/settings','PUT',{expected_revision:revision,patch}),
 tasks:(id:string)=>request<Task[]>('/projects/'+id+'/jobs'),
 task:(id:string)=>request<Task>('/jobs/'+id),
 start:(id:string,revision:number,kind:Task['kind'],options:Record<string,unknown>={})=>request<Task>('/projects/'+id+'/jobs','POST',{kind,expected_revision:revision,request_id:requestId(),options}),
 cancel:(id:string)=>request<Task>('/jobs/'+id+'/cancel','POST',{}),
 apply:(id:string)=>request<History>('/jobs/'+id+'/apply','POST',{}),
 query:(id:string,external_id?:string)=>request<Task>('/jobs/'+id+'/query-original','POST',{external_id}),
 messages:(id:string)=>request<{id:string;role:'assistant'|'user';text:string;task?:string}[]>('/projects/'+id+'/messages'),
 file:(task:string,file:string)=>'/api/jobs/'+task+'/files/'+encodeURIComponent(file),
 projectFile:(id:string)=>'/api/projects/'+id+'/project.json',
}
