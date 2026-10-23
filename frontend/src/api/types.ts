/** Names and literal values mirror contracts/openapi.yaml and contracts/enums.json. */
export type CaseStatus = 'RECEIVED' | 'ANALYZING' | 'AWAITING_APPROVAL' | 'ESCALATED' | 'CONTAINED' | 'RESOLVED' | 'NO_IMPACT' | 'DUPLICATE';
export type FieldStatus = 'FOUND' | 'MISSING' | 'AMBIGUOUS';
export type BatchDecision = 'NO_IMPACT' | 'HOLD' | 'HOLD_RELABEL' | 'CLAIM_CONFLICT' | 'SHIPPED_ESCALATE' | 'UNCERTAIN_ESCALATE' | 'NOT_IN_SCOPE';
export type ActionType = 'PLACE_HOLD' | 'BLOCK_RECEIPT' | 'REMOVE_FROM_SHIPMENT' | 'RELEASE_HOLD' | 'CREATE_RELABEL_TICKET' | 'SEND_RETAILER_NOTICE' | 'SEND_SUPPLIER_QUERY';
export type ActionStatus = 'PROPOSED' | 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED' | 'EXECUTING' | 'EXECUTED' | 'VERIFIED' | 'VERIFY_FAILED' | 'ESCALATED';
export type Role = 'supplier' | 'qa_specialist' | 'qa_manager' | 'shipping_supervisor' | 'admin' | 'agent';
export type ErrorCode = 'UNAUTHENTICATED' | 'FORBIDDEN' | 'NOT_FOUND' | 'VALIDATION_ERROR' | 'CONFLICT' | 'POLICY_VIOLATION' | 'UPSTREAM_FAILED' | 'NOT_IMPLEMENTED' | 'INTERNAL_ERROR';
export type UncertaintyFlag = 'SUPPLIER_UNVERIFIED' | 'LLM_UNCERTAIN' | 'EVIDENCE_MISMATCH' | 'CRITICAL_FIELD_UNRESOLVED';
export type DispositionValue = 'RELABEL' | 'REWORK' | 'DESTROY' | 'RETURN_TO_SUPPLIER' | 'RELEASE_AS_IS';
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
export interface CaseSummary { id: string; notice_id: string; status: CaseStatus; supplier: string; subject: string; opened_at: string; contained_at: string | null; duplicate_of: string | null; pending_approvals: number; uncertainty_flags: UncertaintyFlag[] }
export interface Action { id: string; case_id?: string; type: ActionType; target: Record<string, string>; status: ActionStatus; requires_approval: boolean; requested_by?: string; idempotency_key?: string; created_at?: string; result?: Record<string, unknown> | null }
export interface ApproveRequest { comment?: string }
export interface RejectRequest { reason: string }
export interface ReleaseRequest { batch_id: string; reason: string }
export interface DispositionRequest { batch_id: string; disposition: DispositionValue; evidence: string }
export interface Disposition extends DispositionRequest { id: string; case_id: string; recorded_by: string; recorded_at: string }
export interface NoticeRef { id: string; supplier: string; subject: string; received_at: string }
export interface Evidence { source: 'email' | 'attachment'; page: number | null; quote: string }
export interface ExtractedField { value: string | null; status: FieldStatus; confidence: number | null; evidence: Evidence | null }
export interface AllergenAdded { allergen: string; rule_id: string }
export interface Extraction { fields: Record<string, ExtractedField>; allergens_added: AllergenAdded[]; uncertainty_flags: UncertaintyFlag[]; model?: string; prompt_version?: string }
export interface StockLocation { location: string; qty: number; status: string }
export interface ShipmentLine { shipment_id: string; destination: string; departs_at: string; qty: number }
export interface TraceBatch { batch_id: string; sku: string; product: string; locations: StockLocation[]; shipments: ShipmentLine[] }
export interface TraceGap { kind: string; detail: string }
export interface Trace { material_lots: string[]; batches: TraceBatch[]; gaps: TraceGap[] }
export interface BatchDecisionRow { batch_id: string; decision: BatchDecision; rule_ids: string[]; rationale: string; uncertainty_flags?: UncertaintyFlag[] }
export interface CaseMetrics { agent_started_at: string | null; elapsed_seconds: number | null }
export interface CaseDetail { id: string; status: CaseStatus; notice: NoticeRef; extraction: Extraction | null; trace: Trace | null; batch_decisions: BatchDecisionRow[]; actions: Action[]; metrics: CaseMetrics; duplicate_of?: string | null; opened_at?: string; contained_at?: string | null; uncertainty_flags?: UncertaintyFlag[] }
export interface RunStarted { case_id: string; run_id: string }
export interface AuditEvent { id: string; case_id: string; ts: string; actor: string; kind: string; payload: Record<string, unknown>; prev_hash: string | null; hash: string }
export interface ReportBatch { batch_id: string; decision: BatchDecision; final_state: string; verified: boolean }
export interface CaseReport { case_id: string; status: CaseStatus; opened_at: string; contained_at: string | null; batches: ReportBatch[]; action_counts: Partial<Record<ActionStatus, number>>; metrics: CaseMetrics & { seconds_to_contained: number | null } }
export interface IngestEmailRequest { gmail_message_id: string; thread_id: string; from: string; subject: string; body_text: string; received_at: string; attachments: { filename: string; mime_type: 'application/pdf'; content_base64: string }[] }
export interface IngestEmailResponse extends NoticeCreated { duplicate: boolean }
export interface LabelLockApi {
  login(username: string, password: string): Promise<LoginResponse>;
  me(token: string): Promise<User>;
  createNotice(token: string, input: NoticeInput): Promise<NoticeCreated>;
  listMyNotices(token: string): Promise<NoticeSummary[]>;
  getInbox(token: string): Promise<InboxItem[]>;
  getNotice(token: string, id: string): Promise<Notice>;
  getCaseByMessage(token: string, messageId: string): Promise<CaseSummary>;
  ingestEmail(token: string, input: IngestEmailRequest): Promise<IngestEmailResponse>;
  getCase(token: string, id: string): Promise<CaseDetail>;
  listCases(token: string): Promise<CaseSummary[]>;
  getTimeline(token: string, id: string): Promise<AuditEvent[]>;
  getReport(token: string, id: string): Promise<CaseReport>;
  runCase(token: string, id: string): Promise<RunStarted>;
  listApprovals(token: string, status?: ActionStatus): Promise<Action[]>;
  approveAction(token: string, id: string, comment?: string): Promise<Action>;
  rejectAction(token: string, id: string, reason: string): Promise<Action>;
  requestRelease(token: string, caseId: string, body: ReleaseRequest): Promise<Action>;
  recordDisposition(token: string, caseId: string, body: DispositionRequest): Promise<Disposition>;
}
