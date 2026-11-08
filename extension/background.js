chrome.action.onClicked.addListener(tab => {
  chrome.tabs.create({url: chrome.runtime.getURL('reader.html#current-tab'), windowId: tab.windowId, openerTabId: tab.id});
});
