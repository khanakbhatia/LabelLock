import type { GmailTransport } from './gmail';

export interface DetectedEmail { messageIds: string[]; threadId?: string }
const gmailId = /^[a-zA-Z0-9_-]{10,}$/;
export function detectOpenEmail(doc: Pick<Document, 'querySelectorAll'>, locationHref: string): DetectedEmail {
  const hash = new URL(locationHref).hash;
  const suffix = hash.match(/(?:^|\/)([a-zA-Z0-9_-]{10,})(?:[/?]|$)/)?.[1];
  const ids: string[] = [];
  for (const element of doc.querySelectorAll('[data-message-id], [data-legacy-message-id], [data-thread-id]')) {
    if (!suffix && element.getAttribute('aria-expanded') !== 'true' && !element.closest('[aria-expanded="true"]')) continue;
    const candidate = element.getAttribute('data-message-id') ?? element.getAttribute('data-legacy-message-id');
    if (candidate && gmailId.test(candidate) && !ids.includes(candidate)) ids.push(candidate);
  }
  return { messageIds: ids, threadId: suffix };
}

export async function verifyDetectedEmail(candidate: DetectedEmail, gmail: GmailTransport): Promise<string | null> {
  for (const id of candidate.messageIds) {
    try {
      const message = await gmail.getMessage(id);
      if (!candidate.threadId || message.threadId === candidate.threadId) return message.id;
    } catch { /* Gmail markup may hold a stale DOM id. */ }
  }
  if (candidate.threadId) {
    try {
      const thread = await gmail.getThread(candidate.threadId);
      const id = thread.messages?.at(-1)?.id;
      if (id) return (await gmail.getMessage(id)).id;
    } catch { /* The recent-email list remains available. */ }
  }
  return null;
}
