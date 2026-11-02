export const $ = (id) => document.getElementById(id);
export const fmt = (n) => (n == null ? '—' : Math.round(Number(n)).toLocaleString());
export const pct = (n) =>
  n == null || !Number.isFinite(Number(n)) ? '—' : `${(Number(n) * 100).toFixed(1)}%`;
export const date = (value) =>
  value
    ? new Date(value.length === 10 ? `${value}T12:00:00` : value).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      })
    : '—';

export function cell(row, content, className = '') {
  const td = document.createElement('td');
  td.className = className;
  if (content instanceof Node) td.append(content);
  else td.textContent = content;
  row.append(td);
  return td;
}

export function loadingIndicator(message) {
  const root = document.createElement('div');
  root.className = 'loading-state';
  root.setAttribute('role', 'status');
  const spinner = document.createElement('span');
  spinner.className = 'spinner';
  spinner.setAttribute('aria-hidden', 'true');
  const label = document.createElement('span');
  label.textContent = message;
  root.append(spinner, label);
  return root;
}

export const number = (n) => (n == null ? null : Number(n));
export function section(title) {
  const el = document.createElement('section');
  el.className = 'detail-section';
  const h = document.createElement('h3');
  h.textContent = title;
  el.append(h);
  return el;
}
