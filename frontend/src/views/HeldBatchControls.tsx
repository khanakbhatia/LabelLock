import { useState } from 'react';
import { api, ApiError, type Action, type DispositionValue, type Role } from '../api';
import styles from './Workspace.module.css';

const dispositions: DispositionValue[] = ['RELABEL', 'REWORK', 'DESTROY', 'RETURN_TO_SUPPLIER', 'RELEASE_AS_IS'];
export function HeldBatchControls({ token, role, caseId, batchId, onAction }: {
  token: string;
  role: Role;
  caseId: string;
  batchId: string;
  onAction: (action: Action) => void;
}) {
  const [disposition, setDisposition] = useState<DispositionValue>('RELABEL');
  const [evidence, setEvidence] = useState('');
  const [reason, setReason] = useState('');
  const [validation, setValidation] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  async function record() {
    if (!evidence.trim()) { setError(''); setValidation('Evidence is required to record a disposition.'); return; }
    setBusy(true); setValidation(''); setError(''); setMessage('');
    try { const result = await api.recordDisposition(token, caseId, { batch_id: batchId, disposition, evidence: evidence.trim() }); setMessage(`Disposition ${result.disposition.replaceAll('_', ' ')} recorded for ${batchId}.`); }
    catch (cause) { setError(cause instanceof ApiError ? `${cause.code}: ${cause.message} · Request ID: ${cause.request_id}` : 'Could not record disposition.'); }
    finally { setBusy(false); }
  }
  async function release() {
    if (!reason.trim()) { setError(''); setValidation('A reason is required to request release.'); return; }
    setBusy(true); setValidation(''); setError(''); setMessage('');
    try { const action = await api.requestRelease(token, caseId, { batch_id: batchId, reason: reason.trim() }); onAction(action); setMessage(`Release requested for ${batchId}: ${action.status.replaceAll('_', ' ')}.`); }
    catch (cause) {
      if (cause instanceof ApiError && cause.code === 'POLICY_VIOLATION') setError(`POLICY_VIOLATION: ${batchId} needs an approved disposition first. ${cause.message} · Request ID: ${cause.request_id}`);
      else setError(cause instanceof ApiError ? `${cause.code}: ${cause.message} · Request ID: ${cause.request_id}` : 'Could not request release.');
    } finally { setBusy(false); }
  }
  return <article className={styles.batch} aria-label={`Held batch ${batchId}`}><h3>{batchId} · HELD</h3>
    {validation && <p role="alert" className={styles.error}>{validation}</p>}{error && <p role="alert" className={styles.error}>{error}</p>}{message && <p role="status" className={styles.success}>{message}</p>}
    <div className={styles.actionForms}>
      {role === 'qa_manager' && <div className={styles.actionForm}><h4>Record disposition</h4><label htmlFor={`disposition-${batchId}`}>Disposition</label><select id={`disposition-${batchId}`} value={disposition} onChange={e => setDisposition(e.target.value as DispositionValue)}>{dispositions.map(value => <option value={value} key={value}>{value.replaceAll('_', ' ')}</option>)}</select><label htmlFor={`evidence-${batchId}`}>Evidence (required)</label><textarea id={`evidence-${batchId}`} value={evidence} onChange={e => { setEvidence(e.target.value); setValidation(''); }} /><button type="button" disabled={busy} onClick={() => void record()}>Record disposition</button></div>}
      <div className={styles.actionForm}><h4>Request release</h4><label htmlFor={`release-reason-${batchId}`}>Reason (required)</label><textarea id={`release-reason-${batchId}`} value={reason} onChange={e => { setReason(e.target.value); setValidation(''); }} /><button type="button" disabled={busy} onClick={() => void release()}>Request release</button></div>
    </div>
  </article>;
}
