import loginExample from '../../../contracts/examples/login.json';
import meExample from '../../../contracts/examples/me.json';
import inboxExample from '../../../contracts/examples/inbox.json';
import noticeExample from '../../../contracts/examples/notice.json';
import forbiddenExample from '../../../contracts/examples/error_forbidden.json';
import { ApiError, type InboxItem, type LabelLockApi, type Notice, type NoticeSummary, type Role, type User } from './types';

const users: Record<string, User> = {
  'valley.ingredients': { id: 'u_valley', name: 'Valley Ingredients', role: 'supplier' },
  'priya.qa': meExample as User,
  'daniel.qam': { id: 'u_daniel', name: 'Daniel Okafor', role: 'qa_manager' },
  'marco.ship': { id: 'u_marco', name: 'Marco Rossi', role: 'shipping_supervisor' },
  admin: { id: 'u_admin', name: 'Admin', role: 'admin' },
  'labellock-agent': { id: 'u_agent', name: 'LabelLock Agent', role: 'agent' },
};
const seededInbox: InboxItem[] = inboxExample as InboxItem[];
const seededNotice: Notice = noticeExample as Notice;
let added: Notice[] = [];
let sequence = 100;
let forcedInboxError = false;

const delay = () => new Promise<void>(resolve => setTimeout(resolve, 300 + Math.floor(Math.random() * 301)));
function error(status: number, code: 'FORBIDDEN' | 'UNAUTHENTICATED' | 'NOT_FOUND' | 'VALIDATION_ERROR' | 'UPSTREAM_FAILED', message: string): never {
  throw new ApiError(status, { error: { code, message, details: {}, request_id: 'req_mock' } });
}
function userFor(token: string): User {
  const user = users[token.replace(/^mock:/, '')];
  if (!token.startsWith('mock:') || !user) return error(401, 'UNAUTHENTICATED', 'Missing or invalid token');
  return user;
}
function requireRole(token: string, roles: Role[]): User {
  const user = userFor(token);
  if (!roles.includes(user.role)) {
    throw new ApiError(403, { error: { ...forbiddenExample.error, code: 'FORBIDDEN', message: `Role ${user.role} cannot access this resource`, details: {} } });
  }
  return user;
}
const summary = (n: Notice): NoticeSummary => ({ id: n.id, subject: n.subject, received_at: n.received_at, has_attachment: !!n.attachment, case_id: n.case_id, case_status: 'RECEIVED' });

export const mocks: LabelLockApi = {
  async login(username, password) {
    await delay();
    if (password !== 'demo' || !users[username]) return error(401, 'UNAUTHENTICATED', 'Invalid username or password');
    return { ...loginExample, token: `mock:${username}`, user: users[username] };
  },
  async me(token) { await delay(); return userFor(token); },
  async createNotice(token, input) {
    await delay();
    requireRole(token, ['supplier']);
    if (!input.subject.trim() || !input.body.trim() || input.attachment.type !== 'application/pdf' || input.attachment.size > 5 * 1024 * 1024) {
      return error(422, 'VALIDATION_ERROR', 'A subject, message and PDF up to 5 MB are required');
    }
    const id = `n_${++sequence}`;
    const caseId = `c_${sequence}`;
    added = [{ id, case_id: caseId, supplier_id: 's_valley', supplier: 'Valley Ingredients', subject: input.subject.trim(), body: input.body.trim(), received_at: new Date().toISOString(), attachment: { filename: input.attachment.name, mime_type: input.attachment.type, size_bytes: input.attachment.size }, content_hash: 'sha256:mock', }, ...added];
    return { notice_id: id, case_id: caseId, case_status: 'RECEIVED' };
  },
  async listMyNotices(token) {
    await delay(); requireRole(token, ['supplier']);
    return [...added.map(summary), summary(seededNotice)].sort((a, b) => b.received_at.localeCompare(a.received_at));
  },
  async getInbox(token) {
    await delay(); requireRole(token, ['qa_specialist', 'qa_manager', 'admin']);
    if (forcedInboxError) return error(502, 'UPSTREAM_FAILED', 'Inbox temporarily unavailable');
    return [...added.map(n => ({ ...summary(n), notice_id: n.id, supplier: n.supplier })), ...seededInbox].sort((a, b) => b.received_at.localeCompare(a.received_at));
  },
  async getNotice(token, id) {
    await delay(); requireRole(token, ['supplier', 'qa_specialist', 'qa_manager']);
    const notice = [...added, seededNotice].find(n => n.id === id);
    if (!notice) return error(404, 'NOT_FOUND', 'Notice not found');
    return notice;
  },
};

/** Test hook; never imported by views. */
export const mockControls = {
  reset() { added = []; sequence = 100; forcedInboxError = false; },
  setInboxError(value: boolean) { forcedInboxError = value; },
};
