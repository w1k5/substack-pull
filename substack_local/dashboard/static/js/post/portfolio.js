import { $, date, fmt, pct, loadingIndicator } from '../shared.js';

const MIN_FIRST_WEEK_VIEWS = 100;
const MIN_LIFETIME_VIEWS = 1000;
const RESPONSE_MODES = ['likes', 'comments', 'restacks'];
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
    value: (row) => row.signup_yield,
    format: (value) => value.toFixed(1),
  },
  sharing: {
    description: 'Compare Substack-recorded share actions relative to post reach.',
    yTitle: 'Share actions per 1,000 lifetime views',
    window: 'Lifetime totals',
    footnote: 'Share actions are a separate Substack metric from restacks. Rates use lifetime views; posts need at least 1,000 views. Publication dates and exposure windows differ.',
    value: (row) => row.share_rate,
    format: (value) => value.toFixed(1),
  },
  ...Object.fromEntries(RESPONSE_MODES.map((name) => [name, {
    description: `Compare ${name} relative to post reach. Select dots to inspect the underlying counts.`,
    yTitle: `${name[0].toUpperCase()}${name.slice(1)} per 1,000 lifetime views`,
    window: 'Lifetime totals',
    footnote: `${name[0].toUpperCase()}${name.slice(1)} are lifetime totals per 1,000 lifetime views. Posts need at least 1,000 views. These counts include different exposure windows; views are not unique readers.`,
    value: (row) => row[`${name}_rate`],
    format: (value) => value.toFixed(1),
  }])),
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
const lifetimeMode = () => mode === 'sharing' || RESPONSE_MODES.includes(mode);
const xValue = (row) => lifetimeMode() ? Number(row.lifetime_views) : row.views;
const xTitle = () => lifetimeMode() ? 'Lifetime views · log scale' : 'First-week views · log scale';
const minViews = () => lifetimeMode() ? MIN_LIFETIME_VIEWS : MIN_FIRST_WEEK_VIEWS;
const medianOutcome = (value) => mode === 'staying' ? `later share · ${pct(value)}`
  : mode === 'yield' ? `signup yield · ${value.toFixed(1)} / 1k views`
    : mode === 'sharing' ? `share actions · ${value.toFixed(1)} / 1k views`
      : RESPONSE_MODES.includes(mode) ? `${mode} · ${value.toFixed(1)} / 1k views`
        : `later views · ${fmt(value)}`;

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
    : mode === 'sharing' ? 'share actions / 1k' : RESPONSE_MODES.includes(mode) ? `${mode} / 1k` : 'later views';
  detail.textContent = `${fmt(xValue(row))} ${lifetimeMode() ? 'lifetime' : 'first-week'} views · ${MODES[mode].format(MODES[mode].value(row))} ${suffix}`;
  const published = document.createElement('small');
  published.textContent = `Published ${date(row.date)}`;
  tooltip.append(title, detail, published);
  tooltip.hidden = false;
  const rect = $('post-map-plot').getBoundingClientRect();
  const anchor = event?.clientX == null ? point.getBoundingClientRect() : { left: event.clientX, top: event.clientY };
  tooltip.style.left = `${Math.max(8, Math.min(rect.width - 225, anchor.left - rect.left + 12))}px`;
  tooltip.style.top = `${Math.max(8, anchor.top - rect.top - 76)}px`;
}

function card(row, comparison) {
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
  const common = [[fmt(xValue(row)), `${lifetimeMode() ? 'lifetime' : 'first-week'} views · ${comparison.reach_multiple[String(row.id)].toFixed(1)}× median`]];
  const details = mode === 'staying' ? [
    [fmt(row.launch_views), 'day-one views'],
    [fmt(row.later_week_views), 'views on days 2–7'],
    [pct(row.later_week_share), 'first-week views after day one'],
  ] : mode === 'yield' ? [
    [fmt(row.signups), 'first-week signups'],
    [MODES.yield.format(MODES.yield.value(row)), 'signups per 1,000 views'],
    [pct(row.later_week_share), 'views after day one'],
  ] : mode === 'sharing' ? [
    [fmt(row.lifetime_shares), 'share actions'],
    [MODES.sharing.format(row.share_rate), 'share actions per 1,000 views'],
    [fmt(row.views), 'first-week views'],
  ] : RESPONSE_MODES.includes(mode) ? [
    [fmt(row[`lifetime_${mode}`]), mode],
    [MODES[mode].format(MODES[mode].value(row)), `${mode} per 1,000 views`],
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
  if (RESPONSE_MODES.includes(mode)) {
    const related = document.createElement('small');
    related.className = 'post-map-related';
    related.textContent = ['likes', 'comments', 'restacks']
      .filter((name) => name !== mode)
      .map((name) => `${fmt(row[`lifetime_${name}`])} ${name}`)
      .join(' · ');
    root.insertBefore(related, open);
  }
  return root;
}

function compactCard(row, comparison) {
  const root = document.createElement('div');
  root.className = 'post-map-mini';
  const title = document.createElement('a');
  title.href = `/posts/${encodeURIComponent(row.id)}`;
  title.dataset.route = '';
  title.textContent = row.title;
  const context = document.createElement('small');
  context.textContent = `${date(row.date)} · ${comparison.reach_multiple[String(row.id)].toFixed(1)}× median reach`;
  const metrics = document.createElement('div');
  metrics.className = 'post-map-mini-metrics';
  const count = mode === 'staying' ? row.later_week_views : mode === 'yield' ? row.signups
    : mode === 'sharing' ? row.lifetime_shares : mode === 'tail' ? row.later_views
      : row[`lifetime_${mode}`];
  const countLabel = mode === 'staying' || mode === 'tail' ? 'Later views'
    : mode === 'yield' ? 'Signups' : mode === 'sharing' ? 'Shares' : mode;
  const outcome = mode === 'tail' ? `${row.later_multiple.toFixed(1)}×`
    : MODES[mode].format(MODES[mode].value(row));
  for (const [value, label] of [
    [fmt(xValue(row)), lifetimeMode() ? 'Views' : 'Week 1 views'],
    [fmt(count), countLabel],
    [outcome, mode === 'staying' ? 'Later share' : mode === 'tail' ? 'Later / week 1' : 'Per 1k views'],
  ]) {
    const item = document.createElement('span');
    const amount = document.createElement('b');
    amount.textContent = value;
    const caption = document.createElement('small');
    caption.textContent = label;
    item.append(amount, caption);
    metrics.append(item);
  }
  root.append(title, context, metrics);
  return root;
}

function renderSelection(rows, comparison) {
  const root = $('post-map-comparison');
  root.replaceChildren();
  const selected = selectedIds.map((id) => rows.find((row) => row.id === id)).filter(Boolean);
  if (!selected.length) {
    const heading = document.createElement('strong');
    heading.textContent = 'Read the map';
    const guide = document.createElement('p');
    guide.textContent = 'Farther right means more views. Higher means more of the outcome on the vertical axis. Dashed lines mark cohort medians.';
    const action = document.createElement('p');
    action.textContent = 'Choose a dot to inspect its counts, then a second to compare posts.';
    root.append(heading, guide, action);
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
  selected.forEach((row) => cards.append(selected.length === 2
    ? compactCard(row, comparison) : card(row, comparison)));
  root.append(heading, cards);
  if (selected.length === 1) {
    const hint = document.createElement('p');
    hint.textContent = 'Select one more dot to compare these posts.';
    root.append(hint);
  }
}

export function renderPostPortfolio(state) {
  snapshot = state;
  const { data, error, loading, visibleIds } = state;
  const panel = $('post-map');
  const status = $('post-map-status');
  const key = $('post-map-key');
  const loadingRoot = $('post-map-loading');
  const retry = $('post-map-retry');
  const workspace = $('post-map-workspace');
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
  $('post-response-metrics').hidden = !RESPONSE_MODES.includes(mode);
  document.querySelectorAll('[data-post-map]').forEach((button) => {
    const active = button.dataset.postMap === mode
      || button.dataset.postMap === 'response' && RESPONSE_MODES.includes(mode);
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  document.querySelectorAll('[data-post-response]').forEach((button) => {
    const active = button.dataset.postResponse === mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  loadingRoot.replaceChildren();
  if (loading) loadingRoot.append(loadingIndicator('Comparing post outcomes…'));
  retry.hidden = !error;
  workspace.hidden = true;
  key.hidden = true;
  comparison.replaceChildren();
  if (error) { status.textContent = `Comparison unavailable: ${error}`; return; }
  if (!data) {
    status.textContent = loading ? 'Loading completed first-week results…' : 'Open Posts to load the comparison.';
    return;
  }
  const model = data.comparison;
  if (!model?.lenses?.[mode]) {
    status.textContent = 'Comparison data is unavailable. Refresh the dashboard.';
    return;
  }
  const lens = model.lenses[mode];
  const eligibleIds = new Set(lens.eligible_ids);
  const standoutIds = new Set(lens.standout_ids);
  const eligible = (data.rows || []).filter((row) => eligibleIds.has(String(row.id)));
  const visible = eligible.filter((row) => visibleIds.has(String(row.id)));
  status.textContent = `${eligible.length} of ${model.cohort_size} comparable posts have at least ${fmt(minViews())} ${lifetimeMode() ? 'lifetime' : 'first-week'} views${visible.length < eligible.length ? ` · ${visible.length} shown` : ''}${model.other_types ? ` · ${model.other_types} other post types` : ''}${data.incomplete ? ` · ${data.incomplete} too new` : ''}${data.unavailable ? ` · ${data.unavailable} unavailable` : ''}${data.total > data.considered ? ` · latest ${data.considered} of ${data.total} considered` : ''}.`;
  if (eligible.length < 3) {
    status.textContent += ' At least three are needed to draw the map.';
    return;
  }
  if (!visible.length) {
    status.textContent = 'No comparable posts match the current search or filters.';
    return;
  }
  workspace.hidden = false;
  const medianViews = lens.median_x;
  const medianY = lens.median_y;
  key.replaceChildren();
  for (const label of [
    `Median reach · ${fmt(medianViews)} ${lifetimeMode() ? 'lifetime' : 'first-week'} views`,
    `Median ${medianOutcome(medianY)}`,
    ...(['staying', 'yield'].includes(mode) ? ['Amber dots clear both medians'] : []),
  ]) {
    const item = document.createElement('span');
    item.textContent = label;
    key.append(item);
  }
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
  guide(grid, 'horizontal', y.position(medianY), null, true);
  selectedIds = selectedIds.filter((id) => visible.some((row) => row.id === id));
  visible.forEach((row) => {
    const outcome = definition.value(row);
    const point = document.createElement('button');
    point.type = 'button';
    point.className = 'post-map-point';
    if (standoutIds.has(String(row.id))) point.classList.add('standout');
    if (selectedIds.includes(row.id)) point.classList.add('selected');
    point.style.left = `${x(xValue(row))}%`;
    point.style.top = `${y.position(outcome)}%`;
    point.setAttribute('aria-label', `${row.title}: ${fmt(xValue(row))} ${lifetimeMode() ? 'lifetime' : 'first-week'} views, ${definition.format(outcome)} ${definition.yTitle.toLowerCase()}`);
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
  renderSelection(visible, lens);
}

export function setupPostPortfolio() {
  $('post-map-lenses').addEventListener('click', (event) => {
    const selected = event.target.closest('[data-post-map]')?.dataset.postMap;
    if (!selected || selected !== 'response' && !MODES[selected]) return;
    const next = selected === 'response' ? RESPONSE_MODES[0] : selected;
    if (next === mode) return;
    mode = next;
    if (snapshot) renderPostPortfolio(snapshot);
  });
  $('post-response-metrics').addEventListener('click', (event) => {
    const selected = event.target.closest('[data-post-response]')?.dataset.postResponse;
    if (!RESPONSE_MODES.includes(selected) || selected === mode) return;
    mode = selected;
    if (snapshot) renderPostPortfolio(snapshot);
  });
}
