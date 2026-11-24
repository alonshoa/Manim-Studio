import * as vscode from "vscode";
import {randomUUID} from "crypto";
import {readFileSync} from "fs";
import {join,dirname,basename} from "path";
import {StudioRpcClient} from "./studioClient";
type Data=Record<string,any>;
const STORE="manimStudio.integrity.v1";

export function integrityHtml():string {
 const nonce=randomUUID(),asset=(suffix:string)=>readFileSync(join(__dirname,"..","media",`integrity.${suffix}`),"utf8");
 return `<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'"><style nonce="${nonce}">${asset("css")}</style></head><body>${asset("html")}<script nonce="${nonce}">${asset("js")}</script></body></html>`;
}

export class IntegrityPanel {
 private panel?:vscode.WebviewPanel;
 private session?:string;
 private generation=0;
 private disposed=false;
 private busy=false;
 private loading=false;
 private poll?:NodeJS.Timeout;
 private persistence:Promise<void>=Promise.resolve();
 constructor(private context:vscode.ExtensionContext,private rpc:StudioRpcClient,private root:string){
  this.session=this.stored().session_id || context.workspaceState.get<string>("manimStudio.selectedResearchSession");
 }
 register():void {
  this.context.subscriptions.push(vscode.commands.registerCommand("manimStudio.research.showIntegrity",()=>this.open()),{dispose:()=>this.dispose()});
  this.poll=setInterval(()=>{if(this.panel)void this.refresh().catch(e=>this.error(e));},2000);
 }
 private stored():Data{return this.context.workspaceState.get<Data>(STORE)||{};}
 private persist(change:(s:Data)=>void):Promise<void>{
  const next=this.persistence.catch(()=>undefined).then(async()=>{const s=structuredClone(this.stored());change(s);await this.context.workspaceState.update(STORE,s);});this.persistence=next;return next;
 }
 private send(data:Data):void {if(!this.disposed)void this.panel?.webview.postMessage(data);}
 private error(error:unknown):void {this.send({type:"error",message:String(error),pending:!!this.stored().pending});}
 private async request(action:string,params:Data):Promise<Data>{
  const r=await this.rpc.request(action,params);if(!r.ok)throw Object.assign(new Error(r.error?.message||"Research operation failed"),{code:r.error?.code});return r.data!;
 }
 async open():Promise<void>{
  if(!vscode.workspace.isTrusted||this.disposed)return;
  if(this.panel){this.panel.reveal();await this.refresh();return;}
  const panel=this.panel=vscode.window.createWebviewPanel("manimStudio.researchIntegrity","תקינות וייצוא · מחקר",vscode.ViewColumn.Beside,{enableScripts:true,retainContextWhenHidden:true});
  panel.webview.html=integrityHtml();panel.webview.onDidReceiveMessage(m=>{void this.handle(m).catch(e=>this.error(e));});
  panel.onDidDispose(()=>{if(this.panel===panel)this.panel=undefined;});
 }
 private async choose():Promise<void>{
  if(this.stored().pending)throw new Error("יש פעולה ממתינה. נסה אותה שוב לפני החלפת מחקר.");
  const r=await this.request("research.list",{});
  const selected=await vscode.window.showQuickPick([...(r.sessions||[]),...(r.legacy_sessions||[])].map((s:Data)=>({label:s.title||s.session_id,description:s.session_id,id:s.session_id})),{placeHolder:"בחר מחקר לבדיקה וייצוא"});
  if(!selected||this.disposed)return;
  this.session=selected.id;this.generation++;
  await this.persist(s=>{s.session_id=selected.id;});await this.refresh();
 }
 private async refresh():Promise<void>{
  if(!this.session||this.disposed||!vscode.workspace.isTrusted||this.loading)return;
  const session=this.session,generation=this.generation;this.loading=true;
  try {
   const integrity=await this.request("integrity.status",{session_id:session});
   const exports=await this.request("exports.list",{session_id:session});
   if(session===this.session&&generation===this.generation)this.send({type:"state",session_id:session,checks:integrity.jobs,exports:exports.jobs,pending:!!this.stored().pending});
  } finally {this.loading=false;}
 }
 private async mutate(method:string,params:Data={},retry=false):Promise<void>{
  if(this.busy)return;this.busy=true;
  try {
   let pending:Data|undefined;
   await this.persist(s=>{if(s.pending&&!retry)throw new Error("יש פעולה ממתינה; השתמש בניסיון חוזר.");pending=retry?s.pending:{method,params:{...params,session_id:this.session,request_id:randomUUID()}};if(!pending)throw new Error("אין פעולה ממתינה");s.pending=pending;});
   try{await this.request(pending!.method,pending!.params);}catch(error){
    if((error as Data).code&&(error as Data).code!=="storage_error")await this.persist(s=>{s.pending=undefined;});throw error;
   }
   await this.persist(s=>{s.pending=undefined;});await this.refresh();
  }finally{this.busy=false;}
 }
 async handle(message:Data):Promise<void>{
  if(!message||typeof message.action!=="string"||this.disposed||!vscode.workspace.isTrusted)return;
  if(this.busy)return;
  if(message.action==="choose"){await this.choose();return;}
  if(message.action==="ready"){if(this.stored().pending?.params.session_id)this.session=this.stored().pending.params.session_id;if(!this.session)await this.choose();else await this.refresh();return;}
  if(!this.session)return;
  if(message.session_id&&message.session_id!==this.session)return;
  if(message.action==="refresh"){await this.refresh();return;}
  if(message.action==="retry"){await this.mutate("",{},true);return;}
  if(message.action==="check"){await this.mutate("integrity.check",{deep:message.deep===true});return;}
  const session=this.session,generation=this.generation;
  if(message.action==="recover"){
   await this.mutate("integrity.reconcile");
   this.send({type:"notice",message:"בדיקת ההתאוששות הסתיימה. תוצאות לא ידועות נשארות לא ידועות. הפעל בדיקה חדשה לרענון הדוח."});return;
  }
  if(message.action==="export"){
   if(!["full","metadata"].includes(message.mode))return;
   const destination=await vscode.window.showSaveDialog({title:"ייצוא מחקר — בחר יעד מחוץ לתיקיית הפרויקט",defaultUri:vscode.Uri.file(join(dirname(this.root),`${basename(this.root)}-research-${session.slice(0,8)}-${Date.now()}.zip`)),filters:{"Research ZIP":["zip"]}});
   if(!destination||this.disposed||this.session!==session||generation!==this.generation)return;
   await this.mutate("exports.start",{mode:message.mode,destination:destination.fsPath});return;
  }
  if(message.action==="cancel"&&typeof message.job_id==="string"&&["integrity","exports"].includes(message.namespace)){
   await this.mutate(`${message.namespace}.cancel`,{job_id:message.job_id});return;
  }
 }
 dispose():void{if(this.disposed)return;this.disposed=true;if(this.poll)clearInterval(this.poll);this.panel?.dispose();this.rpc.dispose();}
}
