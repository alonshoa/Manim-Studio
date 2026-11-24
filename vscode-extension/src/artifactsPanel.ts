import * as vscode from "vscode";
import { randomUUID } from "crypto";
import { readFileSync } from "fs";
import { join } from "path";
import { StudioRpcClient } from "./studioClient";
type Data = Record<string, any>;
const STORE = "manimStudio.artifacts.v1";

export function artifactsHtml(): string {
  const folder=join(__dirname,"..","media"), nonce=randomUUID();
  const asset=(name:string) => readFileSync(join(folder,`artifacts.${name}`),"utf8");
  return `<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'"><style nonce="${nonce}">${asset("css")}</style></head><body>${asset("html")}<script nonce="${nonce}">${asset("js")}</script></body></html>`;
}

export class ArtifactsPanel {
  private panel?: vscode.WebviewPanel;
  private session?: string;
  private page?: Data;
  private generation=0;
  private offset=0;
  private timer?: NodeJS.Timeout;
  private busy=false;
  private loading=false;
  private disposed=false;
  constructor(private context:vscode.ExtensionContext, private rpc:StudioRpcClient) {}
  register():void {
    for(const [command,action] of [["showArtifacts","open"],["captureCheckpoint","checkpoint"],["configureCaptureScope","configure"]]) {
      this.context.subscriptions.push(vscode.commands.registerCommand(`manimStudio.research.${command}`,async()=>{await this.open();if(action!=="open" && this.session) await this.handle({action});}));
    }
    this.context.subscriptions.push({dispose:()=>this.dispose()});
  }
  private stored():Data { return this.context.workspaceState.get<Data>(STORE) || {}; }
  private async request(action:string,params:Data):Promise<Data> {
    const result=await this.rpc.request(`artifacts.${action}`,params);
    if(!result.ok) throw Object.assign(new Error(result.error?.message || "Artifact operation failed"),{code:result.error?.code});
    return result.data!;
  }
  private send(message:Data):void { if(!this.disposed) void this.panel?.webview.postMessage(message); }
  async open():Promise<void> {
    if(!vscode.workspace.isTrusted || this.disposed) return;
    if(this.panel) {this.panel.reveal();return;}
    this.session=this.stored().session_id || this.context.workspaceState.get<string>("manimStudio.selectedResearchSession");
    this.panel=vscode.window.createWebviewPanel("manimStudio.researchArtifacts","תוצרים והחלטות · מחקר",vscode.ViewColumn.Beside,{enableScripts:true,retainContextWhenHidden:true});
    const panel=this.panel;panel.webview.html=artifactsHtml();
    panel.webview.onDidReceiveMessage(message=>{void this.handle(message).catch(error=>this.send({type:"error",message:String(error)}));});
    panel.onDidDispose(()=>{if(this.panel===panel){this.panel=undefined;this.generation++;if(this.timer)clearInterval(this.timer);}});
    this.timer=setInterval(()=>{if(this.panel?.visible && !this.busy)void this.refresh().catch(error=>this.send({type:"error",message:String(error)}));},4000);
  }
  private async choose():Promise<void> {
    if(this.stored().pending) {this.send({type:"error",message:"יש פעולה ממתינה. נסה אותה שוב לפני החלפת מחקר."});return;}
    const response=await this.rpc.request("research.list",{});
    if(!response.ok)throw new Error(response.error?.message);
    const rows=[...(response.data?.sessions as Data[] || []),...(response.data?.legacy_sessions as Data[] || [])];
    const choice=await vscode.window.showQuickPick(rows.map(s=>({label:s.title || s.label || s.session_id,id:s.session_id})),{placeHolder:"בחר מחקר לתוצרים ולהחלטות"});
    if(!choice)return;
    this.session=choice.id;this.offset=0;this.generation++;
    await this.context.workspaceState.update(STORE,{...this.stored(),session_id:this.session});await this.refresh();
  }
  private async refresh():Promise<void> {
    if(!this.session || this.loading)return;
    this.loading=true;
    const session=this.session,generation=this.generation;
    try {
      const page=await this.request("list",{session_id:session,offset:this.offset});
      if(session!==this.session || generation!==this.generation)return;
      this.page=page;this.send({type:"state",sessionTitle:page.session_title,...page});
    } finally {this.loading=false;}
  }
  private async mutate(action:string,params:Data,retry=false):Promise<void> {
    if(this.busy)return;
    this.busy=true;
    try {
      const old=this.stored();
      if(old.pending && !retry)throw new Error("יש פעולה ממתינה; השתמש בניסיון חוזר לפני פעולה נוספת.");
      const pending=retry?old.pending:{action,params:{...params,session_id:this.session,project_id:this.page?.project_id,request_id:randomUUID()}};
      if(!pending)throw new Error("אין פעולה ממתינה");
      await this.context.workspaceState.update(STORE,{...old,session_id:this.session,pending});
      try {
        await this.request(pending.action,pending.params);
      } catch(error) {
        const code=(error as Data).code;
        if(code && code!=="storage_error") await this.context.workspaceState.update(STORE,{...this.stored(),pending:undefined});
        throw error;
      }
      await this.context.workspaceState.update(STORE,{...this.stored(),pending:undefined});
      this.send({type:"notice",message:"הפעולה נשמרה"});await this.refresh();
    } finally {this.busy=false;}
  }
  private async content(id:string):Promise<Data> {
    return this.request("content",{session_id:this.session,artifact_id:id});
  }
  async handle(message:Data):Promise<void> {
    if(this.busy || !message || typeof message.action!=="string")return;
    if(message.action==="choose"){await this.choose();return;}
    if(message.action==="ready"){if(!this.session)await this.choose();else await this.refresh();return;}
    if(!this.session)return;
    if(message.action==="refresh"){await this.refresh();return;}
    if(message.action==="next" || message.action==="previous") {
      this.offset=message.action==="next"?this.page?.next_offset ?? this.offset:Math.max(0,this.offset-100);this.generation++;await this.refresh();return;
    }
    if(message.action==="checkpoint" || message.action==="retry_jobs"){await this.mutate(message.action,{});return;}
    if(message.action==="retry"){await this.mutate("",{},true);return;}
    if(message.action==="configure") {
      const session=this.session,generation=this.generation;
      const scope=await vscode.window.showQuickPick([{label:"למחקר הזה",scope:"session"},{label:"ברירת מחדל לפרויקט",scope:"project"}],{placeHolder:"היכן להחיל את הגדרות האיסוף?"});
      if(!scope || session!==this.session || generation!==this.generation)return;
      const policy=await this.request("policy",{session_id:session});
      const input=await vscode.window.showInputBox({prompt:"קבצים או תיקיות נוספים בפרויקט, מופרדים בפסיקים; ריק משאיר את ברירת המחדל",value:policy.values.paths.join(", ")});
      if(input===undefined || session!==this.session || generation!==this.generation)return;
      const quota=await vscode.window.showInputBox({prompt:"מכסת תוכן למחקר ב־MiB",value:String(policy.values.session_bytes/1024**2),validateInput:value=>Number.isInteger(Number(value)) && Number(value)>0?undefined:"נדרש מספר חיובי שלם"});
      if(quota===undefined || session!==this.session || generation!==this.generation)return;
      const projectQuota=scope.scope==="project"?await vscode.window.showInputBox({prompt:"מכסת תוכן לפרויקט ב־MiB",value:String(policy.values.project_bytes/1024**2),validateInput:value=>Number.isInteger(Number(value)) && Number(value)>0?undefined:"נדרש מספר חיובי שלם"}):String(policy.values.project_bytes/1024**2);
      if(projectQuota===undefined || session!==this.session || generation!==this.generation)return;
      const values={...policy.values,project_bytes:Number(projectQuota)*1024**2,paths:input.split(",").map(s=>s.trim()).filter(Boolean),session_bytes:Number(quota)*1024**2};
      const preview=await this.request("preview_scope",{session_id:session,values});
      const answer=await vscode.window.showInformationMessage(`היקף: ${preview.paths.length} קבצים. ${preview.paths.slice(0,12).join(", ")}. ההגדרה חלה קדימה בלבד.`,{modal:true},"שמור היקף");
      if(answer!=="שמור היקף" || session!==this.session || generation!==this.generation)return;
      await this.mutate("configure",{values,scope:scope.scope,expected_revision:scope.scope==="project"?policy.project_revision:policy.revision});return;
    }
    const artifact=this.page?.artifacts.find((a:Data)=>a.artifact_id===message.artifact_id);
    const session=this.session,generation=this.generation;
    if(message.action==="compare") {
      const decision=this.page?.decisions.find((d:Data)=>d.decision_id===message.decision_id);
      if(!decision)return;
      const candidate=await this.content(decision.candidate.candidate_source.artifact_id);
      const baseline=await this.content(decision.candidate.baseline_source.artifact_id);
      if(session!==this.session || generation!==this.generation)return;
      const left=await vscode.workspace.openTextDocument({content:baseline.text,language:"python"});
      const right=await vscode.workspace.openTextDocument({content:candidate.text,language:"python"});
      await vscode.commands.executeCommand("vscode.diff",left.uri,right.uri,"בסיס ↔ מועמד שנשמר");return;
    }
    if(!artifact && message.action!=="open")return;
    if(message.action==="detail") {
      const history=await this.request("history",{session_id:session,artifact_id:artifact.artifact_id});
      if(session===this.session && generation===this.generation)this.send({type:"content",text:`קובץ: ${artifact.path}\nמצב: ${artifact.status}\nגודל: ${artifact.size ?? "לא ידוע"} bytes\nSHA-256: ${artifact.sha256 ?? "לא נשמר"}\n\nהיסטוריה:\n${history.events.map((e:Data)=>`${e.timestamp} · ${e.type} · ${e.payload.status || e.payload.reason || ""}`).join("\n")}`});return;
    }
    if(message.action==="purge") {
      const answer=await vscode.window.showWarningMessage(`להסיר את התוכן השמור של ${artifact.path}? ההיסטוריה תישאר; לא תוכל לשחזר את התוכן מרשומה זו.`,{modal:true},"הסר תוכן");
      if(answer==="הסר תוכן" && session===this.session && generation===this.generation)await this.mutate("purge",{artifact_id:artifact.artifact_id,expected_revision:artifact.revision});return;
    }
    if(message.action==="open") {
      const result=await this.content(message.artifact_id);
      if(session!==this.session || generation!==this.generation)return;
      if(result.path) await vscode.commands.executeCommand("vscode.open",vscode.Uri.file(result.path));
      else {const doc=await vscode.workspace.openTextDocument({content:result.text,language:result.artifact.path.endsWith(".py")?"python":"plaintext"});await vscode.window.showTextDocument(doc,{preview:true});}
      if(session!==this.session || generation!==this.generation || !this.page?.can_capture)return;
      await this.mutate("presented",{artifact_id:result.artifact.artifact_id,sha256:result.artifact.sha256});
    }
  }
  private presentations = new Set<string>();
  async recordPresentation(session:string,build:string):Promise<void> {
    const key=`${session}/${build}`;
    if(this.presentations.has(key))return;
    this.presentations.add(key);
    try {await this.request("presented_build",{session_id:session,build_id:build,request_id:`preview:${session}:${build}`});}
    catch {this.presentations.delete(key);}
  }
  dispose():void {this.disposed=true;this.generation++;if(this.timer)clearInterval(this.timer);this.panel?.dispose();this.rpc.dispose();}
}
