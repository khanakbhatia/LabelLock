import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError, type Action } from '../api';
import { useAuth } from '../auth';
import { ApprovalDecision, describeAction } from './ApprovalDecision';
import { Chip } from './caseDisplay';
import { ActionDetail } from './actionDetail';
import styles from './Workspace.module.css';

const age = (value?: string) => {
  if (!value) return 'Age unavailable';
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60000));
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)} hr ago`;
  return `${Math.floor(minutes / 1440)} days ago`;
};
const messageFor = (reason: unknown) => reason instanceof ApiError ? `${reason.code}: ${reason.message}${reason.request_id ? ` · Request ID: ${reason.request_id}` : ''}` : 'Could not load approvals.';

export function Approvals() {
  const { token, user } = useAuth();
  const [actions, setActions] = useState<Action[]>([]);
  const [destinations, setDestinations] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true); setError('');
    try {
      const pending = await api.listApprovals(token, 'PENDING_APPROVAL');
      setActions(pending.sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '')));
      const cases = [...new Set(pending.map(a => a.case_id).filter((id): id is string => !!id))];
      const result = await Promise.allSettled(cases.map(id => api.getCase(token, id)));
      const names: Record<string, string> = {};
      result.forEach((entry, index) => {
        if (entry.status !== 'fulfilled') return;
        for (const batch of entry.value.trace?.batches ?? []) for (const shipment of batch.shipments) names[`${cases[index]}:${shipment.shipment_id}`] = shipment.destination;
      });
      setDestinations(names);
    } catch (cause) { setError(messageFor(cause)); }
    finally { setLoading(false); }
  }, [token]);
  useEffect(() => { void load(); }, [load]);
  const describe = (action: Action) => {
    const destination = destinations[`${action.case_id}:${action.target.shipment_id}`];
    return destination && action.type === 'REMOVE_FROM_SHIPMENT' ? `${describeAction(action)} to ${destination}` : describeAction(action);
  };
  return <main className={styles.page}><div className={styles.heading}><div><span className={styles.eyebrow}>NORTHFIELD QA / GOVERNANCE</span><h1>Approvals</h1><p>Restricted actions require a QA manager decision.</p></div><button onClick={() => void load()} disabled={loading}>Refresh</button></div>
    {user?.role === 'qa_specialist' && <p>A QA manager must approve or reject these actions.</p>}
    {error && <p role="alert" className={styles.error}>{error} <button onClick={() => void load()}>Retry</button></p>}
    {message && <p role="status" className={styles.success}>{message}</p>}
    {loading ? <p role="status">Loading approvals…</p> : !error && actions.length === 0 ? <section className={styles.card}>No pending approvals.</section> : actions.map(action => <section className={styles.card} key={action.id} aria-label={`Action ${action.id}`}>
      <div className={styles.heading}><div><small>{action.id} · {age(action.created_at)}</small><h2>{describe(action)}</h2></div><Chip tone={action.status === 'REJECTED' ? 'danger' : action.status === 'PENDING_APPROVAL' ? 'warning' : 'good'}>{action.status.replaceAll('_', ' ')}</Chip></div>
      <p>Requested by: {action.requested_by ?? 'Unknown'}</p>
      <ActionDetail action={action} open />
      {action.case_id && <Link to={`/cases/${action.case_id}`}>View case {action.case_id}</Link>}
      {user?.role === 'qa_manager' && token && <ApprovalDecision action={action} description={describe(action)} token={token} onDecision={updated => { setActions(current => current.map(item => item.id === updated.id ? updated : item)); setMessage(`${updated.id}: ${updated.status.replaceAll('_', ' ')}`); }} />}
    </section>)}
  </main>;
}
