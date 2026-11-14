import { detailHeader } from './post/detail-card.js';
import { $, fmt, date, loadingIndicator } from './shared.js';
import { loadNoteStats, noteReachCard } from './post/notes.js';
import { updateComparedNote } from './notes-compare.js';
import { notePreview } from './note-preview.js';

let detailRequest = 0;
let displayedId;

export function renderNotesPage(data, selectedId) {
  const notes = (data.publication_events || [])
    .filter((event) => event.type === 'note' && /^\d+$/.test(String(event.id)));
  const dialog = $('note-detail');
  if (!selectedId) {
    if (dialog.open) dialog.close();
    if (displayedId) detailRequest++;
    displayedId = undefined;
    return;
  }
  if (!dialog.open) dialog.show();
  if (selectedId !== displayedId) {
    displayedId = selectedId;
    renderSelectedNote(notes.find((note) => String(note.id) === selectedId), selectedId);
  }
}

async function renderSelectedNote(note, selectedId, refresh = false) {
  const request = ++detailRequest;
  const slot = $('note-detail-content');
  const keepDetails = refresh && !!slot.querySelector('.note-reach-card');
  const oldRefresh = keepDetails ? slot.querySelector('.note-detail-heading .refresh') : null;
  const pending = keepDetails ? loadingIndicator('Updating Note reach…', { inline: true }) : null;
  if (keepDetails) {
    slot.querySelector('.note-detail-error')?.remove();
    oldRefresh.disabled = true;
    slot.querySelector('.note-detail-heading').after(pending);
  } else slot.replaceChildren();
  const { heading, meta, button: refreshButton } = detailHeader('Note',
    note?.day ? `Published ${date(note.day)} · lifetime reach` : 'Lifetime reach',
    () => renderSelectedNote(note, selectedId, true));
  const noteBody = document.createElement('div');
  noteBody.className = 'note-detail-text';
  const excerpt = document.createElement('p');
  excerpt.id = 'note-detail-body';
  const expand = document.createElement('button');
  expand.type = 'button';
  expand.className = 'note-detail-expand';
  expand.setAttribute('aria-controls', excerpt.id);
  let fullText = '';
  let expanded = false;
  function showText(value) {
    fullText = value || '';
    const preview = notePreview(fullText, 220);
    excerpt.textContent = expanded ? fullText : preview.text;
    noteBody.hidden = !fullText;
    expand.hidden = !preview.truncated;
    expand.textContent = expanded ? 'Show less' : 'Show full Note';
    expand.setAttribute('aria-expanded', String(expanded));
  }
  expand.addEventListener('click', () => {
    expanded = !expanded;
    showText(fullText);
  });
  noteBody.append(excerpt, expand);
  showText(note?.title);
  if (!keepDetails) slot.append(heading, noteBody, loadingIndicator('Loading Note reach…'));
  try {
    const stats = await loadNoteStats(selectedId, refresh);
    if (request !== detailRequest) return;
    if (!note && stats.published_at)
      meta.textContent = `Published ${date(stats.published_at)} · lifetime reach`;
    showText(stats.full_text || note?.title || stats.preview);
    updateComparedNote(stats);
    refreshButton.disabled = false;
    slot.replaceChildren(heading, noteBody, noteReachCard(stats));
  } catch (error) {
    if (request !== detailRequest) return;
    refreshButton.disabled = false;
    const message = document.createElement('p');
    message.className = 'empty-state note-detail-error';
    message.textContent = `Could not ${keepDetails ? 'update' : 'load'} Note reach: ${error.message}`;
    if (keepDetails) {
      pending.remove();
      oldRefresh.disabled = false;
      slot.querySelector('.note-detail-heading').after(message);
    } else slot.replaceChildren(heading, noteBody, message);
  }
}

export function setupNoteDetail(onClose) {
  const dialog = $('note-detail');
  $('note-detail-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', onClose);
}

export function clearNotePageStats() {
  detailRequest++;
  displayedId = undefined;
}
