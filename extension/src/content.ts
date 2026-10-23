import { detectOpenEmail } from './detection';

let last = '';
let timer: number | undefined;
function sendCandidate() {
  const candidate = detectOpenEmail(document, location.href);
  const signature = JSON.stringify(candidate);
  if (signature === last || (!candidate.messageIds.length && !candidate.threadId)) return;
  last = signature;
  void chrome.runtime.sendMessage({ type: 'GMAIL_CANDIDATE', candidate }).catch(() => {});
}
function schedule() { window.clearTimeout(timer); timer = window.setTimeout(sendCandidate, 400); }
new MutationObserver(schedule).observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ['data-message-id', 'data-legacy-message-id', 'data-thread-id'] });
window.addEventListener('hashchange', schedule);
schedule();
