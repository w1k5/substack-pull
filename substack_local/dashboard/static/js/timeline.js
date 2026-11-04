import { $, fmt, date } from './shared.js';
import { publicationEventList } from './publication-events.js';

let currentData;
let navigateTo;

export function renderPublicationTimeline(data, navigate) {
  currentData = data;
  navigateTo = navigate;
  drawChart(data.series);
}

const CHART_LEFT = 58,
  DAY_MS = 86400000;
let chartWidth = 1000;
let chartRight = 990;
const parseDay = (value) => Date.parse(`${String(value).replaceAll('/', '-')}T12:00:00Z`);
const weekly = () => Number(currentData?.range?.days) > 90;
function chartX(value) {
  const start = parseDay(currentData.range.start),
    end = parseDay(currentData.range.end);
  return CHART_LEFT + ((parseDay(value) - start) / Math.max(DAY_MS, end - start))
    * (chartRight - CHART_LEFT);
}
function isPartialLast(series) {
  const daysSinceStart = (parseDay(currentData.range.end) - parseDay(series.at(-1)?.[0])) / DAY_MS;
  return daysSinceStart >= 0 && daysSinceStart < (weekly() ? 7 : 1);
}
function drawAxis() {
  const axis = $('chart-axis');
  axis.replaceChildren();
  const start = parseDay(currentData.range.start), end = parseDay(currentData.range.end);
  for (let i = 0; i < 5; i++) {
    const label = document.createElement('span');
    label.textContent = new Intl.DateTimeFormat('en-US', {
      month: 'short', day: 'numeric',
      ...(i === 0 || i === 4 ? { year: 'numeric' } : {}),
      timeZone: 'UTC',
    }).format(new Date(start + (end - start) * i / 4));
    axis.append(label);
  }
}
function drawChart(series) {
  const svg = $('chart');
  chartWidth = Math.max(280, Math.round(svg.getBoundingClientRect().width));
  chartRight = chartWidth - 10;
  svg.setAttribute('viewBox', `0 0 ${chartWidth} 240`);
  svg.replaceChildren();
  svg.onpointermove = null;
  svg.onpointerleave = null;
  const points = series || [];
  const isWeekly = weekly();
  const partial = points.length > 0 && isPartialLast(points);
  const complete = partial ? points.slice(0, -1) : points;
  const values = complete.map((point) => Number(point[1]) || 0);
  $('chart-hover').hidden = true;
  const partialLabel = $('chart-partial');
  partialLabel.hidden = !partial;
  if (partial) partialLabel.textContent =
    `${isWeekly ? 'This week' : 'Today'} so far: ${fmt(points.at(-1)[1])} views · shown separately until the period ends`;
  svg.setAttribute('aria-label',
    `${isWeekly ? 'Weekly' : 'Daily'} publication views with post and Note publication markers${partial ? '; current period shown separately' : ''}`);
  drawAxis();
  if (!values.length) {
    const empty = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    empty.setAttribute('x', chartWidth / 2);
    empty.setAttribute('y', '120');
    empty.setAttribute('text-anchor', 'middle');
    empty.setAttribute('class', 'timeline-empty');
    empty.textContent = 'No complete view periods are available yet';
    svg.append(empty);
    drawPublicationEvents(points);
    return;
  }
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
    line.setAttribute('x2', chartRight);
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
  const pts = complete.map(([day, value]) => [
    chartX(day), bottom - ((Number(value) || 0) / max) * (bottom - top),
  ]);
  const area = document.createElementNS(ns, 'path');
  area.setAttribute(
    'd',
    `M ${pts[0][0]} ${bottom} L ${pts.map((p) => p.join(' ')).join(' L ')} L ${pts.at(-1)[0]} ${bottom} Z`,
  );
  area.setAttribute('class', 'timeline-area');
  svg.append(area);
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', `M ${pts.map((p) => p.join(' ')).join(' L ')}`);
  path.setAttribute('class', 'timeline-actual');
  svg.append(path);
  installChartHover(svg, complete, pts, bottom);
  drawPublicationEvents(points);
}
function installChartHover(svg, series, pts, bottom) {
  const ns = 'http://www.w3.org/2000/svg';
  const guide = document.createElementNS(ns, 'line');
  guide.setAttribute('class', 'timeline-hover-guide');
  guide.setAttribute('y1', 12);
  guide.setAttribute('y2', bottom);
  const dot = document.createElementNS(ns, 'circle');
  dot.setAttribute('class', 'timeline-hover-dot');
  dot.setAttribute('r', 4);
  svg.append(guide, dot);
  const tooltip = $('chart-hover');
  const hide = () => {
    guide.classList.remove('is-active');
    dot.classList.remove('is-active');
    tooltip.hidden = true;
  };
  svg.onpointerleave = hide;
  svg.onpointermove = (event) => {
    if (event.target.closest('.event-marker')) {
      hide();
      return;
    }
    const bounds = svg.getBoundingClientRect();
    const x = ((event.clientX - bounds.left) / bounds.width) * chartWidth;
    const y = ((event.clientY - bounds.top) / bounds.height) * 240;
    const spacing = pts.length > 1 ? (pts[1][0] - pts[0][0]) / 2 : 16;
    if (y < 12 || y > bottom || x < pts[0][0] - spacing || x > pts.at(-1)[0] + spacing) {
      hide();
      return;
    }
    let nearest = 0;
    for (let i = 1; i < pts.length; i++) {
      if (Math.abs(pts[i][0] - x) < Math.abs(pts[nearest][0] - x)) nearest = i;
    }
    const [pointX, pointY] = pts[nearest];
    guide.setAttribute('x1', pointX);
    guide.setAttribute('x2', pointX);
    dot.setAttribute('cx', pointX);
    dot.setAttribute('cy', pointY);
    guide.classList.add('is-active');
    dot.classList.add('is-active');
    $('chart-hover-value').textContent = `${fmt(series[nearest][1])} views`;
    $('chart-hover-date').textContent =
      `${weekly() ? 'Week of ' : ''}${date(series[nearest][0].replaceAll('/', '-'))}`;
    tooltip.hidden = false;
    const cursorX = event.clientX - bounds.left,
      cursorY = event.clientY - bounds.top,
      labelWidth = tooltip.offsetWidth;
    tooltip.style.left = `${Math.max(4, Math.min(bounds.width - labelWidth - 4, cursorX - labelWidth / 2))}px`;
    tooltip.style.top = `${cursorY < 30 ? cursorY + 12 : cursorY - 24}px`;
  };
}
function drawPublicationEvents(series) {
  const events = currentData?.publication_events || [];
  if (!events.length || !series?.length) return;
  const ns = 'http://www.w3.org/2000/svg',
    svg = $('chart');
  const byDay = new Map();
  events.forEach((event) => {
    if (!byDay.has(event.day)) byDay.set(event.day, []);
    byDay.get(event.day).push(event);
  });
  [...byDay]
    .sort(([a], [b]) => a.localeCompare(b))
    .forEach(([day, items]) => {
      const x = chartX(day);
      if (x < CHART_LEFT || x > chartRight) return;
      const hasPost = items.some((item) => item.type === 'text'),
        hasNote = items.some((item) => item.type === 'note'),
        postCount = items.filter((item) => item.type === 'text').length,
        noteCount = items.filter((item) => item.type === 'note').length,
        group = document.createElementNS(ns, 'g');
      group.setAttribute('tabindex', '0');
      group.setAttribute('role', 'button');
      group.setAttribute(
        'aria-label',
        `${date(day)}: ${postCount} ${postCount === 1 ? 'post' : 'posts'} and ` +
        `${noteCount} ${noteCount === 1 ? 'Note' : 'Notes'}. Show events`,
      );
      group.setAttribute('class', 'event-marker');
      if (hasPost) {
        const line = document.createElementNS(ns, 'line');
        line.setAttribute('x1', x);
        line.setAttribute('x2', x);
        line.setAttribute('y1', 18);
        line.setAttribute('y2', 218);
        line.setAttribute('class', 'post-event-line');
        group.append(line);
      }
      for (const [present, y, radius, className] of [
        [hasPost, 213, 6, 'post-event-dot'],
        [hasNote, 230, 4, 'note-event-dot'],
      ]) {
        if (!present) continue;
        const marker = document.createElementNS(ns, 'circle');
        marker.setAttribute('cx', x);
        marker.setAttribute('cy', y);
        marker.setAttribute('r', radius);
        marker.setAttribute('class', className);
        group.append(marker);
      }
      const hit = document.createElementNS(ns, 'rect');
      hit.setAttribute('x', x - 7);
      hit.setAttribute('y', hasPost ? 202 : 218);
      hit.setAttribute('width', 14);
      hit.setAttribute('height', hasPost ? 36 : 20);
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
  const isWeekly = weekly();
  const point = series.find(([start]) => {
    const elapsed = parseDay(day) - parseDay(start);
    return elapsed >= 0 && elapsed < (isWeekly ? 7 * DAY_MS : DAY_MS);
  });
  if (point) {
    const views = document.createElement('span');
    views.className = 'event-views';
    const partial = point === series.at(-1) && isPartialLast(series);
    views.textContent = isWeekly
      ? `${fmt(point[1])} views ${partial ? 'this week so far' : `in the week of ${date(point[0].replaceAll('/', '-'))}`}`
      : `${fmt(point[1])} views ${partial ? 'so far today' : 'that day'}`;
    root.append(views);
  }
  root.append(publicationEventList(items, navigateTo));
  const caveat = document.createElement('p');
  caveat.className = 'footnote';
  caveat.textContent = 'Views here cover the whole publication. Open a piece to see its own performance.';
  root.append(caveat);
}
