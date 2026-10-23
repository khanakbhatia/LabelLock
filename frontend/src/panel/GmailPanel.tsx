import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError, type CaseSummary } from '../api';
import { useAuth } from '../auth';
import { createGmailTransport, emailCard, recentSupplierEmails, type EmailCard } from '../../../extension/src/gmail';
import { verifyDetectedEmail, type DetectedEmail } from '../../../extension/src/detection';
import { analyzeEmail } from '../../../extension/src/flow';
import styles from './GmailPanel.module.css';

const errorText = (reason: unknown) => reason instanceof ApiError
  ? `${reason.code}: ${reason.message}${reason.request_id ? ` · Request ID: ${reason.request_id}` : ''}`
  : reason instanceof Error ? reason.message : 'An unexpected error occurred.';
const getToken = async () => {
  const result = await chrome.identity.getAuthToken({ interactive: true });
  if (!result.token) throw new Error('Gmail authorization did not return a token.');
  return result.token;
};

export function GmailPanel() {
  const { token, user } = useAuth();
  const navigate = useNavigate();
  const gmail = useMemo(() => createGmailTransport(getToken), []);
  const [recent, setRecent] = useState<EmailCard[]>([]);
  const [selected, setSelected] = useState<EmailCard | null>(null);
  const [existing, setExisting] = useState<CaseSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [checking, setChecking] = useState(false);

  const select = useCallback(async (id: string) => {
    if (!token) return;
    setChecking(true); setError(''); setExisting(null);
    try {
      const message = await gmail.getMessage(id);
      setSelected(emailCard(message));
      try { setExisting(await api.getCaseByMessage(token, message.id)); }
      catch (reason) { if (!(reason instanceof ApiError && reason.status === 404)) throw reason; }
    } catch (reason) { setError(errorText(reason)); setSelected(null); }
    finally { setChecking(false); }
  }, [gmail, token]);

  const refresh = useCallback(async () => {
    setBusy(true); setError('');
    try { setRecent(await recentSupplierEmails(gmail)); }
    catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }, [gmail]);

  const handleDetection = useCallback(async (candidate: DetectedEmail) => {
    const id = await verifyDetectedEmail(candidate, gmail);
    if (id) { setNotice('Opened Gmail message verified with the Gmail API.'); await select(id); }
    else { setNotice('Could not verify the opened Gmail message. Choose one from Recent supplier emails.'); await refresh(); }
  }, [gmail, refresh, select]);

  useEffect(() => {
    void refresh();
    void chrome.storage.session.get('detected_email').then(value => {
      if (value.detected_email) void handleDetection(value.detected_email as DetectedEmail);
    });
    const listener = (message: { type?: string; candidate?: DetectedEmail }) => {
      if (message.type === 'GMAIL_CANDIDATE' && message.candidate) void handleDetection(message.candidate);
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, [handleDetection, refresh]);

  async function analyze() {
    if (!selected || !token) return;
    setBusy(true); setError('');
    try {
      const result = await analyzeEmail(selected.id, token, gmail, api);
      setNotice(result.duplicate ? 'This email already had a case.' : 'Email analyzed; case opened.');
      navigate(`/cases/${result.case_id}`);
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }

  return <main className={styles.page}>
    <header><span className={styles.eyebrow}>GMAIL / INTAKE</span><h1>Supplier emails</h1><p>Review an opened message or select a recent PDF email.</p></header>
    {notice && <p className={styles.notice} role="status">{notice}</p>}
    {error && <p className={styles.error} role="alert">{error}</p>}
    {selected && <section className={styles.card} aria-label="Selected email">
      <small>SELECTED EMAIL</small><h2>{selected.subject}</h2><p><strong>From:</strong> {selected.from}</p>
      <p><strong>PDF:</strong> {selected.attachmentNames.join(', ') || 'None'}</p>
      {checking ? <p role="status">Checking for a case…</p> : existing
        ? <><p>Existing case: <strong>{existing.id}</strong> · {existing.status.replaceAll('_', ' ')}</p><button onClick={() => navigate(`/cases/${existing.id}`)}>Open case</button></>
        : user?.role === 'shipping_supervisor' ? <p>Only QA can analyze an email.</p>
          : <button disabled={busy || !selected.attachmentNames.length} onClick={() => void analyze()}>{busy ? 'Analyzing…' : 'Analyze with LabelLock'}</button>}
    </section>}
    <section className={styles.card} aria-labelledby="recent-heading"><div className={styles.row}><h2 id="recent-heading">Recent supplier emails</h2><button onClick={() => void refresh()} disabled={busy}>Refresh</button></div>
      {busy && !recent.length ? <p role="status">Loading Gmail emails…</p> : recent.length === 0 ? <p>No inbox PDF emails found.</p> : <ul>{recent.map(email => <li key={email.id}><button className={styles.emailButton} onClick={() => void select(email.id)} aria-current={selected?.id === email.id ? 'true' : undefined}><strong>{email.subject}</strong><span>{email.from}</span><small>{email.attachmentNames.join(', ')}</small></button></li>)}</ul>}
    </section>
  </main>;
}
