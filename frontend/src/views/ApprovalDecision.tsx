import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type Action, type CaseDetail } from '../api';
import { isMessage, MessagePreview } from './actionDetail';
import styles from './Workspace.module.css';

export function describeAction(action: Action, trace?: CaseDetail['trace']): string {
  const batch = action.target.batch_id;
  const shipment = action.target.shipment_id;
  if (action.type === 'REMOVE_FROM_SHIPMENT') {
    const destination = trace?.batches.flatMap(b => b.shipments).find(s => s.shipment_id === shipment)?.destination;
    return `Remove ${batch ?? 'batch'} from shipment ${shipment ?? 'unknown'}${destination ? ` to ${destination}` : ''}`;
  }
  if (action.type === 'RELEASE_HOLD') return `Release hold for ${batch ?? 'batch'}`;
  if (action.type === 'PLACE_HOLD') return `Hold ${batch ?? 'batch'}${action.target.location ? ` at ${action.target.location}` : ''}`;
  if (action.type === 'CREATE_RELABEL_TICKET') return `Relabel ticket for ${action.target.sku ?? 'SKU'}`;
  if (action.type === 'SEND_RETAILER_NOTICE') return `Withdrawal notice to ${action.target.to ?? 'retailer'} for ${batch ?? 'batch'}${shipment ? ` (shipment ${shipment})` : ''}`;
  if (action.type === 'SEND_SUPPLIER_QUERY') return `Clarification request to ${action.target.to ?? 'supplier'}`;
  return `${action.type.replaceAll('_', ' ')}${batch ? ` for ${batch}` : ''}`;
}

export function ApprovalDecision({ action, description, token, onDecision }: {
  action: Action;
  description: string;
  token: string;
  onDecision: (updated: Action) => void;
}) {
  const [decision, setDecision] = useState<'approve' | 'reject' | null>(null);
  const [comment, setComment] = useState('');
  const [reason, setReason] = useState('');
  const [validation, setValidation] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const firstField = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (decision) firstField.current?.focus(); }, [decision]);
  const close = () => { if (busy) return; setDecision(null); setValidation(''); setError(''); opener.current?.focus(); };
  const open = (choice: 'approve' | 'reject', button: HTMLButtonElement) => { opener.current = button; setDecision(choice); setError(''); };
  const handleDialogKey = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key !== 'Tab' || !dialogRef.current) return;
    const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>('input, textarea, button:not(:disabled)')];
    if (!focusable.length) return;
    if (event.shiftKey && document.activeElement === focusable[0]) { event.preventDefault(); focusable[focusable.length - 1].focus(); }
    else if (!event.shiftKey && document.activeElement === focusable[focusable.length - 1]) { event.preventDefault(); focusable[0].focus(); }
  };
  async function confirm() {
    if (!decision) return;
    if (decision === 'reject' && !reason.trim()) { setValidation('A reason is required to reject this action.'); return; }
    setBusy(true); setError(''); setValidation('');
    try {
      const updated = decision === 'approve' ? await api.approveAction(token, action.id, comment.trim() || undefined) : await api.rejectAction(token, action.id, reason.trim());
      onDecision(updated);
      setDecision(null);
      opener.current?.focus();
    } catch (cause) {
      setError(cause instanceof ApiError ? `${cause.code}: ${cause.message}${cause.request_id ? ` · Request ID: ${cause.request_id}` : ''}` : 'Could not submit decision.');
    } finally { setBusy(false); }
  }
  if (action.status !== 'PENDING_APPROVAL') return null;
  return <div className={styles.decisionControls}>
    <button type="button" disabled={busy} onClick={e => open('approve', e.currentTarget)}>Approve</button>
    <button type="button" disabled={busy} onClick={e => open('reject', e.currentTarget)}>Reject</button>
    {decision && <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={`Confirm ${decision} ${action.id}`} className={styles.confirmDialog} onKeyDown={handleDialogKey}>
      <h3>Confirm {decision === 'approve' ? 'approval' : 'rejection'}</h3>
      <p>{decision === 'approve' ? 'Approve' : 'Reject'}: <strong>{description}</strong></p>
      {isMessage(action) && <>{decision === 'approve' && <p>Approving sends this message outside the company exactly as written:</p>}<MessagePreview action={action} /></>}
      {decision === 'approve' ? <><label htmlFor={`comment-${action.id}`}>Comment (optional)</label><input ref={firstField as React.RefObject<HTMLInputElement>} id={`comment-${action.id}`} value={comment} onChange={e => setComment(e.target.value)} /></> : <><label htmlFor={`reason-${action.id}`}>Reason (required)</label><textarea ref={firstField as React.RefObject<HTMLTextAreaElement>} id={`reason-${action.id}`} value={reason} onChange={e => { setReason(e.target.value); setValidation(''); }} aria-invalid={!!validation} aria-describedby={validation ? `reason-error-${action.id}` : undefined} />{validation && <p id={`reason-error-${action.id}`} className={styles.error}>{validation}</p>}</>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
      <div className={styles.buttons}><button type="button" disabled={busy} onClick={close}>Cancel</button><button type="button" disabled={busy} onClick={() => void confirm()}>{busy ? 'Submitting…' : `Confirm ${decision}`}</button></div>
    </div>}
  </div>;
}
