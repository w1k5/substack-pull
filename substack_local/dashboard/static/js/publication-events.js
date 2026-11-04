import { date } from './shared.js';

export function publicationEventList(items, navigate, showDay = false) {
  const list = document.createElement('ul');
  items.forEach((item) => {
    const li = document.createElement('li');
    const kind = document.createElement('span');
    kind.className = `event-kind ${item.type === 'note' ? 'note-kind' : 'post-kind'}`;
    kind.textContent = item.type === 'note' ? 'Note' : 'Post';
    const available = /^\d+$/.test(String(item.id));
    const action = document.createElement(available ? 'button' : 'span');
    action.className = 'event-analysis';
    const title = document.createElement('span');
    title.className = 'event-title';
    title.textContent = showDay ? `${date(item.day)} · ${item.title}` : item.title;
    action.append(title);
    if (available) {
      action.type = 'button';
      const prompt = document.createElement('small');
      prompt.textContent = 'View analysis →';
      action.append(prompt);
      action.addEventListener('click', () =>
        navigate(`/${item.type === 'note' ? 'notes' : 'posts'}/${item.id}`));
    }
    li.append(kind, action);
    list.append(li);
  });
  return list;
}
