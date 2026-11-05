import { $, fmt, pct, date, cell, section, loadingIndicator } from '../shared.js';
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
function linkLabel(value) {
  const label = String(value);
  if (label.startsWith('/i/')) return 'Image opened';
  if (label.startsWith('/comment')) return 'Comment section';
  return label;
}

function renderPostDetail(post) {
  $('detail-title').textContent = post.title;
  $('detail-meta').textContent =
    `Published ${date(post.date)} · lifetime totals · compared with ${fmt(post.comps.n_comp_posts)} similar posts`;
  const root = $('detail-content');
  root.replaceChildren();
  const story = post.story || {};
  const afterWeek = story.after_week || [];
  if (afterWeek.length) {
    const panel = section('First week and later reach');
    panel.classList.add('afterlife-panel');
    const context = document.createElement('p');
    context.className = 'detail-context';
    context.textContent = 'Lifetime totals split at the end of day 7';
    panel.append(context);
    for (const item of afterWeek) {
      const row = document.createElement('div');
      row.className = 'afterlife-row';
      const heading = document.createElement('div');
      heading.className = 'afterlife-heading';
      const name = document.createElement('strong');
      name.textContent = item.name;
      const amounts = document.createElement('span');
      amounts.textContent = `${fmt(item.first)} first week · ${fmt(item.later)} later · ${fmt(item.lifetime)} lifetime`;
      heading.append(name, amounts);
      const track = document.createElement('div');
      track.className = 'afterlife-track';
      const early = document.createElement('i');
      early.className = 'afterlife-early';
      early.style.width = pct(item.first_share);
      const late = document.createElement('i');
      late.className = 'afterlife-late';
      late.style.width = pct(item.later_share);
      track.append(early, late);
      row.append(heading, track);
      panel.append(row);
    }
    const caveat = document.createElement('p');
    caveat.className = 'footnote';
    caveat.textContent = 'Later volume has no daily dates in the available post response.';
    panel.append(caveat);
    root.append(panel);
  }
  if (story.performance) {
    const performance = story.performance;
    const panel = section('Performance over time');
    panel.classList.add('performance-story');
    const label = document.createElement('p');
    label.className = 'detail-context';
    label.textContent = `${performance.current_day ? 'Current day' : 'Last complete day'}: day ${performance.day} of 7${performance.has_partial_day ? ' · current partial day shown below but excluded from this summary' : ''}`;
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
    statement('Views', fmt(performance.views), `${performance.views_vs_typical} at the same age`);
    statement(
      'Free signups',
      fmt(performance.signups),
      `${performance.signups_vs_typical} at the same age`,
    );
    statement(
      'Signup yield',
      performance.signup_yield == null ? '—' : `${performance.signup_yield.toFixed(1)} / 1k views`,
      `${performance.yield_vs_typical} at the same age`,
    );
    panel.append(summary);
    if ((post.first_week || []).length > 1) panel.append(renderPostTrajectory(post.first_week, post.notes || []));
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

export async function showPost(row, publication, force = false) {
  const request = ++detailRequest;
  const panel = $('post-detail');
  panel.hidden = false;
  panel.setAttribute('aria-busy', 'true');
  $('detail-refresh').disabled = true;
  $('detail-title').textContent = row.title;
  $('detail-meta').textContent = '';
  $('detail-open').href = `${publication}/publish/posts/detail/${encodeURIComponent(row.id)}`;
  $('detail-content').replaceChildren(loadingIndicator('Loading post details…'));
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  try {
    const response = await fetch(
      `/api/post/${encodeURIComponent(row.id)}${force ? '?refresh=1' : ''}`,
      { cache: 'no-store' },
    );
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not load post');
    if (request === detailRequest) renderPostDetail(payload);
  } catch (error) {
    if (request === detailRequest) {
      $('detail-content').replaceChildren();
      $('detail-meta').textContent = `Could not load details: ${error.message}`;
    }
  } finally {
    if (request === detailRequest) {
      panel.setAttribute('aria-busy', 'false');
      $('detail-refresh').disabled = false;
    }
  }
}
