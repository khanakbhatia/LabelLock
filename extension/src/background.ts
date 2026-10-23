chrome.action.onClicked.addListener(tab => {
  if (!tab.id || !tab.url?.startsWith('https://mail.google.com/')) return;
  void chrome.sidePanel.open({ tabId: tab.id });
});
chrome.runtime.onMessage.addListener((message: { type?: string; candidate?: unknown }, sender) => {
  if (message.type === 'GMAIL_CANDIDATE' && sender.tab?.url?.startsWith('https://mail.google.com/') && message.candidate) {
    void chrome.storage.session.set({ detected_email: message.candidate });
  }
});
