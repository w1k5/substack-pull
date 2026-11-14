import { $, fmt } from '../shared.js';

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}
function link(path, text) {
  const node = element('a', '', text);
  node.href = path;
  node.dataset.route = '';
  return node;
}
function delta(change) {
  if (change?.percent == null) return 'Previous period unavailable';
  return (change.percent > 0 ? '+' : '') + change.percent.toFixed(1) + '% vs prior period';
}
export function renderEditorialOverview(data, latest) {
  const pulse = $('editorial-pulse');
  pulse.replaceChildren();
  for (const [label, key, unit] of [
    ['AUDIENCE GROWTH', 'subscribers', 'new subscribers'],
    ['REACH', 'views', 'publication views'],
  ]) {
    const block = element('div', key === 'subscribers' ? 'editorial-primary' : 'editorial-secondary');
    block.append(element('span', 'eyebrow', label),
      element('strong', '', fmt(data.totals?.[key])),
      element('span', '', unit + ' in this period'),
      element('small', '', delta(data.briefing?.changes?.[key])));
    pulse.append(block);
  }
  const findings = $('editorial-highlights');
  findings.replaceChildren();
  const observations = [
    ...(data.editorial?.observations || []),
    ...(latest?.note_observation ? [latest.note_observation] : []),
  ];
  findings.hidden = !observations.length;
  findings.parentElement.classList.toggle('single', !observations.length);
  const heading = element('div', 'editorial-findings-heading');
  heading.append(element('span', 'eyebrow', 'ONE THING TO NOTICE'));
  findings.append(heading);
  for (const item of observations.slice(0, 1)) {
    const row = element('div', 'editorial-finding');
    row.append(link(item.path, item.title));
    const comparison = item.comparison;
    if (comparison) {
      const figures = element('dl', 'editorial-finding-figures');
      for (const [label, value] of [['New subscribers', comparison.subscribers], ['Publication views', comparison.views]]) {
        const figure = element('div');
        figure.append(element('dt', '', label), element('dd', '', value));
        figures.append(figure);
      }
      row.append(element('p', '', comparison.days
        ? `Compared with the previous ${comparison.days} days` : 'Compared with the previous period'), figures);
      if (comparison.yield) {
        const context = element('p', 'editorial-finding-yield');
        context.append(element('strong', '', comparison.yield.current),
          ` subscribers per 1,000 views · ${comparison.yield.previous} previously`);
        row.append(context);
      }
    } else {
      row.append(element('p', '', item.detail));
    }
    findings.append(row);
  }
}
