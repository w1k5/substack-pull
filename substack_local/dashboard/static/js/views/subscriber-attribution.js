import { $, fmt, pct } from '../shared.js';

function element(name, className, text) {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function renderFallback(root, data) {
  root.className = 'insight-callout';
  root.removeAttribute('aria-labelledby');
  const copy = element('div');
  copy.append(
    element('span', 'insight-label', 'SUBSCRIBER ATTRIBUTION'),
    element('strong', '', 'Where subscribers found you'),
    element('p', '', data.briefing?.substack_attributed == null
      ? 'Source attribution is unavailable for this period.'
      : `${fmt(data.briefing.substack_attributed)} subscribers were credited to Substack. Its child sources are a breakdown of that total.`),
  );
  root.append(copy);
}

function legendItem(label, count, share, kind) {
  const item = element('div', 'notes-source-legend-item');
  const heading = element('span', 'notes-source-legend-label');
  heading.append(element('i', `notes-source-swatch ${kind}`), document.createTextNode(label));
  item.append(heading, element('strong', '', `${fmt(count)} · ${pct(share)}`));
  return item;
}

function rankedItems(items, kind, heading) {
  const group = element('div', 'notes-source-ranking');
  group.append(element('h3', '', heading));
  if (!items.length) {
    group.append(element('p', 'notes-source-no-items', 'No individual links reported.'));
    return group;
  }
  const list = element('ol');
  for (const item of items) {
    const row = element('li');
    const path = item.in_dashboard ? `/${kind === 'post' ? 'posts' : 'notes'}/${item.id}` : null;
    const title = element(path ? 'a' : 'span', 'notes-source-item-title', item.preview || `${kind === 'post' ? 'Post' : 'Note'} ${item.id}`);
    if (path) {
      title.href = path;
      title.dataset.route = '';
      title.setAttribute('aria-label', `Open ${kind}: ${item.preview || item.id}`);
    }
    row.append(title, element('strong', 'notes-source-item-count', fmt(item.subscribers)));
    list.append(row);
  }
  group.append(list);
  return group;
}

export function renderDiscoveryInsight(data) {
  const root = $('discovery-insight');
  const attribution = data.notes_source_attribution;
  root.replaceChildren();
  if (attribution?.status !== 'available' || !attribution.subscribers) {
    renderFallback(root, data);
    return;
  }

  root.className = 'panel notes-source-panel';
  root.setAttribute('aria-labelledby', 'notes-source-title');
  const heading = element('div', 'panel-heading');
  const title = element('div');
  title.append(element('div', 'eyebrow', 'SUBSCRIBERS FROM NOTES'));
  const headline = {
    post: 'Most were credited to posts shared in Notes',
    note: 'Most were credited to Notes themselves',
  }[attribution.majority_link_type] || 'Which items were credited for signups?';
  const h2 = element('h2', '', headline);
  h2.id = 'notes-source-title';
  title.append(h2);
  heading.append(title, element('span', 'panel-meta', `${fmt(attribution.subscribers)} new subscribers · selected period`));

  const content = element('div', 'notes-source-content');
  const split = element('div', 'notes-source-split');
  split.append(element('p', '',
    `A post can be shared inside Notes. The bar divides those ${fmt(attribution.subscribers)} new subscribers by the item Substack credited: a shared post, a Note, or an item it did not identify.`));
  const bar = element('div', 'notes-source-bar');
  bar.setAttribute('role', 'img');
  bar.setAttribute('aria-label', `${fmt(attribution.post_link_subscribers)} credited to posts shared in Notes, ${fmt(attribution.note_link_subscribers)} credited to Notes, ${fmt(attribution.unclassified_subscribers)} with no identified item`);
  for (const [kind, share] of [
    ['post', attribution.post_link_share],
    ['note', attribution.note_link_share],
    ['unknown', attribution.unclassified_share],
  ]) {
    const segment = element('span', `notes-source-segment ${kind}`);
    segment.style.width = `${(share || 0) * 100}%`;
    bar.append(segment);
  }
  split.append(bar);
  const legend = element('div', 'notes-source-legend');
  legend.append(
    legendItem('Posts shared in Notes', attribution.post_link_subscribers, attribution.post_link_share, 'post'),
    legendItem('Notes', attribution.note_link_subscribers, attribution.note_link_share, 'note'),
    legendItem('Unspecified items', attribution.unclassified_subscribers, attribution.unclassified_share, 'unknown'),
  );
  split.append(legend);

  const rankings = element('div', 'notes-source-rankings');
  rankings.append(
    rankedItems(data.discovery_rankings?.post || [], 'post', 'Top shared posts'),
    rankedItems(data.discovery_rankings?.note || [], 'note', 'Top Notes'),
  );
  content.append(split, rankings);
  root.append(heading, content);
  const outside = attribution.outside_items || [];
  if (outside.length) {
    const details = element('details', 'notes-outside');
    details.append(element('summary', '', 'Other writers and outside links'));
    details.append(element('p', 'footnote', 'Substack names these credited items; this does not identify everyone who shared your writing.'));
    const list = element('ul');
    for (const item of outside.slice(0, 8)) {
      const row = element('li');
      const label = `${item.author_label ? `${item.author_label} · ` : ''}${item.surface}: ${item.preview}`;
      const title = element(item.href ? 'a' : 'span', '', label);
      if (item.href) {
        title.href = item.href;
        title.target = '_blank';
        title.rel = 'noopener noreferrer';
      }
      row.append(title, element('strong', '', fmt(item.subscribers)));
      list.append(row);
    }
    details.append(list);
    root.append(details);
  }
  root.append(element('p', 'footnote',
    'Numbers beside titles are subscribers credited to that item in this period. Items can belong to other writers. Attribution does not prove what persuaded a reader to subscribe.'));
}
