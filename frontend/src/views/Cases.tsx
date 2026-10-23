import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, ApiError, type CaseSummary } from '../api';
import { useAuth } from '../auth';
import { Chip, flagLabel, formatTime } from './caseDisplay';
import styles from './Workspace.module.css';

export function Cases() {
  const { token } = useAuth();
  const navigate = useNavigate();
  const [items, setItems] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true); setError('');
    try { setItems(await api.listCases(token)); }
    catch (reason) { setError(reason instanceof ApiError ? `${reason.code}: ${reason.message} · Request ID: ${reason.request_id}` : 'Could not load cases.'); }
    finally { setLoading(false); }
  }, [token]);
  useEffect(() => { void load(); }, [load]);
  return <main className={styles.page}><div className={styles.heading}><div><span className={styles.eyebrow}>NORTHFIELD QA / CASES</span><h1>Cases</h1><p>Current supplier changes and their containment state.</p></div><button onClick={() => void load()} disabled={loading}>Refresh</button></div>
    {loading ? <div role="status" aria-label="Loading cases" className={styles.skeleton}><span>Loading cases…</span><div /><div /><div /></div> : error ? <div role="alert" className={styles.error}><p>{error}</p><button onClick={() => void load()}>Retry</button></div> : items.length === 0 ? <div className={styles.card}>No cases yet.</div> : <div className={styles.card}><div className={styles.scroll}><table><thead><tr><th>Supplier / subject</th><th>Opened</th><th>Status</th><th>Pending approvals</th></tr></thead><tbody>{items.map(item => <tr key={item.id} onClick={() => navigate(`/cases/${item.id}`)}><td><strong>{item.supplier}</strong><br /><Link to={`/cases/${item.id}`}>{item.subject}</Link><br /><small>{item.id}</small>{item.uncertainty_flags.map(flag => <Chip key={flag} tone="warning">{flagLabel(flag)}</Chip>)}</td><td><time dateTime={item.opened_at}>{formatTime(item.opened_at)}</time></td><td><Chip tone={item.status === 'ESCALATED' ? 'danger' : item.status === 'AWAITING_APPROVAL' ? 'warning' : 'neutral'}>{item.status.replaceAll('_', ' ')}</Chip></td><td>{item.pending_approvals}</td></tr>)}</tbody></table></div></div>}
  </main>;
}
