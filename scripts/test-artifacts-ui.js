/* Exact extension webview/controller + real Python RPC, hosted in Chromium.
 * VS Code hosting APIs are simulated; this is not native Windows IDE acceptance.
 * Requires playwright and CHROMIUM_EXECUTABLE; only synthetic data is used.
 */
const assert=require('assert'),fs=require('fs'),os=require('os'),path=require('path');
const {spawn,spawnSync}=require('child_process');const readline=require('readline');
const {chromium}=require('playwright');
const {installFakeVscode}=require('../vscode-extension/test/fake-vscode');
const repo=path.resolve(__dirname,'..'),root=fs.mkdtempSync(path.join(os.tmpdir(),'artifacts-ui-'));
const env={...process.env,PYTHONPATH:path.join(repo,'src')},python=process.env.PYTHON || 'python';
const seed=spawnSync(python,['-X','utf8',path.join(__dirname,'artifacts-demo.py'),root],{env,encoding:'utf8'});assert.strictEqual(seed.status,0,seed.stderr);const fixture=JSON.parse(seed.stdout);
const child=spawn(python,['-X','utf8','-m','manim_studio.research_cli','--root',root,'rpc'],{env});
let seq=0,stderr='';const pending=new Map();child.stderr.on('data',b=>stderr+=String(b));
readline.createInterface({input:child.stdout}).on('line',line=>{const r=JSON.parse(line),p=pending.get(r.id);if(p){clearTimeout(p.timer);pending.delete(r.id);p.resolve(r);}});
function request(method,params){return new Promise((resolve,reject)=>{const id=++seq,timer=setTimeout(()=>reject(new Error('RPC timeout '+stderr)),15000);pending.set(id,{resolve,timer});child.stdin.write(JSON.stringify({id,method,params})+'\n');});}
let drop=false;
const rpc={async request(method,params){const result=await request(method,params);if(drop && method==='artifacts.checkpoint'){drop=false;throw new Error('Injected lost reply');}return result;},dispose(){}};
const installed=installFakeVscode();const vscode=installed.vscode;
const {ArtifactsPanel}=require('../vscode-extension/out/artifactsPanel');
const store=new Map([['manimStudio.selectedResearchSession',fixture.session_id]]);
const context={subscriptions:[],workspaceState:{get:k=>store.get(k),update:async(k,v)=>store.set(k,v)}};
const opened=[];let browser,page,controller,receive;
async function main(){
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE,args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu']});
 page=await browser.newPage({viewport:{width:1440,height:1100},deviceScaleFactor:1});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 vscode.window.createWebviewPanel=()=>({visible:true,webview:{html:'',onDidReceiveMessage:f=>{receive=f;return{dispose(){}};},postMessage:async data=>{if(!page.isClosed())await page.evaluate(data=>window.dispatchEvent(new MessageEvent('message',{data})),data);return true;}},reveal(){},onDidDispose(){return{dispose(){}};},dispose(){}});
 vscode.workspace.openTextDocument=async options=>{opened.push(options.content);return{uri:{fsPath:'synthetic-read-only-document'}};};
 vscode.window.showTextDocument=async()=>{};vscode.window.showWarningMessage=async()=> 'הסר תוכן';
 const executed=[];vscode.commands.executeCommand=async(...args)=>executed.push(args);
 controller=new ArtifactsPanel(context,rpc);await controller.open();await page.exposeFunction('__host',m=>receive(m));
 await page.evaluate(()=>{window.acquireVsCodeApi=()=>({postMessage:m=>window.__host(m)});});await page.setContent(controller.panel.webview.html);await page.waitForSelector('#decisions article');
 assert((await page.locator('#decisions').textContent()).includes('דחייה'));assert((await page.locator('#decisions').textContent()).includes('קבלה'));
 assert((await page.locator('#coverage').textContent()).includes('חוסרים'));assert((await page.locator('#artifacts').textContent()).includes('לא נשמר'));
 await page.screenshot({path:path.join(repo,'docs/screenshots/research-artifacts.png'),fullPage:false});
 const compare=page.getByRole('button',{name:'השווה לגרסת הבסיס'}).first();await compare.click();await page.waitForTimeout(100);assert(executed.some(c=>c[0]==='vscode.diff'));
 const initial=await request('artifacts.list',{session_id:fixture.session_id});const snapshotCount=initial.data.snapshots.length;
 drop=true;await page.locator('[data-action="checkpoint"]').click();await page.waitForFunction(()=>document.getElementById('feedback').textContent.includes('lost reply'));
 assert(store.get('manimStudio.artifacts.v1').pending);await page.locator('[data-action="retry"]').click();await page.waitForFunction(()=>!document.getElementById('feedback').textContent.includes('lost reply'));
 const after=await request('artifacts.list',{session_id:fixture.session_id});assert.strictEqual(after.data.snapshots.length,snapshotCount+1);
 const artifact=after.data.artifacts.find(a=>a.path==='lesson-plan.md' && a.status==='retained');
 await page.locator(`[data-artifact="${artifact.artifact_id}"]`).getByRole('button',{name:'פתח עותק שמור'}).click();await page.waitForTimeout(150);assert(opened.some(s=>s.includes('וקטורים')));
 await page.locator(`[data-artifact="${artifact.artifact_id}"]`).getByRole('button',{name:'הסר תוכן שמור'}).click();await page.waitForFunction(id=>document.querySelector(`[data-artifact="${id}"]`).textContent.includes('התוכן הוסר'),artifact.artifact_id);
 assert.strictEqual((await request('artifacts.get',{session_id:fixture.session_id,artifact_id:artifact.artifact_id})).data.artifact.status,'purged');
 assert.deepStrictEqual(errors,[]);
 console.log(JSON.stringify({passed:true,checks:['decision origins and outcomes','missing coverage visible','snapshot and artifact list','exact baseline/candidate comparison','lost-reply idempotent retry','open archived source','purge retains history','no webview JavaScript errors'],screenshot:'research-artifacts.png'},null,2));
}
main().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{controller?.dispose();if(browser)await browser.close();child.kill();installed.restore();fs.rmSync(root,{recursive:true,force:true});});
