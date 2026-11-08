const tabViewKey = 'bionic-tab-view';

export async function digestBytes(data) {
  const digest = await crypto.subtle.digest('SHA-256', data);
  return btoa(String.fromCharCode(...new Uint8Array(digest)));
}

export function savedTabView() {
  try { return JSON.parse(sessionStorage.getItem(tabViewKey)); } catch { return null; }
}

export function clearTabView() {
  try { sessionStorage.removeItem(tabViewKey); } catch {}
}

// A tab keeps its own navigation history. Byte-identical PDFs opened in different
// ways share the persistent position, even if they have been renamed or moved.
export class ReadingProgress {
  #source;
  #resume;
  #legacyHandoff;
  #last;

  constructor(file, resume, handedBack) {
    this.#source = file.sourceKey ? {sourceKey:file.sourceKey} : {local:true};
    this.#source.documentId = crypto.randomUUID();
    this.#resume = resume;
    // Before content hashes, the only conclusive identity was the exact File
    // handed back by the previous tab using its one-time documentId.
    this.#legacyHandoff = handedBack && resume?.local && !resume.contentKey;
  }

  get documentId() { return this.#source.documentId; }

  identify(contentKey, restoreTab = true) {
    this.#source.contentKey = contentKey;
    this.#last = null;
    if (!restoreTab) return null;
    const resume = this.#resume;
    if (resume && (resume.contentKey === contentKey || this.#legacyHandoff)) {
      this.#source.documentId = resume.documentId;
      return resume.position;
    }
    // A legacy global fingerprint can describe several unrelated PDFs.
    try { return localStorage.getItem('bionic-page-sha256-' + contentKey); } catch { return null; }
  }

  save(position) {
    const value = JSON.stringify(position);
    if (value === this.#last) return;
    this.#last = value;
    try { sessionStorage.setItem(tabViewKey, JSON.stringify({...this.#source, position})); }
    catch { clearTabView(); }
    if (this.#source.contentKey) {
      try { localStorage.setItem('bionic-page-sha256-' + this.#source.contentKey, value); } catch {}
    }
  }
}
