import { fmt, pct, number, loadingIndicator } from './common.js';

function noteComparison(actual, average) {
  const a = number(actual),
    b = number(average);
  if (a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b) || b <= 0) return '—';
  const ratio = a / b;
  return ratio >= 3
    ? `${ratio.toFixed(1)}× avg`
    : `${a >= b ? '+' : ''}${Math.round((ratio - 1) * 100)}% vs avg`;
}
function noteComparisonAt(stats) {
  const actual = stats.impression_series?.find((series) => series.is_primary)?.points || [];
  const typical = stats.impression_series?.find((series) => !series.is_primary)?.points || [];
  const first = Date.parse(actual[0]?.timestamp),
    last = Date.parse(actual.at(-1)?.timestamp);
  const age =
    Number.isFinite(first) && Number.isFinite(last)
      ? `${Math.round((last - first) / 3600000)}h`
      : 'same age';
  return { actual: actual.at(-1)?.value, typical: typical.at(-1)?.value, age };
}

function noteReachCard(stats) {
  const card = document.createElement('div');
  card.className = 'note-reach-card';
  const matched = noteComparisonAt(stats);
  const heading = document.createElement('div');
  heading.className = 'note-reach-heading';
  const title = document.createElement('strong');
  title.textContent = 'Note reach';
  heading.append(title);
  card.append(heading);
  const profileVisits = stats.interactions?.items?.find(
    (item) => item.title === 'Profile visit',
  )?.value;
  const metrics = document.createElement('div');
  metrics.className = 'note-reach-metrics';
  for (const [label, value, context] of [
    ['Impressions', fmt(stats.impressions), 'Total to date'],
    [
      `Pace at ${matched.age}`,
      noteComparison(matched.actual, matched.typical),
      `${fmt(matched.actual)} impressions · avg ${fmt(matched.typical)}`,
    ],
    ['Profile visits', fmt(profileVisits), 'From this Note'],
  ]) {
    const item = document.createElement('div');
    const name = document.createElement('span');
    name.textContent = label;
    const amount = document.createElement('strong');
    amount.textContent = value;
    const detail = document.createElement('small');
    detail.textContent = context;
    item.append(name, amount, detail);
    metrics.append(item);
  }
  card.append(metrics);
  const breakdown = document.createElement('div');
  breakdown.className = 'note-reach-breakdown';
  for (const [label, items] of [
    ['Seen in', stats.surfaces],
    ['Seen by', stats.audience],
  ]) {
    const group = document.createElement('div');
    const h = document.createElement('strong');
    h.textContent = label;
    group.append(h);
    (items || [])
      .filter((item) => Number(item.value) > 0)
      .slice(0, 3)
      .forEach((item) => {
        const row = document.createElement('div');
        row.className = 'note-reach-row';
        const name = document.createElement('span');
        name.textContent = item.title;
        const bar = document.createElement('i');
        bar.style.width = `${Math.max(0, Math.min(100, Number(item.percent || 0) * 100))}%`;
        const value = document.createElement('b');
        value.textContent = pct(item.percent);
        row.append(name, bar, value);
        group.append(row);
      });
    breakdown.append(group);
  }
  card.append(breakdown);
  const actions = (stats.interactions?.items || [])
    .filter((item) => Number(item.value) > 0 && item.title !== 'Profile visit')
    .map((item) => {
      const title = item.title.toLowerCase(),
        plural = title === 'reply' ? 'replies' : `${title}s`;
      return `${fmt(item.value)} ${Number(item.value) === 1 ? title : plural}`;
    });
  const foot = document.createElement('p');
  foot.className = 'note-reach-foot';
  foot.textContent = `${actions.join(' · ') || 'No recorded interactions'} · Impressions and unique audience use different totals.`;
  card.append(foot);
  if (stats.permalink) {
    const link = document.createElement('a');
    link.href = stats.permalink + '/stats';
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Open Note stats ↗';
    card.append(link);
  }
  return card;
}
const noteStatsRequests = new Map();
function loadNoteStats(id) {
  if (!noteStatsRequests.has(id)) {
    const request = fetch(`/api/note/${encodeURIComponent(id)}`, { cache: 'no-store' })
      .then(async (response) => {
        const stats = await response.json();
        if (!response.ok) throw new Error(stats.error || 'Could not load Note stats');
        return stats;
      })
      .catch((error) => {
        noteStatsRequests.delete(id);
        throw error;
      });
    noteStatsRequests.set(id, request);
  }
  return noteStatsRequests.get(id);
}
export function attachNoteInspectors(list, notes, activity) {
  const slot = document.createElement('div');
  slot.className = 'note-reach-slot';
  activity.append(slot);
  const buttons = [];
  [...list.children].forEach((li, index) => {
    const note = notes[index];
    if (note.type && note.type !== 'note') return;
    if (!String(note.id || '').match(/^\d+$/)) return;
    const id = String(note.id);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'note-inspect';
    button.textContent = 'Loading reach…';
    button.setAttribute('aria-label', `View reach for ${note.title}`);
    li.append(button);
    buttons.push(button);
    loadNoteStats(id)
      .then((stats) => {
        const matched = noteComparisonAt(stats);
        if (button.isConnected)
          button.textContent = `${fmt(stats.impressions)} total · ${noteComparison(matched.actual, matched.typical)} at ${matched.age}`;
      })
      .catch(() => {
        if (button.isConnected) button.textContent = 'Reach unavailable · retry';
      });
    button.addEventListener('click', async () => {
      list
        .querySelectorAll('.note-inspect')
        .forEach((b) => b.setAttribute('aria-pressed', String(b === button)));
      slot.replaceChildren(loadingIndicator('Loading Note reach…'));
      try {
        const stats = await loadNoteStats(id);
        if (activity.contains(slot) && button.getAttribute('aria-pressed') === 'true')
          slot.replaceChildren(noteReachCard(stats));
      } catch (error) {
        if (activity.contains(slot) && button.getAttribute('aria-pressed') === 'true') {
          const message = document.createElement('p');
          message.className = 'detail-empty';
          message.textContent = `Could not load Note reach: ${error.message}`;
          slot.replaceChildren(message);
        }
      }
    });
  });
  return buttons;
}

export function clearNoteStatsRequests() {
  noteStatsRequests.clear();
}
