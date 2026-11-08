chrome.action.onClicked.addListener(tab => {
  chrome.tabs.create({url: chrome.runtime.getURL('reader.html#current-tab'), windowId: tab.windowId, openerTabId: tab.id});
});

// Firefox extension pages use an event page in place of a service worker.
if (typeof window !== 'undefined' && globalThis.browser?.runtime) {
  const handoff = import('./file-handoff.mjs');
  browser.runtime.onMessage.addListener((message, sender) => {
    if (message?.kind === 'selected-file' && sender.url?.split(/[?#]/, 1)[0] === browser.runtime.getURL('reader.html')) {
      return handoff.then(({exchangeFile}) => exchangeFile(message));
    }
  });
}
