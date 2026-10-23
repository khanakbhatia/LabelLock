import { classes } from '../styles';
import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, ApiError, type CaseStatus, type InboxItem } from '../api';
import { useAuth } from '../auth';

const statusClass: Record<CaseStatus, string> = {
  RECEIVED: 'received', ANALYZING: 'analyzing', AWAITING_APPROVAL: 'awaiting', ESCALATED: 'escalated',
  CONTAINED: 'contained', RESOLVED: 'resolved', NO_IMPACT: 'no-impact', DUPLICATE: 'duplicate',
};
const time = (value: string) => new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
export function Inbox() {
  const { token } = useAuth();
  const navigate = useNavigate();
  const [items, setItems] = useState<InboxItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true); setError('');
    try { setItems(await api.getInbox(token)); }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : 'Could not load the inbox.'); }
    finally { setLoading(false); }
  }, [token]);
  useEffect(() => { void load(); }, [load]);
  return <main className={classes("page")}><div className={classes("page-heading inbox-heading")}><div><span className={classes("eyebrow")}>NORTHFIELD QA / INTAKE</span><h1>QA inbox</h1><p>Supplier changes awaiting review and containment.</p></div><span className={classes("inbox-counter")}>{items.length} notices</span></div><section className={classes("card inbox-card")} aria-labelledby="inbox-title"><div className={classes("card-title")}><div><span className={classes("step-number")}>INCOMING NOTICES</span><h2 id="inbox-title">Change notices</h2></div><button className={classes("button secondary small")} onClick={() => void load()} disabled={loading}>Refresh</button></div>{loading ? <div className={classes("skeleton-list")} role="status" aria-label="Loading inbox"><span>Loading inbox…</span><div /><div /><div /></div> : error ? <div className={classes("empty-state")} role="alert"><span className={classes("placeholder-icon")} aria-hidden="true">!</span><h3>Inbox unavailable</h3><p>{error}</p><button className={classes("button primary")} onClick={() => void load()}>Retry</button></div> : items.length === 0 ? <div className={classes("empty-state")}><span className={classes("placeholder-icon")} aria-hidden="true">◇</span><h3>No notices yet</h3><p>New supplier changes will appear here.</p></div> : <div className={classes("table-scroll")}><table><thead><tr><th scope="col">Supplier / subject</th><th scope="col">Received</th><th scope="col">Attachment</th><th scope="col">Case status</th><th scope="col"><span className={classes("sr-only")}>Open case</span></th></tr></thead><tbody>{items.map(item => <tr key={item.notice_id} onClick={() => navigate(`/cases/${item.case_id}`)}><td><span className={classes("supplier-name")}>{item.supplier}</span><Link className={classes("subject-link")} to={`/cases/${item.case_id}`}>{item.subject}</Link><span className={classes("row-id")}>{item.case_id} · {item.notice_id}</span></td><td><time dateTime={item.received_at}>{time(item.received_at)}</time></td><td>{item.has_attachment ? <span className={classes("attachment-indicator")}><span aria-hidden="true">▤</span> PDF</span> : <span className={classes("muted")}>None</span>}</td><td><span className={classes(`status-chip ${statusClass[item.case_status]}`)}><span className={classes("status-dot")} aria-hidden="true" />{item.case_status.replaceAll('_', ' ')}</span></td><td><Link className={classes("row-arrow")} to={`/cases/${item.case_id}`} aria-label={`Open case ${item.case_id}`}>↗</Link></td></tr>)}</tbody></table></div>}</section><p className={classes("inbox-footnote")}>Showing newest first · Open a notice to view its case</p></main>;
}
