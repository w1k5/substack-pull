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
let snapshot = { rows: [], total: 0, analyzed: false, failed: 0, loading: false, cohort: null, error: '', navigate: null };

function niceCeiling(value) {
  if (!Number.isFinite(value) || value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const unit = value / magnitude;
  return (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10) * magnitude;
}

function navigateToNote(row) {
  snapshot.navigate(`/notes/${row.note.id}`);
}

function showNote(row, outcome) {
  const detail = $('note-map-detail');
  detail.replaceChildren();
  const eyebrow = document.createElement('span');
  eyebrow.className = 'eyebrow';
  eyebrow.textContent = 'SELECTED NOTE';
  const title = document.createElement('strong');
  title.textContent = row.note.title;
  const meta = document.createElement('small');
  meta.textContent = `${date(row.note.day)} · ${fmt(row.impressions)} impressions to date`;
  const pace = document.createElement('p');
  pace.textContent = `${row.pace.ratio.toFixed(2)}× usual reach at ${row.pace.age}`;
  const action = document.createElement('p');
  action.textContent = `${lenses[lens].format(outcome)} ${lenses[lens].axis.toLowerCase()}`;
  const open = document.createElement('button');
  open.type = 'button';
  open.className = 'note-map-open';
  open.textContent = 'Open Note analysis →';
  open.addEventListener('click', () => navigateToNote(row));
  detail.append(eyebrow, title, meta, pace, action, open);
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
  const plotted = rows.filter((row) => Number.isFinite(row.pace.ratio)
    && row.pace.ratio > 0 && Number.isFinite(definition.value(row)));
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
  const y = (value) => 100 * (1 - value / yMax);
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

  plotted.forEach((row) => {
    const outcome = definition.value(row);
    const point = document.createElement('button');
    point.type = 'button';
    point.className = 'note-map-point';
    if (row.pace.ratio >= 1 && outcome >= middle) point.classList.add('standout');
    if (query && !row.note.title.toLowerCase().includes(query)) point.classList.add('dimmed');
    if (location.pathname === `/notes/${row.note.id}`) point.classList.add('selected');
    point.style.left = `${x(row.pace.ratio)}%`;
    point.style.top = `${y(outcome)}%`;
    point.setAttribute('aria-label',
      `${row.note.title}: ${row.pace.ratio.toFixed(2)} times typical reach, ${definition.format(outcome)} ${definition.axis.toLowerCase()}`);
    point.title = row.note.title;
    point.addEventListener('pointerenter', () => showNote(row, outcome));
    point.addEventListener('focus', () => showNote(row, outcome));
    point.addEventListener('click', () => navigateToNote(row));
    points.append(point);
  });
  const selected = plotted.find((row) => location.pathname === `/notes/${row.note.id}`);
  if (selected) showNote(selected, definition.value(selected));
  else $('note-map-detail').textContent = 'Hover or focus a dot to see the Note. Select it to open the full analysis.';
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
