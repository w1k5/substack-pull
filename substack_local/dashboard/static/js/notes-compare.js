import { $, date, fmt, pct, cell } from './shared.js';
import { downloadCsv } from './export.js';
import { renderNotesMap, setupNotesMap } from './notes-map.js';
import { notePreview } from './note-preview.js';

const lenses = {
  day: 'Newest Notes first. Choose a metric column to rank them by performance.',
  pace: 'Reach relative to your typical Note at the same age. Use this to spot ideas worth revisiting.',
  visits: 'Profile visits per 1,000 impressions. This separates reader curiosity from sheer exposure.',
  responses: 'Likes, replies, shares, and restacks per 1,000 impressions. This shows response to the writing.',
  clicks: 'Link clicks per 1,000 impressions. This shows which Notes sent readers onward.',
  unconnected: 'Share of the Note’s audience that was not already connected to you. Audience counts are people, not impressions.',
};
const PAGE_SIZE = 50;

let notes = [];
let signature = '';
let sourceData;
let analyzed = false;
let loading = false;
let generation = 0;
let cohort = null;
let loadError = '';
let sort = { key: 'day', direction: 'desc' };
let query = '';
let selectedId = '';
let visibleCount = PAGE_SIZE;
let navigateTo;
const measured = new Map();
const failed = new Set();

function values(note) {
  const stats = measured.get(String(note.id));
  if (!stats) return { note, stats: null, impressions: null, pace: null,
    visits: null, responses: null, clicks: null,
    visitRate: null, responseRate: null, clickRate: null,
    audienceCount: null, unconnectedCount: null, unconnected: null };
  return { note, stats, ...stats.comparison };
}

function sortValue(row) {
  switch (sort.key) {
    case 'day': return row.note.day;
    case 'title': return row.note.title.toLowerCase();
    case 'pace': return row.pace?.ratio;
    case 'visits': return row.visitRate;
    case 'responses': return row.responseRate;
    case 'clicks': return row.clickRate;
    case 'unconnected': return row.unconnected;
    default: return row.impressions;
  }
}

function rows() {
  const ranked = cohort?.[sort.key]?.ranked_ids;
  const ranks = ranked ? new Map(ranked.map((id, index) => [String(id), index])) : null;
  return notes.filter((note) => note.title.toLowerCase().includes(query))
    .map(values)
    .sort((a, b) => {
      const av = sortValue(a), bv = sortValue(b);
      if (av == null) return bv == null ? 0 : 1;
      if (bv == null) return -1;
      if (ranks) {
        const order = (ranks.get(String(a.note.id)) ?? Infinity) - (ranks.get(String(b.note.id)) ?? Infinity);
        if (order) return order * (sort.direction === 'asc' ? -1 : 1);
      }
      const order = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
      return order * (sort.direction === 'asc' ? 1 : -1)
        || b.note.day.localeCompare(a.note.day);
    });
}

function measuredRows() {
  return notes.filter((note) => measured.has(String(note.id))).map(values);
}

function markSelected() {
  document.querySelectorAll('#note-compare-rows .note-compare-link').forEach((button) => {
    const current = button.dataset.noteId === selectedId;
    if (current) button.setAttribute('aria-current', 'true');
    else button.removeAttribute('aria-current');
    button.closest('tr').classList.toggle('selected', current);
  });
}

function metric(main, detail) {
  const wrapper = document.createElement('span');
  wrapper.className = 'note-compare-metric';
  const strong = document.createElement('strong');
  strong.textContent = main;
  const small = document.createElement('small');
  small.textContent = detail;
  wrapper.append(strong, small);
  return wrapper;
}

function renderTable() {
  const body = $('note-compare-rows');
  const scroller = $('note-compare-scroll');
  const scrollTop = scroller.scrollTop;
  const scrollLeft = scroller.scrollLeft;
  body.replaceChildren();
  const result = rows();
  $('note-compare-results').hidden = !result.length;
  $('note-compare-empty').hidden = !!result.length;
  if (!result.length) {
    $('note-compare-empty').textContent = notes.length
      ? 'No Notes match that search.'
      : 'No published Notes appear in this period. Try a longer period.';
    return;
  }
  result.slice(0, visibleCount).forEach((row) => {
    const tr = document.createElement('tr');
    const title = document.createElement('button');
    title.type = 'button';
    title.className = 'note-compare-link';
    title.textContent = notePreview(row.note.title, 110).text;
    title.dataset.noteId = String(row.note.id);
    title.addEventListener('click', () => navigateTo(`/notes/${row.note.id}`));
    const noteCell = document.createElement('span');
    noteCell.className = 'note-compare-metric';
    const exposure = document.createElement('small');
    exposure.textContent = `${date(row.note.day)}${row.stats ? ` · ${fmt(row.impressions)} impressions to date` : ''}`;
    noteCell.append(title, exposure);
    cell(tr, noteCell);
    cell(tr, metric(row.stats ? row.pace.label : '—',
      row.stats ? `${fmt(row.pace.actual)} vs ${fmt(row.pace.typical)} at ${row.pace.age}`
        : loading ? 'Comparing…' : analyzed ? 'Unavailable' : ''));
    cell(tr, metric(row.visitRate == null ? '—' : row.visitRate.toFixed(1),
      row.stats ? `${fmt(row.visits)} visits${row.visitRate == null ? ' · small sample' : ''}` : ''));
    cell(tr, metric(row.responseRate == null ? '—' : row.responseRate.toFixed(1),
      row.stats ? `${fmt(row.responses)} responses${row.responseRate == null ? ' · small sample' : ''}` : ''));
    cell(tr, metric(row.clickRate == null ? '—' : row.clickRate.toFixed(1),
      row.stats ? `${fmt(row.clicks)} clicks${row.clickRate == null ? ' · small sample' : ''}` : ''));
    cell(tr, metric(row.unconnected == null ? '—' : pct(row.unconnected),
      row.stats ? `${fmt(row.unconnectedCount)} of ${fmt(row.audienceCount)} people${row.unconnected == null ? ' · small sample' : ''}` : ''));
    body.append(tr);
  });
  const more = $('note-compare-more');
  more.hidden = result.length <= visibleCount;
  more.textContent = `Show more Notes · ${Math.min(visibleCount, result.length)} of ${result.length} shown`;
  markSelected();
  scroller.scrollTop = scrollTop;
  scroller.scrollLeft = scrollLeft;
}

function renderControls() {
  $('note-compare-export').disabled = !rows().length;
  $('note-compare-guide').textContent = lenses[sort.key]
    || 'Select a column to compare the measured Notes.';
  document.querySelectorAll('[data-note-sort]').forEach((button) => {
    const th = button.closest('th');
    th.setAttribute('aria-sort', button.dataset.noteSort === sort.key
      ? sort.direction === 'asc' ? 'ascending' : 'descending' : 'none');
    button.querySelector('.sort-arrow').textContent = button.dataset.noteSort === sort.key
      ? sort.direction === 'asc' ? '↑' : '↓' : '↕';
  });
}

function render() {
  $('note-compare-count').textContent = `${notes.length} Notes published in this period${loading ? ' · comparing performance…' : ''}`;
  renderControls();
  renderTable();
  renderMap();
}

function renderMap() {
  renderNotesMap({
    rows: analyzed ? measuredRows() : [], total: notes.length,
    analyzed, failed: failed.size, loading, cohort, error: loadError,
  });
}

export function renderNotesComparison(data, navigate, activeId) {
  navigateTo = navigate;
  selectedId = String(activeId || '');
  const nextNotes = (data.publication_events || [])
    .filter((event) => event.type === 'note' && /^\d+$/.test(String(event.id)))
    .sort((a, b) => b.day.localeCompare(a.day) || Number(b.id) - Number(a.id));
  const nextSignature = `${data.range?.days}:${nextNotes.map((note) => note.id).join(',')}`;
  const nextQuery = $('global-search').value.toLowerCase().trim();
  const changed = sourceData !== data || signature !== nextSignature || query !== nextQuery;
  const newCohort = signature !== nextSignature;
  if (newCohort) {
    signature = nextSignature;
    visibleCount = PAGE_SIZE;
    generation++;
    analyzed = false;
    loading = false;
    cohort = null;
    loadError = '';
    measured.clear();
    failed.clear();
    $('note-compare-results').removeAttribute('aria-busy');
  }
  notes = nextNotes;
  sourceData = data;
  query = nextQuery;
  if (changed) render();
  else markSelected();
  if (newCohort && notes.length) analyzeNotes();
}

export function filterNotesComparison(value) {
  query = value.toLowerCase().trim();
  visibleCount = PAGE_SIZE;
  renderControls();
  renderTable();
}

async function analyzeNotes(retryUnavailable = false) {
  if (loading || !notes.length) return;
  loading = true;
  loadError = '';
  const currentGeneration = generation;
  $('note-compare-results').setAttribute('aria-busy', 'true');
  render();
  try {
    const days = sourceData?.range?.days || 90;
    const response = await fetch(`/api/note-comparison?days=${days}${retryUnavailable ? '&retry=1' : ''}`, { cache: 'no-store' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not analyze Notes.');
    if (generation !== currentGeneration) return;
    measured.clear();
    result.rows.forEach((row) => measured.set(String(row.id), { comparison: row }));
    failed.clear();
    result.unavailable_ids.forEach((id) => failed.add(String(id)));
    cohort = result.lenses;
    analyzed = true;
  } catch (error) {
    if (generation !== currentGeneration) return;
    loadError = error.message || 'Could not analyze Notes.';
  }
  if (generation !== currentGeneration) return;
  loading = false;
  $('note-compare-results').removeAttribute('aria-busy');
  render();
}

export async function retryNotesComparison() {
  await analyzeNotes(true);
}

export function clearNotesComparison() {
  generation++;
  signature = '';
  sourceData = undefined;
  analyzed = false;
  loading = false;
  cohort = null;
  loadError = '';
  measured.clear();
  failed.clear();
  $('note-compare-results').removeAttribute('aria-busy');
  render();
}

export function updateComparedNote(stats) {
  const id = String(stats.id);
  if (notes.some((note) => String(note.id) === id)) {
    measured.set(id, stats);
    if (analyzed && !loading) analyzeNotes();
    else render();
  }
}

export function setupNotesComparison() {
  setupNotesMap(retryNotesComparison);
  $('note-compare-more').addEventListener('click', () => {
    visibleCount += PAGE_SIZE;
    renderTable();
  });
  $('note-compare-export').addEventListener('click', () => {
    downloadCsv('substack-notes-comparison.csv',
      ['Published', 'Note', 'Note ID', 'Impressions', 'Pace vs typical',
        'Profile visits', 'Profile visits per 1k impressions', 'Responses',
        'Responses per 1k impressions', 'Link clicks', 'Link clicks per 1k impressions',
        'Unconnected people', 'Audience people', 'Unconnected share'],
      rows().map((row) => [row.note.day, row.note.title, row.note.id,
        row.impressions, row.stats ? row.pace.label : null, row.visits, row.visitRate,
        row.responses, row.responseRate, row.clicks, row.clickRate,
        row.unconnectedCount, row.audienceCount, row.unconnected]));
  });
  $('note-compare-table').addEventListener('click', (event) => {
    const key = event.target.closest('[data-note-sort]')?.dataset.noteSort;
    if (!key) return;
    sort = {
      key,
      direction: sort.key === key
        ? sort.direction === 'desc' ? 'asc' : 'desc'
        : key === 'title' ? 'asc' : 'desc',
    };
    visibleCount = PAGE_SIZE;
    render();
  });
}
