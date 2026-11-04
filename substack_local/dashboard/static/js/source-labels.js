// Names and descriptions follow Substack's published metric definitions.
// Keep post traffic and subscriber acquisition separate: "Email" on a post
// means a newsletter view, while "Email clicks" on Sources means a link visit.
export function sourceLabel(raw, context = 'traffic', parent = '') {
  const name = String(raw || '').trim();
  const key = name.toLowerCase().replace(/[\s_]+/g, '-');
  if (key === 'direct') return {
    name: 'Direct or unidentified',
    detail: 'Typed address, bookmark, or a visit without referral data.',
  };
  if (key === 'direct-to-app') return {
    name: 'Unknown external link → app',
    detail: 'Opened in the Substack app from an external link; its origin was not identified.',
  };
  if (key === 'email-clicks' || (key === 'email' && context !== 'post')) return {
    name: 'Links in email',
    detail: 'Visits from links in an email, including forwarded messages.',
  };
  if (key === 'email' && context === 'post') return {
    name: 'Newsletter email',
    detail: 'This post was opened and viewed in an email from the publication.',
  };
  if (key === 'email-opens') return {
    name: 'Newsletter email opens',
    detail: 'Views from opening a publication email; separate from clicking a link in an email.',
  };
  if (key === 'substack-app') return {
    name: 'Substack app · surface unknown',
    detail: 'The referrer identifies the app, but not which part of the app sent the reader.',
  };
  if (key === 'open.substack.com') return {
    name: 'Substack link · page unknown',
    detail: 'The recorded referrer is open.substack.com; it does not identify an originating page or feature.',
  };
  if (key === 'other' && parent.toLowerCase() === 'substack') return {
    name: 'Other links',
    detail: 'Links elsewhere on Substack, such as a profile, inbox, or direct message.',
  };
  if (key === 'other' && context === 'post') return {
    name: 'Small sources combined',
    detail: 'Substack combines traffic sources that individually account for less than 1% of views.',
  };
  if (key === 'onboarding' && context === 'growth') return {
    name: 'New-user recommendations',
    detail: 'Recommendations shown as someone first joined Substack.',
  };
  if (key === 'trackbacks' && context === 'growth') return {
    name: 'Links from other Substacks',
    detail: 'A link on another Substack, such as a post, comment, or homepage sidebar.',
  };
  if (key === 'share' && context === 'growth') return {
    name: 'Copied Substack links',
    detail: 'Readers arrived through a link copied using Substack’s share action.',
  };
  return { name: name || 'Unidentified', detail: '' };
}
