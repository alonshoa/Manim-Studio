/* Real time webview/controller + persistent Python RPC in Chromium.
 * VS Code host APIs are simulated; native Windows IDE acceptance is separate.
 */
const assert=require('assert'),fs=require('fs'),os=require('os'),path=require('path');
const {spawn,spawnSync}=require('child_process'),readline=require('readline');
const {chromium}=require('playwright');
const {installFakeVscode}=require('../vscode-extension/test/fake-vscode');
const repo=path.resolve(__dirname,'..'),root=fs.mkdtempSync(path.join(os.tmpdir(),'time-ui-'));
const env={...process.env,PYTHONPATH:path.join(repo,'src')},python=process.env.PYTHON||'python';
const seed=spawnSync(python,['-X','utf8',path.join(__dirname,'time-demo.py'),root],{env,encoding:'utf8'});
assert.strictEqual(seed.status,0,seed.stderr);const fixture=JSON.parse(seed.stdout);
const child=spawn(python,['-X','utf8','-m','manim_studio.research_cli','--root',root,'rpc'],{env});
let seq=0,stderr='',drop=false;const pending=new Map();child.stderr.on('data',b=>stderr+=b);
readline.createInterface({input:child.stdout}).on('line',line=>{const r=JSON.parse(line),p=pending.get(r.id);if(p){clearTimeout(p.timer);pending.delete(r.id);p.resolve(r);}});
function request(method,params){return new Promise((resolve,reject)=>{const id=++seq,timer=setTimeout(()=>reject(new Error('RPC timeout '+stderr)),15000);pending.set(id,{resolve,timer});child.stdin.write(JSON.stringify({id,method,params})+'\n');});}
const rpc={async request(method,params){const result=await request(method,params);if(drop&&method==='timing.report'){drop=false;throw new Error('Injected lost reply');}return result;},dispose(){}};
const installed=installFakeVscode(),vscode=installed.vscode;
const {TimePanel}=require('../vscode-extension/out/timePanel');
const store=new Map([['manimStudio.selectedResearchSession',fixture.session_id]]);
const context={subscriptions:[],extension:{packageJSON:{version:'0.1.0'}},workspaceState:{get:k=>store.get(k),update:async(k,v)=>store.set(k,v)}};
let browser,page,controller,receive;const errors=[];
async function mount(){
 controller=new TimePanel(context,rpc);await controller.open();await page.goto('about:blank');
 await page.setContent(controller.panel.webview.html);
 await page.waitForFunction(()=>document.getElementById('feedback').textContent.includes('וקטורים'));
}
async function main(){
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE,args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu']});
 page=await browser.newPage({viewport:{width:1440,height:1150},deviceScaleFactor:1});page.on('pageerror',e=>errors.push(e.message));
 vscode.window.createWebviewPanel=()=>({webview:{html:'',onDidReceiveMessage:f=>{receive=f;return{dispose(){}};},postMessage:async data=>{if(!page.isClosed())await page.evaluate(data=>window.dispatchEvent(new MessageEvent('message',{data})),data);return true;}},reveal(){},onDidDispose(){return{dispose(){}};},dispose(){}});
 vscode.window.showWarningMessage=async()=> 'בטל דיווח';
 vscode.window.showQuickPick=async items=>items.find(i=>i.id===fixture.other_session_id);
 await page.exposeFunction('__host',m=>receive(m));
 await page.addInitScript(()=>{window.acquireVsCodeApi=()=>({postMessage:m=>window.__host(m)});});
 await mount();assert((await page.locator('#summary').textContent()).includes('120.0'));
 assert((await page.locator('#contexts').textContent()).includes('synthetic-demo'));
 await page.screenshot({path:path.join(repo,'docs/screenshots/research-time.png'),fullPage:true});
 await page.locator('#duration').fill('42');await page.waitForFunction(()=>document.getElementById('draft-status').textContent.includes('נשמרה'));
 controller.dispose();await mount();assert.strictEqual(await page.locator('#duration').inputValue(),'42');
 await page.locator('#unit').selectOption('1');drop=true;
 await page.getByRole('button',{name:'שמור דיווח',exact:true}).click();
 await page.waitForFunction(()=>document.getElementById('feedback').textContent.includes('lost reply'));
 assert(store.get('manimStudio.time.v1').pending);
 await page.locator('[data-action="retry"]').click();await page.waitForFunction(()=>document.getElementById('reports').textContent.includes('42.0'));
 let status=await request('timing.status',{session_id:fixture.session_id});
 assert.strictEqual(status.data.reports.length,2);assert.strictEqual(status.data.summary.self_reported_seconds.authoring,42);
 await page.locator('#reports article').filter({hasText:'42.0'}).getByRole('button',{name:'ערוך דיווח'}).click();await page.locator('#duration').fill('31');
 await page.getByRole('button',{name:'שמור דיווח',exact:true}).click();await page.waitForFunction(()=>document.getElementById('reports').textContent.includes('31.0'));
 await page.locator('#reports article').filter({hasText:'31.0'}).getByRole('button',{name:'בטל דיווח'}).click();
 await page.waitForFunction(()=>[...document.querySelectorAll('#reports article')].some(e=>e.textContent.includes('31.0')&&e.textContent.includes('בוטל')));
 await page.locator('[data-action="start"]').click();await page.waitForFunction(()=>!document.querySelector('[data-action="pause"]').disabled);
 await controller.heartbeat();await page.locator('[data-action="pause"]').click();await page.waitForFunction(()=>!document.querySelector('[data-action="start"]').disabled);
 await page.locator('#category').selectOption('classification');await page.locator('[data-action="start"]').click();
 await page.waitForFunction(()=>document.getElementById('active').textContent.includes('סיווג'));
 await page.locator('[data-action="choose"]').click();await page.waitForFunction(()=>document.getElementById('feedback').textContent.includes('מדדי מרכז'));
 assert((await page.locator('#active').textContent()).includes('וקטורים'));
 await page.locator('[data-action="transfer"]').click();await page.waitForFunction(()=>document.getElementById('active').textContent.includes('מדדי מרכז'));
 await page.locator('[data-action="stop"]').click();await page.waitForFunction(()=>document.getElementById('active').textContent.includes('אין טיימר'));
 status=await request('timing.status',{session_id:fixture.session_id});assert.strictEqual(status.data.reports.filter(r=>!r.voided).length,1);
 const history=await request('timing.history',{session_id:fixture.session_id});
 assert(history.data.events.some(e=>e.type==='time.corrected'));assert(history.data.events.some(e=>e.type==='time.voided'));assert.deepStrictEqual(errors,[]);
 console.log(JSON.stringify({passed:true,checks:['separate timer/report summaries','run context','draft restored after controller restart','lost reply exact retry without duplicate','edit and void preserve history','start heartbeat pause stop','pinned research selection','explicit cross-research transfer','no webview JS errors'],screenshot:'research-time.png'},null,2));
}
main().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{controller?.dispose();if(browser)await browser.close();child.kill();installed.restore();fs.rmSync(root,{recursive:true,force:true});});
