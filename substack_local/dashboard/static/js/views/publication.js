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
  if (briefing.notes_share > 0) {
    showCallout(
      'briefing-insight', 'A PATH TO NEW READERS',
      `${fmt(briefing.notes_attributed)} subscribers were attributed to Notes`,
      `${pct(briefing.notes_share)} of new subscribers in this period. Attribution describes a channel, not which individual Note caused a signup.`,
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
  if (data.briefing?.substack_share != null) {
    showCallout(
      'discovery-insight', 'SUBSCRIBER ATTRIBUTION',
      `${pct(data.briefing.substack_share)} of new subscribers were credited to Substack`,
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
