import { $, date, fmt, loadingIndicator, cell, emptyMessage } from '../shared.js';

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}
function link(path, text) {
  const node = element('a', '', text);
  node.href = path;
  node.dataset.route = '';
  return node;
}
function delta(change) {
  if (change?.percent == null) return 'Previous period unavailable';
  return (change.percent > 0 ? '+' : '') + change.percent.toFixed(1) + '% vs prior period';
}
export function renderEditorialOverview(data, latest) {
  const pulse = $('editorial-pulse');
  pulse.replaceChildren();
  for (const [label, key, unit] of [
    ['AUDIENCE GROWTH', 'subscribers', 'new subscribers'],
    ['REACH', 'views', 'publication views'],
  ]) {
    const block = element('div', key === 'subscribers' ? 'editorial-primary' : 'editorial-secondary');
    block.append(element('span', 'eyebrow', label),
      element('strong', '', fmt(data.totals?.[key])),
      element('span', '', unit + ' in this period'),
      element('small', '', delta(data.briefing?.changes?.[key])));
    pulse.append(block);
  }
  const findings = $('editorial-highlights');
  findings.replaceChildren();
  const observations = [
    ...(data.editorial?.observations || []),
    ...(latest?.note_observation ? [latest.note_observation] : []),
  ];
  findings.hidden = !observations.length;
  findings.parentElement.classList.toggle('single', !observations.length);
  const heading = element('div', 'editorial-findings-heading');
  heading.append(element('span', 'eyebrow', 'ONE THING TO NOTICE'));
  findings.append(heading);
  for (const item of observations.slice(0, 1)) {
    const row = element('div', 'editorial-finding');
    row.append(link(item.path, item.title));
    const comparison = item.comparison;
    if (comparison) {
      const figures = element('dl', 'editorial-finding-figures');
      for (const [label, value] of [['New subscribers', comparison.subscribers], ['Publication views', comparison.views]]) {
        const figure = element('div');
        figure.append(element('dt', '', label), element('dd', '', value));
        figures.append(figure);
      }
      row.append(element('p', '', comparison.days
        ? `Compared with the previous ${comparison.days} days` : 'Compared with the previous period'), figures);
      if (comparison.yield) {
        const context = element('p', 'editorial-finding-yield');
        context.append(element('strong', '', comparison.yield.current),
          ` subscribers per 1,000 views · ${comparison.yield.previous} previously`);
        row.append(context);
      }
    } else {
      row.append(element('p', '', item.detail));
    }
    findings.append(row);
  }
}
export function createLeaderboard({ needNotes, needPostComparison }) {
  let type = 'posts', sort = 'growth', outcome = 'growth', descending = true, shown = 40, rankRates = false;
  let snapshot = { data: null, notes: null, notesLoading: false, notesError: '',
    notesProgress: null, portfolio: null, portfolioLoading: false,
    portfolioProgress: null };
  let visibleRowCount = 0;
  function metric(value, supporting) {
    const wrapper = element('span', 'editorial-cell');
    wrapper.append(element('strong', '', typeof value === 'string' ? value : fmt(value)));
    if (supporting) wrapper.append(element('small', '', supporting));
    return wrapper;
  }
  const rate = (value) => value == null ? null : value.toFixed(1) + ' per 1k';
  const labels = { reach: 'Reach', growth: 'Signups', likes: 'Likes',
    discussion: 'Comments / replies', restacks: 'Restacks', shares: 'Shares',
    relative: 'First week vs peers' };
  const rateFields = { growth: 'signupYield', likes: 'likeRate',
    discussion: 'discussionRate', restacks: 'restackRate', shares: 'shareRate' };
  function result(row) {
    if (outcome === 'relative') return metric(row.relative == null ? null : row.relative.toFixed(1) + '×',
      row.relative == null ? null : row.kind === 'Note' ? 'typical reach at the same age' : 'median first-week views');
    const value = row[outcome];
    if (outcome === 'reach') return metric(value, row.kind === 'Post' ? 'views' : 'impressions');
    const perThousand = row[rateFields[outcome]];
    if (rankRates) return metric(perThousand == null ? null : perThousand.toFixed(1) + ' / 1k',
      value == null ? null : fmt(value) + ' total');
    return metric(value, rate(perThousand));
  }
  function renderLoading() {
    const { notesLoading, notesProgress, portfolioLoading, portfolioProgress } = snapshot;
    const loading = $('leaderboard-loading');
    loading.replaceChildren();
    if (type !== 'posts' && notesLoading)
      loading.append(loadingIndicator('Comparing Notes…', {
        completed: notesProgress?.considered, total: notesProgress?.total,
        inline: !!visibleRowCount,
      }));
    else if (type !== 'notes' && portfolioLoading && sort === 'relative')
      loading.append(loadingIndicator('Comparing posts…', {
        completed: portfolioProgress?.considered, total: portfolioProgress?.target,
        inline: !!visibleRowCount,
      }));
  }
  function render(next) {
    if (next) snapshot = { ...snapshot, ...next };
    const { data, notes, notesLoading, notesError, portfolio, portfolioLoading } = snapshot;
    if (!data) return;
    if (type !== 'posts' && !notes && !notesLoading && !notesError) {
      needNotes();
      return;
    }
    const postRatios = portfolio?.comparison?.lenses?.staying?.reach_multiple || {};
    const posts = (data.posts || []).filter((post) => post.publication_day >= data.range.start
      && post.publication_day <= data.range.end).map((post) => ({
      kind: 'Post', id: post.id, title: post.title || 'Untitled post',
      date: post.publication_day, reach: post.views, growth: post.signups,
      likes: post.likes, discussion: post.comments, restacks: post.restacks, shares: post.shares,
      likeRate: post.likes_per_1k, discussionRate: post.comments_per_1k,
      restackRate: post.restacks_per_1k, shareRate: post.shares_per_1k,
      signupYield: post.signup_yield, relative: postRatios[String(post.id)] ?? null,
    }));
    const noteRows = (notes?.rows || []).map((note) => ({
      kind: 'Note', id: note.id, title: note.title || 'Note',
      date: note.day, reach: note.impressions, growth: null,
      likes: note.likes, discussion: note.replies, restacks: note.restacks, shares: note.shares,
      likeRate: note.likeRate, discussionRate: note.replyRate,
      restackRate: note.restackRate, shareRate: note.shareRate,
      signupYield: null, relative: note.pace?.ratio ?? null,
    }));
    const query = $('global-search').value.toLowerCase().trim();
    const rateKey = rankRates ? rateFields[sort] : null;
    const rankValue = (row) => row[rateKey || sort];
    const rows = (type === 'posts' ? posts : type === 'notes' ? noteRows : [...posts, ...noteRows])
      .filter((row) => row.title.toLowerCase().includes(query))
      .sort((a, b) => {
        const left = rankValue(a), right = rankValue(b);
        if (left == null) return right == null ? 0 : 1;
        if (right == null) return -1;
        const order = typeof left === 'string' ? left.localeCompare(right) : left - right;
        return (descending ? -1 : 1) * order || b.date.localeCompare(a.date);
      });
    $('leaderboard-scope').textContent = 'Published ' + date(data.range.start) + ' – ' + date(data.range.end);
    $('leaderboard-ranking-controls').hidden = type === 'all';
    $('leaderboard-explainer').textContent = type === 'all'
      ? 'All writing opens in publication order. Choose Posts or Notes to rank by performance.'
      : type === 'notes'
        ? 'Note reach is impressions. Reader actions are lifetime counts; rates require at least 100 impressions.'
        : 'Post reach is lifetime views. Signups are attributed to the post; rates require at least 1,000 views.';
    visibleRowCount = rows.length;
    renderLoading();
    const loading = $('leaderboard-loading');
    if (notesError && type !== 'posts') loading.append(emptyMessage('Note comparisons are unavailable: ' + notesError));
    const body = $('leaderboard-rows');
    body.replaceChildren();
    for (const row of rows.slice(0, shown)) {
      const tr = document.createElement('tr');
      const title = element('span', 'editorial-title-cell');
      title.append(link('/' + (row.kind === 'Post' ? 'posts' : 'notes') + '/' + row.id, row.title));
      if (type === 'all') title.append(element('small', '', row.kind));
      cell(tr, title);
      cell(tr, date(row.date));
      cell(tr, result(row));
      body.append(tr);
    }
    if (!rows.length && !notesLoading) {
      const tr = document.createElement('tr');
      const td = cell(tr, emptyMessage(notesError || 'No writing matches this period and search.'));
      td.colSpan = 3;
      body.append(tr);
    }
    const more = $('leaderboard-more');
    more.hidden = rows.length <= shown;
    more.textContent = 'Show more · ' + shown + ' of ' + rows.length;
    document.querySelectorAll('[data-board-type]').forEach((button) => {
      const active = button.dataset.boardType === type;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    const relativeLabel = type === 'notes' ? 'Reach vs typical Note' : labels.relative;
    document.querySelectorAll('[data-board-sort]').forEach((button) => {
      const key = button.dataset.boardSort === 'metric' ? outcome : button.dataset.boardSort;
      const active = key === sort;
      button.disabled = (type === 'notes' && key === 'growth')
        || (type === 'all' && !['date', 'title'].includes(key));
      if (button.closest('th')) {
        if (button.dataset.boardSort === 'metric') button.hidden = button.disabled;
        button.closest('th').setAttribute('aria-sort', active
          ? descending ? 'descending' : 'ascending' : 'none');
        button.querySelector('.sort-arrow').textContent = active ? descending ? '↓' : '↑' : '↕';
      } else {
        button.hidden = button.disabled;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
        if (button.dataset.boardSort === 'discussion')
          button.textContent = type === 'notes' ? 'Replies' : 'Comments';
        if (button.dataset.boardSort === 'reach')
          button.textContent = type === 'notes' ? 'Impressions' : 'Views';
        if (button.dataset.boardSort === 'relative')
          button.textContent = relativeLabel;
      }
    });
    const resultLabel = outcome === 'reach' && type !== 'all'
      ? type === 'notes' ? 'Impressions' : 'Views'
      : outcome === 'discussion' ? type === 'notes' ? 'Replies' : 'Comments'
        : outcome === 'relative' ? relativeLabel : labels[outcome];
    $('leaderboard-result-label').textContent = resultLabel + (rankRates && rateFields[outcome] ? ' / 1k' : '');
    $('leaderboard-result-static').hidden = type !== 'all';
    const toggle = $('leaderboard-rate-toggle');
    toggle.setAttribute('aria-pressed', String(rankRates));
    toggle.hidden = type === 'all' || !rateFields[outcome];
  }
  $('leaderboard-types').addEventListener('click', (event) => {
    const selected = event.target.closest('[data-board-type]')?.dataset.boardType;
    if (!selected || selected === type) return;
    type = selected;
    sort = type === 'all' ? 'date' : type === 'notes' ? 'likes' : 'growth';
    outcome = type === 'all' ? 'reach' : sort;
    descending = true;
    shown = 40;
    if (type !== 'posts') needNotes();
    render();
  });
  document.querySelectorAll('[data-board-sort]').forEach((button) =>
    button.addEventListener('click', () => {
      const next = button.dataset.boardSort === 'metric' ? outcome : button.dataset.boardSort;
      if (type === 'all' && next !== 'date' && next !== 'title') return;
      descending = sort === next ? !descending : true;
      sort = next;
      if (labels[next]) outcome = next;
      shown = 40;
      if (type !== 'notes' && sort === 'relative') needPostComparison();
      render();
    }));
  $('leaderboard-more').addEventListener('click', () => { shown += 40; render(); });
  $('leaderboard-rate-toggle').addEventListener('click', () => {
    rankRates = !rankRates;
    sort = outcome;
    descending = true;
    shown = 40;
    render();
  });
  return { render, search: () => render(), progress: (next) => {
    snapshot = { ...snapshot, ...next };
    renderLoading();
  } };
}
