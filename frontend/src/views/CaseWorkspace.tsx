import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError, type AuditEvent, type AuditVerification, type CaseDetail, type CaseReport, type Extraction, type Trace } from '../api';
import { useAuth } from '../auth';
import { Chip, flagLabel, formatTime } from './caseDisplay';
import { ApprovalDecision, describeAction } from './ApprovalDecision';
import { HeldBatchControls } from './HeldBatchControls';
import { ActionDetail } from './actionDetail';
import styles from './Workspace.module.css';

type Tab = 'Analysis' | 'Batch Detective' | 'Label Check' | 'Actions' | 'Timeline';
const tabs: Tab[] = ['Analysis', 'Batch Detective', 'Label Check', 'Actions', 'Timeline'];
const messageFor = (reason: unknown, fallback: string) => reason instanceof ApiError ? `${reason.code}: ${reason.message}${reason.request_id ? ` · Request ID: ${reason.request_id}` : ''}` : fallback;
const label = (value: string) => value.replaceAll('_', ' ');
const actionTone = (status: string) => status === 'VERIFY_FAILED' || status === 'ESCALATED' ? 'danger' : status === 'PENDING_APPROVAL' ? 'warning' : 'neutral';

function Analysis({ extraction }: { extraction: Extraction | null }) {
  if (!extraction) return <p>Analysis has not run yet.</p>;
  return <><div className={styles.scroll}><table><thead><tr><th>Field</th><th>Value</th><th>Status</th><th>Confidence</th><th>Evidence</th></tr></thead><tbody>{Object.entries(extraction.fields).map(([name, field]) => <tr key={name}><th scope="row">{label(name)}</th><td>{field.value ?? '—'}</td><td><Chip tone={field.status === 'FOUND' ? 'good' : field.status === 'MISSING' ? 'danger' : 'warning'}>{field.status}</Chip></td><td>{field.confidence == null ? '—' : `${Math.round(field.confidence * 100)}%`}</td><td>{field.evidence ? <>“{field.evidence.quote}” <small>— {field.evidence.source === 'email' ? 'Email' : `PDF page ${field.evidence.page}`}</small></> : 'No evidence'}</td></tr>)}</tbody></table></div><h3>Allergens added</h3>{extraction.allergens_added.length ? <ul>{extraction.allergens_added.map(item => <li key={item.rule_id}>{item.allergen} · Rule {item.rule_id}</li>)}</ul> : <p>None recorded.</p>}<h3>Extraction uncertainty</h3>{extraction.uncertainty_flags.length ? extraction.uncertainty_flags.map(flag => <Chip tone="warning" key={flag}>{flagLabel(flag)}</Chip>) : <p>No uncertainty flags.</p>}</>;
}
function Detective({ trace }: { trace: Trace | null }) {
  if (!trace) return <p>Not traced yet.</p>;
  return <>{trace.gaps.map((gap, i) => <p role="alert" className={styles.warningBox} key={`${gap.kind}-${i}`}>{gap.kind}: {gap.detail}</p>)}{trace.material_lots.length ? trace.material_lots.map(lot => <section key={lot} className={styles.lot}><h3>Material lot {lot}</h3>{trace.batches.length ? trace.batches.map(batch => <article key={batch.batch_id} className={styles.batch}><h4>{batch.batch_id} · {batch.product} <small>({batch.sku})</small></h4><h5>Stock locations</h5>{batch.locations.length ? <ul>{batch.locations.map(loc => <li key={loc.location}>{loc.location} · Qty {loc.qty} <Chip tone={loc.status === 'HELD' ? 'good' : 'warning'}>{loc.status}</Chip></li>)}</ul> : <p>No stock locations.</p>}<h5>Outbound shipments</h5>{batch.shipments.length ? <ul>{batch.shipments.map(ship => <li key={ship.shipment_id}>{ship.shipment_id} · {ship.destination} · Qty {ship.qty} · <time dateTime={ship.departs_at}>{formatTime(ship.departs_at)}</time></li>)}</ul> : <p>No outbound shipments.</p>}</article>) : <p>No linked batches.</p>}</section>) : <p>No material lots.</p>}</>;
}
const timelineFilter = (kind: string, filter: string) => filter === 'All' || (filter === 'Decisions' && kind === 'RULE_FIRED') || (filter === 'Actions' && (kind.startsWith('ACTION_') || ['APPROVAL_REQUESTED', 'VERIFICATION', 'VERIFY_MISMATCH'].includes(kind))) || (filter === 'Escalations' && ['ESCALATED', 'POLICY_VIOLATION', 'RUN_FAILED', 'SUPPLIER_QUERY_SKIPPED'].includes(kind)) || (filter === 'System calls' && kind === 'ADAPTER_CALL');
function Timeline({ events }: { events: AuditEvent[] }) {
  const [filter, setFilter] = useState('All');
  return <><div className={styles.filters} aria-label="Timeline filters">{['All', 'Decisions', 'Actions', 'Escalations', 'System calls'].map(value => <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)}>{value}</button>)}</div>{events.filter(event => timelineFilter(event.kind, filter)).sort((a, b) => a.ts.localeCompare(b.ts)).map(event => <article className={styles.event} key={event.id}><time dateTime={event.ts}>{formatTime(event.ts)}</time><strong>{label(event.kind)}</strong><span>{event.actor}</span><p>{Object.entries(event.payload).slice(0, 2).map(([key, value]) => `${label(key)}: ${Array.isArray(value) ? value.join(', ') : String(value)}`).join(' · ') || 'No details'}</p><details><summary>Raw payload</summary><pre>{JSON.stringify(event.payload, null, 2)}</pre></details></article>)}{!events.some(event => timelineFilter(event.kind, filter)) && <p>No events in this filter.</p>}</>;
}
function Report({ report }: { report: CaseReport }) {
  return <section className={styles.card} aria-label="Case report"><h2>Case report</h2><p>Seconds to contained: {report.metrics.seconds_to_contained ?? 'Not contained yet'}</p><h3>Batch outcomes</h3>{report.batches.map(batch => <p key={batch.batch_id}><strong>{batch.batch_id}</strong> · {label(batch.final_state)} · Verified: {batch.verified ? 'Yes' : 'No'}</p>)}<h3>Action counts</h3>{Object.entries(report.action_counts).map(([status, count]) => <p key={status}>{label(status)}: {count}</p>)}</section>;
}

export function CaseWorkspace() {
  const { id = '' } = useParams();
  const { token, user } = useAuth();
  const [caseInfo, setCaseInfo] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<Tab>('Analysis');
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [timelineError, setTimelineError] = useState('');
  const [chain, setChain] = useState<AuditVerification | null>(null);
  const [report, setReport] = useState<CaseReport | null>(null);
  const [reportError, setReportError] = useState('');
  const [polling, setPolling] = useState(false);
  const [approvalPoll, setApprovalPoll] = useState<string | null>(null);
  const pollStart = useRef(0);
  const load = useCallback(async () => {
    if (!token) return;
    try { setCaseInfo(await api.getCase(token, id)); setError(''); }
    catch (reason) { setError(messageFor(reason, 'Could not load case.')); }
    finally { setLoading(false); }
  }, [id, token]);
  useEffect(() => { setCaseInfo(null); setLoading(true); setPolling(false); setEvents(null); setReport(null); void load(); }, [load]);
  useEffect(() => {
    if (!polling || !token) return;
    if (caseInfo && !['RECEIVED', 'ANALYZING'].includes(caseInfo.status)) { setPolling(false); setMessage(`Agent finished: ${label(caseInfo.status)}.`); return; }
    const timer = window.setInterval(async () => {
      if (Date.now() - pollStart.current >= 30000) { window.clearInterval(timer); setPolling(false); setMessage('Still running after 30 seconds. Refresh this case to check again.'); return; }
      try {
        const updated = await api.getCase(token, id);
        setCaseInfo(updated);
        if (!['RECEIVED', 'ANALYZING'].includes(updated.status)) { window.clearInterval(timer); setPolling(false); setMessage(`Agent finished: ${label(updated.status)}.`); }
      } catch (reason) { window.clearInterval(timer); setPolling(false); setError(messageFor(reason, 'Could not check agent progress.')); }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [caseInfo?.status, id, polling, token]);
  useEffect(() => {
    if (!approvalPoll || !token) return;
    let active = true;
    const deadline = Date.now() + 30000;
    const timer = window.setInterval(async () => {
      if (Date.now() >= deadline) { window.clearInterval(timer); if (active) { setApprovalPoll(null); setMessage('Action is still processing. Refresh this case to check again.'); } return; }
      try {
        const updated = await api.getCase(token, id);
        if (!active) return;
        setCaseInfo(updated);
        const status = updated.actions.find(action => action.id === approvalPoll)?.status;
        if (status === 'VERIFIED' || status === 'VERIFY_FAILED' || status === 'ESCALATED') {
          window.clearInterval(timer); setApprovalPoll(null); setMessage(`Action ${approvalPoll}: ${label(status)}.`);
        }
      } catch (reason) { if (active) { window.clearInterval(timer); setApprovalPoll(null); setError(messageFor(reason, 'Could not check action status.')); } }
    }, 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [approvalPoll, id, token]);
  const loadTimeline = useCallback(async () => { if (!token) return; setTimelineError(''); try { setEvents(await api.getTimeline(token, id)); setChain(await api.verifyTimeline(token, id).catch(() => null)); } catch (reason) { setTimelineError(messageFor(reason, 'Could not load timeline.')); } }, [id, token]);
  useEffect(() => { if (tab === 'Timeline' && events === null) void loadTimeline(); }, [tab, events, loadTimeline]);
  async function run() {
    if (!token) return;
    setBusy(true); setError(''); setMessage('');
    try { const result = await api.runCase(token, id); pollStart.current = Date.now(); setCaseInfo(current => current ? { ...current, status: 'ANALYZING' } : current); setMessage(`Analysis queued: ${result.run_id}. Checking progress…`); setPolling(true); }
    catch (reason) { setError(messageFor(reason, 'Could not start analysis.')); }
    finally { setBusy(false); }
  }
  async function loadReport() { if (!token) return; setReportError(''); try { setReport(await api.getReport(token, id)); } catch (reason) { setReportError(messageFor(reason, 'Could not load report.')); } }
  const heldBatches = [...new Set(caseInfo?.trace?.batches.filter(batch => batch.locations.some(location => location.status === 'HELD')).map(batch => batch.batch_id) ?? [])];
  const decided = (updated: CaseDetail['actions'][number]) => {
    setCaseInfo(current => current ? { ...current, actions: current.actions.map(action => action.id === updated.id ? updated : action) } : current);
    setMessage(`${updated.id}: ${label(updated.status)}.`);
    if (updated.status === 'APPROVED') setApprovalPoll(updated.id);
  };
  const releaseRequested = (action: CaseDetail['actions'][number]) => {
    setCaseInfo(current => current ? { ...current, actions: [...current.actions, action] } : current);
  };
  return <main className={styles.page}>
    <Link to={user?.role === 'shipping_supervisor' ? '/cases' : '/inbox'}>← {user?.role === 'shipping_supervisor' ? 'Cases' : 'QA inbox'}</Link><h1>Case workspace</h1>
    {error && <p role="alert" className={styles.error}>{error}</p>}{message && <p role="status" className={styles.success}>{message}</p>}
    {loading && !caseInfo && <div role="status" className={styles.skeleton}>Loading case…<div /><div /></div>}
    {error && !caseInfo && <button onClick={() => { setLoading(true); void load(); }}>Retry</button>}
    {caseInfo && <><section className={styles.card}><small>{caseInfo.id}</small><h2>{caseInfo.notice.subject}</h2><p>{caseInfo.notice.supplier}</p><div className={styles.chips}><Chip tone={caseInfo.status === 'ESCALATED' ? 'danger' : caseInfo.status === 'AWAITING_APPROVAL' ? 'warning' : 'neutral'}>{label(caseInfo.status)}</Chip>{(caseInfo.uncertainty_flags ?? []).map(flag => <Chip key={flag} tone="warning">{flagLabel(flag)}</Chip>)}</div><p>Opened: <time dateTime={caseInfo.opened_at ?? caseInfo.notice.received_at}>{formatTime(caseInfo.opened_at ?? caseInfo.notice.received_at)}</time> · Agent elapsed: {caseInfo.metrics.elapsed_seconds == null ? 'Not run' : `${caseInfo.metrics.elapsed_seconds}s`}</p><div className={styles.buttons}><button onClick={() => void load()}>Refresh case</button>{['qa_specialist', 'qa_manager'].includes(user?.role ?? '') && <button disabled={busy || polling} onClick={() => void run()}>{busy ? 'Starting…' : 'Run agent'}</button>}{['qa_specialist', 'qa_manager'].includes(user?.role ?? '') && <button onClick={() => void loadReport()}>View report</button>}</div></section>
      {reportError && <p role="alert" className={styles.error}>{reportError}</p>}{report && <Report report={report} />}
      <div className={styles.tabBar} role="tablist" aria-label="Case views">{tabs.map(value => <button key={value} id={`tab-${value.replaceAll(' ', '-')}`} role="tab" aria-selected={tab === value} aria-controls="case-tab-panel" tabIndex={tab === value ? 0 : -1} onClick={() => setTab(value)} onKeyDown={e => { const index = tabs.indexOf(value); if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); const next = tabs[(index + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length]; setTab(next); document.getElementById(`tab-${next.replaceAll(' ', '-')}`)?.focus(); } }}>{value}</button>)}</div>
      <label className={styles.mobileTabs}>Case view <select value={tab} onChange={e => setTab(e.target.value as Tab)}>{tabs.map(value => <option key={value}>{value}</option>)}</select></label>
      <section className={styles.card} id="case-tab-panel" role="tabpanel" aria-labelledby={`tab-${tab.replaceAll(' ', '-')}`}><h2>{tab}</h2>
        {tab === 'Analysis' && <Analysis extraction={caseInfo.extraction} />}
        {tab === 'Batch Detective' && <Detective trace={caseInfo.trace} />}
        {tab === 'Label Check' && (caseInfo.batch_decisions.length ? <div className={styles.grid}>{caseInfo.batch_decisions.map(row => <article key={row.batch_id} className={styles.batch}><h3>{row.batch_id}</h3><Chip tone={['NO_IMPACT', 'NOT_IN_SCOPE'].includes(row.decision) ? 'good' : ['SHIPPED_ESCALATE', 'UNCERTAIN_ESCALATE'].includes(row.decision) ? 'danger' : 'warning'}>{label(row.decision)}{['NO_IMPACT', 'NOT_IN_SCOPE'].includes(row.decision) ? ' · no action' : ''}</Chip><p>{row.rationale}</p><p>Rules: {row.rule_ids.join(', ') || 'None'}</p>{row.uncertainty_flags?.map(flag => <Chip tone="warning" key={flag}>{flagLabel(flag)}</Chip>)}</article>)}</div> : <p>No batch decisions yet.</p>)}
        {tab === 'Actions' && <>{caseInfo.actions.length ? <div className={styles.scroll}><table><thead><tr><th>Type</th><th>Target</th><th>Status</th><th>Approval</th></tr></thead><tbody>{caseInfo.actions.map(action => <tr key={action.id}><td>{label(action.type)}</td><td>{describeAction(action, caseInfo.trace)}<ActionDetail action={action} /></td><td><Chip tone={actionTone(action.status)}>{label(action.status)}</Chip></td><td>{action.requires_approval ? action.status === 'PENDING_APPROVAL' ? <>{user?.role === 'qa_manager' && token ? <ApprovalDecision action={action} description={describeAction(action, caseInfo.trace)} token={token} onDecision={decided} /> : user?.role === 'qa_specialist' ? 'A QA manager must approve.' : 'Approval required.'}{user?.role !== 'shipping_supervisor' && <Link to="/approvals">Open queue</Link>}</> : 'Required' : 'Not required'}</td></tr>)}</tbody></table></div> : <p>No actions yet.</p>}{heldBatches.length > 0 && token && user && <section><h3>Held batches</h3>{heldBatches.map(batchId => <HeldBatchControls key={batchId} token={token} role={user.role} caseId={id} batchId={batchId} onAction={releaseRequested} />)}</section>}</>}
        {tab === 'Timeline' && <>{timelineError && <p role="alert" className={styles.error}>{timelineError}</p>}<button onClick={() => void loadTimeline()}>Refresh timeline</button>{chain && <p role="status" className={chain.valid ? styles.success : styles.error}>{chain.valid ? `Audit hash chain verified · ${chain.events} events` : `Audit hash chain broken at ${chain.first_invalid_event_id}`}</p>}{events ? <Timeline events={events} /> : !timelineError && <p role="status">Loading timeline…</p>}</>}
      </section></>}
  </main>;
}
