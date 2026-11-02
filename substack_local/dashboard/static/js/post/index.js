import { $, fmt, pct, date, cell, number, section, loadingIndicator } from '../shared.js';
import { renderPostTrajectory } from './trajectory.js';
import { renderPostInsights } from './insights.js';
export { clearNoteStatsRequests } from './notes.js';

function detailTable(headers, rows) {
  const wrap = document.createElement('div');
  wrap.className = 'table-scroll';
  const table = document.createElement('table');
  const head = document.createElement('thead');
  const hr = document.createElement('tr');
  headers.forEach((h) => {
    const th = document.createElement('th');
    th.textContent = h;
    hr.append(th);
  });
  head.append(hr);
  table.append(head);
  const body = document.createElement('tbody');
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    row.forEach((value) => cell(tr, value));
    body.append(tr);
  });
  table.append(body);
  wrap.append(table);
  return wrap;
}
function comparison(actual, average) {
  const a = number(actual),
    b = number(average);
  if (a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b) || b <= 0) return '—';
  const ratio = a / b;
  return ratio >= 3
    ? `${ratio.toFixed(1)}× typical`
    : `${a >= b ? '+' : ''}${Math.round((ratio - 1) * 100)}%`;
}

function linkLabel(value) {
  const label = String(value);
  if (label.startsWith('/i/')) return 'Image opened';
  if (label.startsWith('/comment')) return 'Comment section';
  return label;
}

function renderPostDetail(post) {
  $('detail-title').textContent = post.title;
  $('detail-meta').textContent =
    `Published ${date(post.date)} · compared with ${fmt(post.comps.n_comp_posts)} similar posts`;
  const root = $('detail-content');
  root.replaceChildren();
  const daily = [...(post.first_week || [])].sort((a, b) => Number(a.day_n) - Number(b.day_n));
  const now = new Date(),
    today = [
      now.getFullYear(),
      String(now.getMonth() + 1).padStart(2, '0'),
      String(now.getDate()).padStart(2, '0'),
    ].join('-');
  const complete = daily.filter((d) => !d.dt || d.dt.slice(0, 10) !== today);
  const latest = complete.at(-1) || daily.at(-1);
  if (latest) {
    const day = Number(latest.day_n) + 1,
      partial = !complete.length && daily.length > 0;
    const views = number(latest.cumulative_views),
      typicalViews = number(latest.comps?.avg_cumulative_views);
    const signups = number(latest.cumulative_signups),
      typicalSignups = number(latest.comps?.avg_cumulative_signups);
    const rate = views > 0 && signups != null ? (signups / views) * 1000 : null,
      typicalRate =
        typicalViews > 0 && typicalSignups != null ? (typicalSignups / typicalViews) * 1000 : null;
    const hasPartial = complete.length < daily.length;
    const panel = section('Performance over time');
    panel.classList.add('performance-story');
    const label = document.createElement('p');
    label.className = 'detail-context';
    label.textContent = `${partial ? 'Current day' : 'Last complete day'}: day ${day} of 7${hasPartial ? ' · current partial day shown below but excluded from this summary' : ''}`;
    panel.append(label);
    const summary = document.createElement('div');
    summary.className = 'performance-summary';
    const statement = (name, value, context) => {
      const item = document.createElement('div');
      const heading = document.createElement('span');
      heading.textContent = name;
      const amount = document.createElement('strong');
      amount.textContent = value;
      const note = document.createElement('small');
      note.textContent = context;
      item.append(heading, amount, note);
      summary.append(item);
    };
    statement('Views', fmt(views), `${comparison(views, typicalViews)} at the same age`);
    statement(
      'Free signups',
      fmt(signups),
      `${comparison(signups, typicalSignups)} at the same age`,
    );
    statement(
      'Signup yield',
      rate == null ? '—' : `${rate.toFixed(1)} / 1k views`,
      `${comparison(rate, typicalRate)} at the same age`,
    );
    panel.append(summary);
    if (daily.length > 1) panel.append(renderPostTrajectory(daily, post.notes || []));
    root.append(panel);
  } else {
    const p = document.createElement('p');
    p.className = 'detail-empty';
    p.textContent = 'Age-matched daily data is unavailable for this post.';
    root.append(p);
  }
  root.append(renderPostInsights(post));
  const clicks = (post.links || [])
    .filter((r) => Array.isArray(r) && r.length >= 2)
    .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0));
  if (clicks.length) {
    const details = document.createElement('details');
    details.className = 'click-details';
    const summary = document.createElement('summary');
    summary.textContent = 'Reader actions and link clicks';
    details.append(
      summary,
      detailTable(
        ['Link or action', 'Clicks'],
        clicks.map((r) => [linkLabel(r[0]), fmt(r[1])]),
      ),
    );
    if (post.has_more_links) {
      const p = document.createElement('p');
      p.className = 'footnote';
      p.textContent = 'Only the first set of links was returned.';
      details.append(p);
    }
    root.append(details);
  }
}
let detailRequest = 0;

export async function showPost(row, publication) {
  const request = ++detailRequest;
  const panel = $('post-detail');
  panel.hidden = false;
  panel.setAttribute('aria-busy', 'true');
  $('detail-title').textContent = row.title;
  $('detail-meta').textContent = '';
  $('detail-open').href = `${publication}/publish/posts/detail/${encodeURIComponent(row.id)}`;
  $('detail-content').replaceChildren(loadingIndicator('Loading post details…'));
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  try {
    const response = await fetch(`/api/post/${encodeURIComponent(row.id)}`, { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not load post');
    if (request === detailRequest) renderPostDetail(payload);
  } catch (error) {
    if (request === detailRequest) {
      $('detail-content').replaceChildren();
      $('detail-meta').textContent = `Could not load details: ${error.message}`;
    }
  } finally {
    if (request === detailRequest) panel.setAttribute('aria-busy', 'false');
  }
}
$('detail-close').addEventListener('click', () => {
  detailRequest++;
  $('post-detail').hidden = true;
});
