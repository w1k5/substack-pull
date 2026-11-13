import { $, date, fmt } from '../shared.js';

function element(tag, value) {
  const node = document.createElement(tag);
  if (value != null) node.textContent = value;
  return node;
}

let items = [];
const recordLabels = {notes: 'Note', posts: 'Post', sources: 'Subscriber sources'};

async function request(path = '', options) {
  const response = await fetch('/api/local-data' + path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Could not access local data.');
  return result;
}

function renderIndex() {
  const query = $('backup-search').value.trim().toLowerCase();
  const rows = items.filter((item) => [item.title, item.group, item.category, item.status]
    .some((value) => value.toLowerCase().includes(query)));
  const body = $('backup-rows');
  body.replaceChildren();
  $('backup-count').textContent = rows.length ? `${rows.length} saved items` : 'No matching backups.';
  for (const item of rows) {
    const row = element('tr');
    const title = element('td');
    if (item.markdown) {
      const button = element('button', item.title);
      button.type = 'button';
      button.className = 'note-compare-link';
      button.addEventListener('click', async () => {
        const dialog = $('backup-preview');
        $('backup-preview-title').textContent = item.title;
        $('backup-preview-body').textContent = 'Opening backup…';
        dialog.showModal();
        try {
          const result = await request('/markdown?file=' + encodeURIComponent(item.markdown));
          $('backup-preview-body').textContent = result.markdown;
        } catch (error) {
          $('backup-preview-body').textContent = error.message;
        }
      });
      title.append(button);
    } else {
      title.textContent = item.title;
    }
    row.append(title, element('td', date(item.date)), element('td', item.group),
      element('td', item.status === 'present' ? item.category : `${item.category} · ${item.status}`));
    body.append(row);
  }
}

export async function renderLocalData() {
  const status = $('local-data-status');
  status.textContent = 'Reading local files…';
  try {
    const data = await request();
    const groups = $('local-data-groups');
    groups.replaceChildren();
    for (const group of data.groups) {
      const row = element('tr');
      row.append(element('th', group.label), element('td', group.path),
        element('td', group.bytes ? `${(group.bytes / 1024).toLocaleString(undefined, {maximumFractionDigits: 1})} KB` : '0 KB'),
        element('td', group.last_sync_at ? new Date(group.last_sync_at).toLocaleString() : '—'));
      groups.append(row);
    }
    items = data.items;
    renderIndex();
    const picker = $('saved-analytics-record');
    const selected = picker.value;
    picker.replaceChildren(new Option(data.analytics.length ? 'Choose a record' : 'No saved measurements yet', ''));
    for (const {kind, key} of data.analytics)
      picker.append(new Option(`${recordLabels[kind]} · ${key.replace('_', ' to ')}`, `${kind}/${key}`));
    picker.value = [...picker.options].some((option) => option.value === selected) ? selected : '';
    if (!picker.value) $('saved-analytics-detail').replaceChildren();
    picker.disabled = !data.analytics.length;
    status.textContent = '';
  } catch (error) {
    status.textContent = error.message;
  }
}

export function setupLocalData() {
  $('backup-search').addEventListener('input', renderIndex);
  $('saved-analytics-record').addEventListener('change', async (event) => {
    const selection = event.target.value;
    const detail = $('saved-analytics-detail');
    detail.replaceChildren();
    if (!selection) return;
    const [kind, key] = selection.split('/');
    detail.textContent = 'Opening saved measurements…';
    try {
      const record = await request('/analytics?' + new URLSearchParams({kind, key}));
      if (event.target.value !== selection) return;
      const data = record.data;
      const rows = kind === 'notes'
        ? Object.entries(data.checkpoints).map(([hour, point]) => [`${hour} hours`, point.impressions, point.typical_impressions])
        : kind === 'posts'
          ? data.daily.filter((day) => [1, 3, 7].includes(day.day)).map((day) => [`Day ${day.day}`, day.views, day.signups])
          : data.growth_sources.map((source) => [[source.parent, source.name].filter(Boolean).join(' / '), source.subscribers]);
      const headings = kind === 'notes' ? ['Age', 'Impressions', 'Typical impressions']
        : kind === 'posts' ? ['Checkpoint', 'Views', 'Signups'] : ['Source', 'New subscribers credited'];
      const table = element('table');
      const header = table.createTHead().insertRow();
      for (const label of headings) header.append(element('th', label));
      const body = table.createTBody();
      for (const [label, ...values] of rows) {
        const row = body.insertRow();
        row.append(element('th', label), ...values.map((value) => element('td', fmt(value))));
      }
      const scroll = element('div');
      scroll.className = 'table-scroll';
      scroll.append(table);
      detail.replaceChildren(element('p', `Saved ${new Date(record.saved_at).toLocaleString()}`), scroll);
    } catch (error) {
      if (event.target.value === selection) detail.textContent = error.message;
    }
  });
  for (const button of document.querySelectorAll('[data-local-action]')) {
    button.addEventListener('click', async () => {
      const action = button.dataset.localAction;
      const status = $('local-data-status');
      button.disabled = true;
      status.textContent = action === 'export' ? 'Creating backup ZIP…' : '';
      try {
        const result = await request('/' + action, {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}',
        });
        if (action === 'clear-cache') await renderLocalData();
        status.textContent = action === 'export' ? `Backup ZIP saved to ${result.path}`
          : action === 'clear-cache' ? 'Temporary cache cleared.' : 'Opened the data folder.';
      } catch (error) {
        status.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
  }
}
