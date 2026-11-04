import { $, fmt, pct, date, emptyMessage } from '../shared.js';
import { renderPublicationTimeline } from '../timeline.js';
import { sourceLabel } from '../source-labels.js';

function showCallout(id, label, headline, detail, path, action) {
  const root = $(id);
  root.replaceChildren();
  const copy = document.createElement('div');
  const kicker = document.createElement('span');
  kicker.className = 'insight-label';
  kicker.textContent = label;
  const title = document.createElement('strong');
  title.textContent = headline;
  const description = document.createElement('p');
  description.textContent = detail;
  copy.append(kicker, title, description);
  root.append(copy);
  if (path) {
    const link = document.createElement('a');
    link.href = path;
    link.dataset.route = '';
    link.textContent = action || 'Explore →';
    root.append(link);
  }
}

function priorDelta(current, previous, days) {
  if (current == null || previous == null) return 'Previous period unavailable';
  if (Number(previous) === 0) return Number(current) ? 'New compared with prior period' : 'No change';
  const delta = ((Number(current) - Number(previous)) / Number(previous)) * 100;
  return `${delta > 0 ? '+' : ''}${delta.toFixed(1)}% vs previous ${days} days · ${fmt(previous)} before`;
}

export function renderBriefing(data, navigate) {
  const totals = data.totals || {}, previous = data.previous?.totals || {};
  for (const key of ['views', 'visitors', 'subscribers']) {
    $(key).textContent = fmt(totals[key]);
    $(`${key}-delta`).textContent = priorDelta(totals[key], previous[key], data.range.days);
  }
  $('briefing-period').textContent =
    `${date(data.range.start)} – ${date(data.range.end)} · compared with the preceding ${data.range.days} days · today may be incomplete`;
  const notes = (data.growth_sources || []).find(
    (source) => source.parent === 'Substack' && source.name === 'Notes',
  );
  if (notes && Number(notes.subscribers) > 0 && Number(totals.subscribers) > 0) {
    const share = Number(notes.subscribers) / Number(totals.subscribers);
    showCallout(
      'briefing-insight', 'A PATH TO NEW READERS',
      `${fmt(notes.subscribers)} subscribers were attributed to Notes`,
      `${pct(share)} of new subscribers in this period. Attribution describes a channel, not which individual Note caused a signup.`,
      '/notes', 'Explore Notes →',
    );
  } else {
    showCallout(
      'briefing-insight', 'START HERE', 'Trace the change in your publication',
      'Select a post or Note marker below, then inspect where readers came from and what they did next.',
      '/discovery', 'Explore discovery →',
    );
  }
  $('period').textContent = `${data.range.days > 90 ? 'Weekly' : 'Daily'} totals`;
  $('event-detail').hidden = true;
  renderPublicationTimeline(data, navigate);
}

export function renderDiscoveryInsight(data) {
  const ecosystem = (data.growth_sources || []).find(
    (source) => source.name === 'Substack' && !source.parent,
  );
  const total = Number(data.totals?.subscribers || 0);
  if (ecosystem && total) {
    showCallout(
      'discovery-insight', 'SUBSCRIBER ATTRIBUTION',
      `${pct(Number(ecosystem.subscribers || 0) / total)} of new subscribers were credited to Substack`,
      'This parent source includes Notes and other Substack surfaces. Its children are a breakdown, not additional subscribers.',
    );
  } else {
    showCallout(
      'discovery-insight', 'TWO LENSES', 'Compare discovery with traffic',
      'Subscriber attribution and traffic referrers use different definitions, so their counts do not form a single funnel.',
    );
  }
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
