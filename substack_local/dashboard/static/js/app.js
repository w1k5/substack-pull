import { $, emptyMessage } from './shared.js';
import { showPost, clearNoteStatsRequests } from './post/index.js';
import { renderPublicationTimeline } from './timeline.js';
import { renderSubscriberSourceTrend } from './source-trend.js';
import { renderNotesPage, setupNoteDetail, clearNotePageStats } from './notes-page.js';
import { renderNotesComparison, filterNotesComparison, clearNotesComparison, setupNotesComparison } from './notes-compare.js';
import { setNoteMapQuery } from './notes-map.js';
import { renderDiscoveryPost } from './post/discovery.js';
import { setupDataOptions } from './data-options.js';
import { renderPlannerRoute, setupPlanner } from './planner.js';
import { setupPostPortfolio, updatePostPortfolioProgress } from './post/portfolio.js';
import { renderBriefing, renderGrowth } from './views/publication.js';
import { renderDiscoveryInsight } from './views/subscriber-attribution.js';
import { renderLatest } from './views/latest.js';
import { createTables } from './views/tables.js';
import { renderEditorialOverview } from './views/editorial.js';
import { readComparison } from './stream.js';

let data;
let activePostId;
let loadRequest = 0;
let renderedPath = location.pathname;
let postPortfolio = null;
let postPortfolioProgress = null;
let postPortfolioStale = false;
let postPortfolioError = null;
let postPortfolioLoading = false;
let postPortfolioRequest = 0;
let latestData = null;
let latestLoading = false;
let latestError = null;
let latestRequest = 0;

const updatedLabel = (snapshot) =>
  `Updated ${new Date(snapshot.refreshed_at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`;

function render() {
  $('updated').textContent = updatedLabel(data);
  renderRoute();
}
function currentRoute() {
  const path = location.pathname;
  if (path === '/discovery') {
    const detail = new URLSearchParams(location.search).get('piece')?.match(/^(post|note)-(\d+)$/);
    return { view: 'discovery', kind: detail?.[1], id: detail?.[2] };
  }
  if (/^\/posts\/\d+$/.test(path)) return { view: 'post-detail', id: path.split('/')[2] };
  if (path === '/notes/compare') return { view: 'notes' };
  if (/^\/notes\/\d+$/.test(path)) return { view: 'notes', id: path.split('/')[2] };
  if (['/posts', '/notes', '/planner'].includes(path))
    return { view: path.slice(1) };
  return { view: 'briefing' };
}
const localView = (view) => view === 'planner';

function renderRoute() {
  const route = currentRoute();
  renderedPath = location.pathname;
  $('period-control').hidden = route.view === 'post-detail' || localView(route.view);
  $('lifetime-scope').hidden = route.view !== 'post-detail';
  $('refresh').hidden = route.view === 'post-detail' || localView(route.view);
  $('updated').hidden = route.view === 'post-detail' || localView(route.view);
  document.querySelector('.top-search').hidden = localView(route.view);
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
    briefing: 'Briefing',
    posts: 'Posts', discovery: 'Discovery',
    notes: 'Notes', planner: 'Note planner', 'post-detail': 'Post story',
  };
  document.title = `${titles[route.view]} · Clearview`;
  if (route.view === 'planner') renderPlannerRoute();
  if (!data) return;
  if (route.view === 'briefing') {
    if (!latestData && !latestLoading && !latestError) loadLatest();
    renderBriefing(data, navigate);
    renderEditorialOverview(data, latestData);
    renderLatest({ data: latestData, loading: latestLoading, error: latestError });
  }
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
  }
  renderPieceDetail(route);
}

function renderPieceDetail(route = currentRoute()) {
  const noteId = route.view === 'notes' || route.kind === 'note' ? route.id : undefined;
  const postDialog = $('post-story-dialog');
  const discoveryPostId = route.kind === 'post' ? route.id : undefined;
  if (!data) return;
  renderNotesPage(data, noteId);
  if (discoveryPostId) {
    const row = data.posts?.find((post) => String(post.id) === discoveryPostId);
    renderDiscoveryPost(discoveryPostId, row?.title || 'Post');
    if (!postDialog.open) {
      postDialog.scrollTop = 0;
      postDialog.show();
    }
  } else {
    if (postDialog.open) postDialog.close();
    renderDiscoveryPost();
  }
  syncPieceDialog();
  const postId = route.view === 'post-detail' ? route.id : undefined;
  if (postId !== activePostId) {
    activePostId = postId;
    if (postId) showPost({ id: postId, title: data.posts?.find((post) => String(post.id) === postId)?.title || 'Post' },
      data.publication);
  }
}
const isNoteLibraryPath = (path) => /^\/notes(?:\/\d+)?$/.test(path);
function keepPosition(from, to) {
  return (from === '/discovery' && to === '/discovery')
    || (isNoteLibraryPath(from) && isNoteLibraryPath(to));
}
function navigate(path) {
  const current = location.pathname;
  const piece = current === '/discovery' && path.match(/^\/(post|note)s\/(\d+)$/);
  if (piece) path = `/discovery?piece=${piece[1]}-${piece[2]}`;
  const preservePosition = keepPosition(current, path.split('?')[0]);
  if (current + location.search !== path) history.pushState({ discoveryDetail: Boolean(piece) }, '', path);
  $('search-results').hidden = true;
  if (!preservePosition) {
    $('global-search').value = '';
    setNoteMapQuery('');
  }
  if (current === '/discovery' && preservePosition) renderPieceDetail();
  else renderRoute();
  if (!localView(currentRoute().view) && !data && $('overview').getAttribute('aria-busy') !== 'true') load();
  if (!preservePosition) window.scrollTo({ top: 0, behavior: 'instant' });
}

function closeDiscoveryDetail(kind) {
  if (currentRoute().kind !== kind) return;
  if (history.state?.discoveryDetail) history.back();
  else {
    history.replaceState({}, '', '/discovery');
    renderPieceDetail();
  }
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
  const changingPeriod = !!(data && data.range.days !== days);
  if (!data) {
    $('boot-message').textContent = 'Gathering your publication’s story…';
    $('boot-spinner').hidden = false;
    $('boot-retry').hidden = true;
  }
  $('refresh').disabled = true;
  $('range').disabled = true;
  $('header-spinner').hidden = false;
  if (!data) $('overview').setAttribute('aria-busy', 'true');
  $('updated').textContent = !data ? 'Loading publication data…'
    : changingPeriod ? 'Updating period…' : 'Refreshing…';
  $('updated').title = changingPeriod ? 'The previous period remains visible until this update finishes.' : '';
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
      postPortfolioStale = true;
      postPortfolioProgress = null;
      postPortfolioError = null;
      postPortfolioLoading = false;
    }
    data = payload;
    activePostId = undefined;
    tables.resetPages();
    // Charts measure their container during render, so reveal the shell first.
    document.body.classList.remove('boot-loading');
    render();
    if (force && (latestData || latestError)) loadLatest(true);
    renderSearchResults();
  } catch (error) {
    if (request !== loadRequest) return;
    if (priorData && changingPeriod) {
      $('range').value = String(priorData.range.days);
      renderRoute();
    }
    const failedDays = days;
    const retry = () => { $('range').value = String(failedDays); load(force); };
    if (priorData) {
      showLoadError(`Could not update publication data: ${error.message} The last loaded data is still shown.`, retry);
    } else {
      $('boot-message').textContent = `Could not load publication data: ${error.message}`;
      $('boot-spinner').hidden = true;
      $('boot-retry').hidden = false;
      $('boot-retry').onclick = retry;
    }
    $('updated').textContent = priorData ? updatedLabel(priorData) : 'Data unavailable';
  } finally {
    if (request === loadRequest) {
      $('refresh').disabled = false;
      $('range').disabled = false;
      $('header-spinner').hidden = true;
      $('updated').title = '';
      $('overview').setAttribute('aria-busy', 'false');
    }
  }
}

async function loadLatest(force = false) {
  if (!force && (latestLoading || latestData)) return;
  const request = ++latestRequest;
  latestLoading = true;
  latestError = null;
  if (currentRoute().view === 'briefing') renderLatest({ data: latestData, loading: true });
  try {
    const response = await fetch(`/api/latest${force ? '?refresh=1' : ''}`, { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not load latest writing');
    if (request !== latestRequest) return;
    latestData = payload;
  } catch (error) {
    if (request !== latestRequest) return;
    latestError = error.message;
  } finally {
    if (request === latestRequest) {
      latestLoading = false;
      if (currentRoute().view === 'briefing')
        renderLatest({ data: latestData, loading: false, error: latestError });
      if (currentRoute().view === 'briefing' && data)
        renderEditorialOverview(data, latestData);
    }
  }
}

async function loadPostPortfolio(force = false) {
  if (!data || postPortfolioLoading
      || ((postPortfolio || postPortfolioError) && !force && !postPortfolioStale)) return;
  const request = ++postPortfolioRequest;
  postPortfolioLoading = true;
  postPortfolioProgress = null;
  postPortfolioError = null;
  tables.renderPosts();
  try {
    const response = await fetch(`/api/post-portfolio?stream=1${force ? '&refresh=1' : ''}`, { cache: 'no-store' });
    const payload = await readComparison(response, (partial) => {
      if (request !== postPortfolioRequest) return;
      postPortfolioProgress = { considered: partial.considered, target: partial.target };
      if (currentRoute().view === 'posts') updatePostPortfolioProgress(postPortfolioProgress);

    });
    if (request !== postPortfolioRequest) return;
    postPortfolio = payload;
    postPortfolioStale = false;
  } catch (error) {
    if (request !== postPortfolioRequest) return;
    postPortfolioError = error.message;
    postPortfolioStale = false;
  } finally {
    if (request === postPortfolioRequest) {
      postPortfolioLoading = false;
      postPortfolioProgress = null;
      if (currentRoute().view === 'posts') tables.renderPosts();

    }
  }
}

// Old section links open their corresponding views after an upgrade.
if (location.pathname === '/leaderboard') history.replaceState({}, '', '/posts');
if (location.pathname === '/notes/compare') history.replaceState({}, '', '/notes');
if (location.pathname === '/insights') history.replaceState({}, '', '/');
if (location.pathname === '/local-data') history.replaceState({}, '', '/');
if (location.pathname === '/' && ['#posts', '#sources', '#overview'].includes(location.hash)) {
  history.replaceState({}, '', { '#posts': '/posts', '#sources': '/discovery', '#overview': '/' }[location.hash]);
}
const tables = createTables({
  getData: () => data,
  getPortfolio: () => ({ data: postPortfolio, progress: postPortfolioProgress,
    error: postPortfolioError, loading: postPortfolioLoading }),
  navigate,
});
setupNotesComparison();
setupPostPortfolio();
const postStory = $('post-story-dialog');
setupNoteDetail(() => {
  syncPieceDialog();
  if (currentRoute().kind === 'note') closeDiscoveryDetail('note');
  else if (currentRoute().view === 'notes' && currentRoute().id) navigate('/notes');
});
postStory.addEventListener('close', () => {
  syncPieceDialog();
  closeDiscoveryDetail('post');
});
$('discovery-post-close').addEventListener('click', () => postStory.close());
function syncPieceDialog() {
  const open = Boolean(document.querySelector('.note-detail-dialog[open]'));
  $('piece-scrim').hidden = !open;
  document.querySelectorAll('main > .topbar, #overview > .view').forEach((element) => {
    element.inert = open;
  });
}
function closePieceDialog() {
  const dialog = document.querySelector('.note-detail-dialog[open]');
  if (!dialog) return false;
  dialog.close();
  syncPieceDialog();
  return true;
}
$('piece-scrim').addEventListener('click', closePieceDialog);
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !event.defaultPrevented && closePieceDialog()) event.preventDefault();
});
setupPlanner();
setupDataOptions();
if (localView(currentRoute().view)) document.body.classList.remove('boot-loading');
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
  const preservePosition = keepPosition(renderedPath, location.pathname);
  if (renderedPath === '/discovery' && preservePosition) renderPieceDetail();
  else renderRoute();
  if (!localView(currentRoute().view) && !data && $('overview').getAttribute('aria-busy') !== 'true') load();
  if (!preservePosition) window.scrollTo(0, 0);
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
  const { view, id } = currentRoute();
  if (view === 'post-detail' && id && data) showPost({ id, title: $('detail-title').textContent }, data.publication, true);
});
if (!localView(currentRoute().view)) {
  load();
}
