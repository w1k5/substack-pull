import { $, date, fmt, pct, loadingIndicator } from '../shared.js';

const MIN_FIRST_WEEK_VIEWS = 100;
const MIN_LIFETIME_VIEWS = 1000;
const MODES = {
  staying: {
    description: 'See which posts kept finding readers after launch day.',
    yTitle: 'Days 2–7 share of first-week views',
    window: 'Same 7-day window',
    footnote: 'Days 2–7 share is views after day one divided by first-week views. Posts need seven complete days and at least 100 first-week views. Views are not unique readers.',
    value: (row) => row.later_week_share,
    format: pct,
  },
  yield: {
    description: 'See which posts turned first-week attention into new subscribers.',
    yTitle: 'Signups per 1,000 first-week views',
    window: 'Same 7-day window',
    footnote: 'Signup yield is first-week signups per 1,000 first-week views. Posts need seven complete days and at least 100 first-week views. Attribution is directional; views are not unique readers.',
    value: (row) => 1000 * row.signups / row.views,
    format: (value) => value.toFixed(1),
  },
  sharing: {
    description: 'Find the writing readers chose to pass along.',
    yTitle: 'Shares per 1,000 lifetime views',
    window: 'Lifetime totals',
    footnote: 'Sharing rate is Substack-recorded shares per 1,000 lifetime views. Posts need at least 1,000 lifetime views. Published at different times, these posts have had different exposure windows.',
    value: (row) => row.share_rate,
    format: (value) => value.toFixed(1),
  },
  tail: {
    description: 'Find posts that continued to draw views after their first week.',
    yTitle: 'Views after first week · log scale',
    window: 'Unequal later windows',
    footnote: 'Later views are lifetime views minus first-week views. Older posts have had more time to accumulate them, so compare publication dates before drawing conclusions. Views are not unique readers.',
    value: (row) => row.later_views,
    format: fmt,
  },
};

let mode = 'staying';
let selectedIds = [];
let snapshot;
const xValue = (row) => mode === 'sharing' ? Number(row.lifetime_views) : row.views;
const xTitle = () => mode === 'sharing' ? 'Lifetime views · log scale' : 'First-week views · log scale';
const minViews = () => mode === 'sharing' ? MIN_LIFETIME_VIEWS : MIN_FIRST_WEEK_VIEWS;

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function niceCeiling(value) {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const unit = value / magnitude;
  return (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10) * magnitude;
}

function guide(root, axis, position, label, medianLine = false) {
  const line = document.createElement('i');
  line.className = `post-map-guide ${axis}${medianLine ? ' median' : ''}`;
  line.style[axis === 'vertical' ? 'left' : 'top'] = `${position}%`;
  root.append(line);
  if (label == null) return;
  const tick = document.createElement('span');
  tick.className = `post-map-tick ${axis}`;
  tick.style[axis === 'vertical' ? 'left' : 'top'] = `${position}%`;
  tick.textContent = label;
  root.append(tick);
}

function yScale(values) {
  if (mode === 'staying') return {
    position: (value) => 95 - 90 * value, ticks: [0, .5, 1],
    label: (value) => `${Math.round(value * 100)}%`,
  };
  if (mode === 'tail') {
    const positive = values.filter((value) => value > 0);
    const floor = positive.length ? Math.max(0, Math.floor(Math.log10(Math.min(...positive))) - .25) : 0;
    const ceiling = Math.max(floor + 1, Math.ceil(Math.log10(1 + Math.max(...values))) + .1);
    const ticks = [];
    for (let power = Math.ceil(floor); power <= Math.floor(ceiling); power++) {
      ticks.push(10 ** power);
    }
    if (values.includes(0)) ticks.unshift(0);
    return {
      position: (value) => value === 0 ? 95
        : 95 - 90 * (Math.log10(1 + value) - floor) / (ceiling - floor),
      ticks,
      label: fmt,
    };
  }
  const ceiling = niceCeiling(Math.max(...values) * 1.08);
  return {
    position: (value) => 95 - 90 * value / ceiling,
    ticks: [0, ceiling / 2, ceiling],
    label: (value) => Number(value.toFixed(1)).toLocaleString(),
  };
}

function showTooltip(row, event, point) {
  const tooltip = $('post-map-tooltip');
  tooltip.replaceChildren();
  const title = document.createElement('strong');
  title.textContent = row.title;
  const detail = document.createElement('span');
  const suffix = mode === 'staying' ? 'after day one' : mode === 'yield' ? 'signups / 1k'
    : mode === 'sharing' ? 'shares / 1k' : 'later views';
  detail.textContent = `${fmt(xValue(row))} ${mode === 'sharing' ? 'lifetime' : 'first-week'} views · ${MODES[mode].format(MODES[mode].value(row))} ${suffix}`;
  const published = document.createElement('small');
  published.textContent = `Published ${date(row.date)}`;
  tooltip.append(title, detail, published);
  tooltip.hidden = false;
  const rect = $('post-map-plot').getBoundingClientRect();
  const anchor = event?.clientX == null ? point.getBoundingClientRect() : { left: event.clientX, top: event.clientY };
  tooltip.style.left = `${Math.max(8, Math.min(rect.width - 225, anchor.left - rect.left + 12))}px`;
  tooltip.style.top = `${Math.max(8, anchor.top - rect.top - 76)}px`;
}

function card(row, medianViews) {
  const root = document.createElement('div');
  root.className = 'post-map-card';
  const heading = document.createElement('div');
  const title = document.createElement('strong');
  title.textContent = row.title;
  const published = document.createElement('small');
  published.textContent = date(row.date);
  heading.append(title, published);
  const metrics = document.createElement('div');
  metrics.className = 'post-map-card-metrics';
  const common = [[fmt(xValue(row)), `${(xValue(row) / medianViews).toFixed(1)}× median ${mode === 'sharing' ? 'lifetime' : 'first-week'} reach`]];
  const details = mode === 'staying' ? [
    [fmt(row.launch_views), 'day-one views'],
    [fmt(row.later_week_views), 'views on days 2–7'],
    [pct(row.later_week_share), 'first-week views after day one'],
  ] : mode === 'yield' ? [
    [fmt(row.signups), 'first-week signups'],
    [MODES.yield.format(MODES.yield.value(row)), 'signups per 1,000 views'],
    [pct(row.later_week_share), 'views after day one'],
  ] : mode === 'sharing' ? [
    [fmt(row.lifetime_shares), 'recorded shares'],
    [MODES.sharing.format(row.share_rate), 'shares per 1,000 views'],
    [fmt(row.views), 'first-week views'],
  ] : [
    [fmt(row.later_views), 'views after week one'],
    [`${row.later_multiple.toFixed(1)}×`, 'later / first week'],
    [fmt(row.lifetime_views), 'lifetime views'],
  ];
  for (const [value, label] of [...common, ...details]) {
    const item = document.createElement('span');
    const amount = document.createElement('b');
    amount.textContent = value;
    const caption = document.createElement('small');
    caption.textContent = label;
    item.append(amount, caption);
    metrics.append(item);
  }
  const open = document.createElement('a');
  open.href = `/posts/${encodeURIComponent(row.id)}`;
  open.dataset.route = '';
  open.textContent = 'Open post story →';
  root.append(heading, metrics, open);
  return root;
}

function renderSelection(rows, medianViews) {
  const root = $('post-map-comparison');
  root.replaceChildren();
  const selected = selectedIds.map((id) => rows.find((row) => row.id === id)).filter(Boolean);
  if (!selected.length) {
    root.textContent = 'Select a dot to inspect a post; select a second to compare them.';
    return;
  }
  const heading = document.createElement('div');
  heading.className = 'post-map-selection-heading';
  const label = document.createElement('strong');
  label.textContent = selected.length === 1 ? 'Selected post' : 'Side by side';
  const clear = document.createElement('button');
  clear.type = 'button';
  clear.className = 'refresh';
  clear.textContent = 'Clear selection';
  clear.addEventListener('click', () => { selectedIds = []; renderPostPortfolio(snapshot); });
  heading.append(label, clear);
  const cards = document.createElement('div');
  cards.className = 'post-map-cards';
  selected.forEach((row) => cards.append(card(row, medianViews)));
  root.append(heading, cards);
  if (selected.length === 1) {
    const hint = document.createElement('p');
    hint.textContent = 'Select one more dot to compare these posts.';
    root.append(hint);
  }
}

function renderInsight(rows) {
  const root = $('post-map-later');
  root.replaceChildren();
  if (!rows.length) { root.hidden = true; return; }
  const label = document.createElement('strong');
  const text = document.createElement('span');
  if (mode === 'staying') {
    const sustained = rows.filter((row) => row.later_week_share >= .5).length;
    label.textContent = 'After launch day';
    text.textContent = `${sustained} of ${rows.length} shown posts received at least half their first-week views on days 2–7. Their reach continued beyond launch day.`;
  } else if (mode === 'yield') {
    const growing = rows.filter((row) => row.signups > 0).length;
    label.textContent = 'Reader growth';
    text.textContent = `${growing} of ${rows.length} shown posts brought in at least one signup during week one. Compare rates alongside the underlying counts.`;
  } else if (mode === 'sharing') {
    label.textContent = 'Reader sharing';
    text.textContent = `The median shown post earned ${median(rows.map((row) => row.share_rate)).toFixed(1)} recorded shares per 1,000 lifetime views. Open high-rate posts to inspect their distribution.`;
  } else {
    const delayed = [...rows].sort((a, b) => b.later_multiple - a.later_multiple)[0];
    label.textContent = 'Later discovery';
    text.textContent = `${delayed.title} has ${fmt(delayed.later_views)} views after its first week, ${delayed.later_multiple.toFixed(1)}× its first-week total. Publication dates matter here.`;
  }
  root.append(label, text);
  root.hidden = false;
}

export function renderPostPortfolio(state) {
  snapshot = state;
  const { data, error, loading, visibleIds } = state;
  const panel = $('post-map');
  const status = $('post-map-status');
  const key = $('post-map-key');
  const loadingRoot = $('post-map-loading');
  const retry = $('post-map-retry');
  const visual = $('post-map-visual');
  const comparison = $('post-map-comparison');
  const definition = MODES[mode];
  panel.setAttribute('aria-busy', String(loading));
  $('post-map-description').textContent = definition.description;
  $('post-map-eyebrow').textContent = mode === 'staying' || mode === 'yield'
    ? 'FIRST-WEEK COMPARISON' : 'LIFETIME COMPARISON';
  $('post-map-y-title').textContent = definition.yTitle;
  $('post-map-x-title').textContent = xTitle();
  $('post-map-window').textContent = definition.window;
  $('post-map-footnote').textContent = definition.footnote;
  document.querySelectorAll('[data-post-map]').forEach((button) => {
    const active = button.dataset.postMap === mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  loadingRoot.replaceChildren();
  if (loading) loadingRoot.append(loadingIndicator('Comparing post outcomes…'));
  retry.hidden = !error;
  visual.hidden = true;
  key.hidden = true;
  $('post-map-later').hidden = true;
  comparison.replaceChildren();
  if (error) { status.textContent = `Comparison unavailable: ${error}`; return; }
  if (!data) {
    status.textContent = loading ? 'Loading completed first-week results…' : 'Open Posts to load the comparison.';
    return;
  }
  const groups = new Map();
  for (const row of data.rows || []) {
    const group = `${row.post_type}|${row.audience}`;
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(row);
  }
  const cohort = [...groups.values()].sort((a, b) => b.length - a.length)[0] || [];
  const eligible = cohort.filter((row) => Number.isFinite(xValue(row)) && xValue(row) >= minViews()
    && Number.isFinite(definition.value(row)) && definition.value(row) >= 0);
  const visible = eligible.filter((row) => visibleIds.has(String(row.id)));
  const otherTypes = (data.rows || []).length - cohort.length;
  status.textContent = `${eligible.length} of ${cohort.length} comparable posts meet this view’s sample rule${visible.length < eligible.length ? ` · ${visible.length} shown` : ''}${otherTypes ? ` · ${otherTypes} other post types` : ''}${data.incomplete ? ` · ${data.incomplete} too new` : ''}${data.unavailable ? ` · ${data.unavailable} unavailable` : ''}${data.total > data.considered ? ` · latest ${data.considered} of ${data.total} considered` : ''}.`;
  if (eligible.length < 3) {
    comparison.textContent = `At least three comparable posts with ${fmt(minViews())} ${mode === 'sharing' ? 'lifetime' : 'first-week'} views are needed for this view.`;
    return;
  }
  if (!visible.length) {
    comparison.textContent = 'No comparable posts match the current search or filters.';
    return;
  }
  visual.hidden = false;
  const medianViews = median(eligible.map(xValue));
  const medianOutcome = median(eligible.map(definition.value));
  const metric = mode === 'staying' ? 'views after day one' : mode === 'yield'
    ? 'signups / 1k views' : mode === 'sharing' ? 'shares / 1k views' : 'later views';
  key.textContent = `Cohort medians (dashed): ${fmt(medianViews)} ${mode === 'sharing' ? 'lifetime' : 'first-week'} views · ${definition.format(medianOutcome)} ${metric}.${mode === 'tail' || mode === 'sharing' ? ' Check publication dates.' : ' Amber dots clear both.'}`;
  key.hidden = false;
  const minLog = Math.floor(Math.log10(Math.min(...eligible.map(xValue)))) - .15;
  const maxLog = Math.ceil(Math.log10(Math.max(...eligible.map(xValue)))) + .15;
  const x = (value) => 100 * (Math.log10(value) - minLog) / (maxLog - minLog);
  const y = yScale(eligible.map(definition.value));
  const grid = $('post-map-grid');
  const points = $('post-map-points');
  grid.replaceChildren();
  points.replaceChildren();
  for (let power = Math.ceil(minLog); power <= Math.floor(maxLog); power++) {
    const value = 10 ** power;
    guide(grid, 'vertical', x(value), fmt(value));
  }
  guide(grid, 'vertical', x(medianViews), null, true);
  y.ticks.forEach((value) => guide(grid, 'horizontal', y.position(value), y.label(value)));
  guide(grid, 'horizontal', y.position(medianOutcome), null, true);
  selectedIds = selectedIds.filter((id) => visible.some((row) => row.id === id));
  visible.forEach((row) => {
    const outcome = definition.value(row);
    const point = document.createElement('button');
    point.type = 'button';
    point.className = 'post-map-point';
    if (mode !== 'tail' && mode !== 'sharing' && xValue(row) >= medianViews && outcome >= medianOutcome) point.classList.add('standout');
    if (selectedIds.includes(row.id)) point.classList.add('selected');
    point.style.left = `${x(xValue(row))}%`;
    point.style.top = `${y.position(outcome)}%`;
    point.setAttribute('aria-label', `${row.title}: ${fmt(xValue(row))} ${mode === 'sharing' ? 'lifetime' : 'first-week'} views, ${definition.format(outcome)} ${definition.yTitle.toLowerCase()}`);
    point.setAttribute('aria-pressed', String(selectedIds.includes(row.id)));
    point.addEventListener('pointermove', (event) => showTooltip(row, event, point));
    point.addEventListener('pointerenter', (event) => showTooltip(row, event, point));
    point.addEventListener('pointerleave', () => { $('post-map-tooltip').hidden = true; });
    point.addEventListener('focus', () => showTooltip(row, null, point));
    point.addEventListener('blur', () => { $('post-map-tooltip').hidden = true; });
    point.addEventListener('click', () => {
      selectedIds = selectedIds.includes(row.id)
        ? selectedIds.filter((id) => id !== row.id)
        : [...selectedIds.slice(-1), row.id];
      renderPostPortfolio(snapshot);
    });
    points.append(point);
  });
  $('post-map-tooltip').hidden = true;
  renderInsight(visible);
  renderSelection(visible, medianViews);
}

export function setupPostPortfolio() {
  $('post-map-lenses').addEventListener('click', (event) => {
    const selected = event.target.closest('[data-post-map]')?.dataset.postMap;
    if (!selected || !MODES[selected] || selected === mode) return;
    mode = selected;
    if (snapshot) renderPostPortfolio(snapshot);
  });
}
