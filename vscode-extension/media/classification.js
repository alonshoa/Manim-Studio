(() => {
  const vscode = acquireVsCodeApi();
  const $ = id => document.getElementById(id);
  let schema, page, detail, draft, displayedSuggestion, busy = false, draftTimer;
  const filterLabels = {unclassified: 'טרם סווגו', deferred: 'דולגו', confirmed: 'סווגו', all: 'הכול'};
  let filter = 'unclassified';
  const post = (type, data = {}) => vscode.postMessage({type, session_id: page?.session_id, prompt_id: detail?.prompt_id, ...data});
  const label = (group, code) => schema?.[group]?.find(item => item.code === code)?.label ?? code;
  const statusLabel = state => ({unclassified: 'טרם סווג', confirmed: 'סיווג אנושי', deferred: 'דולג בינתיים'}[state] || state);
  function element(tag, text, className) { const node = document.createElement(tag); if (text != null) node.textContent = text; if (className) node.className = className; return node; }
  function announce(text, error = true) { $('feedback').textContent = text; $('feedback').style.color = error ? '#a24949' : 'var(--accent)'; }
  function setBusy(value) {
    busy = value;
    for (const node of document.querySelectorAll('#form button,#form input,#form textarea,#filters button,#prompt-list button,#paging button')) node.disabled = value;
    $('session').disabled = value;
  }
  function persistDraft() {
    if (!detail || !draft?.dirty) return;
    clearTimeout(draftTimer);
    $('draft-status').textContent = 'שומר טיוטה…'; $('draft-status').className = 'draft-status';
    post('draft', {draft: {...draft}});
  }
  function changed() {
    if (!draft || busy) return;
    draft.prompt_type = document.querySelector('input[name="prompt-type"]:checked')?.value ?? null;
    draft.other = $('other').value || null;
    draft.dirty = true;
    $('draft-status').textContent = 'טיוטה שטרם נשמרה';
    draftTimer = setTimeout(persistDraft, 180);
    $('other-field').hidden = !(draft.reasons || []).includes('other');
  }
  function renderFields() {
    $('types').replaceChildren();
    for (const item of schema.prompt_types) {
      const choice = element('label', null, 'type-option');
      const input = element('input'); input.type = 'radio'; input.name = 'prompt-type'; input.value = item.code;
      input.checked = draft.prompt_type === item.code;
      input.addEventListener('change', changed); choice.append(input, element('span', item.label)); $('types').append(choice);
    }
    $('reasons').replaceChildren();
    for (const item of schema.reasons) {
      const choice = element('label', null, 'reason-option');
      const input = element('input'); input.type = 'checkbox'; input.value = item.code; input.name = 'reason';
      input.checked = (draft.reasons || []).includes(item.code);
      input.addEventListener('change', () => {
        draft.reasons = [...document.querySelectorAll('input[name="reason"]:checked')].map(n => n.value);
        if (!draft.reasons.includes('other')) {draft.other = null; $('other').value = '';}
        changed(); renderReasonStatus();
      });
      choice.append(input, element('span', item.label)); $('reasons').append(choice);
    }
    $('other').value = draft.other || '';
    $('other-field').hidden = !(draft.reasons || []).includes('other');
    renderReasonStatus();
    $('draft-status').textContent = draft.dirty ? 'טיוטה משוחזרת — טרם נשמר סיווג' : detail.current ? 'הסיווג האנושי נשמר' : 'לא נשמר סיווג אנושי';
    $('draft-status').className = detail.current && !draft.dirty ? 'draft-status saved' : 'draft-status';
    setBusy(busy);
  }
  function renderReasonStatus() { $('reason-status').textContent = draft.reasons === null ? 'לא סופקו סיבות' : draft.reasons.length ? `${draft.reasons.length} סיבות נבחרו` : 'נבחר במפורש: ללא סיבות'; }
  function renderSuggestion() {
    const suggestion = displayedSuggestion;
    $('suggestion').hidden = !suggestion;
    if (!suggestion) return;
    const value = suggestion.payload;
    $('suggestion-state').textContent = detail.current?.payload.suggestion_id === suggestion.id ? 'בסיס לסיווג האנושי' : 'הצעה בלבד';
    $('suggestion-text').textContent = [label('prompt_types', value.prompt_type), ...(value.reasons || []).map(r => label('reasons', r)), ...(value.other ? [`אחר: ${value.other}`] : [])].join(' · ');
    const classifier = value.classifier || {};
    $('suggestion-source').textContent = `מסווג: ${classifier.name || 'לא נמסר'} · גרסה: ${classifier.version || 'לא נמסרה'} · הצעה בלבד, אינה סיווג אנושי`;
    $('new-suggestion').hidden = !detail.suggestion || detail.suggestion.id === suggestion.id;
    $('approve-suggestion').disabled = busy || !schema.prompt_types.some(t => t.code === value.prompt_type) || (value.taxonomy_version ?? 1) !== 1
      || (value.reasons || []).some(r => !schema.reasons.some(s => s.code === r)) || ((value.reasons || []).includes('other') && !value.other?.trim());
  }
  function renderDetail(next, storedDraft) {
    const same = detail?.prompt_id === next?.prompt_id && detail?.session_id === next?.session_id;
    if (!next) {detail = undefined; $('form').hidden = true; $('empty').hidden = false; return;}
    const keep = same && draft?.dirty;
    detail = next;
    if (!keep) {
      const value = storedDraft?.dirty ? storedDraft : next.current?.payload;
      draft = value ? {prompt_type: value.prompt_type ?? null, reasons: value.reasons ?? null, other: value.other ?? null,
        dirty: !!storedDraft?.dirty, expected_human_head: storedDraft?.dirty ? storedDraft.expected_human_head : next.human_head_event_id,
        suggestion_id: storedDraft?.suggestion_id} : {prompt_type: null, reasons: null, other: null, dirty: false, expected_human_head: next.human_head_event_id};
      displayedSuggestion = next.suggestion;
    }
    $('form').hidden = false; $('empty').hidden = true;
    const row = page?.prompts.find(p => p.prompt_id === next.prompt_id);
    $('prompt-number').textContent = row ? `פרומפט ${String(row.number).padStart(2, '0')} / ${page.counts.total}` : 'פרומפט במחקר';
    $('prompt-text').textContent = next.prompt.payload.text || 'תוכן הפרומפט אינו זמין';
    $('review-badge').textContent = statusLabel(next.review_status);
    $('review-badge').className = 'badge ' + (next.current ? 'green' : '');
    $('skip').hidden = !!next.current; $('clear').hidden = !next.current;
    $('context').replaceChildren();
    for (const item of next.context || []) {
      const node = element('div', null, 'context-item');
      node.append(element('small', {preceding: 'תגובה קודמת בשיחה', linked: 'מקושר לפרומפט', shared: 'הקשר משותף — השיוך אינו חד־משמעי'}[item.relation] || item.relation), element('span', item.text));
      $('context').append(node);
    }
    $('conflict').hidden = draft.expected_human_head === next.human_head_event_id;
    renderFields(); renderSuggestion();
  }
  function renderPage(next, nextDetail, storedDraft) {
    page = next;
    $('session-title').textContent = next.session.title;
    $('session-topic').textContent = next.session.topic;
    $('lifecycle').textContent = {active: 'מחקר פעיל', paused: 'המחקר מושהה', finished: 'המחקר הסתיים', legacy: 'תיעוד קיים'}[next.session.state] || next.session.state;
    $('coverage').textContent = next.coverage.known_gaps ? `תיעוד חלקי · ${next.coverage.known_gaps} פערים ידועים` : 'שלמות איסוף השיחה אינה מאומתת';
    const c = next.counts;
    $('total').textContent = c.total;
    $('progress-caption').textContent = c.total ? `${c.confirmed} מתוך ${c.total} פרומפטים שנאספו סווגו` : 'אין עדיין פרומפטים שנאספו למחקר';
    $('progress-bar').style.width = (c.total ? c.confirmed / c.total * 100 : 0) + '%';
    $('counts').replaceChildren(element('span', `${c.missing} ללא סיווג`), element('span', `מתוכם ${c.deferred} דולגו`));
    $('filters').replaceChildren();
    for (const [key, value] of Object.entries(filterLabels)) {
      const button = element('button', value, 'filter ' + (filter === key ? 'active' : ''));
      button.setAttribute('data-filter', key);
      button.onclick = () => {persistDraft(); filter = key; setBusy(true); post('filter', {filter: key});};
      $('filters').append(button);
    }
    $('prompt-list').replaceChildren();
    for (const item of next.prompts) {
      const button = element('button', null, 'prompt-row ' + (item.prompt_id === nextDetail?.prompt_id ? 'selected' : ''));
      button.dataset.promptId = item.prompt_id;
      const body = element('div', null, 'row-body');
      body.append(element('div', item.preview, 'row-text'));
      const meta = element('div', null, 'row-meta');
      meta.append(element('span', statusLabel(item.review_status), 'badge ' + (item.current ? 'green' : '')));
      if (item.suggestion && !item.current) meta.append(element('span', '✧ הצעה', 'muted'));
      body.append(meta); button.append(element('span', String(item.number).padStart(2, '0'), 'row-number'), body);
      button.onclick = () => {persistDraft(); setBusy(true); post('select', {prompt_id: item.prompt_id});};
      $('prompt-list').append(button);
    }
    if (!next.prompts.length) $('prompt-list').append(element('p', 'אין פרומפטים במסנן הנוכחי', 'muted'));
    $('paging').replaceChildren();
    if (next.offset > 0) {
      const previous = element('button', '→ העמוד הקודם', 'text-button'); previous.onclick = () => {persistDraft(); setBusy(true); post('page', {offset: Math.max(0, next.offset-next.limit)});}; $('paging').append(previous);
    }
    if (next.next_offset != null) {
      const button = element('button', 'העמוד הבא ←', 'text-button'); button.onclick = () => {persistDraft(); setBusy(true); post('page', {offset: next.next_offset});}; $('paging').append(button);
    }
    setBusy(false); renderDetail(nextDetail, storedDraft);
  }
  function write(action, next = false) {
    if (!detail || busy) return;
    if (action === 'save' && !draft.prompt_type) {announce('יש לבחור סוג פרומפט לפני השמירה.'); return;}
    if (action === 'save' && (draft.reasons || []).includes('other') && !draft.other?.trim()) {announce('יש להוסיף פירוט קצר עבור ״אחר״.'); return;}
    persistDraft(); announce(''); setBusy(true);
    post('write', {action, next, ...draft});
  }
  $('save').onclick = () => write('save'); $('save-next').onclick = () => write('save', true);
  $('skip').onclick = () => write('skip', true); $('clear').onclick = () => write('clear');
  $('other').oninput = changed;
  $('no-reasons').onclick = () => {draft.reasons = []; draft.other = null; draft.dirty = true; renderFields(); persistDraft();};
  $('copy-suggestion').onclick = () => {
    const value = displayedSuggestion.payload;
    const supported = (value.taxonomy_version ?? 1) === 1;
    draft = {...draft, prompt_type: supported ? value.prompt_type : null, reasons: supported ? (value.reasons ?? null) : null, other: supported ? (value.other ?? null) : null,
      suggestion_id: displayedSuggestion.id, dirty: true}; renderFields(); persistDraft();
    if (!supported) announce('גרסת ההצעה אינה נתמכת. יש לבחור סיווג ידני לפי האפשרויות הנוכחיות.');
  };
  $('approve-suggestion').onclick = () => {$('copy-suggestion').click(); write('save');};
  $('new-suggestion').onclick = () => {displayedSuggestion = detail.suggestion; renderSuggestion();};
  $('resolve-conflict').onclick = () => {draft.expected_human_head = detail.human_head_event_id; draft.dirty = true; $('conflict').hidden = true; persistDraft(); announce('הטיוטה שלך נשמרה. אפשר לערוך ולשמור על בסיס הסיווג העדכני.', false);};
  $('discard').onclick = () => {draft = undefined; post('discard');};
  $('history-button').onclick = () => post('history'); $('close-history').onclick = () => {$('history').hidden = true;};
  $('session').onclick = () => {persistDraft(); post('session');}; $('refresh').onclick = () => {persistDraft(); post('refresh');};
  $('retry').onclick = () => post('retry');
  window.addEventListener('message', ({data}) => {
    if (data.type === 'schema') {schema = data.schema;}
    else if (data.type === 'page') {renderPage(data.page, data.detail, data.draft); $('retry-row').hidden = !data.pending;}
    else if (data.type === 'draftSaved' && detail?.prompt_id === data.prompt_id && detail?.session_id === data.session_id) {$('draft-status').textContent = '● הטיוטה נשמרה מקומית'; $('draft-status').className = 'draft-status saved';}
    else if (data.type === 'saving') {setBusy(true); $('draft-status').textContent = 'שומר סיווג…';}
    else if (data.type === 'idle') {setBusy(false); renderSuggestion();}
    else if (data.type === 'saved' && data.result.prompt_id === detail?.prompt_id && data.result.session_id === detail?.session_id) {
      draft = undefined; announce(data.action === 'skip' ? 'הפרומפט סומן לחזרה מאוחר יותר, ללא סיווג.' : data.action === 'clear' ? 'הסיווג נוקה. ההיסטוריה נשמרה.' : 'הסיווג נשמר בהיסטוריית המחקר.', false); $('retry-row').hidden = true;
    } else if (data.type === 'writeError' && detail?.prompt_id === data.prompt_id && detail?.session_id === data.session_id) {
      if (data.current) {detail = data.current; $('conflict').hidden = false;}
      $('retry-row').hidden = !data.pending;
      $('draft-status').textContent = data.pending ? 'תוצאת השמירה אינה ידועה' : 'הסיווג לא עודכן · הטיוטה נשארה זמינה';
      $('draft-status').className = 'draft-status';
      announce(data.code === 'classification_conflict' ? 'הסיווג השתנה בחלון אחר. הטיוטה שלך לא נמחקה.' : 'השמירה לא אושרה. הטיוטה נשארה זמינה.');
    } else if (data.type === 'error' || data.type === 'stale') {setBusy(false); announce(data.message || 'לא ניתן לרענן את המידע. המצב המוצג עשוי להיות ישן.');}
    else if (data.type === 'history' && data.data.prompt_id === detail?.prompt_id && data.data.session_id === detail?.session_id) {
      $('history-content').replaceChildren();
      for (const event of [...data.data.history].reverse()) {
        const node = element('div', null, 'history-item');
        const names = {'classification.confirmed':'סיווג אנושי', 'classification.suggested':'הצעת מודל', 'classification.skipped':'דילוג בינתיים', 'classification.cleared':'ניקוי סיווג'};
        const p = event.payload;
        node.append(element('strong', names[event.type] || event.type), element('small', new Date(event.timestamp).toLocaleString('he-IL', {dateStyle:'short',timeStyle:'short'})),
          element('span', [p.prompt_type ? label('prompt_types', p.prompt_type) : 'ללא סיווג תקף', ...(p.reasons || []).map(r => label('reasons', r))].join(' · ')));
        if (p.other) node.append(element('p', `אחר: ${p.other}`));
        if (event.type === 'classification.confirmed') node.append(element('small', p.reasons === null || p.reasons === undefined ? 'לא סופקו סיבות' : !p.reasons.length ? 'נבחר במפורש: ללא סיבות' : `טקסונומיה ${p.taxonomy_version ?? 1}`));
        $('history-content').append(node);
      }
      if (!data.data.history.length) $('history-content').append(element('p', 'אין עדיין היסטוריית סיווג.'));
      $('history').hidden = false;
    }
  });
  post('ready');
})();
