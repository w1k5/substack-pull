import { $, fmt, date, loadingIndicator } from './shared.js';
import { loadNoteStats, noteReachCard } from './post/notes.js';
import { updateComparedNote } from './notes-compare.js';

let detailRequest = 0;
let lastData;
let displayedId;

export function renderNotesPage(data, selectedId) {
  const notes = (data.publication_events || [])
    .filter((event) => event.type === 'note' && /^\d+$/.test(String(event.id)));
  if (data !== lastData) {
    const attributed = (data.growth_sources || []).find(
      (source) => source.name === 'Notes' && source.parent === 'Substack',
    )?.subscribers;
    const insight = $('notes-insight');
    insight.replaceChildren();
    const copy = document.createElement('div');
    const label = document.createElement('span');
    label.className = 'insight-label';
    label.textContent = 'NOTES IN THIS PERIOD';
    const heading = document.createElement('strong');
    heading.textContent = `${fmt(notes.length)} published · ${fmt(attributed)} subscribers attributed to Notes`;
    const caveat = document.createElement('p');
    caveat.textContent = 'Subscriber attribution is for Notes as a channel, not for an individual Note.';
    copy.append(label, heading, caveat);
    insight.append(copy);
    lastData = data;
  }

  const dialog = $('note-detail');
  if (!selectedId) {
    if (dialog.open) dialog.close();
    if (displayedId) detailRequest++;
    displayedId = undefined;
    return;
  }
  if (!dialog.open) dialog.showModal();
  if (selectedId !== displayedId) {
    displayedId = selectedId;
    renderSelectedNote(notes.find((note) => String(note.id) === selectedId), selectedId);
  }
}

async function renderSelectedNote(note, selectedId, refresh = false) {
  const request = ++detailRequest;
  const slot = $('note-detail-content');
  slot.replaceChildren();
  const heading = document.createElement('div');
  heading.className = 'note-detail-heading';
  const title = document.createElement('h2');
  title.textContent = note?.title || `Note c-${selectedId}`;
  const meta = document.createElement('p');
  meta.textContent = note?.day ? `Published ${date(note.day)} · lifetime reach` : 'Lifetime reach';
  const copy = document.createElement('div');
  copy.append(title, meta);
  const refreshButton = document.createElement('button');
  refreshButton.type = 'button';
  refreshButton.className = 'refresh';
  refreshButton.textContent = '↻ Refresh Note';
  refreshButton.disabled = true;
  refreshButton.addEventListener('click', () => renderSelectedNote(note, selectedId, true));
  heading.append(copy, refreshButton);
  slot.append(heading, loadingIndicator('Loading Note reach…'));
  try {
    const stats = await loadNoteStats(selectedId, refresh);
    if (request !== detailRequest) return;
    if (!note && stats.preview)
      title.textContent = `${stats.preview.slice(0, 125)}${stats.preview.length > 125 ? '…' : ''}`;
    if (!note && stats.published_at)
      meta.textContent = `Published ${date(stats.published_at)} · lifetime reach`;
    updateComparedNote(stats);
    refreshButton.disabled = false;
    slot.replaceChildren(heading, noteReachCard(stats));
  } catch (error) {
    if (request !== detailRequest) return;
    refreshButton.disabled = false;
    const message = document.createElement('p');
    message.className = 'empty-state';
    message.textContent = `Could not load Note reach: ${error.message}`;
    slot.replaceChildren(heading, message);
  }
}

export function setupNoteDetail(navigate) {
  const dialog = $('note-detail');
  $('note-detail-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    if (/^\/notes\/\d+$/.test(location.pathname)) navigate('/notes');
  });
}

export function clearNotePageStats() {
  detailRequest++;
  displayedId = undefined;
}
