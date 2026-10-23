import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError, type CaseDetail } from '../api';
import { useAuth } from '../auth';
import styles from './Workspace.module.css';

export function CaseWorkspace() {
  const { id = '' } = useParams();
  const { token, user } = useAuth();
  const [caseInfo, setCaseInfo] = useState<CaseDetail | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    if (!token) return;
    try { setCaseInfo(await api.getCase(token, id)); setError(''); }
    catch (reason) { setError(reason instanceof ApiError ? `${reason.code}: ${reason.message} · Request ID: ${reason.request_id}` : 'Could not load case.'); }
  }, [id, token]);
  useEffect(() => {
    void load();
  }, [load]);
  async function run() {
    if (!token) return;
    setBusy(true); setError('');
    try { const result = await api.runCase(token, id); setMessage(`Analysis queued: ${result.run_id}. Refresh to see progress.`); }
    catch (reason) { setError(reason instanceof ApiError ? `${reason.code}: ${reason.message} · Request ID: ${reason.request_id}` : 'Could not start analysis.'); }
    finally { setBusy(false); }
  }
  return <main className={styles.page}>
    <Link to="/inbox">← QA inbox</Link><h1>Case workspace</h1>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {message && <p role="status" className={styles.success}>{message}</p>}
    {!caseInfo && !error && <p role="status">Loading case…</p>}
    {caseInfo && <>
      <section className={styles.card}><small>{caseInfo.id} · {caseInfo.status.replaceAll('_', ' ')}</small><h2>{caseInfo.notice.subject}</h2><p>{caseInfo.notice.supplier}</p><div className={styles.buttons}><button onClick={() => void load()}>Refresh case</button>{user?.role !== 'shipping_supervisor' && <button disabled={busy} onClick={() => void run()}>{busy ? 'Starting…' : 'Run case analysis'}</button>}</div></section>
      <section className={styles.card}><h2>Analysis and evidence</h2>{caseInfo.extraction ? <ul>{Object.entries(caseInfo.extraction.fields).map(([name, field]) => <li key={name}><strong>{name.replaceAll('_', ' ')}:</strong> {field.value ?? field.status}{field.evidence && <p>Evidence: “{field.evidence.quote}” ({field.evidence.source}{field.evidence.page ? `, page ${field.evidence.page}` : ''})</p>}</li>)}</ul> : <p>Analysis has not run yet.</p>}</section>
      <section className={styles.card}><h2>Batch trace and decisions</h2>{caseInfo.trace ? <ul>{caseInfo.trace.batches.map(batch => <li key={batch.batch_id}><strong>{batch.batch_id} · {batch.product}</strong><p>{batch.locations.map(location => `${location.location}: ${location.qty} ${location.status}`).join('; ')}</p><p>{batch.shipments.map(shipment => `Shipment ${shipment.shipment_id}: ${shipment.qty}`).join('; ')}</p></li>)}</ul> : <p>Trace has not run yet.</p>}{caseInfo.batch_decisions.map(decision => <p key={decision.batch_id}>{decision.batch_id}: <strong>{decision.decision.replaceAll('_', ' ')}</strong> — {decision.rationale}</p>)}</section>
      <section className={styles.card}><h2>Actions</h2><ul>{caseInfo.actions.map(action => <li key={action.id}>{action.type.replaceAll('_', ' ')} · {action.status.replaceAll('_', ' ')}</li>)}</ul><Link to="/approvals">Review approval queue</Link></section>
    </>}
  </main>;
}
