import { $, date, fmt } from './shared.js';
import { publicationEventList } from './publication-events.js';
import { sourceLabel } from './source-labels.js';

const COLORS = ['#295847', '#c07a35', '#647ca9', '#a26983', '#668a70',
  '#a26938', '#547e8a', '#8670a5', '#8a9250', '#a25d5d'];
const TOP = 12, BOTTOM = 215;
let data;
let navigateTo;
let selected = new Set();
let rangeKey = '';

const svgElement = (name, attrs = {}) => {
  const element = document.createElementNS('http://www.w3.org/2000/svg', name);
  Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
};
const dayTime = (day) => Date.parse(`${day}T12:00:00Z`);
const formatDate = (day) => date(day);

function ceiling(value) {
  if (!value) return 1;
  const unit = 10 ** Math.floor(Math.log10(value / 4));
  return (Math.ceil(value / (unit * 4)) * unit) * 4;
}

function renderChoices(lines) {
  const root = $('source-trend-choices');
  root.replaceChildren();
  lines.forEach((line, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'segment source-trend-choice';
    const active = selected.has(line.key);
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
    const lastSelected = active && selected.size === 1;
    button.disabled = lastSelected || (!active && selected.size >= 5);
    const label = sourceLabel(line.name, 'growth');
    button.title = lastSelected ? 'Keep at least one source selected'
      : button.disabled ? 'Choose up to five sources at a time' : label.detail;
    const swatch = document.createElement('i');
    swatch.style.backgroundColor = COLORS[index % COLORS.length];
    button.append(swatch, document.createTextNode(label.name));
    button.addEventListener('click', () => {
      if (active) {
        if (selected.size === 1) return;
        selected.delete(line.key);
      } else selected.add(line.key);
      renderChart();
    });
    root.append(button);
  });
  $('source-trend-selection-help').textContent = selected.size >= 5
    ? 'Five sources selected. Remove one to compare another. The vertical scale stays fixed.'
    : 'Keep at least one source selected; compare up to five. The vertical scale stays fixed.';
}

function showSourcePublicationEvents(index, items, kind, days, weekly, marker) {
  const root = $('source-trend-event-detail');
  root.hidden = false;
  root.replaceChildren();
  const heading = document.createElement('strong');
  heading.textContent = `${weekly ? 'Week of ' : ''}${formatDate(days[index])} · ${kind === 'note' ? 'Notes' : 'Posts'} published`;
  root.append(heading, publicationEventList(items, navigateTo, weekly));
  const caveat = document.createElement('p');
  caveat.className = 'footnote';
  caveat.textContent = 'Source counts cover the publication. Open a piece to see its own performance.';
  root.append(caveat);
  $('source-trend-chart').querySelectorAll('.source-trend-event-marker').forEach((item) =>
    item.classList.toggle('selected', item === marker));
  root.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function renderChart() {
  const lines = data?.subscriber_source_series || [];
  renderChoices(lines);
  const chart = $('source-trend-chart');
  chart.replaceChildren();
  const width = Math.max(320, chart.getBoundingClientRect().width);
  const left = width < 500 ? 43 : 62;
  const right = width - (width < 500 ? 10 : 24);
  chart.setAttribute('viewBox', `0 0 ${width} 265`);
  const hover = $('source-trend-hover');
  hover.hidden = true;
  $('source-trend-event-detail').hidden = true;
  chart.onpointermove = null;
  chart.onpointerleave = null;
  const error = data?.subscriber_source_series_error;
  const active = lines.filter((line) => selected.has(line.key));
  $('source-trend-empty').hidden = !!active.length && !error;
  $('source-trend-empty').textContent = error
    || 'No subscriber source history was returned for this period.';
  $('source-trend-visual').hidden = !active.length || !!error;
  if (!active.length || error) return;

  const days = [...new Set(lines.flatMap((line) => line.points.map((point) => point[0])))].sort();
  if (!days.length) {
    $('source-trend-visual').hidden = true;
    $('source-trend-empty').hidden = false;
    $('source-trend-empty').textContent = 'No dated subscriber source history was returned.';
    return;
  }
  const weekly = data.range.days > 90;
  const series = active.map((line) => ({
    line,
    values: new Map(line.points.map(([day, value]) => [day, Number(value) || 0])),
    color: COLORS[lines.indexOf(line) % COLORS.length],
  }));
  const maxValue = Math.max(0, ...lines.flatMap((line) =>
    line.points.map(([, value]) => Number(value) || 0)));
  const max = ceiling(Math.max(4, maxValue));
  const x = (index) => left + (right - left) * index / Math.max(1, days.length - 1);
  const y = (value) => BOTTOM - (BOTTOM - TOP) * value / max;

  for (let i = 0; i <= 4; i++) {
    const value = max * i / 4, yy = y(value);
    chart.append(svgElement('line', { x1: left, x2: right, y1: yy, y2: yy,
      class: 'source-trend-grid' }));
    const label = svgElement('text', { x: left - 12, y: yy + 4,
      'text-anchor': 'end', class: 'source-trend-tick' });
    label.textContent = fmt(value);
    chart.append(label);
  }
  const eventDays = new Map();
  (data.publication_events || []).forEach((event) => {
    const index = weekly
      ? days.findLastIndex((day) => dayTime(day) <= dayTime(event.day))
      : days.indexOf(event.day);
    if (index < 0) return;
    const bucket = eventDays.get(index) || { notes: [], posts: [] };
    if (event.type === 'note') bucket.notes.push(event);
    if (event.type === 'text') bucket.posts.push(event);
    eventDays.set(index, bucket);
  });
  for (const [index, events] of eventDays) {
    for (const [kind, items] of [['post', events.posts], ['note', events.notes]]) {
      if (!items.length) continue;
      const marker = svgElement('g', {
        class: 'source-trend-event-marker', role: 'button', tabindex: '0',
        'aria-label': `${weekly ? 'Week of ' : ''}${formatDate(days[index])}: ${items.length} ${kind === 'note' ? 'Note' : 'post'}${items.length === 1 ? '' : 's'} published. Open pieces`,
      });
      marker.append(kind === 'post'
        ? svgElement('rect', { x: x(index) - 3, y: 234, width: 6, height: 6, rx: 1,
          class: 'source-trend-post-event' })
        : svgElement('circle', { cx: x(index), cy: 250, r: 3,
          class: 'source-trend-note-event' }));
      marker.append(svgElement('rect', { x: x(index) - 7,
        y: kind === 'post' ? 227 : 243, width: 14, height: 14, fill: 'transparent' }));
      const title = svgElement('title');
      title.textContent = marker.getAttribute('aria-label');
      marker.append(title);
      const select = () => showSourcePublicationEvents(index, items, kind, days, weekly, marker);
      marker.addEventListener('click', select);
      marker.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          select();
        }
      });
      chart.append(marker);
    }
  }
  for (const item of series) {
    const points = days.map((day, index) => [x(index), y(item.values.get(day) || 0)]);
    const complete = points.length > 1 ? points.slice(0, -1) : points;
    chart.append(svgElement('path', {
      d: `M ${complete.map((point) => point.join(' ')).join(' L ')}`,
      fill: 'none', stroke: item.color, 'stroke-width': 2.5,
      'stroke-linecap': 'round', 'stroke-linejoin': 'round',
      class: 'source-trend-line',
    }));
    if (points.length > 1) {
      chart.append(svgElement('line', {
        x1: points.at(-2)[0], y1: points.at(-2)[1],
        x2: points.at(-1)[0], y2: points.at(-1)[1],
        stroke: item.color, 'stroke-width': 2.5,
        'stroke-dasharray': '4 5', class: 'source-trend-line',
      }));
    }
    chart.append(svgElement('circle', {
      cx: points.at(-1)[0], cy: points.at(-1)[1], r: 3.5,
      fill: '#fff', stroke: item.color, 'stroke-width': 2,
      class: 'source-trend-line',
    }));
  }
  const guide = svgElement('line', { y1: TOP, y2: BOTTOM,
    class: 'source-trend-guide' });
  chart.append(guide);
  const dots = series.map((item) => {
    const dot = svgElement('circle', { r: 4, fill: item.color,
      class: 'source-trend-hover-dot' });
    chart.append(dot);
    return dot;
  });
  const axis = $('source-trend-axis');
  axis.replaceChildren();
  axis.style.paddingLeft = `${100 * left / width}%`;
  axis.style.paddingRight = `${100 * (width - right) / width}%`;
  for (const index of [...new Set([0, Math.floor((days.length - 1) / 3),
    Math.floor(2 * (days.length - 1) / 3), days.length - 1])]) {
    const tick = document.createElement('span');
    tick.textContent = formatDate(days[index]);
    axis.append(tick);
  }
  $('source-trend-unit').textContent = weekly
    ? 'Per-source subscribers · weekly' : 'Per-source subscribers · daily';
  $('source-trend-partial').textContent = weekly
    ? 'Dashed end = this week so far' : 'Dashed end = today so far';

  const hide = () => {
    guide.classList.remove('visible');
    dots.forEach((dot) => dot.classList.remove('visible'));
    hover.hidden = true;
  };
  chart.onpointerleave = hide;
  chart.onpointermove = (event) => {
    const bounds = chart.getBoundingClientRect();
    const cursorX = (event.clientX - bounds.left) / bounds.width * width;
    const cursorY = (event.clientY - bounds.top) / bounds.height * 265;
    if (cursorX < left || cursorX > right || cursorY < TOP || cursorY > BOTTOM) {
      hide();
      return;
    }
    const index = Math.max(0, Math.min(days.length - 1,
      Math.round((cursorX - left) / (right - left) * (days.length - 1))));
    const day = days[index];
    guide.setAttribute('x1', x(index));
    guide.setAttribute('x2', x(index));
    guide.classList.add('visible');
    dots.forEach((dot, dotIndex) => {
      dot.setAttribute('cx', x(index));
      dot.setAttribute('cy', y(series[dotIndex].values.get(day) || 0));
      dot.classList.add('visible');
    });
    const title = document.createElement('strong');
    title.textContent = `${weekly ? 'Week of ' : ''}${formatDate(day)}${index === days.length - 1 ? ' · so far' : ''}`;
    const rows = series.map((item) => {
      const row = document.createElement('span');
      const swatch = document.createElement('i');
      swatch.style.backgroundColor = item.color;
      row.append(swatch, document.createTextNode(sourceLabel(item.line.name, 'growth').name));
      const value = document.createElement('b');
      value.textContent = fmt(item.values.get(day) || 0);
      row.append(value);
      return row;
    });
    const events = eventDays.get(index);
    const eventLabel = document.createElement('small');
    if (events) eventLabel.textContent = [
      events.posts.length ? `${events.posts.length} ${events.posts.length === 1 ? 'post' : 'posts'}` : '',
      events.notes.length ? `${events.notes.length} ${events.notes.length === 1 ? 'Note' : 'Notes'}` : '',
    ].filter(Boolean).join(' · ') + ' published';
    hover.replaceChildren(title, ...rows, eventLabel);
    eventLabel.hidden = !events;
    hover.hidden = false;
    const cursorPx = event.clientX - bounds.left;
    const tooltipWidth = hover.offsetWidth;
    hover.style.left = `${Math.max(4, Math.min(bounds.width - tooltipWidth - 4, cursorPx + 14))}px`;
    hover.style.top = `${Math.max(4, (event.clientY - bounds.top) - hover.offsetHeight - 8)}px`;
  };
}

export function renderSubscriberSourceTrend(nextData, navigate) {
  data = nextData;
  navigateTo = navigate;
  const nextRange = `${data.range.start}:${data.range.end}`;
  const lines = data.subscriber_source_series || [];
  const retained = lines.filter((line) => selected.has(line.key));
  if (nextRange !== rangeKey || !retained.length) {
    selected = new Set((retained.length ? retained : lines.slice(0, 3)).map((line) => line.key));
    rangeKey = nextRange;
  }
  renderChart();
}
