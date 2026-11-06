export function comparisonMetrics(className, entries) {
  const metrics = document.createElement('div');
  metrics.className = className;
  for (const [value, label] of entries) {
    const item = document.createElement('span');
    const amount = document.createElement('b');
    amount.textContent = value;
    const caption = document.createElement('small');
    caption.textContent = label;
    item.append(amount, caption);
    metrics.append(item);
  }
  return metrics;
}

export function comparisonSelectionHeading(className, kind, count, onClear) {
  const heading = document.createElement('div');
  heading.className = className;
  const label = document.createElement('strong');
  label.textContent = count === 1 ? `Selected ${kind}` : `2 ${kind}s selected`;
  const clear = document.createElement('button');
  clear.type = 'button';
  clear.className = 'refresh';
  clear.textContent = 'Clear selection';
  clear.addEventListener('click', onClear);
  heading.append(label, clear);
  return heading;
}
