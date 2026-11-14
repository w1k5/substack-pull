import { $, date, emptyMessage, fmt, loadingIndicator } from '../shared.js';
import { detailHeader, metricGroup } from './detail-card.js';
import { sourceLabel } from '../source-labels.js';

let activeId;
let request = 0;

function element(tag, text) {
  const node = document.createElement(tag);
  node.textContent = text;
  return node;
}

export async function renderDiscoveryPost(id, title, refresh = false) {
  if (!refresh && id === activeId) return;
  activeId = id;
  const version = ++request;
  if (!id) return;
  const slot = $('discovery-post-content');
  const keepDetails = refresh && !!slot.querySelector('.discovery-post-growth');
  const { heading, title: label, meta: context, button: retry } = detailHeader('Post',
    'Lifetime subscriber growth', () => renderDiscoveryPost(id, title, true));
  label.id = 'discovery-post-title';

  const titleBlock = element('div', '');
  titleBlock.className = 'note-detail-text';
  const name = element('p', title);
  titleBlock.append(name);
  const pending = loadingIndicator(keepDetails ? 'Updating subscriber growth…' : 'Loading subscriber growth…',
    { inline: keepDetails });
  if (keepDetails) {
    slot.querySelector('.note-detail-error')?.remove();
    slot.querySelector('.note-detail-heading .refresh').disabled = true;
    slot.querySelector('.note-detail-heading').after(pending);
  } else {
    slot.replaceChildren(heading, titleBlock, pending);
  }
  try {
    const response = await fetch(`/api/post/${id}${refresh ? '?refresh=1' : ''}`, { cache: 'no-store' });
    const post = await response.json();
    if (!response.ok) throw new Error(post.error || 'Could not load subscriber growth.');
    if (version !== request) return;
    name.textContent = post.title || title;
    if (post.date) context.textContent = `Published ${date(post.date)} · lifetime subscriber growth`;
    const growth = document.createElement('div');
    growth.className = 'discovery-post-growth';
    growth.append(metricGroup('Subscriber growth', [
      ['Signups', fmt(post.growth?.signups), 'Attributed to this post'],
      ['Paid subscriptions', fmt(post.growth?.subscribes), 'Attributed to this post'],
      ['Unsubscribes', fmt(post.growth?.unsubscribes), 'Attributed to this post'],
    ]));
    const sources = post.insights?.signup_sources || [];
    const breakdown = document.createElement('div');
    breakdown.className = 'note-reach-breakdown discovery-source-breakdown';
    const group = document.createElement('div');
    group.append(element('strong', 'Sources credited with signups'));
    if (sources.length) {
      for (const row of sources) {
        const item = document.createElement('div');
        item.className = 'note-reach-row';
        const label = sourceLabel(row.source, 'post', row.source_category);
        const title = element('span', label.name);
        title.title = label.name;
        const bar = document.createElement('i');
        bar.style.width = `${row.signup_share * 100}%`;
        bar.setAttribute('aria-hidden', 'true');
        item.append(title, bar, element('b', fmt(row.attributed_signups)));
        group.append(item);
      }
      const note = element('p', 'Bars show each source’s share of attributed signups.');
      note.className = 'note-reach-foot';
      group.append(note);
    } else {
      group.append(emptyMessage('No signup sources were reported for this post.'));
    }
    breakdown.append(group);
    growth.append(breakdown);
    const link = element('a', 'Open full post analytics →');
    link.href = `/posts/${id}`;
    // An explicit link to the full page leaves Discovery.
    growth.append(link);
    slot.replaceChildren(heading, titleBlock, growth);
  } catch (error) {
    if (version !== request) return;
    const message = emptyMessage(error.message);
    message.classList.add('note-detail-error');
    if (keepDetails) {
      pending.replaceWith(message);
      slot.querySelector('.note-detail-heading .refresh').disabled = false;
    } else {
      slot.replaceChildren(heading, titleBlock, message);
    }
  } finally {
    if (version === request) retry.disabled = false;
  }
}
