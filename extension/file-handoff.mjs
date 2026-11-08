// A reload consumes the selected File once. A closed tab leaves only a short-lived
// memory reference. No PDF content is written to browser storage.
const pending = new Map();
export function exchangeFile({documentId, file}) {
  if (typeof documentId !== 'string') return null;
  const previous = pending.get(documentId);
  if (previous) clearTimeout(previous.timer);
  if (file instanceof File) {
    const timer = setTimeout(() => pending.delete(documentId), 30000);
    pending.set(documentId, {file, timer});
    return null;
  }
  pending.delete(documentId);
  return previous?.file ?? null;
}

if (typeof window === 'undefined') {
  self.onmessage = ({data, ports}) => {
    const file = exchangeFile(data);
    ports[0]?.postMessage(file);
  };
}
