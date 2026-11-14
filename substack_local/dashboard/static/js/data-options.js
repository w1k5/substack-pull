import { $ } from './shared.js';

export function setupDataOptions() {
  const options = $('data-options');
  const status = $('local-action-status');
  const message = $('local-action-message');
  const buttons = [...options.querySelectorAll('[data-local-action]')];
  let running = false;

  options.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !options.open) return;
    options.open = false;
    options.querySelector('summary').focus();
  });
  document.addEventListener('click', (event) => {
    if (!options.contains(event.target)) options.open = false;
  });
  $('dismiss-local-action').addEventListener('click', () => { status.hidden = true; });

  for (const button of buttons) {
    button.addEventListener('click', async () => {
      if (running) return;
      running = true;
      const action = button.dataset.localAction;
      if (options.open) options.querySelector('summary').focus();
      options.open = false;
      const pending = {
        open: 'Opening the data folder…',
        export: 'Creating backup ZIP…',
        'clear-cache': 'Clearing temporary cache…',
      };
      message.textContent = pending[action];
      status.hidden = false;
      try {
        const response = await fetch('/api/local-data/' + action, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Could not complete the action.');
        message.textContent = action === 'export' ? `Backup ZIP saved to ${result.path}`
          : action === 'clear-cache' ? 'Temporary cache cleared.' : 'Opened the data folder.';
      } catch (error) {
        message.textContent = error.message;
      } finally {
        running = false;
        status.hidden = false;
      }
    });
  }
}
