import * as vscode from "vscode";
import {randomUUID} from "crypto";
import {readFileSync} from "fs";
import {join} from "path";
import {StudioRpcClient} from "./studioClient";
type Data=Record<string,any>;
const STORE="manimStudio.time.v1";

export function timeHtml():string {
 const nonce=randomUUID(),asset=(suffix:string)=>readFileSync(join(__dirname,"..","media",`time.${suffix}`),"utf8");
 return `<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'"><style nonce="${nonce}">${asset("css")}</style></head><body>${asset("html")}<script nonce="${nonce}">${asset("js")}</script></body></html>`;
}

export class TimePanel {
 private panel?:vscode.WebviewPanel;
 private session?:string;
 private page?:Data;
 private generation=0;
 private busy=false;
 private beating=false;
 private loading=false;
 private disposed=false;
 private poll?:NodeJS.Timeout;
 private beat?:NodeJS.Timeout;
 private persistence:Promise<void>=Promise.resolve();
 private readonly client=randomUUID();
 private readonly bar:vscode.StatusBarItem;
 constructor(private context:vscode.ExtensionContext,private rpc:StudioRpcClient){
  this.session=this.stored().session_id || context.workspaceState.get<string>("manimStudio.selectedResearchSession");
  this.bar=vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left,98);this.bar.command="manimStudio.research.showTime";
 }
 register():void {
  this.context.subscriptions.push(vscode.commands.registerCommand("manimStudio.research.showTime",()=>this.open()),{dispose:()=>this.dispose()});
  this.poll=setInterval(()=>{void this.refresh().catch(e=>this.error(e));},5000);
  this.beat=setInterval(()=>{void this.heartbeat().catch(e=>this.error(e));},15000);
 }
 private stored():Data {return this.context.workspaceState.get<Data>(STORE)||{drafts:{}};}
 private persist(change:(state:Data)=>void):Promise<void>{
  const next=this.persistence.catch(()=>undefined).then(async()=>{const state=structuredClone(this.stored());state.drafts ||= {};change(state);await this.context.workspaceState.update(STORE,state);});
  this.persistence=next;return next;
 }
 private send(data:Data):void {if(!this.disposed)void this.panel?.webview.postMessage(data);}
 private error(error:unknown):void {this.send({type:"error",message:String(error)});this.bar.text="זמן מחקר: המצב אינו מעודכן";this.bar.show();}
 private async request(action:string,params:Data):Promise<Data>{
  const r=await this.rpc.request(`timing.${action}`,params);if(!r.ok)throw Object.assign(new Error(r.error?.message||"Time operation failed"),{code:r.error?.code});return r.data!;
 }
 async open():Promise<void>{
  if(!vscode.workspace.isTrusted || this.disposed)return;
  if(this.panel){this.panel.reveal();return;}
  this.panel=vscode.window.createWebviewPanel("manimStudio.researchTime","זמן עבודה · מחקר",vscode.ViewColumn.Beside,{enableScripts:true,retainContextWhenHidden:true});
  const panel=this.panel;panel.webview.html=timeHtml();
  panel.webview.onDidReceiveMessage(message=>{void this.handle(message).catch(e=>this.error(e));});
  panel.onDidDispose(()=>{if(this.panel===panel)this.panel=undefined;});
 }
 private async choose():Promise<void>{
  if(this.stored().pending){this.send({type:"error",message:"יש פעולה ממתינה. נסה אותה שוב לפני החלפת מחקר."});return;}
  const r=await this.rpc.request("research.list",{});if(!r.ok)throw new Error(r.error?.message);
  const sessions=[...(r.data?.sessions as Data[]||[]),...(r.data?.legacy_sessions as Data[]||[])];
  const picked=await vscode.window.showQuickPick(sessions.map(s=>({label:s.title||s.label||s.session_id,id:s.session_id})),{placeHolder:"בחר מחקר למדידה ודיווח"});
  if(!picked)return;this.session=picked.id;this.generation++;
  await this.persist(state=>{state.session_id=this.session;});await this.refresh();
 }
 private async refresh():Promise<void>{
  if(!this.session || this.disposed || !vscode.workspace.isTrusted || this.loading)return;
  this.loading=true;const session=this.session,generation=this.generation;
  try {
   const state=await this.request("status",{session_id:session,client_id:this.client});
   const contexts=await this.request("contexts",{session_id:session});
   if(session!==this.session||generation!==this.generation||this.disposed)return;
   this.page=state;this.send({type:"state",...state,contexts:contexts.contexts,draft:this.stored().drafts?.[session]});
   this.bar.text=state.active?`$(clock) ${state.active.title} · ${state.active.category==="classification"?"סיווג":"עבודה"} · ${Number(state.active.measured_seconds).toFixed(0)}s מאושרות` : "$(clock) זמן מחקר: מושהה";this.bar.show();
  }finally{this.loading=false;}
 }
 private async mutate(action:string,params:Data={},retry=false):Promise<void>{
  if(this.busy)return;this.busy=true;
  try {
   let pending:Data|undefined;
   await this.persist(state=>{
    if(state.pending&&!retry)throw new Error("יש פעולה ממתינה; השתמש בניסיון חוזר לפני פעולה נוספת.");
    pending=retry?state.pending:{action,params:{...params,session_id:params.session_id||this.session,project_id:this.page?.project_id,client_id:this.client,request_id:randomUUID()},draft:state.drafts?.[this.session!]};
    if(!pending)throw new Error("אין פעולה ממתינה");
    state.pending=pending;
   });
   try {await this.request(pending!.action,pending!.params);}catch(error){const code=(error as Data).code;if(code&&code!=="storage_error")await this.persist(s=>{s.pending=undefined;});throw error;}
   let cleared=false;
   await this.persist(s=>{s.pending=undefined;if(["report","correct"].includes(pending!.action)&&JSON.stringify(s.drafts?.[pending!.params.session_id])===JSON.stringify(pending!.draft)){delete s.drafts[pending!.params.session_id];cleared=true;}});
   if(cleared&&pending!.params.session_id===this.session)this.send({type:"saved",draft:pending!.draft});
   else this.send({type:"notice",message:"הפעולה אושרה. טיוטה חדשה יותר, אם קיימת, נשמרה."});
   await this.refresh();
  }finally{this.busy=false;}
 }
 async heartbeat():Promise<void>{
  if(this.disposed||this.beating||!vscode.workspace.isTrusted)return;
  const active=this.page?.active;if(!active?.owned)return;
  this.beating=true;
  try {
   let pending:Data|undefined;
   await this.persist(s=>{
    // A report awaiting explicit retry must not starve the live timer's lease.
    const prior=s.heartbeat;
    pending=prior?.params.client_id===this.client&&prior.params.interval_id===active.interval_id?prior:
     {params:{session_id:active.session_id,project_id:this.page?.project_id,client_id:this.client,interval_id:active.interval_id,sequence:active.sequence+1,request_id:randomUUID()}};
    s.heartbeat=pending;
   });
   try{await this.request("heartbeat",pending!.params);}catch(error){
    if((error as Data).code&&(error as Data).code!=="storage_error")await this.persist(s=>{s.heartbeat=undefined;});
    throw error;
   }
   await this.persist(s=>{s.heartbeat=undefined;});await this.refresh();
  }finally{this.beating=false;}
 }
 async handle(message:Data):Promise<void>{
  if(!message||typeof message.action!=="string"||this.disposed)return;
  if(message.action==="draft"){
   if(typeof message.session_id!=="string"||message.session_id!==this.session||!message.fields||JSON.stringify(message.fields).length>16000)return;
   await this.persist(s=>{s.drafts[message.session_id]=message.fields;});this.send({type:"draftSaved"});return;
  }
  if(this.busy)return;
  if(message.action==="choose"){await this.choose();return;}
  if(message.action==="ready"){if(!this.session)await this.choose();else await this.refresh();return;}
  if(!this.session)return;
  if(message.action==="refresh"){await this.refresh();return;}
  if(message.action==="retry"){await this.mutate("",{},true);return;}
  const session=this.session,generation=this.generation,page=this.page;
  if(!page){await this.refresh();return;}
  if(message.action==="start"){await this.mutate("start",{category:message.category,extension_version:this.context.extension?.packageJSON.version||null,expected_revision:page.revision});return;}
  if(["pause","stop","transfer"].includes(message.action)){
   const active=page.active;if(!active)return;
   await this.mutate(message.action,{session_id:active.session_id,interval_id:active.interval_id,expected_revision:page.revision,
    ...(message.action==="transfer"?{target_session_id:session,category:message.category,extension_version:this.context.extension?.packageJSON.version||null}:{})});return;
  }
  if(["report","correct","void"].includes(message.action)){
   if(message.session_id&&message.session_id!==session)return;
   const report=page.reports.find((r:Data)=>r.report_id===message.report_id);
   if(message.action!=="report"&&!report)return;
   const replacement=message.replaces_interval_id??report?.replaces_interval_id;
   const interval=page.intervals.find((i:Data)=>i.interval_id===replacement);
   const params:Data={};
   for(const key of ["category","seconds","start_utc","end_utc","measurement_ref","replaces_interval_id","report_id","expected_revision"]){if(message[key]!==undefined)params[key]=message[key];}
   if(interval)params.expected_interval_revision=interval.revision;
   if(message.action==="void"){
    const answer=await vscode.window.showWarningMessage("לבטל דיווח זה? הגרסאות הקודמות יישארו בהיסטוריה.",{modal:true},"בטל דיווח");
    if(answer!=="בטל דיווח"||session!==this.session||generation!==this.generation)return;
   }
   await this.mutate(message.action,params);return;
  }
  if(message.action==="observe_context"){
   await this.mutate("observe_context",{extension_version:this.context.extension?.packageJSON.version||null});return;
  }
  if(message.action==="history"){
   const result=await this.request("history",{session_id:session});
   if(session===this.session&&generation===this.generation)this.send({type:"history",events:result.events});
  }
 }
 dispose():void{this.disposed=true;if(this.poll)clearInterval(this.poll);if(this.beat)clearInterval(this.beat);this.panel?.dispose();this.bar.dispose();this.rpc.dispose();}
}
