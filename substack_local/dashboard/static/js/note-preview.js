export function notePreview(value, maxLength) {
  const full = String(value || '').replace(/\s+/g, ' ').trim();
  const characters = Array.from(full);
  if (characters.length <= maxLength) return { text: full, truncated: false };
  const start = characters.slice(0, maxLength).join('');
  const lastSpace = start.lastIndexOf(' ');
  const cut = lastSpace > maxLength * .7 ? start.slice(0, lastSpace) : start;
  return { text: `${cut.trimEnd()}…`, truncated: true };
}
