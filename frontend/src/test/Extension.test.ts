import { beforeEach, describe, expect, it, vi } from 'vitest';
import messageFixture from '../../../extension/tests/fixtures/gmail-nested-pdf.json';
import attachmentFixture from '../../../extension/tests/fixtures/pdf-attachment.json';
import contractRequest from '../../../contracts/examples/ingest_email_request.json';
import contractResponse from '../../../contracts/examples/ingest_email_response.json';
import { mocks, mockControls } from '../api/mocks';
import { client } from '../api/client';
import { base64urlToBase64, decodeBase64url, recentSupplierEmails, toIngestRequest, walkParts, type GmailMessage, type GmailTransport } from '../../../extension/src/gmail';
import { detectOpenEmail, verifyDetectedEmail } from '../../../extension/src/detection';
import { analyzeEmail } from '../../../extension/src/flow';

const message = messageFixture as GmailMessage;
const gmail: GmailTransport = {
  list: vi.fn(async () => [message.id]),
  getMessage: vi.fn(async id => { if (id !== message.id) throw new Error('Gmail 404'); return message; }),
  getThread: vi.fn(async id => { if (id !== message.threadId) throw new Error('Gmail 404'); return { messages: [{ id: message.id, threadId: id }] }; }),
  getAttachment: vi.fn(async () => attachmentFixture.data),
};
beforeEach(() => { mockControls.reset(); vi.clearAllMocks(); document.body.innerHTML = ''; });

describe('Gmail MIME and encoding', () => {
  it('walks nested MIME parts and converts base64url PDF bytes', async () => {
    expect(walkParts(message.payload).map(part => part.mimeType)).toContain('application/pdf');
    expect(new TextDecoder().decode(decodeBase64url(attachmentFixture.data)).startsWith('%PDF-')).toBe(true);
    expect(base64urlToBase64(attachmentFixture.data)).toBe(contractRequest.attachments[0].content_base64);
    const request = await toIngestRequest(message, gmail.getAttachment);
    expect(request).toEqual({ ...contractRequest, gmail_message_id: message.id, thread_id: message.threadId, received_at: new Date(contractRequest.received_at).toISOString() });
  });
  it('lists only messages with PDFs', async () => {
    expect(await recentSupplierEmails(gmail)).toEqual([expect.objectContaining({ id: message.id, attachmentNames: ['RM-114_spec_rev4.pdf'] })]);
  });
});

describe('opened-message fallback', () => {
  it('detects DOM ids then verifies them with Gmail, falling back to the URL thread', async () => {
    document.body.innerHTML = '<div data-message-id="staleMessage123"></div>';
    const candidate = detectOpenEmail(document, `https://mail.google.com/mail/u/0/#inbox/${message.threadId}`);
    expect(candidate.messageIds).toContain('staleMessage123');
    expect(detectOpenEmail(document, 'https://mail.google.com/mail/u/0/#inbox').messageIds).toEqual([]);
    expect(await verifyDetectedEmail(candidate, gmail)).toBe(message.id);
    expect(await verifyDetectedEmail({ messageIds: ['badMessage123'], threadId: 'badThread123' }, gmail)).toBeNull();
    expect(await verifyDetectedEmail({ messageIds: [message.id], threadId: 'unrelatedThread123' }, gmail)).toBeNull();
  });
});

describe('analyze flow', () => {
  it('ingests a new email, then returns the same case as a duplicate', async () => {
    const token = (await mocks.login('priya.qa', 'demo')).token;
    await expect(mocks.getCaseByMessage(token, message.id)).rejects.toMatchObject({ status: 404, code: 'NOT_FOUND' });
    const created = await analyzeEmail(message.id, token, gmail, mocks);
    expect(created).toMatchObject({ case_status: contractResponse.case_status, duplicate: false });
    expect((await mocks.getCaseByMessage(token, message.id)).id).toBe(created.case_id);
    expect(await analyzeEmail(message.id, token, gmail, mocks)).toMatchObject({ case_id: created.case_id, duplicate: true });
  });
  it('shows backend authorization errors instead of masking them', async () => {
    const token = (await mocks.login('priya.qa', 'demo')).token;
    await expect(mocks.approveAction(token, 'a_012', '')).rejects.toMatchObject({ status: 403, response: { error: { code: 'FORBIDDEN', request_id: expect.any(String) } } });
  });
  it('turns a disconnected backend into a typed network error', async () => {
    const original = globalThis.fetch;
    globalThis.fetch = vi.fn(async () => { throw new TypeError('Failed to fetch'); });
    try { await expect(client.getCaseByMessage('token', message.id)).rejects.toMatchObject({ status: 0, code: 'UPSTREAM_FAILED' }); }
    finally { globalThis.fetch = original; }
  });
});
