const assert = require('assert');
const {installFakeVscode} = require('./fake-vscode');
const installed=installFakeVscode();
const {ArtifactsPanel, artifactsHtml}=require('../out/artifactsPanel');
(async()=>{
  const vscode=installed.vscode;
  const originalPanel=vscode.window.createWebviewPanel;
  vscode.window.createWebviewPanel=(...args)=>({...originalPanel(...args),dispose(){}});
  const html=artifactsHtml();assert(html.includes("default-src 'none'"));assert(html.includes('תוצרים והחלטות'));assert(html.includes('textContent'));assert(!html.includes('innerHTML'));
  const store=new Map([['manimStudio.selectedResearchSession','A']]);
  const context={subscriptions:[],workspaceState:{get:k=>store.get(k),update:async(k,v)=>store.set(k,v)}};
  const calls=[];let lose=false;
  const rpc={dispose(){},async request(method,params){calls.push({method,params:structuredClone(params)});
    if(method==='artifacts.list')return {ok:true,data:{project_id:'project',session_id:params.session_id,artifacts:[],decisions:[],snapshots:[],offset:0,total:0}};
    if(method==='artifacts.checkpoint' && lose){lose=false;throw new Error('reply lost');}
    return {ok:true,data:{}};
  }};
  const panel=new ArtifactsPanel(context,rpc);await panel.open();await panel.handle({action:'ready'});
  store.set('manimStudio.selectedResearchSession','B');await panel.handle({action:'refresh'});
  assert.strictEqual(calls.at(-1).params.session_id,'A');
  lose=true;await assert.rejects(()=>panel.handle({action:'checkpoint'}),/reply lost/);
  const first=calls.at(-1);const pending=store.get('manimStudio.artifacts.v1').pending;
  assert.strictEqual(pending.params.request_id,first.params.request_id);
  await panel.handle({action:'retry'});
  const requests=calls.filter(c=>c.method==='artifacts.checkpoint');assert.deepStrictEqual(requests[1].params,first.params);
  assert.strictEqual(store.get('manimStudio.artifacts.v1').pending,undefined);
  // Recreating the controller restores the explicit artifacts selection.
  panel.dispose();const restored=new ArtifactsPanel(context,rpc);await restored.open();await restored.handle({action:'ready'});assert.strictEqual(calls.at(-1).params.session_id,'A');restored.dispose();
  console.log('artifact panel persistence, pinned selection and idempotent retry ok');
})().finally(()=>installed.restore()).catch(error=>{console.error(error);process.exitCode=1;});
