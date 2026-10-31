/* Render the extension's exact webview and exercise it against its real Python RPC.
 * Requires playwright + a Chromium executable. No model calls or user data.
 * CHROMIUM_EXECUTABLE can point to a locally provisioned Chromium build.
 */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const os = require('os');
const {spawn, spawnSync} = require('child_process');
const readline = require('readline');
const {chromium} = require('playwright');
const {installFakeVscode} = require('../vscode-extension/test/fake-vscode');
const repo = path.resolve(__dirname, '..');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'classification-ui-'));
const env = {...process.env, PYTHONPATH: path.join(repo, 'src')};
const python = process.env.PYTHON || 'python';
const seed = spawnSync(python, ['-X','utf8',path.join(__dirname,'classification-demo.py'),root], {env,encoding:'utf8'});
assert.strictEqual(seed.status,0,seed.stderr);
const fixture = JSON.parse(seed.stdout);
const child = spawn(python,['-X','utf8','-m','manim_studio.research_cli','--root',root,'rpc'],{env,stdio:['pipe','pipe','pipe']});
const requests = new Map(); let nextId = 0, stderr = '', dropNextSaveReply = false, holdNextSave = false, releaseHeld;
child.stderr.on('data', b => stderr += b.toString());
readline.createInterface({input:child.stdout}).on('line',line=>{const response=JSON.parse(line);const item=requests.get(response.id);requests.delete(response.id);if(item){clearTimeout(item.timer);item.resolve(response);}});
function request(method,params) {
  const id=++nextId;
  return new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('RPC timeout '+stderr)),8000);requests.set(id,{resolve,reject,timer});child.stdin.write(JSON.stringify({id,method,params})+'\n');});
}
const rpc={async request(method,params){const result=await request(method,params);if(method==='classification.save'&&holdNextSave){holdNextSave=false;await new Promise(resolve=>releaseHeld=resolve);}if(method==='classification.save'&&dropNextSaveReply){dropNextSaveReply=false;throw new Error('Injected lost reply after commit');}return result;},dispose(){}};
const installed=installFakeVscode();
const {ClassificationPanel}=require('../vscode-extension/out/classificationPanel');
const store = new Map([['manimStudio.selectedResearchSession', fixture.session_id]]);
const context={subscriptions:[],workspaceState:{get(key){return store.get(key);},async update(key,value){store.set(key,value);}}};
let browser,page,controller,receive;
const consoleErrors=[];
async function mount(){
  page=await browser.newPage({viewport:{width:1440,height:1120},deviceScaleFactor:1,timezoneId:'Asia/Jerusalem'});
  page.on('pageerror',error=>consoleErrors.push(error.message));
  installed.vscode.window.createWebviewPanel=()=>({visible:true,webview:{html:'',onDidReceiveMessage(handler){receive=handler;return {dispose(){}};},async postMessage(data){if(!page.isClosed())await page.evaluate(data=>window.dispatchEvent(new MessageEvent('message',{data})),data);return true;}},onDidDispose(){return {dispose(){}};},reveal(){},dispose(){}});
  controller=new ClassificationPanel(context,rpc);
  await controller.open();
  await page.exposeFunction('__hostMessage',message=>receive(message));
  await page.addInitScript(()=>{window.acquireVsCodeApi=()=>({postMessage:message=>window.__hostMessage(message)});});
  // setContent does not navigate, so install the bridge before executing webview JS.
  await page.evaluate(()=>{window.acquireVsCodeApi=()=>({postMessage:message=>window.__hostMessage(message)});});
  await page.setContent(controller.panel.webview.html, {waitUntil:'load'});
  await page.waitForSelector('.prompt-row');
}
async function fieldType(value){await page.locator(`input[name="prompt-type"][value="${value}"]`).check();}
async function backendGet(){const r=await request('classification.get',{session_id:fixture.session_id,prompt_id:fixture.prompts[2]});assert(r.ok);return r.data;}
async function saved(){await page.waitForFunction(()=>document.getElementById('feedback').textContent.includes('הסיווג נשמר'));}
async function main(){
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{}),args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu']});
  await mount();
  await page.locator(`[data-prompt-id="${fixture.prompts[2]}"]`).click();
  await page.waitForFunction(()=>!document.getElementById('form').hidden);
  assert.strictEqual(await page.locator('input[name="prompt-type"]:checked').count(),0,'model suggestion must not prefill human fields');
  await fieldType('corrective');
  await page.locator('input[name="reason"][value="unclear_explanation"]').check();
  await page.locator('input[name="reason"][value="narrative_order"]').check();
  await page.waitForFunction(()=>document.getElementById('draft-status').textContent.includes('נשמרה מקומית'));
  const screenshots=path.join(repo,'docs','screenshots');fs.mkdirSync(screenshots,{recursive:true});
  await page.screenshot({path:path.join(screenshots,'classification-editor.png'),fullPage:true});
  // Reload the real frontend/controller with the same durable workspace draft.
  controller.dispose();await page.close();await mount();
  await page.waitForSelector('input[name="prompt-type"][value="corrective"]:checked');
  assert.strictEqual(await page.locator('input[name="reason"]:checked').count(),2);
  await page.locator('#save').click();await saved();
  let state=await backendGet();assert.strictEqual(state.current.payload.prompt_type,'corrective');
  assert.strictEqual(state.suggestion.actor,'model');
  // Correct the human decision and inspect all prior revisions.
  await page.locator('input[name="reason"][value="visual_animation"]').check();
  await page.locator('#save').click();await page.waitForFunction(()=>document.getElementById('draft-status').textContent.includes('הסיווג האנושי נשמר'));
  await page.locator('#history-button').click();await page.waitForSelector('#history:not([hidden])');
  assert.strictEqual(await page.locator('.history-item').count(),3);
  await page.screenshot({path:path.join(screenshots,'classification-history.png'),fullPage:true});
  await page.locator('#close-history').click();
  // A second writer updates the head; the first writer's dirty draft must survive.
  await fieldType('continuation');
  state=await backendGet();
  const second=await request('classification.save',{project_id:fixture.project_id,session_id:fixture.session_id,prompt_id:fixture.prompts[2],
    expected_human_head:state.human_head_event_id,request_id:'second-window',prompt_type:'irrelevant',reasons:null});assert(second.ok);
  await page.locator('#save').click();await page.waitForSelector('#conflict:not([hidden])');
  assert(await page.locator('input[value="continuation"]').isChecked());
  await page.screenshot({path:path.join(screenshots,'classification-conflict.png'),fullPage:true});
  await page.locator('#resolve-conflict').click();
  // Lost success reply: retry must reuse the receipt, not append a duplicate.
  dropNextSaveReply=true;
  await page.locator('#save').click();await page.waitForSelector('#retry-row:not([hidden])');
  const committed=(await request('classification.history',{session_id:fixture.session_id,prompt_id:fixture.prompts[2]})).data.history.length;
  await page.locator('#retry').click();await saved();
  const replayed=(await request('classification.history',{session_id:fixture.session_id,prompt_id:fixture.prompts[2]})).data.history.length;
  assert.strictEqual(replayed,committed);
  assert.strictEqual((await backendGet()).current.payload.prompt_type,'continuation');
  await page.locator('#clear').click();await page.waitForFunction(()=>document.getElementById('review-badge').textContent==='טרם סווג');
  assert.strictEqual((await backendGet()).current,null);
  await page.locator('#skip').click();await page.waitForFunction(()=>document.getElementById('feedback').textContent.includes('לחזרה מאוחר'));
  assert.strictEqual((await backendGet()).review_status,'deferred');
  assert.strictEqual((await backendGet()).current,null);
  await page.locator('[data-filter="deferred"]').click();await page.waitForSelector(`[data-prompt-id="${fixture.prompts[2]}"]`);
  await page.locator(`[data-prompt-id="${fixture.prompts[2]}"]`).click();
  await page.waitForFunction(()=>document.getElementById('review-badge').textContent==='דולג בינתיים');
  await fieldType('irrelevant');await page.locator('#no-reasons').click();await page.locator('#save').click();await saved();
  state=await backendGet();assert.strictEqual(state.current.payload.prompt_type,'irrelevant');assert.deepStrictEqual(state.current.payload.reasons,[]);
  // A delayed annotation response must not occupy the authoring RPC process.
  await fieldType('initial');holdNextSave=true;await page.locator('#save').click();
  for(let i=0;i<100&&!releaseHeld;i++)await new Promise(resolve=>setTimeout(resolve,10));
  assert(releaseHeld,'save did not reach held-response checkpoint');
  const creation=spawnSync(python,['-X','utf8','-m','manim_studio.cli','authoring','rpc','--repo-root',root],{
    env,encoding:'utf8',timeout:5000,input:JSON.stringify({id:1,method:'start_session',params:{title:'Independent authoring',deck_id:'independent',_research:{}}})+'\n'});
  assert.strictEqual(creation.status,0,creation.stderr);assert.strictEqual(JSON.parse(creation.stdout).ok,true,creation.stdout);
  releaseHeld();await saved();
  assert.deepStrictEqual(consoleErrors,[]);
  console.log(JSON.stringify({passed:true,checks:['no model auto-approval','draft restoration','save','correction/history','conflict preserves draft','lost-reply idempotent retry','clear retains history','skip is not irrelevant','explicit empty reasons','authoring while annotation reply is delayed'],screenshots:['classification-editor.png','classification-history.png','classification-conflict.png']},null,2));
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;}).finally(async()=>{controller?.dispose();await browser?.close();child.kill();installed.restore();fs.rmSync(root,{recursive:true,force:true});});
