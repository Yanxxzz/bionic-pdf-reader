import {savedPosition} from './navigation.mjs';
import {bookmarkPrefix} from './reading-progress.mjs';

const format = 'bionic-pdf-progress/1';
const documentHash = /^[A-Za-z0-9+/]{43}=$/;
export const settingsKey = 'bionic-pdf-settings';

export function makeBackup(storage, settings) {
  const bookmarks = {};
  for (let i = 0; i < storage.length; i++) {
    const key = storage.key(i);
    if (!key.startsWith(bookmarkPrefix)) continue;
    const hash = key.slice(bookmarkPrefix.length);
    if (documentHash.test(hash)) bookmarks[hash] = savedPosition(storage.getItem(key), Number.MAX_SAFE_INTEGER, 'fit');
  }
  return {format, settings, bookmarks};
}

export function restoreBackup(data, storage, preferences) {
  if (data?.format !== format || !data.settings || typeof data.settings !== 'object' || Array.isArray(data.settings) ||
      !data.bookmarks || typeof data.bookmarks !== 'object' || Array.isArray(data.bookmarks)) {
    throw new Error('请选择由本阅读器导出的进度备份。');
  }
  const entries = Object.entries(data.bookmarks);
  const changes = entries.map(([hash, position]) => {
    if (!documentHash.test(hash) || !Number.isSafeInteger(position?.number) || position.number < 1) {
      throw new Error('备份中的阅读位置无效。');
    }
    const key = bookmarkPrefix + hash;
    return [key, JSON.stringify(savedPosition(position, Number.MAX_SAFE_INTEGER, 'fit')), storage.getItem(key)];
  });
  changes.push([settingsKey, JSON.stringify(preferences), storage.getItem(settingsKey)]);
  let written = 0;
  try {
    for (const [key, value] of changes) {
      storage.setItem(key, value);
      written++;
    }
  } catch (error) {
    for (const [key, , previous] of changes.slice(0, written).reverse()) {
      if (previous === null) storage.removeItem(key);
      else storage.setItem(key, previous);
    }
    throw error;
  }
  return entries.length;
}
