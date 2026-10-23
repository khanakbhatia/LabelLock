import type { Action } from '../api';
import { formatTime } from './caseDisplay';
import styles from './Workspace.module.css';

const text = (value: unknown) => typeof value === 'string' ? value : '';

/** Message actions carry their draft in result: {draft_id, to, subject, body, sent_at?}. */
export const isMessage = (action: Action) => action.type === 'SEND_RETAILER_NOTICE' || action.type === 'SEND_SUPPLIER_QUERY';

function deliveryState(action: Action) {
  const sentAt = text(action.result?.sent_at);
  if (sentAt) return `Sent ${formatTime(sentAt)}`;
  if (action.status === 'REJECTED') return 'Rejected - not sent';
  if (action.status === 'ESCALATED') return 'Could not be drafted - not sent';
  return 'Draft - not sent';
}

/** The exact text a QA manager is approving, so nothing leaves the company unread. */
export function MessagePreview({ action }: { action: Action }) {
  const r = action.result ?? {};
  if (!text(r.draft_id)) return <p>No draft available yet.</p>;
  return <div className={styles.message} aria-label={`Message ${text(r.draft_id)}`}>
    <p><strong>{deliveryState(action)}</strong></p>
    <dl><dt>To</dt><dd>{text(r.to)}</dd><dt>Subject</dt><dd>{text(r.subject)}</dd></dl>
    <pre className={styles.messageBody}>{text(r.body)}</pre>
  </div>;
}

/** Extra detail for tickets and messages; nothing for other action types. */
export function ActionDetail({ action, open = false }: { action: Action; open?: boolean }) {
  const r = action.result ?? {};
  if (action.type === 'CREATE_RELABEL_TICKET' && text(r.ticket_id)) {
    return <details open={open}><summary>Ticket {text(r.ticket_id)}</summary><p>{text(r.summary)}</p></details>;
  }
  if (isMessage(action)) {
    return <details open={open}><summary>{deliveryState(action)}: view message</summary><MessagePreview action={action} /></details>;
  }
  return null;
}
