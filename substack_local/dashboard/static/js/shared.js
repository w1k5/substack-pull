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

export function loadingIndicator(message, { completed, total, inline = false } = {}) {
  const root = document.createElement('div');
  root.className = 'loading-state';
  if (inline) root.classList.add('loading-inline');
  root.setAttribute('role', 'status');
  const spinner = document.createElement('span');
  spinner.className = 'spinner';
  spinner.setAttribute('aria-hidden', 'true');
  const label = document.createElement('span');
  label.textContent = message;
  root.append(spinner, label);
  if (Number.isFinite(completed) && Number.isFinite(total) && total > 0) {
    const progress = document.createElement('progress');
    progress.max = total;
    progress.value = Math.max(0, Math.min(completed, total));
    progress.setAttribute('aria-label', message);
    const percent = document.createElement('strong');
    percent.className = 'loading-percent';
    percent.textContent = `${progress.value === total ? 100 : Math.floor(progress.value / total * 100)}%`;
    root.append(progress, percent);
  }
  return root;
}

export function emptyMessage(message) {
  const element = document.createElement('p');
  element.className = 'empty-state';
  element.textContent = message;
  return element;
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

export function setupOutcomeMode(id, onChange) {
  const buttons = [...$(id).querySelectorAll('button[data-mode]')];
  for (const button of buttons) {
    button.addEventListener('click', () => {
      if (button.getAttribute('aria-pressed') === 'true') return;
      for (const choice of buttons) {
        choice.setAttribute('aria-pressed', String(choice === button));
        choice.classList.toggle('active', choice === button);
      }
      onChange(button.dataset.mode === 'rate');
    });
  }
}
