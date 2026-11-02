import { fmt, number } from './common.js';
import { attachNoteInspectors } from './post_notes.js';

export function renderPostTrajectory(rows, notes = []) {
  const panel = document.createElement('div');
  panel.className = 'trajectory-panel';
  const controls = document.createElement('div');
  controls.className = 'trajectory-controls';
  const description = document.createElement('p');
  description.className = 'detail-context';
  description.textContent =
    'Cumulative performance versus similar posts at the same age · latest day may be incomplete';
  const modes = document.createElement('div');
  modes.className = 'trajectory-modes';
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 1000 270');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('role', 'img');
  svg.classList.add('trajectory-chart');
  const legend = document.createElement('div');
  legend.className = 'trajectory-legend';
  legend.innerHTML =
    '<span><i class="actual-key"></i>This post</span><span><i class="typical-key"></i>Typical post</span><span><i class="note-key"></i>Note published</span><span>Select a day to inspect</span>';
  const readout = document.createElement('div');
  readout.className = 'trajectory-readout';
  readout.hidden = true;
  const activity = document.createElement('div');
  activity.className = 'trajectory-notes';
  activity.hidden = true;
  const notesByDay = new Map();
  notes.forEach((note) => {
    if (!notesByDay.has(note.day)) notesByDay.set(note.day, []);
    notesByDay.get(note.day).push(note);
  });
  const draw = (metric) => {
    modes
      .querySelectorAll('button')
      .forEach((button) =>
        button.setAttribute('aria-pressed', String(button.dataset.metric === metric)),
      );
    svg.replaceChildren();
    svg.setAttribute(
      'aria-label',
      `${metric === 'views' ? 'Views' : 'Signups'} for this post and typical posts over the first week`,
    );
    const ns = 'http://www.w3.org/2000/svg',
      left = 65,
      right = 980,
      top = 18,
      bottom = 224;
    const actualKey = `cumulative_${metric}`,
      typicalKey = `avg_cumulative_${metric}`;
    const actual = rows.map((row) => number(row[actualKey]) || 0),
      typical = rows.map((row) => number(row.comps?.[typicalKey]) || 0);
    const largest = Math.max(1, ...actual, ...typical),
      rawStep = largest / 4,
      magnitude = 10 ** Math.floor(Math.log10(rawStep)),
      unit = rawStep / magnitude,
      step = (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 2.5 ? 2.5 : unit <= 5 ? 5 : 10) * magnitude,
      max = step * 4;
    const x = (index) => left + (index * (right - left)) / Math.max(1, rows.length - 1),
      y = (value) => bottom - (value / max) * (bottom - top);
    for (let i = 0; i <= 4; i++) {
      const gy = y(step * i),
        line = document.createElementNS(ns, 'line');
      line.setAttribute('x1', left);
      line.setAttribute('x2', right);
      line.setAttribute('y1', gy);
      line.setAttribute('y2', gy);
      line.setAttribute('class', 'trajectory-grid');
      svg.append(line);
      const label = document.createElementNS(ns, 'text');
      label.setAttribute('x', left - 12);
      label.setAttribute('y', gy + 4);
      label.setAttribute('text-anchor', 'end');
      label.setAttribute('class', 'trajectory-axis');
      label.textContent = new Intl.NumberFormat('en-US', {
        notation: 'compact',
        maximumFractionDigits: 1,
      }).format(step * i);
      svg.append(label);
    }
    const plot = (values, css) => {
      const path = document.createElementNS(ns, 'path');
      path.setAttribute(
        'd',
        `M ${values.map((value, index) => `${x(index)} ${y(value)}`).join(' L ')}`,
      );
      path.setAttribute('class', css);
      svg.append(path);
      values.forEach((value, index) => {
        const point = document.createElementNS(ns, 'circle');
        point.setAttribute('cx', x(index));
        point.setAttribute('cy', y(value));
        point.setAttribute('r', '4');
        point.setAttribute('class', `${css}-point`);
        svg.append(point);
      });
    };
    plot(typical, 'trajectory-typical');
    plot(actual, 'trajectory-actual');
    const typicalLabel = (value) =>
      metric === 'signups'
        ? Number(value).toLocaleString('en-US', {
            minimumFractionDigits: 1,
            maximumFractionDigits: 1,
          })
        : fmt(value);
    const select = (index) => {
      const row = rows[index],
        previous = index ? actual[index - 1] : 0;
      const dailyActual = actual[index] - previous,
        dailyTypical = typical[index] - (index ? typical[index - 1] : 0);
      readout.hidden = false;
      readout.replaceChildren();
      const heading = document.createElement('strong');
      heading.textContent = `Day ${Number(row.day_n) + 1}`;
      const total = document.createElement('span');
      total.textContent = `${fmt(actual[index])} ${metric} · typical ${typicalLabel(typical[index])}`;
      const gain = document.createElement('small');
      gain.textContent = `Added that day: ${fmt(dailyActual)} · typical ${typicalLabel(dailyTypical)}`;
      readout.append(heading, total, gain);
      const dayNotes = notesByDay.get(row.dt?.slice(0, 10)) || [];
      activity.replaceChildren();
      activity.hidden = !dayNotes.length;
      if (dayNotes.length) {
        const title = document.createElement('strong');
        title.textContent = `${dayNotes.length} Note${dayNotes.length === 1 ? '' : 's'} published this day`;
        const list = document.createElement('ul');
        dayNotes.forEach((note) => {
          const li = document.createElement('li');
          const time = document.createElement('time');
          time.textContent = new Date(note.date).toLocaleTimeString('en-US', {
            hour: 'numeric',
            minute: '2-digit',
            timeZone: 'America/New_York',
          });
          const name = document.createElement('span');
          name.className = 'note-title';
          name.textContent = note.title;
          name.title = note.title;
          li.append(time, name);
          list.append(li);
        });
        activity.append(title, list);
        const buttons = attachNoteInspectors(list, dayNotes, activity);
        if (buttons.length === 1) buttons[0].click();
      }
    };
    rows.forEach((row, index) => {
      const label = document.createElementNS(ns, 'text');
      label.setAttribute('x', x(index));
      label.setAttribute('y', 256);
      label.setAttribute('text-anchor', 'middle');
      label.setAttribute('class', 'trajectory-axis');
      label.textContent = `D${Number(row.day_n) + 1}`;
      svg.append(label);
      const hit = document.createElementNS(ns, 'rect');
      hit.setAttribute(
        'x',
        x(index) - Math.min(36, ((right - left) / Math.max(2, rows.length)) * 0.42),
      );
      hit.setAttribute('y', top);
      hit.setAttribute('width', Math.min(72, ((right - left) / Math.max(2, rows.length)) * 0.84));
      hit.setAttribute('height', bottom - top + 18);
      hit.setAttribute('fill', 'transparent');
      hit.setAttribute('tabindex', '0');
      hit.setAttribute('role', 'button');
      hit.setAttribute('aria-label', `Show day ${Number(row.day_n) + 1} ${metric}`);
      hit.addEventListener('click', () => select(index));
      hit.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          select(index);
        }
      });
      svg.append(hit);
      const count = (notesByDay.get(row.dt?.slice(0, 10)) || []).length;
      if (count) {
        const marker = document.createElementNS(ns, 'circle');
        marker.setAttribute('cx', x(index));
        marker.setAttribute('cy', 237);
        marker.setAttribute('r', count > 1 ? 9 : 6);
        marker.setAttribute('class', 'trajectory-note-marker');
        svg.append(marker);
        if (count > 1) {
          const text = document.createElementNS(ns, 'text');
          text.setAttribute('x', x(index));
          text.setAttribute('y', 240);
          text.setAttribute('text-anchor', 'middle');
          text.setAttribute('class', 'trajectory-note-count');
          text.textContent = count;
          svg.append(text);
        }
      }
    });
    readout.hidden = true;
    activity.hidden = true;
  };
  for (const [metric, label] of [
    ['views', 'Views'],
    ['signups', 'Signups'],
  ]) {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.metric = metric;
    button.textContent = label;
    button.addEventListener('click', () => draw(metric));
    modes.append(button);
  }
  const caveat = document.createElement('p');
  caveat.className = 'footnote';
  caveat.textContent =
    'Note markers show when you published Notes; they do not establish that a Note drove this post’s performance.';
  controls.append(description, modes);
  panel.append(controls, svg, legend, readout, activity, caveat);
  draw('views');
  return panel;
}
