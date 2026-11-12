const tabViewKey = 'bionic-tab-view';
export const bookmarkPrefix = 'bionic-page-sha256-';

export async function digestBytes(data) {
  const digest = await crypto.subtle.digest('SHA-256', data);
  return btoa(String.fromCharCode(...new Uint8Array(digest)));
}

// A range-loaded PDF already has the bytes needed to open it. Keep only their offsets
// and hashes so a refresh can check the pending bookmark without a second download.
export async function receivedByteProof(bytes, ranges) {
  const parts = await Promise.all(ranges.map(async ([start, end]) =>
    [start, end, await digestBytes(bytes.subarray(start, end))]));
  return {length:bytes.length, parts};
}

export function streamByteProof(stream) {
  if (stream.isDataLoaded !== false) return digestBytes(stream.bytes).then(key => ({key}));
  const ranges = stream.progressiveDataLength ? [[0, stream.progressiveDataLength]] : [];
  for (const index of [...stream._loadedChunks].sort((a, b) => a - b)) {
    const start = index * stream.chunkSize;
    const end = Math.min(start + stream.chunkSize, stream.bytes.length);
    const previous = ranges.at(-1);
    if (previous && start <= previous[1]) previous[1] = Math.max(previous[1], end);
    else ranges.push([start, end]);
  }
  return receivedByteProof(stream.bytes, ranges);
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
  #proof;

  constructor(file, resume, handedBack, proof = null) {
    this.#source = file.sourceKey ? {sourceKey:file.sourceKey} : {local:true};
    this.#source.documentId = crypto.randomUUID();
    this.#resume = resume;
    this.#proof = proof;
    // Before content hashes, the only conclusive identity was the exact File
    // handed back by the previous tab using its one-time documentId.
    this.#legacyHandoff = handedBack && resume?.local && !resume.contentKey;
  }

  get documentId() { return this.#source.documentId; }

  async matchesPending(bytes, contentKey) {
    const saved = this.#resume;
    if (!this.#source.sourceKey || saved?.sourceKey !== this.#source.sourceKey) return false;
    const proof = saved.pending;
    if (proof?.etag && proof.etag !== this.#proof?.etag) return false;
    if (proof?.key) return proof.key === contentKey;
    if (proof?.length !== bytes.length || !Array.isArray(proof.parts) || !proof.parts.length) return false;
    for (const part of proof.parts) {
      if (!Array.isArray(part)) return false;
      const [start, end, expected] = part;
      if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || start >= end ||
          end > bytes.length || await digestBytes(bytes.subarray(start, end)) !== expected) return false;
    }
    return true;
  }

  identify(contentKey, restoreTab = true, pendingMatches = false) {
    this.#source.contentKey = contentKey;
    delete this.#source.pending;
    this.#last = null;
    if (!restoreTab) return null;
    const resume = this.#resume;
    if (resume && (resume.contentKey === contentKey || this.#legacyHandoff || pendingMatches)) {
      this.#source.documentId = resume.documentId;
      return resume.position;
    }
    // A legacy global fingerprint can describe several unrelated PDFs.
    try { return localStorage.getItem(bookmarkPrefix + contentKey); } catch { return null; }
  }

  save(position, moved = false) {
    if (this.#source.sourceKey && !this.#source.contentKey) {
      if (!moved && this.#resume && !this.#source.pending) return; // Loading page one must not erase a reload.
      if (moved && this.#proof && !this.#source.pending) {
        this.#source.pending = this.#proof;
        this.#last = null;
      }
    }
    const value = JSON.stringify(position);
    if (value === this.#last) return;
    this.#last = value;
    try { sessionStorage.setItem(tabViewKey, JSON.stringify({...this.#source, position})); }
    catch { clearTabView(); }
    if (this.#source.contentKey) {
      try { localStorage.setItem(bookmarkPrefix + this.#source.contentKey, value); } catch {}
    }
  }
}
