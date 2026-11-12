import { $, date, fmt, loadingIndicator, emptyMessage } from '../shared.js';

const element = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
};

const link = (path, label, className) => {
  const anchor = element('a', className, label);
  anchor.href = path;
  anchor.dataset.route = '';
  return anchor;
};

const preview = (text, limit = 175) => {
  const clean = String(text || '').replace(/\s+/g, ' ').trim();
  return clean.length > limit ? `${clean.slice(0, limit).trimEnd()}…` : clean;
};

function postCard(post) {
  const card = element('article', 'latest-post-card');
  const heading = element('div', 'latest-post-heading');
  heading.append(element('span', 'latest-card-kicker', 'LATEST POST'),
    link(`/posts/${post.id}`, 'Open post story →', 'latest-action'));
  const title = link(`/posts/${post.id}`, post.title || 'Untitled post', 'latest-post-title');
  const dateLine = element('p', 'latest-date', `Published ${date(post.date)} · totals to date`);
  const stats = element('div', 'latest-post-stats');
  for (const [label, value] of [
    ['Views', post.views],
    ['Signups', post.signups],
    ['Likes', post.likes],
    ['Comments', post.comments],
    ['Shares', post.shares],
  ]) {
    const stat = element('div', 'latest-post-stat');
    stat.append(element('span', 'latest-post-stat-label', label),
      element('strong', '', fmt(value)));
    stats.append(stat);
  }
  card.append(heading, title, dateLine, stats);
  return card;
}

function noteCard(note) {
  const card = element('article', 'latest-note-card');
  const top = element('div', 'latest-note-top');
  top.append(element('span', 'latest-date', date(note.published_at)));
  if (note.relation) top.append(element('span',
    note.relation === 'links to latest post' ? 'latest-relation linked' : 'latest-relation',
    note.relation === 'links to latest post' ? 'Links to latest post' :
      note.relation === 'published after latest post' ? 'After latest post' : 'Before latest post'));
  const title = link(`/notes/${note.id}`, preview(note.preview || note.title), 'latest-note-title');
  card.append(top, title);
  if (note.impressions != null) {
    const count = element('p', 'latest-note-count');
    count.append(element('strong', '', fmt(note.impressions)),
      element('span', '', 'impressions'));
    card.append(count);
  } else {
    card.append(element('p', 'latest-note-unavailable', 'Stats are still collecting.'));
  }
  return card;
}

export function renderLatest({ data, loading, error }) {
  const root = $('latest-content');
  root.replaceChildren();
  if (loading && !data) {
    root.append(loadingIndicator('Finding your latest writing…'));
    return;
  }
  if (error && !data) {
    root.append(emptyMessage(`Latest writing is unavailable right now. ${error}`));
    return;
  }
  if (!data?.post && !data?.notes?.length) {
    root.append(emptyMessage('No published post or recent Note was found.'));
    return;
  }
  const layout = element('div', 'latest-grid');
  if (!data.post) layout.classList.add('no-post');
  if (data.post) layout.append(postCard(data.post));
  const notes = element('div', 'latest-notes');
  const heading = element('div', 'latest-notes-heading');
  heading.append(element('span', 'latest-card-kicker', 'RECENT NOTES'),
    link('/notes', 'All Notes →', 'latest-action'));
  notes.append(heading);
  for (const note of data.notes || []) notes.append(noteCard(note));
  if (!data.notes?.length) notes.append(emptyMessage('No Notes were published in the past year.'));
  layout.append(notes);
  root.append(layout);

  const context = element('div', 'latest-sequence');
  const post = data.post;
  if (post && data.notes_since_post != null) {
    context.append(element('strong', '',
      `${fmt(data.notes_since_post)} ${data.notes_since_post === 1 ? 'Note' : 'Notes'} published since this post`));
    context.append(element('span', '',
      'A Note marked “Links to latest post” contains an explicit post link. Timing alone does not establish an effect.'));
  }
  if (context.childNodes.length) root.append(context);
}
