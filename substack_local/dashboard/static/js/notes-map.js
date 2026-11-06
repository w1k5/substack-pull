import { $, date, fmt, pct } from './shared.js';
import { notePreview } from './note-preview.js';
import { comparisonMetrics, comparisonSelectionHeading } from './comparison-elements.js';

const lenses = {
  responses: {
    label: 'Responses',
    axis: 'Responses per 1,000 impressions',
    value: (row) => row.responseRate,
    format: (value) => value.toFixed(1),
  },
  visits: {
    label: 'Profile visits',
    axis: 'Profile visits per 1,000 impressions',
    value: (row) => row.visitRate,
    format: (value) => value.toFixed(1),
  },
  clicks: {
    label: 'Link clicks',
    axis: 'Link clicks per 1,000 impressions',
    value: (row) => row.clickRate,
    format: (value) => value.toFixed(1),
  },
  unconnected: {
    label: 'Unconnected audience',
    axis: 'Unconnected share of audience',
    value: (row) => row.unconnected,
    format: pct,
  },
};

let lens = 'responses';
let query = '';
let selectedIds = [];
let snapshot = { rows: [], total: 0, analyzed: false, failed: 0, loading: false, cohort: null, error: '' };

function niceCeiling(value) {
  if (!Number.isFinite(value) || value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const unit = value / magnitude;
  return (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10) * magnitude;
}

function showTooltip(row, outcome, event, point) {
  const tooltip = $('note-map-tooltip');
  if (selectedIds.includes(String(row.note.id))) {
    tooltip.hidden = true;
    return;
  }
  tooltip.replaceChildren();
  const title = document.createElement('strong');
  title.textContent = row.note.title.length > 90 ? `${row.note.title.slice(0, 90)}…` : row.note.title;
  const metric = document.createElement('span');
  metric.textContent = `${row.pace.ratio.toFixed(2)}× typical reach · ${lenses[lens].format(outcome)} ${lenses[lens].axis.toLowerCase()}`;
  const published = document.createElement('small');
  published.textContent = `Published ${date(row.note.day)}`;
  tooltip.append(title, metric, published);
  tooltip.hidden = false;
  const rect = $('note-map-plot').getBoundingClientRect();
  const anchor = event?.clientX == null ? point.getBoundingClientRect() : { left: event.clientX, top: event.clientY };
  tooltip.style.left = `${Math.max(8, Math.min(rect.width - 225, anchor.left - rect.left + 12))}px`;
  tooltip.style.top = `${Math.max(8, anchor.top - rect.top - 76)}px`;
}

function card(row) {
  const root = document.createElement('article');
  root.className = 'note-map-card';
  const title = document.createElement('strong');
  title.className = 'note-map-card-copy';
  title.id = `note-map-copy-${row.note.id}`;
  const fullText = String(row.note.title || '');
  const preview = notePreview(fullText, 160);
  title.textContent = preview.text;
  const expand = document.createElement('button');
  expand.type = 'button';
  expand.className = 'note-map-card-expand';
  expand.textContent = 'Show full Note';
  expand.setAttribute('aria-controls', title.id);
  expand.setAttribute('aria-expanded', 'false');
  expand.addEventListener('click', () => {
    const expanded = expand.getAttribute('aria-expanded') !== 'true';
    title.textContent = expanded ? fullText : preview.text;
    expand.textContent = expanded ? 'Show less' : 'Show full Note';
    expand.setAttribute('aria-expanded', String(expanded));
  });
  const published = document.createElement('small');
  published.textContent = `Published ${date(row.note.day)}`;
  const raw = lens === 'responses' ? [fmt(row.responses), 'responses']
    : lens === 'visits' ? [fmt(row.visits), 'profile visits']
    : lens === 'clicks' ? [fmt(row.clicks), 'link clicks']
    : [fmt(row.unconnectedCount), `of ${fmt(row.audienceCount)} people`];
  const items = [
    [fmt(row.impressions), 'lifetime impressions'],
    [row.pace.label, `reach at ${row.pace.age}`],
    [lenses[lens].format(lenses[lens].value(row)), lenses[lens].axis.toLowerCase()],
    raw,
  ];
  const metrics = comparisonMetrics('note-map-card-metrics', items);
  root.append(title);
  if (preview.truncated) root.append(expand);
  root.append(published, metrics);
  return root;
}

function compactCard(row) {
  const root = document.createElement('article');
  root.className = 'note-map-mini';
  const title = document.createElement('strong');
  title.textContent = notePreview(row.note.title, 80).text;
  const context = document.createElement('small');
  context.textContent = `${date(row.note.day)} · ${row.pace.label} reach`;
  const counts = lens === 'responses' ? [row.responses, 'Responses']
    : lens === 'visits' ? [row.visits, 'Visits']
      : lens === 'clicks' ? [row.clicks, 'Clicks']
        : [row.unconnectedCount, 'Unconnected'];
  const metrics = comparisonMetrics('note-map-mini-metrics', [
    [fmt(row.impressions), 'Impressions'],
    [fmt(counts[0]), counts[1]],
    [lenses[lens].format(lenses[lens].value(row)), lens === 'unconnected' ? 'Audience share' : 'Per 1k'],
  ]);
  root.append(title, context, metrics);
  return root;
}

function syncSelection() {
  document.querySelectorAll('#note-map-points .note-map-point').forEach((point) => {
    const active = selectedIds.includes(point.dataset.noteId);
    point.classList.toggle('selected', active);
    point.setAttribute('aria-pressed', String(active));
  });
}

function renderSelection(rows) {
  const root = $('note-map-comparison');
  root.replaceChildren();
  const selected = selectedIds.map((id) => rows.find((row) => String(row.note.id) === id)).filter(Boolean);
  if (!selected.length) {
    const heading = document.createElement('strong');
    heading.textContent = 'Choose a Note';
    const guide = document.createElement('p');
    guide.textContent = 'Select a dot to inspect its numbers here, then another to compare.';
    root.append(heading, guide);
    return;
  }
  const heading = comparisonSelectionHeading('note-map-selection-heading', 'Note', selected.length, () => {
    selectedIds = [];
    syncSelection();
    renderSelection(rows);
  });
  const cards = document.createElement('div');
  cards.className = 'note-map-cards';
  selected.forEach((row) => cards.append(selected.length === 2 ? compactCard(row) : card(row)));
  root.append(heading, cards);
  if (selected.length === 1) {
    const hint = document.createElement('p');
    hint.textContent = 'Select one more dot to compare these Notes.';
    root.append(hint);
  }
}

function addLine(root, direction, position, label, emphasized = false) {
  const line = document.createElement('i');
  line.className = `note-map-gridline ${direction}${emphasized ? ' emphasized' : ''}`;
  line.style[direction === 'vertical' ? 'left' : 'top'] = `${position}%`;
  root.append(line);
  if (label == null) return;
  const tick = document.createElement('span');
  tick.className = `note-map-tick ${direction}`;
  tick.style[direction === 'vertical' ? 'left' : 'top'] = `${position}%`;
  tick.textContent = label;
  root.append(tick);
}

function renderPlot() {
  const { rows, total, analyzed, failed, loading, cohort, error } = snapshot;
  const progress = $('note-map-progress');
  progress.hidden = !loading;
  progress.classList.toggle('with-results', !!rows.length);
  const retry = $('note-map-retry');
  retry.hidden = (!failed && !error) || loading;
  retry.textContent = error ? 'Try again' : 'Retry missing stats';
  document.querySelectorAll('[data-map-lens]').forEach((button) => {
    const active = button.dataset.mapLens === lens;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });

  const definition = lenses[lens];
  const plottedIds = new Set(cohort?.[lens]?.plotted_ids || []);
  const standoutIds = new Set(cohort?.[lens]?.standout_ids || []);
  const plotted = rows.filter((row) => plottedIds.has(String(row.note.id)));
  const display = $('note-map-display');
  display.hidden = !plotted.length;
  const key = $('note-map-key');
  key.hidden = !plotted.length;
  key.textContent = `Dashed lines mark usual reach and the median ${definition.label.toLowerCase()}. Green dots are above both.`;
  $('note-map-empty').hidden = !!plotted.length || loading || (!analyzed && !error && !!total);
  $('note-map-empty').textContent = !total
    ? 'No published Notes appear in this period. Choose a longer period.'
    : error ? `Could not compare Notes: ${error}`
      : !analyzed ? ''
        : 'No Notes have enough data for this measure. Try another outcome.';
  const summary = $('note-map-summary');
  summary.hidden = plotted.length < 5;
  const searchNote = $('note-map-search-note');
  const matches = plotted.filter((row) => row.note.title.toLowerCase().includes(query));
  searchNote.hidden = !query || !plotted.length;
  searchNote.textContent = query
    ? `${matches.length} of ${plotted.length} plotted Notes match “${query}”. Other Notes stay visible for context.`
    : '';
  if (!plotted.length) {
    $('note-map-grid').replaceChildren();
    $('note-map-points').replaceChildren();
    $('note-map-tooltip').hidden = true;
    $('note-map-comparison').replaceChildren();
    return;
  }

  $('note-map-y-title').textContent = definition.axis;
  const grid = $('note-map-grid'), points = $('note-map-points');
  grid.replaceChildren();
  points.replaceChildren();
  const logs = plotted.map((row) => Math.log2(row.pace.ratio));
  const minLog = Math.min(-1, Math.floor(Math.min(...logs)));
  const maxLog = Math.max(1, Math.ceil(Math.max(...logs)));
  const x = (ratio) => 100 * (Math.log2(ratio) - minLog) / (maxLog - minLog);
  const outcomes = plotted.map(definition.value);
  const yMax = lens === 'unconnected' ? 1 : niceCeiling(Math.max(...outcomes));
  const y = (value) => 95 - 90 * value / yMax;
  const middle = cohort?.[lens]?.median;
  for (let power = minLog; power <= maxLog; power++) {
    const ratio = 2 ** power;
    addLine(grid, 'vertical', x(ratio), `${Number(ratio.toFixed(3))}×`, power === 0);
  }
  for (const value of [0, yMax / 2, yMax]) {
    const label = lens === 'unconnected' ? pct(value) : Number(value.toFixed(1)).toLocaleString();
    addLine(grid, 'horizontal', y(value), label);
  }
  addLine(grid, 'horizontal', y(middle), null, true);

  selectedIds = selectedIds.filter((id) => plotted.some((row) => String(row.note.id) === id));
  plotted.forEach((row) => {
    const outcome = definition.value(row);
    const point = document.createElement('button');
    point.type = 'button';
    point.className = 'note-map-point';
    point.dataset.noteId = String(row.note.id);
    if (standoutIds.has(String(row.note.id))) point.classList.add('standout');
    if (query && !row.note.title.toLowerCase().includes(query)) point.classList.add('dimmed');
    point.style.left = `${x(row.pace.ratio)}%`;
    point.style.top = `${y(outcome)}%`;
    point.setAttribute('aria-label',
      `${row.note.title}: ${row.pace.ratio.toFixed(2)} times typical reach, ${definition.format(outcome)} ${definition.axis.toLowerCase()}`);
    point.addEventListener('pointermove', (event) => showTooltip(row, outcome, event, point));
    point.addEventListener('pointerenter', (event) => showTooltip(row, outcome, event, point));
    point.addEventListener('pointerleave', () => { $('note-map-tooltip').hidden = true; });
    point.addEventListener('focus', () => showTooltip(row, outcome, null, point));
    point.addEventListener('blur', () => { $('note-map-tooltip').hidden = true; });
    point.addEventListener('click', () => {
      const id = String(row.note.id);
      selectedIds = selectedIds.includes(id)
        ? selectedIds.filter((selected) => selected !== id)
        : [...selectedIds.slice(-1), id];
      syncSelection();
      renderSelection(plotted);
      $('note-map-tooltip').hidden = true;
    });
    points.append(point);
  });
  $('note-map-tooltip').hidden = true;
  syncSelection();
  renderSelection(plotted);
  const standouts = cohort?.[lens]?.standouts ?? 0;
  summary.textContent = `${standouts} of ${plotted.length} Notes exceeded both benchmarks. Select one to inspect its wording and results.`;
}

export function renderNotesMap(state) {
  snapshot = state;
  renderPlot();
}

export function setNoteMapQuery(value) {
  const nextQuery = value.toLowerCase().trim();
  if (query === nextQuery) return;
  query = nextQuery;
  renderPlot();
}

export function setupNotesMap(retry) {
  $('note-map-retry').addEventListener('click', retry);
  $('note-map-lenses').addEventListener('click', (event) => {
    const selected = event.target.closest('[data-map-lens]')?.dataset.mapLens;
    if (!selected || !lenses[selected]) return;
    lens = selected;
    renderPlot();
  });
}
