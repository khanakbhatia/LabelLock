import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError, type Action } from '../api';
import { useAuth } from '../auth';
import styles from './Workspace.module.css';

export function Approvals() {
  const { token, user } = useAuth();
  const [actions, setActions] = useState<Action[]>([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    if (!token) return;
    try { setActions(await api.listApprovals(token)); setError(''); }
    catch (reason) { setError(reason instanceof ApiError ? `${reason.code}: ${reason.message} · Request ID: ${reason.request_id}` : 'Could not load approvals.'); }
  }, [token]);
  useEffect(() => { void load(); }, [load]);
  async function decide(action: Action, decision: 'approve' | 'reject') {
    if (!token) return;
    const reason = decision === 'reject' ? window.prompt('Reason for rejection (required):') : '';
    if (decision === 'reject' && !reason?.trim()) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const result = decision === 'approve' ? await api.approveAction(token, action.id, '') : await api.rejectAction(token, action.id, reason!);
      setMessage(`${action.id}: ${result.status.replaceAll('_', ' ')}`);
      await load();
    } catch (cause) { setError(cause instanceof ApiError ? `${cause.code}: ${cause.message} · Request ID: ${cause.request_id}` : 'Action failed.'); }
    finally { setBusy(false); }
  }
  return <main className={styles.page}><h1>Approvals</h1><p>Restricted actions require a QA manager decision.</p>
    {error && <p role="alert" className={styles.error}>{error}</p>}{message && <p role="status" className={styles.success}>{message}</p>}
    {actions.length === 0 && !error ? <p>No pending approvals.</p> : actions.map(action => <section className={styles.card} key={action.id}>
      <small>{action.id} · {action.status.replaceAll('_', ' ')}</small><h2>{action.type.replaceAll('_', ' ')}</h2>
      <p>{Object.entries(action.target).map(([key, value]) => `${key}: ${value}`).join(' · ')}</p>
      <Link to={`/cases/${action.case_id}`}>View case {action.case_id}</Link>
      <div className={styles.buttons}><button disabled={busy} onClick={() => void decide(action, 'approve')}>{user?.role === 'qa_manager' ? 'Approve' : 'Attempt approval (permission check)'}</button>{user?.role === 'qa_manager' && <button disabled={busy} onClick={() => void decide(action, 'reject')}>Reject</button>}</div>
    </section>)}
  </main>;
}
