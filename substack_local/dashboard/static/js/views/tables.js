import { $, fmt, pct, date, cell, emptyMessage } from '../shared.js';
import { downloadCsv } from '../export.js';
import { sourceLabel } from '../source-labels.js';
import { renderPostPortfolio } from '../post/portfolio.js';

const PAGE_SIZE = 20;
const sortState = {
  source: { key: 'views', direction: 'desc' },
  post: { key: 'signups', direction: 'desc' },
};
const columns = {
  source: [['name', 'Source'], ['views', 'Views'], ['users', 'Users'],
    ['signups', 'Signups'], ['rate', 'Signup rate']],
  post: [['title', 'Post'], ['date', 'Date'], ['views', 'Views'],
    ['signups', 'Signups'], ['yield', 'Signup yield'], ['shares', 'Shares'],
    ['open_rate', 'Email opens'], ['engagement_rate', 'Engagement']],
};

const sourceSignups = (row) => row.free_signups == null && row.paid_signups == null
  ? null : Number(row.free_signups || 0) + Number(row.paid_signups || 0);
const sourceRate = (row) => sourceSignups(row) != null && Number(row.users) > 0
  ? sourceSignups(row) / Number(row.users) : null;
const postYield = (row) => Number(row.views) >= 1000
  ? 1000 * Number(row.signups || 0) / Number(row.views) : null;

function publicationDay(timestamp) {
  if (!timestamp) return '';
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date(timestamp));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function sortValue(section, row, key) {
  if (section === 'source') {
    if (key === 'name') return sourceLabel(row.name, 'traffic', row.category).name.toLowerCase();
    if (key === 'signups') return sourceSignups(row);
    if (key === 'rate') return sourceRate(row);
  }
  if (section === 'post') {
    if (key === 'title') return (row.title || '').toLowerCase();
    if (key === 'date') return row.date ? new Date(row.date).getTime() : null;
    if (key === 'yield') return postYield(row);
  }
  return row[key] == null ? null : Number(row[key]);
}

function compareRows(section, a, b) {
  const { key, direction } = sortState[section];
  const av = sortValue(section, a, key), bv = sortValue(section, b, key);
  if (av == null && bv == null) return 0;
  if (av == null) return 1;
  if (bv == null) return -1;
  const result = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
  return result * (direction === 'asc' ? 1 : -1)
    || String(a.name || a.title || '').localeCompare(String(b.name || b.title || ''));
}

function emptyTable(body, count, message) {
  const row = document.createElement('tr');
  const td = cell(row, emptyMessage(message));
  td.colSpan = count;
  body.append(row);
}

export function createTables({ getData, getPortfolio, navigate }) {
  const page = { source: 1, post: 1 };
  let visibleSourceRows = [], visiblePostRows = [];

  function renderPagination(section, count, rerender) {
    const root = $(`${section}-pagination`);
    root.replaceChildren();
    const pages = Math.max(1, Math.ceil(count / PAGE_SIZE));
    page[section] = Math.min(page[section], pages);
    if (pages === 1) return;
    const label = document.createElement('span');
    const start = (page[section] - 1) * PAGE_SIZE + 1;
    label.textContent = `${start}–${Math.min(count, start + PAGE_SIZE - 1)} of ${count}`;
    const button = (text, direction) => {
      const element = document.createElement('button');
      element.type = 'button';
      element.className = 'refresh';
      element.textContent = text;
      element.disabled = direction < 0 ? page[section] === 1 : page[section] === pages;
      element.addEventListener('click', () => {
        page[section] += direction;
        rerender();
        root.previousElementSibling.scrollTop = 0;
      });
      return element;
    };
    root.append(label, button('Previous', -1), button('Next', 1));
  }

  function renderSources() {
    const data = getData();
    if (!data) return;
    const query = $('source-search').value.toLowerCase().trim();
    visibleSourceRows = (data.traffic_sources || [])
      .filter((row) => `${row.name || ''} ${sourceLabel(row.name, 'traffic', row.category).name}`
        .toLowerCase().includes(query))
      .sort((a, b) => compareRows('source', a, b));
    $('export-sources').disabled = !visibleSourceRows.length;
    const body = $('source-table');
    body.replaceChildren();
    renderPagination('source', visibleSourceRows.length, renderSources);
    if (!visibleSourceRows.length) {
      emptyTable(body, 5, query ? 'No sources match that search.' : 'No traffic sources were returned.');
      return;
    }
    visibleSourceRows.slice((page.source - 1) * PAGE_SIZE, page.source * PAGE_SIZE).forEach((row) => {
      const tr = document.createElement('tr');
      const label = sourceLabel(row.name, 'traffic', row.category);
      const source = document.createElement('span');
      source.textContent = label.name;
      if (label.detail) source.title = label.detail;
      cell(tr, source);
      cell(tr, fmt(row.views));
      cell(tr, fmt(row.users));
      cell(tr, fmt(sourceSignups(row)));
      cell(tr, pct(sourceRate(row)));
      body.append(tr);
    });
  }

  function filteredPosts(data) {
    const query = $('global-search').value.toLowerCase().trim();
    return (data.posts || []).filter((row) => {
      if (query && !row.title.toLowerCase().includes(query)) return false;
      const day = publicationDay(row.date);
      if ($('posts-in-period').checked && !(day >= data.range.start && day <= data.range.end)) return false;
      if ($('posts-min-views').checked && Number(row.views) < 1000) return false;
      return true;
    });
  }

  function renderPosts() {
    const data = getData();
    if (!data) return;
    const filtered = filteredPosts(data);
    renderPostPortfolio({ ...getPortfolio(), visibleIds: new Set(filtered.map((row) => String(row.id))) });
    visiblePostRows = filtered.sort((a, b) => compareRows('post', a, b));
    $('export-posts').disabled = !visiblePostRows.length;
    const body = $('post-table');
    body.replaceChildren();
    renderPagination('post', visiblePostRows.length, renderPosts);
    if (!visiblePostRows.length) {
      emptyTable(body, 8, 'No posts match these filters.');
      return;
    }
    visiblePostRows.slice((page.post - 1) * PAGE_SIZE, page.post * PAGE_SIZE).forEach((row) => {
      const tr = document.createElement('tr');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'post-select';
      button.textContent = row.title;
      button.addEventListener('click', () => navigate(`/posts/${row.id}`));
      cell(tr, button);
      cell(tr, date(row.date));
      cell(tr, fmt(row.views));
      cell(tr, fmt(row.signups));
      cell(tr, postYield(row) == null ? '—' : postYield(row).toFixed(1));
      cell(tr, fmt(row.shares));
      const email = document.createElement('span');
      email.className = 'email-cell';
      const rate = document.createElement('strong');
      rate.textContent = pct(row.open_rate);
      const count = document.createElement('small');
      count.textContent = `${fmt(row.opens)} / ${fmt(row.sent)}`;
      email.append(rate, count);
      cell(tr, email);
      cell(tr, pct(row.engagement_rate));
      body.append(tr);
    });
  }

  function updateSortControls(section) {
    const { key, direction } = sortState[section];
    const table = $(section === 'source' ? 'source-table' : 'post-table').closest('table');
    table.querySelectorAll('thead th').forEach((th, index) => {
      const [columnKey, label] = columns[section][index];
      const selected = columnKey === key;
      th.setAttribute('aria-sort', selected ? (direction === 'asc' ? 'ascending' : 'descending') : 'none');
      th.querySelector('.sort-arrow').textContent = selected ? direction === 'asc' ? '↑' : '↓' : '↕';
      const nextDirection = selected ? direction === 'asc' ? 'descending' : 'ascending'
        : ['name', 'title'].includes(columnKey) ? 'ascending' : 'descending';
      th.querySelector('.sort-header').setAttribute('aria-label', `Sort by ${label}, ${nextDirection}`);
    });
  }

  function setupSort(section) {
    const table = $(section === 'source' ? 'source-table' : 'post-table').closest('table');
    table.querySelectorAll('thead th').forEach((th, index) => {
      const [key, label] = columns[section][index];
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'sort-header';
      button.setAttribute('aria-label', `Sort by ${label}`);
      button.append(document.createTextNode(label));
      const arrow = document.createElement('span');
      arrow.className = 'sort-arrow';
      arrow.setAttribute('aria-hidden', 'true');
      button.append(arrow);
      th.replaceChildren(button);
      button.addEventListener('click', () => {
        page[section] = 1;
        const state = sortState[section];
        if (state.key === key) state.direction = state.direction === 'asc' ? 'desc' : 'asc';
        else { state.key = key; state.direction = ['name', 'title'].includes(key) ? 'asc' : 'desc'; }
        updateSortControls(section);
        (section === 'source' ? renderSources : renderPosts)();
        table.closest('.table-scroll').scrollTop = 0;
      });
    });
    updateSortControls(section);
  }

  setupSort('source');
  setupSort('post');
  $('source-search').addEventListener('input', () => { page.source = 1; renderSources(); });
  for (const id of ['posts-in-period', 'posts-min-views'])
    $(id).addEventListener('change', () => { page.post = 1; renderPosts(); });
  $('export-sources').addEventListener('click', () => {
    const data = getData();
    if (!data) return;
    downloadCsv(`substack-sources-visible-${data.range.start}-${data.range.end}.csv`,
      ['Source', 'Substack source', 'Category', 'Views', 'Users', 'Free signups', 'Paid signups'],
      visibleSourceRows.map((row) => [sourceLabel(row.name, 'traffic', row.category).name,
        row.name, row.category, row.views, row.users, row.free_signups, row.paid_signups]));
  });
  $('export-posts').addEventListener('click', () => {
    if (!getData()) return;
    downloadCsv('substack-posts-visible-lifetime.csv',
      ['Post', 'Published', 'Views', 'Signups', 'Signups per 1k views (1k+ only)',
        'Shares', 'Opens', 'Sent', 'Open rate', 'Engagement rate'],
      visiblePostRows.map((row) => [row.title, row.date, row.views, row.signups,
        postYield(row), row.shares, row.opens, row.sent, row.open_rate, row.engagement_rate]));
  });

  return {
    renderSources, renderPosts,
    resetPages() { page.source = 1; page.post = 1; },
    resetPostPage() { page.post = 1; },
  };
}
