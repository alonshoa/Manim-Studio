const assert = require('assert');
const fs = require('fs');
const path = require('path');
const {installFakeVscode} = require('./fake-vscode');
const installed = installFakeVscode();
main().then(()=>{installed.restore();console.log('classification panel behavior ok');})
  .catch(error=>{installed.restore();throw error;});

async function main(){
  const {ClassificationPanel,classificationHtml}=require('../out/classificationPanel');
  const state=new Map([['manimStudio.selectedResearchSession','A']]);
  const context={subscriptions:[],workspaceState:{get(key){return state.get(key);},async update(key,value){state.set(key,value);}}};
  const current={project_id:'project',session_id:'A',prompt_id:'p',human_head_event_id:null,review_status:'unclassified',current:null,
    prompt:{payload:{text:'Prompt'}},context:[],history:[],suggestion:null};
  let failOnce=true; const requests=[];
  const rpc={dispose(){},async request(method,params){
    requests.push({method,params:structuredClone(params)});
    if(method==='classification.schema')return {ok:true,data:{prompt_types:[],reasons:[]}};
    if(method==='classification.list')return {ok:true,data:{session_id:'A',session:{title:'A'},snapshot_seq:3,prompts:[{prompt_id:'p'}],counts:{total:1}}};
    if(method==='classification.get')return {ok:true,data:structuredClone(current)};
    if(method==='classification.save'){
      if(failOnce){failOnce=false;throw new Error('Lost reply');}
      return {ok:true,data:{...current,event_id:'saved'}};
    }
    throw new Error('Unexpected method '+method);
  }};
  installed.vscode.window.panel.dispose=()=>{};
  const controller=new ClassificationPanel(context,rpc);controller.register();await controller.open();
  const html=classificationHtml('unit-nonce');
  assert(html.includes("script-src 'nonce-unit-nonce'"));
  assert(html.includes('id="save-next"'));
  assert(html.includes('acquireVsCodeApi'));
  for(const asset of ['classification.html','classification.js','classification.css']){
    assert(fs.existsSync(path.join(__dirname,'..','media',asset)));
  }
  const ignore=fs.readFileSync(path.join(__dirname,'..','..','.gitignore'),'utf8');
  assert(ignore.includes('!vscode-extension/media/**'),'webview assets must survive git/package preparation');
  await controller.handle({type:'ready'});
  await controller.handle({type:'draft',session_id:'A',prompt_id:'p',draft:{prompt_type:'corrective',reasons:null,expected_human_head:null}});
  const key='manimStudio.classifications.v1';
  assert(state.get(key).drafts['A/p'].dirty);
  // A message from another research cannot overwrite this panel's pinned draft.
  await controller.handle({type:'draft',session_id:'B',prompt_id:'p',draft:{prompt_type:'irrelevant'}});
  assert.strictEqual(state.get(key).drafts['A/p'].prompt_type,'corrective');
  await controller.handle({type:'write',session_id:'A',prompt_id:'p',action:'save',prompt_type:'corrective',reasons:null,expected_human_head:null});
  assert(state.get(key).pending,'transport failure must keep the original request');
  const original=requests.filter(r=>r.method==='classification.save').at(-1);
  await controller.handle({type:'retry'});
  const replay=requests.filter(r=>r.method==='classification.save').at(-1);
  assert.deepStrictEqual(replay.params,original.params);
  assert.strictEqual(state.get(key).pending,undefined);
  assert.strictEqual(state.get(key).drafts['A/p'],undefined);
  assert(installed.vscode.window.posted.some(m=>m.type==='saved'));
  controller.dispose();
}
