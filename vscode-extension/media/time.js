const api=acquireVsCodeApi();const $=id=>document.getElementById(id);
const categories={authoring:'עבודה על התוכן',classification:'סיווג פרומפטים',waiting:'המתנה מדווחת'};
const states={active:'פעיל',paused:'הושהה',stopped:'הסתיים',interrupted:'נקטע — זנב הזמן לא ידוע'};
const warnings={unconfirmed_timer_tail:'מקטע נקטע: הזמן מאז האישור האחרון אינו ידוע',clock_anomaly:'זוהה שינוי בשעון; חלק מהזמנים אינם כשירים להשוואה',report_without_range:'דיווח ללא טווח אינו מאפשר בדיקת חפיפה מלאה',overlapping_reports:'יש דיווחים ידניים חופפים',report_overlaps_timer:'דיווח ידני חופף לטיימר; הזמנים אינם מחוברים אוטומטית',overlapping_tracked_intervals:'מקטעים מתוזמנים חופפים: אין סכום קנוני',duplicate_action_completion:'זוהה סיום כפול של פעולה'};
let state,editor={report_id:null,expected_revision:null},dirty=false,draftTimer;
function node(tag,text){const el=document.createElement(tag);el.textContent=text;return el;}
function format(value){return value==null?'לא ידוע':`${Number(value).toFixed(1)} שניות`;}
function local(iso){if(!iso)return '';const d=new Date(iso);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}
function fields(){return {...editor,category:$('report-category').value,duration:$('duration').value,unit:$('unit').value,start:$('start').value,end:$('end').value,measurement_ref:$('measurement').value,replaces_interval_id:$('replacement').value};}
function draft(){if(!state)return;clearTimeout(draftTimer);api.postMessage({action:'draft',session_id:state.session_id,fields:fields()});}
function reset(values={}){editor={report_id:values.report_id||null,expected_revision:values.expected_revision??values.revision??null};$('duration').value=values.duration??(values.seconds!=null?values.seconds:'');$('unit').value=values.unit||(values.seconds!=null?'1':'60');$('report-category').value=values.category||'authoring';$('start').value=values.start??local(values.start_utc);$('end').value=values.end??local(values.end_utc);$('measurement').value=values.measurement_ref||'';$('replacement').value=values.replaces_interval_id||'';dirty=Object.keys(values).length>0;}
function options(id,rows,label){const selected=$(id).value;$(id).replaceChildren(node('option','ללא קישור'));$(id).firstChild.value='';for(const row of rows){const option=node('option',label(row));option.value=row.id;$(id).append(option);}$(id).value=selected;}
$('report-form').addEventListener('input',()=>{dirty=true;clearTimeout(draftTimer);draftTimer=setTimeout(draft,180);});
$('report-form').onsubmit=event=>{event.preventDefault();draft();const f=fields();api.postMessage({action:f.report_id?'correct':'report',session_id:state.session_id,report_id:f.report_id,expected_revision:f.expected_revision,category:f.category,seconds:Number(f.duration)*Number(f.unit),start_utc:f.start?new Date(f.start).toISOString():null,end_utc:f.end?new Date(f.end).toISOString():null,measurement_ref:f.measurement_ref||null,replaces_interval_id:f.replaces_interval_id||null});};
document.querySelectorAll('[data-action]').forEach(button=>button.onclick=()=>{const action=button.dataset.action;if(action==='choose')draft();if(action==='new_report'){reset();dirty=false;draft();return;}api.postMessage({action,category:$('category').value});});
window.addEventListener('message',({data})=>{
 if(data.type==='error'||data.type==='notice'){$('feedback').textContent=data.message;return;}
 if(data.type==='draftSaved'){$('draft-status').textContent='הטיוטה נשמרה מקומית';return;}
 if(data.type==='saved'){if(JSON.stringify(fields())!==JSON.stringify(data.draft))return;reset();dirty=false;$('draft-status').textContent='הדיווח נשמר';return;}
 if(data.type==='history'){const list=$('history');list.replaceChildren();for(const e of data.events)list.append(node('p',`${e.timestamp} · ${e.type}`));return;}
 if(data.type!=='state')return;
 const changed=state?.session_id!==data.session_id;state=data;
 $('feedback').textContent=data.title;
 const active=data.active;
 $('active').textContent=active?`${active.title} · ${categories[active.category]} · ${format(active.measured_seconds)} אושרו${active.owned?'':' · מנוהל בחלון או תהליך אחר'}`:'אין טיימר פעיל. פתיחה מחדש אינה ממשיכה מקטע קודם.';
 for(const action of ['pause','stop'])document.querySelector(`[data-action="${action}"]`).disabled=!active||active.session_id!==data.session_id;
 document.querySelector('[data-action="start"]').disabled=!!active||!data.can_capture;
 document.querySelector('[data-action="transfer"]').disabled=!active||!data.can_capture;
 const summary=$('summary');summary.replaceChildren();
 for(const category of ['authoring','classification'])summary.append(node('div',`${categories[category]} — טיימר: ${format(data.summary.tracked_seconds[category])} · כשיר להשוואה: ${format(data.summary.canonical_tracked_seconds[category])} · דיווחים: ${format(data.summary.self_reported_seconds[category])}`));
 summary.append(node('p',`דיווחי סיווג קודמים: ${format(data.summary.legacy_classification_self_report_seconds)} · המתנה מדווחת: ${format(data.summary.self_reported_seconds.waiting)}`));
 for(const [family,label] of [['model_turn','זמן turn שנצפה'],['tool','פעולות מערכת'],['render','רינדור']]){const row=data.summary.system[family];summary.append(node('p',`${label}: ${format(row.union_seconds)} (איחוד טווחים ידועים) · ${row.incomplete} תצפיות חסרות או לא תקינות`));}
 if(data.summary.human_time_missing)summary.append(node('p','לא תועד זמן אנושי למחקר זה.'));
 $('warnings').replaceChildren(...data.summary.warnings.map(w=>node('p',warnings[w]||w)));
 const intervals=$('intervals');intervals.replaceChildren();
 for(const interval of data.intervals){const row=node('article',`${categories[interval.category]} · ${states[interval.status]} · ${format(interval.measured_seconds)} · ${interval.start_utc}`);if(interval.status!=='active'){const edit=node('button','דווח תיקון למקטע');edit.onclick=()=>{reset({category:interval.category,seconds:interval.measured_seconds,start_utc:interval.start_utc,end_utc:interval.confirmed_end_utc,replaces_interval_id:interval.interval_id});draft();$('report-form').scrollIntoView();};row.append(edit);}intervals.append(row);}
 options('replacement',data.intervals.filter(i=>i.status!=='active').map(i=>({...i,id:i.interval_id})),i=>`${categories[i.category]} · ${format(i.measured_seconds)} · ${i.start_utc}`);
 options('measurement',data.summary.classification_measurements.map(i=>({...i,id:i.measurement_ref})),i=>`סיווג · ${format(i.seconds)}`);
 const reports=$('reports');reports.replaceChildren();
 for(const report of data.reports){const row=node('article',`${categories[report.category]} · דיווח עצמי · ${format(report.seconds)} · ${report.voided?'בוטל':'תקף'} · גרסה ${report.revision}`);const edit=node('button','ערוך דיווח');edit.onclick=()=>{reset(report);draft();$('report-form').scrollIntoView();};const remove=node('button','בטל דיווח');remove.disabled=report.voided;remove.onclick=()=>api.postMessage({action:'void',report_id:report.report_id,expected_revision:report.revision});row.append(edit,remove);reports.append(row);}
 if(changed){reset(data.draft||{});if(data.draft)$('draft-status').textContent='הטיוטה שוחזרה';}
 const contexts=$('contexts');contexts.replaceChildren();for(const c of data.contexts||[]){
  const runtime=c.runtime,git=runtime?.git;
  const row=node('article',`${new Date(c.observed_at).toLocaleString('he-IL')} · מודל: ${c.model?.model||'לא ידוע'} · גרסה: ${c.model?.version||'לא ידועה'} · לקוח: ${c.extension_version||c.model?.client_version||'לא ידוע'}`);
  row.append(node('p',`סביבת הרצה: Studio ${runtime?.studio_version||'לא ידוע'} · Python ${runtime?.python_version||'לא ידוע'} · ${runtime?.os?.system||'מערכת הפעלה לא ידועה'} ${runtime?.os?.release||''}`));
  row.append(node('code',`Git: ${git?.commit||'לא זמין'} · ${git?.dirty===true?'יש שינויים מקומיים':git?.dirty===false?'ללא שינויים מקומיים':'מצב שינויים לא ידוע'}`));
  row.append(node('p',`מקור מידע: ${c.provenance?.runtime==='observed'?'סביבה שנבדקה':c.provenance?.runtime==='previously_observed'?'בדיקת סביבה קודמת':'סביבה חסרה'} · ${c.provenance?.model==='client_reported'?'פרטי מודל שדווחו בידי הלקוח':'פרטי מודל חסרים'}`));
  const settings=Object.entries(c.settings||{}).filter(([,v])=>v!=null);if(settings.length)row.append(node('p',`הגדרות שנמסרו: ${settings.map(([k,v])=>`${k}: ${v}`).join(' · ')}`));contexts.append(row);
 }
});
api.postMessage({action:'ready'});
