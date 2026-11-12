// Add direct GitHub Release asset URLs after validating the packaged builds.
const downloads = {
  mac: null,
  windows: null,
};

for (const [platform, url] of Object.entries(downloads)) {
  if (!url) continue;
  const button = document.getElementById(`download-${platform}`);
  button.href = url;
  button.hidden = false;
}

const available = Object.values(downloads).filter(Boolean).length;
if (available) {
  document.getElementById('download-status').textContent = available === 2
    ? 'Beta downloads are available for Mac and Windows.'
    : 'A beta download is available. The other platform is in preparation.';
}
