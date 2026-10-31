const api = acquireVsCodeApi();
let current;
const find = id => document.getElementById(id);
function node(tag, text) { const el = document.createElement(tag); el.textContent = text; return el; }
function button(label, action, artifact) { const el = node('button', label); el.onclick = () => api.postMessage({action, artifact_id: artifact.artifact_id}); return el; }
const status = {retained:'נשמר ואומת',pending:'ממתין לשימור',unavailable:'לא נשמר',purged:'התוכן הוסר',completed:'בוצעה',failed:'נכשלה',outcome_unknown:'התוצאה לא אומתה'};
const origin = {human:'משתמש — מקור מדווח',automation:'אוטומציה — מקור מדווח',unknown:'מקור לא ידוע'};
const roles={source:'קובץ מקור',planning_document:'מסמך תהליך',candidate_source:'גרסה מועמדת',baseline_source:'גרסת בסיס',preview_video:'וידאו תצוגה',build_manifest:'פרטי בנייה',render_log:'לוג רינדור',final_product:'תוצר סופי',render_image:'תמונת רינדור',render_caption:'כתוביות'};
const reasons={source_missing:'קובץ המקור אינו זמין',source_changed:'המקור השתנה לפני השימור',omitted_quota:'חריגה ממכסת השימור',too_large:'קובץ גדול מהמגבלה',queue_full:'תור השימור מלא',unsafe_path:'נתיב שאינו מאושר',read_error:'שגיאה בקריאת הקובץ'};
const kind = {accept:'קבלה',reject:'דחייה',request_revision:'בקשת תיקון'};
window.addEventListener('message', ({data}) => {
  if (data.type === 'error' || data.type === 'notice') { find('feedback').textContent = data.message; return; }
  if (data.type === 'content') { find('detail').hidden=false; find('content').textContent=data.text; return; }
  if (data.type !== 'state') return;
  current=data;
  find('feedback').textContent = data.sessionTitle || data.session_id;
  find('coverage').textContent = `${data.total} תוצרים · ${data.coverage === 'partial' ? 'יש חוסרים בתיעוד' : 'שלמות הכיסוי אינה מאומתת'}`;
  const list=find('artifacts'); list.replaceChildren();
  for(const artifact of data.artifacts) {
    const row=node('article',''); row.dataset.artifact=artifact.artifact_id;
    const name=node('strong',artifact.path);name.dir='ltr';name.style.display='block';name.style.textAlign='left';
    row.append(name,node('p',`${roles[artifact.role] || artifact.role} · ${status[artifact.status] || artifact.status}${artifact.reason ? ' · '+(reasons[artifact.reason] || artifact.reason) : ''}`));
    if(artifact.sha256) row.append(node('code',artifact.sha256));
    row.append(button('פרטים והיסטוריה','detail',artifact));
    if(artifact.status==='retained') row.append(button('פתח עותק שמור','open',artifact),button('הסר תוכן שמור','purge',artifact));
    list.append(row);
  }
  if(!data.artifacts.length) list.append(node('p','אין תוצרים שנאספו בעמוד זה. נקודת תצפית אוספת את הקבצים שבהיקף כאשר האיסוף פעיל.'));
  const decisions=find('decisions');decisions.replaceChildren();
  for(const decision of data.decisions) {
    const row=node('article','');row.append(node('strong',`${kind[decision.kind] || decision.kind} · ${status[decision.status] || decision.status}`));
    row.append(node('p',`${origin[decision.origin] || origin.unknown} · ${decision.proposal_id}`));
    const candidate=decision.candidate?.candidate_source;
    if(candidate) row.append(node('code',`SHA-256: ${candidate.sha256 || 'unavailable'}`),button('פתח גרסה מועמדת','open',candidate));
    const baseline=decision.candidate?.baseline_source;
    if(baseline?.status==='retained') row.append(button('השווה לגרסת הבסיס','compare', {artifact_id:candidate?.artifact_id,baseline_id:baseline.artifact_id}));
    // Compare is resolved by host from the decision, not from client-supplied file paths.
    row.querySelectorAll('button').forEach(el=>{ if(el.textContent==='השווה לגרסת הבסיס') el.onclick=()=>api.postMessage({action:'compare',decision_id:decision.decision_id}); });
    decisions.append(row);
  }
  if(!data.decisions.length) decisions.append(node('p','עדיין לא תועדו החלטות במחקר הזה.'));
  const snapshots=find('snapshots');snapshots.replaceChildren();
  for(const snapshot of data.snapshots) {
    const row=node('article','');row.append(node('strong',snapshot.reason),node('p',`${Object.keys(snapshot.files).length} קבצים נשמרו · ${snapshot.omitted.length} חוסרים · ${snapshot.missing.length} קבצים אינם נוכחים מאז התצפית הקודמת`));
    if(snapshot.omitted.length || snapshot.missing.length) row.append(node('pre',JSON.stringify({omitted:snapshot.omitted,missing:snapshot.missing},null,2)));
    row.append(node('small',snapshot.boundary_caveat));snapshots.append(row);
  }
  document.querySelector('[data-action="next"]').disabled=data.next_offset==null;
  document.querySelector('[data-action="previous"]').disabled=!data.offset;
});
document.querySelectorAll('[data-action]').forEach(el=>el.onclick=()=>api.postMessage({action:el.dataset.action}));
api.postMessage({action:'ready'});
