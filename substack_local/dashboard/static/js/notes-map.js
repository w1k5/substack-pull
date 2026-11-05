import { $, date, fmt, pct } from './shared.js';

const lenses = {
  responses: {
    label: 'Reader response',
    axis: 'Responses per 1,000 impressions',
    value: (row) => row.responseRate,
    format: (value) => value.toFixed(1),
  },
  visits: {
    label: 'Profile curiosity',
    axis: 'Profile visits per 1,000 impressions',
    value: (row) => row.visitRate,
    format: (value) => value.toFixed(1),
  },
  clicks: {
    label: 'Onward clicks',
    axis: 'Link clicks per 1,000 impressions',
    value: (row) => row.clickRate,
    format: (value) => value.toFixed(1),
  },
  unconnected: {
    label: 'New audience',
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
  title.textContent = row.note.title;
  title.title = row.note.title;
  const published = document.createElement('small');
  published.textContent = `Published ${date(row.note.day)}`;
  const metrics = document.createElement('div');
  metrics.className = 'note-map-card-metrics';
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
  for (const [value, label] of items) {
    const item = document.createElement('span');
    const amount = document.createElement('b');
    amount.textContent = value;
    const caption = document.createElement('small');
    caption.textContent = label;
    item.append(amount, caption);
    metrics.append(item);
  }
  root.append(title, published, metrics);
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
    root.textContent = 'Select a dot to inspect a Note; select a second to compare them.';
    return;
  }
  const heading = document.createElement('div');
  heading.className = 'note-map-selection-heading';
  const label = document.createElement('strong');
  label.textContent = selected.length === 1 ? 'Selected Note' : 'Side by side';
  const clear = document.createElement('button');
  clear.type = 'button';
  clear.className = 'refresh';
  clear.textContent = 'Clear selection';
  clear.addEventListener('click', () => {
    selectedIds = [];
    syncSelection();
    renderSelection(rows);
  });
  heading.append(label, clear);
  const cards = document.createElement('div');
  cards.className = 'note-map-cards';
  selected.forEach((row) => cards.append(card(row)));
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
  $('note-map-progress').hidden = !loading;
  const analyze = $('note-map-analyze');
  analyze.hidden = !total || analyzed;
  analyze.disabled = loading;
  analyze.textContent = error ? 'Retry analysis' : 'Analyze Notes';
  $('note-map-retry').hidden = !failed || loading;
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
  key.textContent = `Dashed guides: 1× typical reach and this cohort’s median ${definition.label.toLowerCase()}. Green dots clear both.`;
  $('note-map-empty').hidden = !!plotted.length || loading;
  $('note-map-empty').textContent = !total
    ? 'No published Notes appear in this period. Choose a longer period.'
    : error || (!analyzed
      ? 'Analyze Notes to see how reach relates to reader outcomes.'
      : 'No measured Notes have enough data for this outcome. Try another lens or retry unavailable Notes.');
  const summary = $('note-map-summary');
  summary.hidden = plotted.length < 5;
  const searchNote = $('note-map-search-note');
  const matches = plotted.filter((row) => row.note.title.toLowerCase().includes(query));
  searchNote.textContent = query
    ? `${matches.length} of ${plotted.length} plotted Notes match “${query}”. Other Notes stay visible for context.`
    : 'Search Notes above to highlight a word or phrase here.';
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
    });
    points.append(point);
  });
  $('note-map-tooltip').hidden = true;
  syncSelection();
  renderSelection(plotted);
  const standouts = cohort?.[lens]?.standouts ?? 0;
  summary.textContent = `${standouts} of ${plotted.length} plotted Notes reached above their usual pace and above this cohort’s median ${definition.label.toLowerCase()}. Inspect their wording for ideas to test again.`;
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

export function setupNotesMap(analyze, retry) {
  $('note-map-analyze').addEventListener('click', analyze);
  $('note-map-retry').addEventListener('click', retry);
  $('note-map-lenses').addEventListener('click', (event) => {
    const selected = event.target.closest('[data-map-lens]')?.dataset.mapLens;
    if (!selected || !lenses[selected]) return;
    lens = selected;
    renderPlot();
  });
}
