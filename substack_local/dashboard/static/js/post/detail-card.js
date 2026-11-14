export function detailHeader(kind, description, refresh) {
  const heading = document.createElement('div');
  heading.className = 'note-detail-heading';
  const copy = document.createElement('div');
  const title = document.createElement('h2');
  title.textContent = kind;
  const meta = document.createElement('p');
  meta.textContent = description;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'refresh';
  button.textContent = `↻ Refresh ${kind}`;
  button.disabled = true;
  button.addEventListener('click', refresh);
  copy.append(title, meta);
  heading.append(copy, button);
  return { heading, title, meta, button };
}

export function detailCard(label) {
  const card = document.createElement('div');
  card.className = 'note-reach-card';
  const heading = document.createElement('div');
  heading.className = 'note-reach-heading';
  const title = document.createElement('strong');
  title.textContent = label;
  heading.append(title);
  card.append(heading);
  return card;
}

export function metricGroup(title, rows) {
  const section = document.createElement('section');
  section.className = 'note-reach-group';
  const heading = document.createElement('h3');
  heading.textContent = title;
  const metrics = document.createElement('div');
  metrics.className = 'note-reach-metrics';
  for (const [label, value, context] of rows) {
    const item = document.createElement('div');
    const name = document.createElement('span');
    name.textContent = label;
    const amount = document.createElement('strong');
    amount.textContent = value;
    const detail = document.createElement('small');
    detail.textContent = context;
    item.append(name, amount, detail);
    metrics.append(item);
  }
  section.append(heading, metrics);
  return section;
}
