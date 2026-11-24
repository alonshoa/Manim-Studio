(()=>{
const api=acquireVsCodeApi(),$=id=>document.getElementById(id);let session;
const send=(action,extra={})=>api.postMessage({action,session_id:session,...extra});
$('choose').onclick=()=>send('choose');$('refresh').onclick=()=>send('refresh');$('retry').onclick=()=>send('retry');
$('quick').onclick=()=>send('check',{deep:false});$('deep').onclick=()=>send('check',{deep:true});$('recover').onclick=()=>send('recover');
$('metadata').onclick=()=>send('export',{mode:'metadata'});$('full').onclick=()=>send('export',{mode:'full'});
const status={pending:'ממתין',running:'בתהליך',completed:'הושלם',cancelled:'בוטל',failed:'נכשל',valid:'תקין',partial:'חלקי',unverified:'לא אומת',invalid:'לא תקין'};
const domain={conversation:'קליטת שיחה',links:'קישורים',decisions:'החלטות',content:'תוכן',timing:'זמן ומטא־דאטה',storage:'אחסון'};
const codes={report_without_range:'דיווח זמן ללא טווח שעות — אי אפשר לבדוק חפיפה',human_time_missing:'לא נשמרו מדידות או דיווחים של זמן אנושי',model_metadata_unknown:'פרטי המודל אינם ידועים',run_context_missing:'הפניה להקשר הרצה חסר',overlapping_reports:'יש חפיפה בין דיווחי זמן',report_overlaps_timer:'דיווח זמן חופף לטיימר',clock_anomaly:'זוהה שינוי חריג בשעון',unconfirmed_timer_tail:'קיים זמן שלא אושר אחרי נקודת המדידה האחרונה',artifact_job_pending_or_interrupted:'עבודת שימור ממתינה או נקטעה',event_reference_invalid:'קישור לאירוע חסר או שגוי',projection_reference_invalid:'קישור לתמונת מצב או תוצר חסר',decision_candidate_changed:'גרסת המועמד בהחלטה אינה תואמת לראיות',source_delivery_unverified:'מסירת כל ההודעות מהלקוח לא אומתה',no_prompts:'לא נשמרו פרומפטים במחקר',capture_gap:'פער ידוע בקליטת השיחה',content_bytes_unverified:'תוכן הקבצים לא נבדק ברמת הבתים בבדיקה המהירה',content_missing_or_corrupt:'תוכן חסר או אינו תואם לחתימה',content_reference_missing:'הפניה לתוכן שלא נשמר',action_pending_or_interrupted:'פעולה פתוחה או תיעוד שנקטע — התוצאה אינה ידועה',action_outcome_unknown:'תוצאת פעולה אינה ידועה',decision_outcome_unknown:'תוצאת החלטה אינה ידועה',decision_origin_unknown:'מקור ההחלטה אינו ידוע',timer_unconfirmed_tail:'הזמן שמאז נקודת האישור האחרונה אינו ידוע',timer_active_at_snapshot:'הטיימר היה פעיל בגבול הבדיקה',snapshot_omitted:'חלק מהקבצים הושמטו מתמונת המצב',run_context_unknown:'הקשר הרצה אינו זמין',artifact_purged:'תוצר נמחק במפורש',artifact_pending:'תוצר ממתין לשימור',artifact_unavailable:'תוצר לא זמין בארכיון'};
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function jobs(target,items,namespace){target.replaceChildren();if(!items?.length){target.append(el('p','אין עדיין תוצאות.','muted'));return;}for(const j of items){
 const card=el('article',undefined,'job');card.append(el('strong',`${status[j.status]||j.status} · ${j.mode==='full'?'תוכן מלא':j.mode==='metadata'?'מטא־דאטה':j.report?.deep?'בדיקה מלאה':'בדיקת תקינות'}`));
 card.append(el('p',`גבול אירועים ${j.snapshot_seq} · ${j.progress}%${j.stale?' · הדוח ישן: נוספו אירועים במחקר':''}`,'muted'));
 if(j.error)card.append(el('p',`הפעולה לא הושלמה: ${j.error}`,'error'));
 if(j.destination)card.append(el('pre',j.destination));if(j.archive_sha256&&j.status==='completed')card.append(el('pre',`SHA-256: ${j.archive_sha256}`));
 if(j.report){const domains=el('div',undefined,'domains');for(const [key,value]of Object.entries(j.report.domains))domains.append(el('span',`${domain[key]||key}: ${status[value]||value}`,`badge ${value}`));card.append(domains);
 const list=el('ul');for(const f of j.report.findings){const li=el('li',codes[f.code]||f.code,f.severity==='error'?'error':'');if(f.entity_id)li.append(el('code',` · ${f.entity_id}`));list.append(li);}card.append(list);}
 if(['pending','running'].includes(j.status)){const cancel=el('button','ביטול');cancel.onclick=()=>send('cancel',{namespace,job_id:j.job_id});card.append(cancel);}target.append(card);
}}
window.addEventListener('message',({data})=>{if(data.type==='state'){session=data.session_id;$('session').textContent=session;$('retry').disabled=!data.pending;jobs($('checks'),data.checks,'integrity');jobs($('exports'),data.exports,'exports');}else if(['error','notice'].includes(data.type)){$('message').textContent=data.message;if(data.type==='error')$('retry').disabled=!data.pending;$('message').className=data.type==='error'?'error':'';}});
send('ready');
})();
