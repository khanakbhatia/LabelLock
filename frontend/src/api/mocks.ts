import loginExample from '../../../contracts/examples/login.json';
import meExample from '../../../contracts/examples/me.json';
import inboxExample from '../../../contracts/examples/inbox.json';
import noticeExample from '../../../contracts/examples/notice.json';
import forbiddenExample from '../../../contracts/examples/error_forbidden.json';
import policyExample from '../../../contracts/examples/error_policy_violation.json';
import caseByMessage from '../../../contracts/examples/case_by_message.json';
import caseDetail from '../../../contracts/examples/case_detail.json';
import caseList from '../../../contracts/examples/case_summary_list.json';
import timelineExample from '../../../contracts/examples/timeline.json';
import reportExample from '../../../contracts/examples/case_report.json';
import approvalExample from '../../../contracts/examples/approvals.json';
import ingestExample from '../../../contracts/examples/ingest_email_response.json';
import { ApiError, type Action, type ActionStatus, type AuditEvent, type CaseDetail, type CaseReport, type CaseSummary, type Disposition, type ErrorCode, type InboxItem, type IngestEmailResponse, type LabelLockApi, type Notice, type NoticeSummary, type Role, type UncertaintyFlag, type User } from './types';

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
const caseByMessageId = new Map<string, CaseSummary>([["18c2f4a9b7e01d3a", caseByMessage as CaseSummary]]);
let approvals: Action[] = approvalExample as Action[];
let dispositions: Disposition[] = [];
let generation = 0;
let runState: Record<string, 'ANALYZING' | 'AWAITING_APPROVAL'> = {};
let runConflict = false;
let casesError = false;
let caseFlags: UncertaintyFlag[] = [];
let actionStatus: ActionStatus | null = null;

const delay = () => new Promise<void>(resolve => setTimeout(resolve, 300 + Math.floor(Math.random() * 301)));
function error(status: number, code: ErrorCode, message: string): never {
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
  async getCaseByMessage(token, id) {
    await delay(); requireRole(token, ['qa_specialist', 'qa_manager', 'shipping_supervisor']);
    const found = caseByMessageId.get(id);
    if (!found) return error(404, 'NOT_FOUND', 'No case for this Gmail message');
    return found;
  },
  async ingestEmail(token, input) {
    await delay(); requireRole(token, ['qa_specialist', 'qa_manager']);
    const existing = caseByMessageId.get(input.gmail_message_id);
    if (existing) return { notice_id: existing.notice_id, case_id: existing.id, case_status: existing.status, duplicate: true };
    if (!input.attachments.length) return error(422, 'VALIDATION_ERROR', 'A PDF attachment is required');
    const response = { ...ingestExample, notice_id: `n_${++sequence}`, case_id: `c_${sequence}` } as IngestEmailResponse;
    caseByMessageId.set(input.gmail_message_id, { id: response.case_id, notice_id: response.notice_id, status: response.case_status, supplier: input.from, subject: input.subject, opened_at: new Date().toISOString(), contained_at: null, duplicate_of: null, pending_approvals: 0, uncertainty_flags: [] });
    return response;
  },
  async getCase(token, id) {
    await delay(); requireRole(token, ['qa_specialist', 'qa_manager', 'shipping_supervisor']);
    const listed = seededInbox.find(item => item.case_id === id);
    const ingested = [...caseByMessageId.values()].find(item => item.id === id);
    const created = added.find(item => item.case_id === id);
    if (id !== 'c_001' && !listed && !ingested && !created) return error(404, 'NOT_FOUND', 'Case not found');
    const baseActions = id === 'c_001' && runState[id] !== 'ANALYZING' ? caseDetail.actions.map((a, i) => i === 0 && actionStatus ? { ...a, status: actionStatus } : a) : [];
    const currentActions = [...baseActions.filter(a => !approvals.some(p => p.id === a.id)), ...approvals.filter(a => a.case_id === id)];
    return { ...caseDetail, id, status: runState[id] ?? listed?.case_status ?? ingested?.status ?? 'RECEIVED', uncertainty_flags: caseFlags, notice: listed ? { id: listed.notice_id, supplier: listed.supplier, subject: listed.subject, received_at: listed.received_at } : ingested ? { id: ingested.notice_id, supplier: ingested.supplier, subject: ingested.subject, received_at: ingested.opened_at } : created ? { id: created.id, supplier: created.supplier, subject: created.subject, received_at: created.received_at } : caseDetail.notice, extraction: id === 'c_001' && runState[id] !== 'ANALYZING' ? caseDetail.extraction : null, trace: id === 'c_001' && runState[id] !== 'ANALYZING' ? caseDetail.trace : null, batch_decisions: id === 'c_001' && runState[id] !== 'ANALYZING' ? caseDetail.batch_decisions : [], actions: currentActions } as unknown as CaseDetail;
  },
  async listCases(token) {
    await delay(); requireRole(token, ['qa_specialist', 'qa_manager', 'shipping_supervisor']);
    if (casesError) return error(502, 'UPSTREAM_FAILED', 'Cases temporarily unavailable');
    return [...added.map(n => ({ id: n.case_id, notice_id: n.id, status: runState[n.case_id] ?? 'RECEIVED', supplier: n.supplier, subject: n.subject, opened_at: n.received_at, contained_at: null, duplicate_of: null, pending_approvals: 0, uncertainty_flags: [] } as CaseSummary)), ...(caseList as CaseSummary[]).map(c => ({ ...c, status: runState[c.id] ?? c.status, uncertainty_flags: c.id === 'c_001' ? caseFlags : c.uncertainty_flags }))].map(c => ({ ...c, pending_approvals: approvals.filter(a => a.case_id === c.id && a.status === 'PENDING_APPROVAL').length })).sort((a, b) => b.opened_at.localeCompare(a.opened_at));
  },
  async getTimeline(token, id) { await delay(); requireRole(token, ['qa_specialist', 'qa_manager', 'shipping_supervisor']); if (id !== 'c_001') return []; return timelineExample as AuditEvent[]; },
  async getReport(token, id) { await delay(); requireRole(token, ['qa_specialist', 'qa_manager']); if (id !== 'c_001') return error(404, 'NOT_FOUND', 'Report not found'); return reportExample as CaseReport; },
  async runCase(token, id) {
    await delay(); requireRole(token, ['qa_specialist', 'qa_manager']);
    if (runConflict || runState[id] === 'ANALYZING') return error(409, 'CONFLICT', 'Agent already running');
    runState[id] = 'ANALYZING';
    setTimeout(() => { if (runState[id] === 'ANALYZING') runState[id] = 'AWAITING_APPROVAL'; }, 1500);
    return { case_id: id, run_id: `run_${id}` };
  },
  async listApprovals(token, status) { await delay(); requireRole(token, ['qa_specialist', 'qa_manager']); return approvals.filter(action => !status || action.status === status).sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '')); },
  async approveAction(token, id) {
    await delay(); requireRole(token, ['qa_manager']);
    const found = approvals.find(action => action.id === id);
    if (!found) return error(404, 'NOT_FOUND', 'Action not found');
    if (found.status !== 'PENDING_APPROVAL') return error(409, 'CONFLICT', 'Action has already been decided');
    approvals = approvals.map(action => action.id === id ? { ...action, status: 'APPROVED' } : action);
    const currentGeneration = generation;
    setTimeout(() => { if (generation === currentGeneration) approvals = approvals.map(action => action.id === id && action.status === 'APPROVED' ? { ...action, status: 'EXECUTED' } : action); }, 500);
    setTimeout(() => { if (generation === currentGeneration) approvals = approvals.map(action => action.id === id && action.status === 'EXECUTED' ? { ...action, status: 'VERIFIED' } : action); }, 1000);
    return { ...found, status: 'APPROVED' };
  },
  async rejectAction(token, id, reason) {
    await delay(); requireRole(token, ['qa_manager']);
    if (!reason.trim()) return error(422, 'VALIDATION_ERROR', 'Reason is required');
    const found = approvals.find(action => action.id === id);
    if (!found) return error(404, 'NOT_FOUND', 'Action not found');
    if (found.status !== 'PENDING_APPROVAL') return error(409, 'CONFLICT', 'Action has already been decided');
    approvals = approvals.map(action => action.id === id ? { ...action, status: 'REJECTED' } : action);
    return { ...found, status: 'REJECTED' };
  },
  async recordDisposition(token, caseId, body) {
    await delay(); const actor = requireRole(token, ['qa_manager']);
    if (!body.batch_id.trim() || !body.evidence.trim()) return error(422, 'VALIDATION_ERROR', 'Batch and evidence are required');
    const disposition: Disposition = { ...body, id: `d_${++sequence}`, case_id: caseId, recorded_by: actor.name, recorded_at: new Date().toISOString() };
    dispositions = [...dispositions, disposition];
    return disposition;
  },
  async requestRelease(token, caseId, body) {
    await delay(); const actor = requireRole(token, ['qa_specialist', 'qa_manager', 'shipping_supervisor']);
    if (!body.batch_id.trim() || !body.reason.trim()) return error(422, 'VALIDATION_ERROR', 'Batch and reason are required');
    if (!dispositions.some(d => d.case_id === caseId && d.batch_id === body.batch_id)) {
      throw new ApiError(409, { error: { ...policyExample.error, code: 'POLICY_VIOLATION', details: { batch_id: body.batch_id, case_id: caseId }, message: `Cannot release ${body.batch_id} without an approved disposition` } });
    }
    const action: Action = { id: `a_${++sequence}`, case_id: caseId, type: 'RELEASE_HOLD', target: { batch_id: body.batch_id }, status: 'PENDING_APPROVAL', requires_approval: true, requested_by: actor.name, created_at: new Date().toISOString(), result: null };
    approvals = [action, ...approvals];
    return action;
  },
};

/** Test hook; never imported by views. */
export const mockControls = {
  reset() { generation++; added = []; dispositions = []; sequence = 100; forcedInboxError = false; casesError = false; runConflict = false; caseFlags = []; actionStatus = null; runState = {}; approvals = approvalExample as Action[]; caseByMessageId.clear(); caseByMessageId.set('18c2f4a9b7e01d3a', caseByMessage as CaseSummary); },
  setInboxError(value: boolean) { forcedInboxError = value; },
  setCasesError(value: boolean) { casesError = value; },
  setRunConflict(value: boolean) { runConflict = value; },
  setCaseFlags(value: UncertaintyFlag[]) { caseFlags = value; },
  setActionStatus(value: ActionStatus | null) { actionStatus = value; },
};
