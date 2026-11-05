import { $ } from './shared.js';

let snapshot;
let loading = false;
let selectedDay;
let selectedNoteId;
let selectedNoteText;
let pendingAction;

const dayDate = (value) => new Date(`${value}T00:00:00Z`);
const ymd = (value) => value.toISOString().slice(0, 10);
function addDays(value, count) {
  const next = dayDate(value);
  next.setUTCDate(next.getUTCDate() + count);
  return ymd(next);
}
const shortDate = (value) => new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(dayDate(value));
const longDate = (value) => new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(dayDate(value));

function node(tag, className, value) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (value !== undefined) item.textContent = value;
  return item;
}

function notice(message = '') {
  $('planner-notice').textContent = message;
  $('planner-notice').hidden = !message;
}

async function api(path, options) {
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Could not load Notes');
  return result;
}

const post = (path, body) => api(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

async function loadPlanner(refresh = false) {
  if (loading) return;
  loading = true;
  notice();
  $('planner-loading').hidden = false;
  $('planner-refresh').disabled = true;
  try {
    const days = $('planner-days').value;
    const spacing = $('planner-spacing').value;
    snapshot = await api(`/api/planner?days=${days}&spacing=${spacing}${refresh ? '&refresh=1' : ''}`);
    if (!selectedDay || selectedDay < snapshot.runway.start || selectedDay > snapshot.runway.end)
      selectedDay = snapshot.runway.start;
    renderPlanner();
  } catch (error) {
    notice(`Could not load the Note plan: ${error.message}`);
  } finally {
    loading = false;
    $('planner-loading').hidden = true;
    $('planner-refresh').disabled = false;
  }
}

function eventMap() {
  const map = new Map();
  for (const event of snapshot.runway.events) {
    if (!map.has(event.date)) map.set(event.date, []);
    map.get(event.date).push(event);
  }
  return map;
}

function renderCalendar() {
  const data = snapshot.runway;
  const map = eventMap();
  const openings = new Set(snapshot.opening_days || []);
  const weekCount = (week) => Array.from({ length: 7 }, (_, i) => map.get(addDays(week, i))?.length || 0)
    .reduce((sum, count) => sum + count, 0);
  const first = dayDate(data.start);
  const gridStart = addDays(data.start, -((first.getUTCDay() + 6) % 7));
  const last = dayDate(data.end);
  const gridEnd = addDays(data.end, 6 - ((last.getUTCDay() + 6) % 7));
  const calendar = $('planner-calendar');
  calendar.replaceChildren();
  const head = node('div', 'planner-week planner-head');
  for (const label of ['Week of', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Load'])
    head.append(node('span', '', label));
  calendar.append(head);
  for (let week = gridStart; week <= gridEnd; week = addDays(week, 7)) {
    const row = node('div', 'planner-week');
    const total = weekCount(week);
    const label = node('div', 'planner-week-label');
    label.append(node('strong', '', shortDate(week)), node('span', '', total ? `${total} scheduled` : 'open'));
    row.append(label);
    for (let offset = 0; offset < 7; offset++) {
      const day = addDays(week, offset);
      const count = map.get(day)?.length || 0;
      const button = node('button', 'planner-day');
      button.type = 'button';
      button.append(node('span', '', String(dayDate(day).getUTCDate())));
      if (count) button.append(node('span', 'count', String(count)));
      if (day < data.start || day > data.end) { button.disabled = true; button.classList.add('outside'); }
      if (count === 1) button.classList.add('one');
      if (count === 2) button.classList.add('cluster');
      if (count >= 3) button.classList.add('busy');
      if (openings.has(day)) button.classList.add('opening');
      if (selectedDay === day) button.classList.add('selected');
      button.setAttribute('aria-label', `${longDate(day)}: ${count} scheduled Notes${openings.has(day) ? ', an open slot' : ''}`);
      button.addEventListener('click', () => {
        selectedDay = day;
        $('planner-at').value = `${day}T09:00`;
        calendar.querySelectorAll('.planner-day').forEach((cell) => cell.classList.remove('selected'));
        button.classList.add('selected');
        renderDayDetail(map);
      });
      row.append(button);
    }
    const load = node('div', 'planner-week-total');
    const bar = node('span', 'bar');
    const fill = node('i');
    fill.style.width = `${data.busiestWeek ? Math.min(100, total / data.busiestWeek * 100) : 0}%`;
    bar.append(fill);
    load.append(node('strong', '', String(total)), bar);
    row.append(load);
    calendar.append(row);
  }
  renderDayDetail(map);
}

function selectNote(noteId, text) {
  selectedNoteId = noteId;
  selectedNoteText = text;
  $('planner-selected-note').textContent = `Note ${noteId} · ${text}`;
  $('planner-preview-schedule').disabled = false;
  if (!$('planner-at').value) $('planner-at').value = `${selectedDay}T09:00`;
  renderDrafts();
}

function renderDayDetail(map = eventMap()) {
  const slot = $('planner-day-detail');
  slot.replaceChildren();
  slot.append(node('h3', '', longDate(selectedDay)));
  const events = map.get(selectedDay) || [];
  slot.append(node('p', '', events.length
    ? `${events.length} scheduled ${events.length === 1 ? 'Note' : 'Notes'} on this day.`
    : 'No Note scheduled here. Choose a draft below to use this date.'));
  for (const event of events) {
    const card = node('div', 'planner-day-note');
    const copy = node('div');
    copy.append(node('strong', '', `${event.time} · Note ${event.id}`), node('span', '', event.text));
    const button = node('button', 'refresh', 'Reschedule');
    button.type = 'button';
    button.addEventListener('click', () => selectNote(event.id, event.text));
    card.append(copy, button);
    slot.append(card);
  }
}

function renderDrafts() {
  const list = $('planner-draft-list');
  list.replaceChildren();
  if (!snapshot.drafts.length) {
    list.append(node('p', 'empty-state', 'No unscheduled drafts yet. Write one to begin.'));
    return;
  }
  for (const draft of snapshot.drafts) {
    const button = node('button', 'planner-draft');
    button.type = 'button';
    if (draft.id === selectedNoteId) button.classList.add('selected');
    button.append(node('small', '', `Note ${draft.id}`), node('span', '', draft.preview || 'Attachment-only Note'));
    button.addEventListener('click', () => selectNote(draft.id, draft.preview || 'Attachment-only Note'));
    list.append(button);
  }
}

function renderPlanner() {
  const data = snapshot.runway;
  $('planner-subhead').textContent = `${shortDate(data.start)}–${longDate(data.end)} · ${data.timezone} · ${snapshot.last_sync_at ? `last synced ${new Date(snapshot.last_sync_at).toLocaleString()}` : 'local backup not synced yet'}`;
  $('planner-scheduled-count').textContent = String(data.scheduledInWindow);
  $('planner-draft-count').textContent = String(data.draftCount);
  $('planner-open-count').textContent = String(data.activeDays);
  $('planner-timezone').textContent = data.timezone;
  renderCalendar();
  renderDrafts();
}

function confirmAction(title, detail, body, button, action) {
  pendingAction = action;
  $('planner-confirm-title').textContent = title;
  $('planner-confirm-detail').textContent = detail;
  $('planner-confirm-body').textContent = body;
  $('planner-apply').textContent = button;
  $('planner-confirm').showModal();
}

async function previewDraft() {
  notice();
  $('planner-preview-draft').disabled = true;
  try {
    const preview = await post('/api/planner/preview-draft', { text: $('planner-text').value });
    confirmAction('Create unpublished draft', 'Review the exact text Substack will store. This will remain an unscheduled draft.', preview.body, 'Create draft', { kind: 'draft', text: preview.body });
  } catch (error) { notice(error.message); }
  finally { $('planner-preview-draft').disabled = false; }
}

async function previewSchedule() {
  notice();
  if (!selectedNoteId || !$('planner-at').value) { notice('Choose a Note and a future date and time.'); return; }
  $('planner-preview-schedule').disabled = true;
  try {
    const at = $('planner-at').value;
    const preview = await post('/api/planner/preview-schedule', { note_id: selectedNoteId, at });
    const scheduledAt = new Intl.DateTimeFormat('en-US', {
      dateStyle: 'medium', timeStyle: 'short', timeZone: preview.timezone,
    }).format(new Date(preview.new_scheduled_at));
    const detail = `Note ${selectedNoteId} · ${preview.current_status === 'scheduled' ? `currently ${preview.current_scheduled_at}` : 'currently a draft'} · new time ${scheduledAt} (${preview.timezone})`;
    confirmAction('Schedule this Note', detail, selectedNoteText || '', 'Save schedule', { kind: 'schedule', note_id: selectedNoteId, at });
  } catch (error) { notice(error.message); }
  finally { $('planner-preview-schedule').disabled = false; }
}

async function applyAction() {
  if (!pendingAction) return;
  const action = pendingAction;
  $('planner-apply').disabled = true;
  try {
    const result = action.kind === 'draft'
      ? await post('/api/planner/create-draft', { text: action.text })
      : await post('/api/planner/schedule', { note_id: action.note_id, at: action.at });
    if (!result.applied) {
      notice(result.duplicate ? 'This exact draft already exists. No new Note was created.' : 'The change was not applied. Check the Note before retrying.');
      $('planner-confirm').close();
      return;
    }
    $('planner-confirm').close();
    pendingAction = undefined;
    if (action.kind === 'draft') $('planner-text').value = '';
    selectedNoteId = undefined;
    selectedNoteText = undefined;
    $('planner-selected-note').textContent = 'Choose a draft or scheduled Note first.';
    $('planner-preview-schedule').disabled = true;
    $('planner-char-count').textContent = `${$('planner-text').value.length.toLocaleString()} / 5,000`;
    await loadPlanner();
  } catch (error) { notice(`The result is uncertain: ${error.message}. Sync Notes and check before retrying.`); }
  finally { $('planner-apply').disabled = false; }
}

export function setupPlanner() {
  $('planner-refresh').addEventListener('click', () => loadPlanner(true));
  $('planner-days').addEventListener('change', () => loadPlanner());
  $('planner-spacing').addEventListener('change', () => loadPlanner());
  $('planner-text').addEventListener('input', () => {
    $('planner-char-count').textContent = `${$('planner-text').value.length.toLocaleString()} / 5,000`;
  });
  $('planner-preview-draft').addEventListener('click', previewDraft);
  $('planner-preview-schedule').addEventListener('click', previewSchedule);
  $('planner-cancel').addEventListener('click', () => $('planner-confirm').close());
  $('planner-apply').addEventListener('click', applyAction);
  $('planner-confirm').addEventListener('close', () => { pendingAction = undefined; });
}

export function renderPlannerRoute() {
  if (!snapshot && !loading) loadPlanner();
}
