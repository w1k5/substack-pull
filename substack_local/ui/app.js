import { $, fmt, pct, date, cell, loadingIndicator } from './common.js';
import { showPost, clearNoteStatsRequests } from './post.js';

let data;
const sortState = {
  source: { key: 'views', direction: 'desc' },
  post: { key: 'date', direction: 'desc' },
};
const sortColumns = {
  source: [
    ['name', 'Source'],
    ['views', 'Views'],
    ['users', 'Users'],
    ['subs', 'Subs'],
    ['rate', 'Subs / users'],
  ],
  post: [
    ['title', 'Post'],
    ['date', 'Date'],
    ['views', 'Views'],
    ['opens', 'Opens'],
    ['open_rate', 'Open rate'],
    ['shares', 'Shares'],
    ['signups', 'Signups'],
    ['engagement_rate', 'Engagement'],
  ],
};

const sourceSubs = (row) => Number(row.free_signups || 0) + Number(row.paid_signups || 0);
const sourceRate = (row) => (Number(row.users) > 0 ? sourceSubs(row) / Number(row.users) : null);
function sortValue(section, row, key) {
  if (section === 'source') {
    if (key === 'name') return (row.name || '').toLowerCase();
    if (key === 'subs') return sourceSubs(row);
    if (key === 'rate') return sourceRate(row);
  }
  if (section === 'post') {
    if (key === 'title') return (row.title || '').toLowerCase();
    if (key === 'date') return row.date ? new Date(row.date).getTime() : null;
  }
  return row[key] == null ? null : Number(row[key]);
}
function compareRows(section, a, b) {
  const { key, direction } = sortState[section],
    av = sortValue(section, a, key),
    bv = sortValue(section, b, key);
  if (av == null && bv == null) return 0;
  if (av == null) return 1;
  if (bv == null) return -1;
  const result = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
  return (
    result * (direction === 'asc' ? 1 : -1) ||
    String(a.name || a.title || '').localeCompare(String(b.name || b.title || ''))
  );
}
function updateSortControls(section) {
  const { key, direction } = sortState[section];
  const table = $(section === 'source' ? 'source-table' : 'post-table').closest('table');
  table.querySelectorAll('thead th').forEach((th, index) => {
    const selected = sortColumns[section][index][0] === key;
    th.setAttribute(
      'aria-sort',
      selected ? (direction === 'asc' ? 'ascending' : 'descending') : 'none',
    );
    th.querySelector('.sort-arrow').textContent = selected
      ? direction === 'asc'
        ? '↑'
        : '↓'
      : '↕';
  });
  $(section === 'source' ? 'source-sort' : 'post-sort').value = key;
  const reverse = $(section === 'source' ? 'source-direction' : 'post-direction');
  reverse.textContent = direction === 'asc' ? '↑' : '↓';
  reverse.setAttribute(
    'aria-label',
    `Reverse ${section} sort direction; currently ${direction === 'asc' ? 'ascending' : 'descending'}`,
  );
}
function setSort(section, key, toggle = false) {
  const state = sortState[section];
  if (state.key === key && toggle) state.direction = state.direction === 'asc' ? 'desc' : 'asc';
  else if (state.key !== key) {
    state.key = key;
    state.direction = ['name', 'title'].includes(key) ? 'asc' : 'desc';
  }
  updateSortControls(section);
  if (data) (section === 'source' ? renderSources : renderPosts)();
}
function setupSort(section) {
  const table = $(section === 'source' ? 'source-table' : 'post-table').closest('table');
  table.querySelectorAll('thead th').forEach((th, index) => {
    const [key, label] = sortColumns[section][index];
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'sort-header';
    button.setAttribute('aria-label', `Sort by ${label}`);
    button.append(document.createTextNode(label));
    const arrow = document.createElement('span');
    arrow.className = 'sort-arrow';
    arrow.setAttribute('aria-hidden', 'true');
    button.append(arrow);
    th.replaceChildren(button);
    button.addEventListener('click', () => setSort(section, key, true));
  });
  const select = $(section === 'source' ? 'source-sort' : 'post-sort');
  select.replaceChildren(...sortColumns[section].map(([key, label]) => new Option(label, key)));
  select.addEventListener('change', () => setSort(section, select.value));
  const reverse = document.createElement('button');
  reverse.type = 'button';
  reverse.className = 'sort-direction';
  reverse.id = `${section}-direction`;
  select.after(reverse);
  reverse.addEventListener('click', () => setSort(section, sortState[section].key, true));
  updateSortControls(section);
}

const CHART_LEFT = 58,
  CHART_RIGHT = 990;
function drawChart(series) {
  const svg = $('chart');
  svg.replaceChildren();
  const values = (series || []).map((point) => Number(point[1]) || 0);
  if (!values.length) return;
  const ns = 'http://www.w3.org/2000/svg',
    top = 12,
    bottom = 218,
    rawStep = Math.max(...values, 1) / 3;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep)),
    unit = rawStep / magnitude;
  const step = (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10) * magnitude,
    max = step * 3;
  for (let i = 0; i < 4; i++) {
    const y = bottom - ((bottom - top) * i) / 3,
      line = document.createElementNS(ns, 'line');
    line.setAttribute('x1', CHART_LEFT);
    line.setAttribute('x2', CHART_RIGHT);
    line.setAttribute('y1', y);
    line.setAttribute('y2', y);
    line.setAttribute('stroke', '#e9eee8');
    line.setAttribute('stroke-dasharray', '4 6');
    svg.append(line);
    const label = document.createElementNS(ns, 'text');
    label.setAttribute('x', CHART_LEFT - 10);
    label.setAttribute('y', y + 3);
    label.setAttribute('text-anchor', 'end');
    label.setAttribute('fill', '#809288');
    label.setAttribute('font-size', '11');
    label.textContent = new Intl.NumberFormat('en-US', {
      notation: 'compact',
      maximumFractionDigits: 1,
    }).format(step * i);
    svg.append(label);
  }
  const pts = values.map((v, i) => [
    CHART_LEFT + (i * (CHART_RIGHT - CHART_LEFT)) / Math.max(1, values.length - 1),
    bottom - (v / max) * (bottom - top),
  ]);
  const area = document.createElementNS(ns, 'path');
  area.setAttribute(
    'd',
    `M ${pts[0][0]} ${bottom} L ${pts.map((p) => p.join(' ')).join(' L ')} L ${pts.at(-1)[0]} ${bottom} Z`,
  );
  area.setAttribute('fill', '#e5efe0');
  svg.append(area);
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', `M ${pts.map((p) => p.join(' ')).join(' L ')}`);
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', '#4f8067');
  path.setAttribute('stroke-width', '3');
  path.setAttribute('vector-effect', 'non-scaling-stroke');
  svg.append(path);
  const peak = values.indexOf(Math.max(...values));
  const circle = document.createElementNS(ns, 'circle');
  circle.setAttribute('cx', pts[peak][0]);
  circle.setAttribute('cy', pts[peak][1]);
  circle.setAttribute('r', '5');
  circle.setAttribute('fill', '#315b44');
  svg.append(circle);
  const title = document.createElementNS(ns, 'title');
  title.textContent = `Peak: ${fmt(values[peak])} views on ${series[peak][0]}`;
  circle.append(title);
  drawPublicationEvents(series);
}
function drawPublicationEvents(series) {
  const events = data?.publication_events || [];
  if (!events.length || !series?.length) return;
  const ns = 'http://www.w3.org/2000/svg',
    svg = $('chart');
  const parseDay = (value) => new Date(`${value.replaceAll('/', '-')}T12:00:00`).getTime();
  const first = parseDay(series[0][0]),
    last = parseDay(series.at(-1)[0]),
    span = Math.max(1, last - first);
  const byDay = new Map();
  events.forEach((event) => {
    if (!byDay.has(event.day)) byDay.set(event.day, []);
    byDay.get(event.day).push(event);
  });
  [...byDay]
    .sort(([a], [b]) => a.localeCompare(b))
    .forEach(([day, items]) => {
      const fraction = (parseDay(day) - first) / span;
      if (fraction < 0 || fraction > 1) return;
      const x = CHART_LEFT + fraction * (CHART_RIGHT - CHART_LEFT);
      const hasPost = items.some((item) => item.type === 'text'),
        group = document.createElementNS(ns, 'g');
      group.setAttribute('tabindex', '0');
      group.setAttribute('role', 'button');
      group.setAttribute(
        'aria-label',
        `${date(day)}: ${items.filter((e) => e.type === 'text').length} posts and ${items.filter((e) => e.type === 'note').length} Notes. Show events`,
      );
      group.setAttribute('class', `event-marker ${hasPost ? 'has-post' : 'note-only'}`);
      if (hasPost) {
        const line = document.createElementNS(ns, 'line');
        line.setAttribute('x1', x);
        line.setAttribute('x2', x);
        line.setAttribute('y1', 18);
        line.setAttribute('y2', 218);
        line.setAttribute('class', 'post-event-line');
        group.append(line);
      }
      const marker = document.createElementNS(ns, 'circle');
      marker.setAttribute('cx', x);
      marker.setAttribute('cy', hasPost ? 215 : 226);
      marker.setAttribute('r', hasPost ? 6 : 4);
      marker.setAttribute('class', hasPost ? 'post-event-dot' : 'note-event-dot');
      group.append(marker);
      const hit = document.createElementNS(ns, 'rect');
      hit.setAttribute('x', x - 6);
      hit.setAttribute('y', hasPost ? 18 : 211);
      hit.setAttribute('width', 12);
      hit.setAttribute('height', hasPost ? 215 : 25);
      hit.setAttribute('fill', 'transparent');
      group.append(hit);
      const label = document.createElementNS(ns, 'title');
      label.textContent = `${date(day)} · ${items.length} publication event${items.length === 1 ? '' : 's'}`;
      group.append(label);
      const select = () => showPublicationDay(day, items, series);
      group.addEventListener('click', select);
      group.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          select();
        }
      });
      svg.append(group);
    });
}
function showPublicationDay(day, items, series) {
  const root = $('event-detail');
  root.hidden = false;
  root.replaceChildren();
  const heading = document.createElement('strong');
  heading.textContent = date(day);
  root.append(heading);
  const point = series.find((row) => row[0].replaceAll('/', '-') === day);
  if (point) {
    const views = document.createElement('span');
    views.className = 'event-views';
    views.textContent = `${fmt(point[1])} views that day`;
    root.append(views);
  }
  const list = document.createElement('ul');
  items.forEach((item) => {
    const li = document.createElement('li');
    const kind = document.createElement('span');
    kind.className = `event-kind ${item.type === 'note' ? 'note-kind' : 'post-kind'}`;
    kind.textContent = item.type === 'note' ? 'Note' : 'Post';
    const title = document.createElement('span');
    title.className = 'event-title';
    title.textContent = item.title;
    title.title = item.title;
    li.append(kind, title);
    list.append(li);
  });
  root.append(list);
  if (items.some((item) => item.type === 'note')) {
    const buttons = attachNoteInspectors(list, items, root);
    if (buttons.length === 1) buttons[0].click();
    const caveat = document.createElement('p');
    caveat.className = 'footnote';
    caveat.textContent =
      'Note impressions are separate from publication views. Shared timing does not show what drove traffic.';
    root.append(caveat);
  }
}
function renderGrowth() {
  const root = $('growth-list');
  root.replaceChildren();
  const rows = [...data.growth_sources]
    .filter((r) => Number(r.subscribers) > 0)
    .sort((a, b) => Number(b.subscribers) - Number(a.subscribers));
  const max = Math.max(...rows.map((r) => Number(r.subscribers)), 1);
  rows.slice(0, 24).forEach((r) => {
    const div = document.createElement('div');
    div.className = `growth-row ${r.parent ? 'child' : ''}`;
    const left = document.createElement('div');
    const name = document.createElement('div');
    name.className = 'growth-name';
    name.textContent = r.parent ? `${r.parent} / ${r.name}` : r.name;
    const bar = document.createElement('div');
    bar.className = 'growth-bar';
    const fill = document.createElement('div');
    fill.className = 'growth-fill';
    fill.style.width = `${Math.max(1, (Number(r.subscribers) / max) * 100)}%`;
    bar.append(fill);
    left.append(name, bar);
    const number = document.createElement('div');
    number.className = 'growth-number';
    number.textContent = fmt(r.subscribers);
    const small = document.createElement('small');
    small.textContent = Number(r.visitors) ? `${fmt(r.visitors)} visitors` : 'Visitors unavailable';
    number.append(small);
    div.append(left, number);
    root.append(div);
  });
}
function renderSources() {
  const q = $('source-search').value.toLowerCase().trim();
  const rows = data.traffic_sources
    .filter((r) => (r.name || '').toLowerCase().includes(q))
    .sort((a, b) => compareRows('source', a, b));
  const body = $('source-table');
  body.replaceChildren();
  rows.forEach((r) => {
    const tr = document.createElement('tr');
    cell(tr, r.name || 'Unknown');
    cell(tr, fmt(r.views));
    cell(tr, fmt(r.users));
    cell(tr, fmt(sourceSubs(r)));
    cell(tr, pct(sourceRate(r)));
    body.append(tr);
  });
}
function renderPosts() {
  const q = $('post-search').value.toLowerCase().trim();
  const rows = data.posts
    .filter((r) => r.title.toLowerCase().includes(q))
    .sort((a, b) => compareRows('post', a, b));
  const body = $('post-table');
  body.replaceChildren();
  rows.forEach((r) => {
    const tr = document.createElement('tr');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'post-select';
    button.textContent = r.title;
    button.addEventListener('click', () => showPost(r, data.publication));
    cell(tr, button);
    cell(tr, date(r.date));
    cell(tr, fmt(r.views));
    cell(tr, fmt(r.opens));
    cell(tr, pct(r.open_rate));
    cell(tr, fmt(r.shares));
    cell(tr, fmt(r.signups));
    cell(tr, pct(r.engagement_rate));
    body.append(tr);
  });
}

function setEmptyPanelsLoading(loading) {
  document.querySelectorAll('.metric,.trend,.two-col > .panel,.posts-panel').forEach((panel) => {
    const existing = panel.querySelector(':scope > .panel-spinner');
    if (loading && !existing) {
      const indicator = loadingIndicator('Loading…');
      indicator.classList.add('panel-spinner');
      indicator.setAttribute('role', 'presentation');
      panel.classList.add('empty-loading');
      panel.append(indicator);
    } else if (!loading) {
      existing?.remove();
      panel.classList.remove('empty-loading');
    }
  });
}

function render() {
  $('views').textContent = fmt(data.totals.views);
  $('visitors').textContent = fmt(data.totals.visitors);
  $('subscribers').textContent = fmt(data.totals.subscribers);
  $('conversion').textContent = Number(data.totals.visitors)
    ? pct(data.totals.subscribers / data.totals.visitors)
    : '—';
  $('period').textContent =
    `${date(data.range.start)} – ${date(data.range.end)} · ${data.range.days > 90 ? 'weekly' : 'daily'}`;
  $('chart').setAttribute(
    'aria-label',
    `${data.range.days > 90 ? 'Weekly' : 'Daily'} publication views with publication markers`,
  );
  $('start-date').textContent = date(data.range.start);
  $('end-date').textContent = date(data.range.end);
  $('updated').textContent =
    `Updated ${new Date(data.refreshed_at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`;
  $('event-detail').hidden = true;
  drawChart(data.series);
  renderGrowth();
  renderSources();
  renderPosts();
}
async function load(force = false) {
  if (force) clearNoteStatsRequests();
  $('refresh').disabled = true;
  $('header-spinner').hidden = false;
  setEmptyPanelsLoading(!data);
  $('overview').setAttribute('aria-busy', 'true');
  $('updated').textContent = 'Loading live data…';
  $('notice').hidden = true;
  try {
    const response = await fetch(
      `/api/dashboard?days=${$('range').value}${force ? '&refresh=1' : ''}`,
      { cache: 'no-store' },
    );
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not load analytics');
    data = payload;
    render();
  } catch (error) {
    $('notice').textContent = `Could not refresh: ${error.message}`;
    $('notice').hidden = false;
    $('updated').textContent = 'Refresh failed';
  } finally {
    $('refresh').disabled = false;
    $('header-spinner').hidden = true;
    setEmptyPanelsLoading(false);
    $('overview').setAttribute('aria-busy', 'false');
  }
}
setupSort('source');
setupSort('post');
$('range').addEventListener('change', () => load());
$('refresh').addEventListener('click', () => load(true));
$('source-search').addEventListener('input', () => data && renderSources());
$('post-search').addEventListener('input', () => data && renderPosts());
load();
