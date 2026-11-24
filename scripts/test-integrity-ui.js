/* Actual integrity webview/controller + Python worker, with a simulated VS Code host. */
const assert=require('assert'),fs=require('fs'),os=require('os'),path=require('path');
const {spawn,spawnSync}=require('child_process'),readline=require('readline');
const {chromium}=require('playwright');
const {installFakeVscode}=require('../vscode-extension/test/fake-vscode');
const repo=path.resolve(__dirname,'..'),base=fs.mkdtempSync(path.join(os.tmpdir(),'integrity-ui-')),root=path.join(base,'project');
const env={...process.env,PYTHONPATH:path.join(repo,'src')},python=process.env.PYTHON||'python';
const seed=spawnSync(python,['-X','utf8',path.join(__dirname,'integrity-demo.py'),root],{env,encoding:'utf8'});
assert.strictEqual(seed.status,0,seed.stderr);const fixture=JSON.parse(seed.stdout);
const child=spawn(python,['-X','utf8','-m','manim_studio.research_cli','--root',root,'rpc'],{env});
let seq=0,stderr='',drop=false;const pending=new Map();child.stderr.on('data',b=>stderr+=b);
readline.createInterface({input:child.stdout}).on('line',line=>{const r=JSON.parse(line),p=pending.get(r.id);if(p){clearTimeout(p.timer);pending.delete(r.id);p.resolve(r);}});
function request(method,params){return new Promise((resolve,reject)=>{const id=++seq,timer=setTimeout(()=>reject(new Error('RPC timeout '+stderr)),15000);pending.set(id,{resolve,timer});child.stdin.write(JSON.stringify({id,method,params})+'\n');});}
const rpc={async request(method,params){const result=await request(method,params);if(drop&&method==='exports.start'){drop=false;throw new Error('Injected lost reply');}return result;},dispose(){}};
const installed=installFakeVscode(),vscode=installed.vscode;
const {IntegrityPanel}=require('../vscode-extension/out/integrityPanel');
const store=new Map([['manimStudio.selectedResearchSession',fixture.session_id]]);
const context={subscriptions:[],workspaceState:{get:k=>store.get(k),update:async(k,v)=>store.set(k,v)}};
let browser,page,controller,receive;const errors=[];
async function mount(){controller=new IntegrityPanel(context,rpc,root);controller.register();await controller.open();await page.goto('about:blank');await page.setContent(controller.panel.webview.html);await page.waitForFunction(()=>document.getElementById('session').textContent.length>0);}
async function main(){
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE,args:['--no-sandbox','--disable-dev-shm-usage']});
 page=await browser.newPage({viewport:{width:1350,height:1050},deviceScaleFactor:1});page.on('pageerror',e=>errors.push(e.message));
 vscode.window.createWebviewPanel=()=>({webview:{html:'',onDidReceiveMessage:f=>{receive=f;return{dispose(){}};},postMessage:async data=>{if(!page.isClosed())await page.evaluate(data=>window.dispatchEvent(new MessageEvent('message',{data})),data);return true;}},reveal(){},onDidDispose(){return{dispose(){}};},dispose(){}});
 vscode.window.showSaveDialog=async()=>({fsPath:path.join(base,'export.zip')});
 vscode.window.showQuickPick=async items=>items.find(i=>i.id===fixture.other_session_id);
 await page.exposeFunction('__host',m=>receive(m));await page.addInitScript(()=>{window.acquireVsCodeApi=()=>({postMessage:m=>window.__host(m)});});
 await mount();
 assert((await page.locator('#checks').textContent()).includes('תוכן חסר'));
 assert((await page.locator('#checks').textContent()).includes('לא אומתה'));
 await page.screenshot({path:path.join(repo,'docs/screenshots/research-integrity.png'),fullPage:true});
 await page.locator('#quick').click();await page.waitForFunction(()=>document.querySelectorAll('#checks .job').length===2);
 await controller.refresh();await page.waitForFunction(()=>document.getElementById('checks').textContent.includes('בבדיקה המהירה'));
 drop=true;await page.locator('#full').click();await page.waitForFunction(()=>document.getElementById('message').textContent.includes('lost reply'));
 assert(await page.locator('#retry').isEnabled());assert(store.get('manimStudio.integrity.v1').pending);
 await page.locator('#retry').click();await page.waitForFunction(()=>document.getElementById('exports').textContent.includes('הושלם'));
 let exports=await request('exports.list',{session_id:fixture.session_id});assert.strictEqual(exports.data.jobs.length,1);
 const verify=spawnSync(python,['-c','from manim_studio.research_export import verify_export; import sys; assert verify_export(sys.argv[1])["valid"]',path.join(base,'export.zip')],{env,encoding:'utf8'});assert.strictEqual(verify.status,0,verify.stderr);
 controller.dispose();await mount();assert.strictEqual(await page.locator('#session').textContent(),fixture.session_id);
 await page.locator('#recover').click();await page.waitForFunction(()=>document.getElementById('message').textContent.includes('התאוששות הסתיימה'));
 await page.locator('#choose').click();await page.waitForFunction(id=>document.getElementById('session').textContent===id,fixture.other_session_id);
 assert((await page.locator('#checks').textContent()).includes('אין עדיין'));
 assert.deepStrictEqual(errors,[]);
 console.log(JSON.stringify({passed:true,checks:['deep findings and honest unverified delivery','quick vs deep report','lost reply exposes enabled retry button','retry produces one export','independent ZIP verification','selection survives reload','safe recovery feedback','other research selection clears prior reports','no webview errors'],screenshot:'research-integrity.png'},null,2));
}
main().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{controller?.dispose();if(browser)await browser.close();child.kill();installed.restore();fs.rmSync(base,{recursive:true,force:true});});
