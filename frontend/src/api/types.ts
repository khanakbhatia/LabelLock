/** Names and literal values mirror contracts/openapi.yaml and contracts/enums.json. */
export type CaseStatus = 'RECEIVED' | 'ANALYZING' | 'AWAITING_APPROVAL' | 'ESCALATED' | 'CONTAINED' | 'RESOLVED' | 'NO_IMPACT' | 'DUPLICATE';
export type FieldStatus = 'FOUND' | 'MISSING' | 'AMBIGUOUS';
export type BatchDecision = 'NO_IMPACT' | 'HOLD' | 'HOLD_RELABEL' | 'CLAIM_CONFLICT' | 'SHIPPED_ESCALATE' | 'UNCERTAIN_ESCALATE' | 'NOT_IN_SCOPE';
export type ActionType = 'PLACE_HOLD' | 'BLOCK_RECEIPT' | 'REMOVE_FROM_SHIPMENT' | 'RELEASE_HOLD' | 'CREATE_RELABEL_TICKET' | 'SEND_RETAILER_NOTICE' | 'SEND_SUPPLIER_QUERY';
export type ActionStatus = 'PROPOSED' | 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED' | 'EXECUTING' | 'EXECUTED' | 'VERIFIED' | 'VERIFY_FAILED' | 'ESCALATED';
export type Role = 'supplier' | 'qa_specialist' | 'qa_manager' | 'shipping_supervisor' | 'admin' | 'agent';
export type ErrorCode = 'UNAUTHENTICATED' | 'FORBIDDEN' | 'NOT_FOUND' | 'VALIDATION_ERROR' | 'CONFLICT' | 'POLICY_VIOLATION' | 'UPSTREAM_FAILED' | 'NOT_IMPLEMENTED' | 'INTERNAL_ERROR';
export type UncertaintyFlag = 'SUPPLIER_UNVERIFIED' | 'LLM_UNCERTAIN' | 'EVIDENCE_MISMATCH' | 'CRITICAL_FIELD_UNRESOLVED';
export interface ErrorResponse { error: { code: ErrorCode; message: string; details?: Record<string, unknown> | null; request_id: string } }
export class ApiError extends Error {
  constructor(public readonly status: number, public readonly response: ErrorResponse) {
    super(response.error.message);
    this.name = 'ApiError';
  }
  get code() { return this.response.error.code; }
  get request_id() { return this.response.error.request_id; }
  get details() { return this.response.error.details; }
}
export interface User { id: string; name: string; role: Role }
export interface LoginResponse { token: string; user: User }
export interface NoticeCreated { notice_id: string; case_id: string; case_status: CaseStatus }
export interface NoticeSummary { id: string; subject: string; received_at: string; has_attachment: boolean; case_id: string; case_status: CaseStatus }
export interface InboxItem { notice_id: string; case_id: string; supplier: string; subject: string; received_at: string; has_attachment: boolean; case_status: CaseStatus }
export interface Attachment { filename: string; mime_type: string; size_bytes: number }
export interface Notice { id: string; supplier_id: string | null; supplier: string; subject: string; body: string; received_at: string; attachment: Attachment | null; content_hash: string; case_id: string }
export interface NoticeInput { subject: string; body: string; attachment: File }
export interface LabelLockApi {
  login(username: string, password: string): Promise<LoginResponse>;
  me(token: string): Promise<User>;
  createNotice(token: string, input: NoticeInput): Promise<NoticeCreated>;
  listMyNotices(token: string): Promise<NoticeSummary[]>;
  getInbox(token: string): Promise<InboxItem[]>;
  getNotice(token: string, id: string): Promise<Notice>;
}
