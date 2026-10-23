export interface GmailPart {
  mimeType?: string;
  filename?: string;
  headers?: { name: string; value: string }[];
  body?: { data?: string; attachmentId?: string; size?: number };
  parts?: GmailPart[];
}
export interface GmailMessage {
  id: string;
  threadId: string;
  internalDate?: string;
  payload?: GmailPart;
}
export interface EmailCard {
  id: string;
  threadId: string;
  from: string;
  subject: string;
  receivedAt: string;
  attachmentNames: string[];
}
export interface IngestAttachment { filename: string; mime_type: 'application/pdf'; content_base64: string }
export interface IngestEmailRequest {
  gmail_message_id: string;
  thread_id: string;
  from: string;
  subject: string;
  body_text: string;
  received_at: string;
  attachments: IngestAttachment[];
}

export function base64urlToBase64(value: string): string {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/').replace(/=+$/, '');
  return normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
}
export function decodeBase64url(value: string): Uint8Array {
  const binary = atob(base64urlToBase64(value));
  return Uint8Array.from(binary, char => char.charCodeAt(0));
}
export function walkParts(part?: GmailPart): GmailPart[] {
  if (!part) return [];
  return [part, ...(part.parts ?? []).flatMap(walkParts)];
}
const header = (part: GmailPart | undefined, name: string) => part?.headers?.find(item => item.name.toLowerCase() === name.toLowerCase())?.value ?? '';
const pdfParts = (message: GmailMessage) => walkParts(message.payload).filter(part => part.mimeType?.toLowerCase() === 'application/pdf' && !!part.filename);
export function emailCard(message: GmailMessage): EmailCard {
  const dateHeader = header(message.payload, 'Date');
  const headerDate = Date.parse(dateHeader);
  return {
    id: message.id, threadId: message.threadId,
    from: header(message.payload, 'From'), subject: header(message.payload, 'Subject') || '(No subject)',
    receivedAt: new Date(Number.isNaN(headerDate) ? Number(message.internalDate ?? Date.now()) : headerDate).toISOString(),
    attachmentNames: pdfParts(message).map(part => part.filename!),
  };
}

export async function toIngestRequest(message: GmailMessage, attachmentData: (messageId: string, attachmentId: string) => Promise<string>): Promise<IngestEmailRequest> {
  const card = emailCard(message);
  const parts = pdfParts(message);
  if (!parts.length || parts.length > 10) throw new Error('The email needs 1–10 PDF attachments.');
  const attachments = await Promise.all(parts.map(async part => {
    const data = part.body?.data ?? (part.body?.attachmentId ? await attachmentData(message.id, part.body.attachmentId) : '');
    const bytes = decodeBase64url(data);
    if (bytes.length > 5 * 1024 * 1024 || new TextDecoder().decode(bytes.slice(0, 5)) !== '%PDF-') {
      throw new Error(`${part.filename} must be a PDF of 5 MB or less.`);
    }
    return { filename: part.filename!, mime_type: 'application/pdf' as const, content_base64: base64urlToBase64(data) };
  }));
  const bodyPart = walkParts(message.payload).find(part => part.mimeType?.toLowerCase() === 'text/plain' && part.body?.data);
  const body_text = bodyPart?.body?.data ? new TextDecoder().decode(decodeBase64url(bodyPart.body.data)) : '';
  return { gmail_message_id: message.id, thread_id: message.threadId, from: card.from, subject: card.subject, body_text, received_at: card.receivedAt, attachments };
}

export interface GmailTransport {
  list(): Promise<string[]>;
  getMessage(id: string): Promise<GmailMessage>;
  getThread(id: string): Promise<{ messages?: GmailMessage[] }>;
  getAttachment(messageId: string, attachmentId: string): Promise<string>;
}
export async function recentSupplierEmails(gmail: GmailTransport): Promise<EmailCard[]> {
  const ids = await gmail.list();
  const messages = await Promise.all(ids.slice(0, 10).map(id => gmail.getMessage(id)));
  return messages.filter(message => pdfParts(message).length > 0).map(emailCard);
}

const gmailBase = 'https://gmail.googleapis.com/gmail/v1/users/me';
export function createGmailTransport(getToken: () => Promise<string>, fetcher: typeof fetch = fetch): GmailTransport {
  async function get<T>(path: string): Promise<T> {
    const response = await fetcher(`${gmailBase}${path}`, { headers: { Authorization: `Bearer ${await getToken()}` } });
    if (!response.ok) throw new Error(`Gmail request failed (${response.status}). Check your Gmail connection and try again.`);
    return response.json() as Promise<T>;
  }
  return {
    async list() {
      const result = await get<{ messages?: { id: string }[] }>('/messages?maxResults=10&q=' + encodeURIComponent('in:inbox has:attachment filename:pdf'));
      return (result.messages ?? []).map(message => message.id);
    },
    getMessage: id => get(`/messages/${encodeURIComponent(id)}?format=full`),
    getThread: id => get(`/threads/${encodeURIComponent(id)}?format=metadata`),
    async getAttachment(messageId, attachmentId) {
      const result = await get<{ data: string }>(`/messages/${encodeURIComponent(messageId)}/attachments/${encodeURIComponent(attachmentId)}`);
      return result.data;
    },
  };
}
