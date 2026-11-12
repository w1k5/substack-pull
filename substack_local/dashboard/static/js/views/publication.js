import { $, fmt, date, emptyMessage } from '../shared.js';
import { renderPublicationTimeline } from '../timeline.js';
import { sourceLabel } from '../source-labels.js';

function priorDelta(comparison, days) {
  if (!comparison || comparison.status === 'unavailable') return 'Previous period unavailable';
  if (comparison.status === 'new') return 'New compared with prior period';
  if (comparison.status === 'unchanged') return 'No change';
  const delta = comparison.percent;
  return `${delta > 0 ? '+' : ''}${delta.toFixed(1)}% vs previous ${days} days · ${fmt(comparison.previous)} before`;
}

export function renderBriefing(data, navigate) {
  const totals = data.totals || {}, briefing = data.briefing || {};
  for (const key of ['views', 'visitors', 'subscribers']) {
    $(key).textContent = fmt(totals[key]);
    $(`${key}-delta`).textContent = priorDelta(briefing.changes?.[key], data.range.days);
  }
  $('briefing-period').textContent =
    `${date(data.range.start)} – ${date(data.range.end)} · compared with the preceding ${data.range.days} days · today may be incomplete`;
  $('period').textContent = `${data.range.days > 90 ? 'Weekly' : 'Daily'} totals`;
  $('event-detail').hidden = true;
  renderPublicationTimeline(data, navigate);
}

export function renderGrowth(data) {
  const root = $('growth-list');
  root.replaceChildren();
  const all = (data.growth_sources || []).filter((row) => Number(row.subscribers) > 0);
  const parents = all.filter((row) => !row.parent)
    .sort((a, b) => Number(b.subscribers) - Number(a.subscribers));
  const rows = parents.flatMap((parent) => [
    parent,
    ...all.filter((child) => child.parent === parent.name)
      .sort((a, b) => Number(b.subscribers) - Number(a.subscribers)),
  ]);
  if (!rows.length) {
    root.append(emptyMessage('No subscriber sources were returned for this period.'));
    return;
  }
  const max = Math.max(...rows.map((row) => Number(row.subscribers)), 1);
  rows.slice(0, 24).forEach((row) => {
    const div = document.createElement('div');
    div.className = `growth-row ${row.parent ? 'child' : ''}`;
    const left = document.createElement('div');
    const name = document.createElement('div');
    name.className = 'growth-name';
    const label = sourceLabel(row.name, 'growth', row.parent);
    name.textContent = row.parent ? `${row.parent} / ${label.name}` : label.name;
    if (label.detail) name.title = label.detail;
    const bar = document.createElement('div');
    bar.className = 'growth-bar';
    const fill = document.createElement('div');
    fill.className = 'growth-fill';
    fill.style.width = `${Math.max(1, (Number(row.subscribers) / max) * 100)}%`;
    bar.append(fill);
    left.append(name, bar);
    const amount = document.createElement('div');
    amount.className = 'growth-number';
    amount.textContent = fmt(row.subscribers);
    const small = document.createElement('small');
    small.textContent = Number(row.visitors) ? `${fmt(row.visitors)} visitors` : 'Visitors unavailable';
    amount.append(small);
    div.append(left, amount);
    root.append(div);
  });
}
