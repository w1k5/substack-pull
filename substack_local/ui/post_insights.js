import { fmt, pct, section } from './common.js';

function progressRow(label, count, total, note) {
  const row = document.createElement('div');
  row.className = 'journey-row';
  const head = document.createElement('div');
  head.className = 'journey-row-head';
  const name = document.createElement('span');
  name.textContent = label;
  const amount = document.createElement('strong');
  amount.textContent = fmt(count);
  head.append(name, amount);
  const track = document.createElement('div');
  track.className = 'journey-track';
  const fill = document.createElement('div');
  fill.className = 'journey-fill';
  fill.style.width = `${Math.max(0, Math.min(100, total ? (100 * Number(count || 0)) / total : 0))}%`;
  track.append(fill);
  const caption = document.createElement('small');
  caption.textContent = note;
  row.append(head, track, caption);
  return row;
}
export function renderPostInsights(post) {
  const root = document.createDocumentFragment(),
    reach = post.reach || {},
    engagement = post.engagement || {},
    growth = post.growth || {},
    traffic = post.traffic || {};
  const sources = (traffic.referrers || [])
    .filter((row) => Number(row.views) > 0)
    .sort(
      (a, b) =>
        Number(b.signups || 0) +
          Number(b.subscribes || 0) -
          Number(a.signups || 0) -
          Number(a.subscribes || 0) || Number(b.views || 0) - Number(a.views || 0),
    );
  if (sources.length) {
    const panel = section('Where the subscribers came from');
    panel.classList.add('source-story');
    const context = document.createElement('p');
    context.className = 'detail-context';
    context.textContent = 'Lifetime view share beside share of source-attributed subscribers';
    panel.append(context);
    const attributed = sources.reduce(
      (sum, row) => sum + Number(row.signups || 0) + Number(row.subscribes || 0),
      0,
    );
    const leading = sources.filter((row) => Number(row.views) >= 20).slice(0, 5);
    if (!leading.length) leading.push(...sources.slice(0, 5));
    const smaller = sources.filter((row) => !leading.includes(row));
    const makeList = (rows) => {
      const list = document.createElement('div');
      list.className = 'source-compare-list';
      rows.forEach((row) => {
        const subs = Number(row.signups || 0) + Number(row.subscribes || 0),
          viewShare = Number(row.percent_of_total_views || 0),
          signupShare = attributed ? subs / attributed : 0;
        const item = document.createElement('div');
        item.className = 'source-compare-row';
        const heading = document.createElement('div');
        heading.className = 'source-compare-heading';
        const name = document.createElement('strong');
        name.textContent = row.source || 'Unknown';
        const counts = document.createElement('small');
        counts.textContent = `${fmt(row.views)} views · ${fmt(subs)} subscribers`;
        heading.append(name, counts);
        item.append(heading);
        for (const [label, share, kind] of [
          ['Views', viewShare, 'view'],
          ['Subscribers', signupShare, 'signup'],
        ]) {
          const lane = document.createElement('div');
          lane.className = `compare-lane ${kind}`;
          const title = document.createElement('span');
          title.textContent = label;
          const track = document.createElement('div');
          track.className = 'compare-track';
          const fill = document.createElement('div');
          fill.className = 'compare-fill';
          fill.style.width = `${Math.max(0, Math.min(100, share * 100))}%`;
          track.append(fill);
          const amount = document.createElement('b');
          amount.textContent = pct(share);
          lane.append(title, track, amount);
          item.append(lane);
        }
        list.append(item);
      });
      return list;
    };
    panel.append(makeList(leading));
    if (smaller.length) {
      const more = document.createElement('details');
      more.className = 'detail-more';
      const summary = document.createElement('summary');
      summary.textContent = `Show ${smaller.length} smaller sources`;
      more.append(summary, makeList(smaller));
      panel.append(more);
    }
    const foot = document.createElement('p');
    foot.className = 'footnote';
    foot.textContent = `${fmt(attributed)} signups have source attribution. Shares are directional; the visit credited with a signup can differ from its counted view.`;
    panel.append(foot);
    root.append(panel);
  }
  const depth = engagement.scroll_depth?.full_post || engagement.scroll_depth?.preview,
    previewOnly = !engagement.scroll_depth?.full_post && !!engagement.scroll_depth?.preview;
  if (reach.sent != null || depth?.readers) {
    const panel = section('What readers did next');
    const grid = document.createElement('div');
    grid.className = 'journey-grid';
    if (reach.sent != null) {
      const email = document.createElement('div');
      email.className = 'journey-card';
      const h = document.createElement('h4');
      h.textContent = 'Email journey';
      const sub = document.createElement('p');
      sub.textContent = `Sent to ${fmt(reach.sent)} recipients`;
      email.append(h, sub);
      email.append(
        progressRow(
          'Delivered',
          reach.delivered,
          Number(reach.sent),
          `${pct(Number(reach.sent) ? Number(reach.delivered) / Number(reach.sent) : null)} of recipients`,
        ),
      );
      email.append(
        progressRow(
          'Opened',
          reach.opened,
          Number(reach.sent),
          `${pct(reach.open_rate)} open rate · typical ${pct(post.comps?.avg_open_rate)}`,
        ),
      );
      email.append(
        progressRow(
          'Clicked',
          reach.clicked,
          Number(reach.sent),
          `${pct(reach.click_through_rate)} of openers · typical ${pct(post.comps?.avg_click_through_rate)}`,
        ),
      );
      grid.append(email);
    }
    if (depth?.readers) {
      const reading = document.createElement('div');
      reading.className = 'journey-card';
      const h = document.createElement('h4');
      h.textContent = 'Reading depth';
      const sub = document.createElement('p');
      sub.textContent = `${fmt(depth.readers)} measured${previewOnly ? ' in preview' : ''} · ${pct(depth.avg_scroll_depth)} average depth`;
      reading.append(h, sub);
      for (const [label, key] of [
        ['25%', 'reached_25'],
        ['50%', 'reached_50'],
        ['75%', 'reached_75'],
        ['End', 'reached_100'],
      ])
        reading.append(
          progressRow(
            label,
            depth[key],
            Number(depth.readers),
            `${pct(Number(depth.readers) ? Number(depth[key] || 0) / Number(depth.readers) : null)} of measured readers`,
          ),
        );
      grid.append(reading);
    }
    panel.append(grid);
    const note = document.createElement('p');
    note.className = 'footnote';
    note.textContent =
      'Email recipients and on-page readers are separate groups; the two tracks are not one funnel.';
    panel.append(note);
    const devices = traffic.devices || [];
    if (devices.length) {
      const more = document.createElement('details');
      more.className = 'detail-more';
      const summary = document.createElement('summary');
      summary.textContent = 'Where people read';
      more.append(summary);
      const total = devices.reduce((sum, row) => sum + Number(row.views || 0), 0);
      const list = document.createElement('div');
      list.className = 'device-list';
      devices.forEach((row) =>
        list.append(
          progressRow(
            row.device_type || 'Unknown',
            row.views,
            total,
            pct(total ? Number(row.views || 0) / total : null),
          ),
        ),
      );
      more.append(list);
      panel.append(more);
    }
    root.append(panel);
  }
  if (engagement.likes != null || engagement.comments != null || reach.shares != null) {
    const panel = section('Reader response');
    const row = document.createElement('div');
    row.className = 'response-grid';
    for (const [label, count, detail] of [
      ['Likes', engagement.likes, null],
      [
        'Comments',
        engagement.comments,
        engagement.commenters == null ? null : `${fmt(engagement.commenters)} commenters`,
      ],
      ['Shares', reach.shares, null],
    ]) {
      if (count == null) continue;
      const card = document.createElement('div');
      const name = document.createElement('span');
      name.textContent = label;
      const value = document.createElement('strong');
      value.textContent = fmt(count);
      const note = document.createElement('small');
      note.textContent =
        detail ||
        `${reach.views ? Math.round((1000 * Number(count)) / Number(reach.views)) : '—'} per 1k views`;
      card.append(name, value, note);
      row.append(card);
    }
    panel.append(row);
    if (Number(growth.subscribes || 0) || Number(growth.unsubscribes || 0)) {
      const note = document.createElement('p');
      note.className = 'footnote';
      note.textContent = `Lifetime: ${fmt(growth.subscribes)} paid subscriptions · ${fmt(growth.unsubscribes)} unsubscribes`;
      panel.append(note);
    }
    root.append(panel);
  }
  return root;
}
