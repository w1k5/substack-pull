import { $, loadingIndicator, emptyMessage } from './shared.js';
import { showPost, clearNoteStatsRequests } from './post/index.js';
import { renderPublicationTimeline } from './timeline.js';
import { renderSubscriberSourceTrend } from './source-trend.js';
import { renderNotesPage, setupNoteDetail, clearNotePageStats } from './notes-page.js';
import { renderNotesComparison, filterNotesComparison, clearNotesComparison, setupNotesComparison } from './notes-compare.js';
import { setNoteMapQuery } from './notes-map.js';
import { renderPlannerRoute, setupPlanner } from './planner.js';
import { setupPostPortfolio } from './post/portfolio.js';
import { renderBriefing, renderDiscoveryInsight, renderGrowth } from './views/publication.js';
import { createTables } from './views/tables.js';

let data;
let activePostId;
let loadRequest = 0;
let renderedPath = location.pathname;
let postPortfolio = null;
let postPortfolioError = null;
let postPortfolioLoading = false;
let postPortfolioRequest = 0;
let publicationLoading = false;
let loadingDifferentPeriod = false;

const updatedLabel = (snapshot) =>
  `Updated ${new Date(snapshot.refreshed_at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`;

function render() {
  $('updated').textContent = updatedLabel(data);
  renderRoute();
}
function currentRoute() {
  const path = location.pathname;
  if (/^\/posts\/\d+$/.test(path)) return { view: 'post-detail', id: path.split('/')[2] };
  if (path === '/notes/compare') return { view: 'notes' };
  if (/^\/notes\/\d+$/.test(path)) return { view: 'notes', id: path.split('/')[2] };
  if (path === '/posts' || path === '/discovery' || path === '/notes' || path === '/planner') return { view: path.slice(1) };
  return { view: 'briefing' };
}
function renderRoute() {
  const route = currentRoute();
  renderedPath = location.pathname;
  if (route.view !== 'notes' && $('note-detail').open) $('note-detail').close();
  $('period-control').hidden = route.view === 'post-detail' || route.view === 'planner';
  $('lifetime-scope').hidden = route.view !== 'post-detail';
  $('refresh').hidden = route.view === 'post-detail' || route.view === 'planner';
  $('updated').hidden = route.view === 'post-detail' || route.view === 'planner';
  document.querySelector('.top-search').hidden = route.view === 'planner';
  for (const view of ['briefing', 'posts', 'discovery', 'notes', 'planner', 'post-detail'])
    $(`view-${view}`).hidden = view !== route.view;
  const primary = route.view === 'post-detail' ? 'posts' : route.view;
  document.querySelectorAll('.side-link').forEach((link) => {
    const selected = link.getAttribute('href') === (primary === 'briefing' ? '/' : `/${primary}`);
    link.classList.toggle('active', selected);
    if (selected) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  const titles = {
    briefing: 'Briefing', posts: 'Posts', discovery: 'Discovery',
    notes: 'Notes', planner: 'Note planner', 'post-detail': 'Post story',
  };
  document.title = `${titles[route.view]} · Clearview`;
  if (route.view === 'planner') renderPlannerRoute();
  if (!data) {
    setEmptyPanelsLoading(publicationLoading);
    return;
  }
  if (route.view === 'briefing') renderBriefing(data, navigate);
  if (route.view === 'posts') {
    tables.renderPosts();
    loadPostPortfolio();
  }
  if (route.view === 'discovery') {
    renderDiscoveryInsight(data);
    renderGrowth(data);
    tables.renderSources();
    renderSubscriberSourceTrend(data, navigate);
  }
  if (route.view === 'notes') {
    renderNotesComparison(data, navigate, route.id);
    renderNotesPage(data, route.id);
  }
  if (route.view === 'post-detail' && route.id !== activePostId) {
    activePostId = route.id;
    const row = (data.posts || []).find((post) => String(post.id) === route.id);
    if (row) showPost(row, data.publication);
    else {
      $('detail-title').textContent = 'Post unavailable';
      $('detail-content').replaceChildren(emptyMessage('This post is not in the published post list.'));
    }
  }
  setEmptyPanelsLoading(publicationLoading && loadingDifferentPeriod);
}
const isNoteLibraryPath = (path) => /^\/notes(?:\/\d+)?$/.test(path);
function navigate(path) {
  const keepNotePosition = isNoteLibraryPath(location.pathname) && isNoteLibraryPath(path);
  if (location.pathname !== path) history.pushState({}, '', path);
  $('search-results').hidden = true;
  if (!keepNotePosition) {
    $('global-search').value = '';
    setNoteMapQuery('');
  }
  renderRoute();
  if (currentRoute().view !== 'planner' && !data && $('overview').getAttribute('aria-busy') !== 'true') load();
  if (!keepNotePosition) window.scrollTo({ top: 0, behavior: 'instant' });
}
function renderSearchResults() {
  const q = $('global-search').value.toLowerCase().trim();
  const results = $('search-results');
  results.replaceChildren();
  if (!q || !data) {
    results.hidden = true;
    return;
  }
  const posts = (data.posts || [])
    .filter((item) => item.title.toLowerCase().includes(q))
    .map((item) => ({ title: item.title, type: 'Post', path: `/posts/${item.id}` }));
  const notes = (data.publication_events || [])
    .filter((item) => item.type === 'note' && /^\d+$/.test(String(item.id)) && item.title.toLowerCase().includes(q))
    .map((item) => ({ title: item.title, type: 'Note', path: `/notes/${item.id}` }));
  for (const item of [...posts, ...notes].slice(0, 8)) {
    const button = document.createElement('button');
    button.type = 'button';
    const type = document.createElement('small');
    type.textContent = item.type;
    const name = document.createElement('span');
    name.textContent = item.title;
    button.append(type, name);
    button.addEventListener('click', () => navigate(item.path));
    results.append(button);
  }
  if (!results.children.length) results.append(emptyMessage('No posts or Notes match.'));
  results.hidden = false;
}
function setEmptyPanelsLoading(loading) {
  document.querySelectorAll('.panel-spinner').forEach((spinner) => spinner.remove());
  document.querySelectorAll('.empty-loading').forEach((panel) => panel.classList.remove('empty-loading'));
  if (!loading || currentRoute().view === 'planner') return;
  document.querySelectorAll(
    '.view:not([hidden]) .metric,.view:not([hidden]) .panel,.view:not([hidden]) .insight-callout',
  ).forEach((panel) => {
    const indicator = loadingIndicator('Loading…');
    indicator.classList.add('panel-spinner');
    indicator.setAttribute('role', 'presentation');
    panel.classList.add('empty-loading');
    panel.append(indicator);
  });
}

function showLoadError(message, retry) {
  const detail = document.createElement('span');
  detail.textContent = message;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'refresh';
  button.textContent = 'Try again';
  button.addEventListener('click', retry);
  $('notice').replaceChildren(detail, button);
  $('notice').hidden = false;
}

async function load(force = false) {
  const request = ++loadRequest;
  const days = Number($('range').value);
  const priorData = data;
  loadingDifferentPeriod = !!(data && data.range.days !== days);
  publicationLoading = true;
  $('refresh').disabled = true;
  $('header-spinner').hidden = false;
  setEmptyPanelsLoading(!data || loadingDifferentPeriod);
  $('overview').setAttribute('aria-busy', 'true');
  $('updated').textContent = !data ? 'Loading publication data…'
    : loadingDifferentPeriod ? 'Loading selected period…'
      : `${updatedLabel(data)} · refreshing…`;
  $('notice').hidden = true;
  try {
    const response = await fetch(
      `/api/dashboard?days=${days}${force ? '&refresh=1' : ''}`,
      { cache: 'no-store' },
    );
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not load analytics');
    if (request !== loadRequest) return;
    if (force) {
      clearNoteStatsRequests();
      clearNotePageStats();
      clearNotesComparison();
      postPortfolioRequest++;
      postPortfolio = null;
      postPortfolioError = null;
      postPortfolioLoading = false;
    }
    data = payload;
    loadingDifferentPeriod = false;
    publicationLoading = false;
    activePostId = undefined;
    tables.resetPages();
    render();
    renderSearchResults();
  } catch (error) {
    if (request !== loadRequest) return;
    const changingPeriod = loadingDifferentPeriod;
    loadingDifferentPeriod = false;
    if (priorData && changingPeriod) {
      $('range').value = String(priorData.range.days);
      renderRoute();
    }
    const failedDays = days;
    showLoadError(
      `${priorData ? 'Could not update' : 'Could not load'} publication data: ${error.message}`
        + (priorData ? ' The last loaded data is still shown.' : ''),
      () => { $('range').value = String(failedDays); load(force); },
    );
    $('updated').textContent = priorData ? updatedLabel(priorData) : 'Data unavailable';
  } finally {
    if (request === loadRequest) {
      publicationLoading = false;
      loadingDifferentPeriod = false;
      $('refresh').disabled = false;
      $('header-spinner').hidden = true;
      setEmptyPanelsLoading(false);
      $('overview').setAttribute('aria-busy', 'false');
    }
  }
}

async function loadPostPortfolio(force = false) {
  if (!data || postPortfolioLoading || ((postPortfolio || postPortfolioError) && !force)) return;
  const request = ++postPortfolioRequest;
  postPortfolioLoading = true;
  postPortfolioError = null;
  tables.renderPosts();
  try {
    const response = await fetch(`/api/post-portfolio${force ? '?refresh=1' : ''}`, { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not compare posts');
    if (request !== postPortfolioRequest) return;
    postPortfolio = payload;
  } catch (error) {
    if (request !== postPortfolioRequest) return;
    postPortfolioError = error.message;
  } finally {
    if (request === postPortfolioRequest) {
      postPortfolioLoading = false;
      if (currentRoute().view === 'posts') tables.renderPosts();
    }
  }
}

// Old section links open their corresponding views after an upgrade.
if (location.pathname === '/notes/compare') history.replaceState({}, '', '/notes');
if (location.pathname === '/' && ['#posts', '#sources', '#overview'].includes(location.hash)) {
  history.replaceState({}, '', { '#posts': '/posts', '#sources': '/discovery', '#overview': '/' }[location.hash]);
}
const tables = createTables({
  getData: () => data,
  getPortfolio: () => ({ data: postPortfolio, error: postPortfolioError, loading: postPortfolioLoading }),
  navigate,
});
setupNotesComparison();
setupPostPortfolio();
setupNoteDetail(navigate);
setupPlanner();
renderRoute();
$('range').addEventListener('change', () => load());
$('refresh').addEventListener('click', () => load(true));
$('post-map-retry').addEventListener('click', () => loadPostPortfolio(true));
$('global-search').addEventListener('input', () => {
  tables.resetPostPage();
  if (data) {
    tables.renderPosts();
    if (currentRoute().view === 'notes') {
      setNoteMapQuery($('global-search').value);
      filterNotesComparison($('global-search').value);
    }
  }
  renderSearchResults();
});
$('global-search').addEventListener('keydown', (event) => {
  if (event.key === 'Escape') $('search-results').hidden = true;
  if (event.key === 'Enter') $('search-results').querySelector('button')?.click();
});
document.addEventListener('click', (event) => {
  const link = event.target.closest('a[data-route]');
  if (link && !event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0) {
    event.preventDefault();
    navigate(link.getAttribute('href'));
  }
  if (!event.target.closest('.top-search')) $('search-results').hidden = true;
});
window.addEventListener('popstate', () => {
  const keepNotePosition = isNoteLibraryPath(renderedPath) && isNoteLibraryPath(location.pathname);
  renderRoute();
  if (currentRoute().view !== 'planner' && !data && $('overview').getAttribute('aria-busy') !== 'true') load();
  if (!keepNotePosition) window.scrollTo(0, 0);
});
let chartResizeFrame;
window.addEventListener('resize', () => {
  if (!data) return;
  cancelAnimationFrame(chartResizeFrame);
  chartResizeFrame = requestAnimationFrame(() => {
    const view = currentRoute().view;
    if (view === 'briefing') renderPublicationTimeline(data, navigate);
    if (view === 'discovery') renderSubscriberSourceTrend(data, navigate);
  });
});
$('detail-refresh').addEventListener('click', () => {
  const id = currentRoute().id;
  const row = (data?.posts || []).find((post) => String(post.id) === id);
  if (row) showPost(row, data.publication, true);
});
if (currentRoute().view !== 'planner') load();
