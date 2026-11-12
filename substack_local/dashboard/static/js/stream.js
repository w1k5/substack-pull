// Only expose progress counts until the server sends the complete comparison.
export async function readComparison(response, onProgress) {
  if (!response.ok) {
    const result = await response.json();
    throw new Error(result.error || 'Could not load comparison');
  }
  if (!response.body) throw new Error('This browser cannot read comparison updates.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  let finalResult = null;
  while (true) {
    const { value, done } = await reader.read();
    pending += decoder.decode(value || new Uint8Array(), { stream: !done });
    let newline;
    while ((newline = pending.indexOf('\n')) !== -1) {
      const line = pending.slice(0, newline);
      pending = pending.slice(newline + 1);
      if (!line) continue;
      const event = JSON.parse(line);
      if (event.type === 'error') throw new Error(event.data.error || 'Could not load comparison');
      if (event.type === 'progress') onProgress?.({
        considered: event.data?.considered,
        total: event.data?.total,
        target: event.data?.target,
      });
      if (event.type === 'done') finalResult = event.data;
    }
    if (done) break;
  }
  if (!finalResult) throw new Error('The comparison ended before it finished.');
  return finalResult;
}
