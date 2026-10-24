import { useState } from 'react';
import { api, ApiError } from '../api';
import { useAuth } from '../auth';
import styles from './Roi.module.css';

const describe = (cause: unknown) => cause instanceof ApiError ? cause.status === 404 ? 'Demo controls are disabled on this server (DEMO_MODE=false)' : `${cause.code}: ${cause.message}${cause.request_id ? ` · Request ID: ${cause.request_id}` : ''}` : 'Could not reach the server. Please retry.';
export function Settings() {
  const { token } = useAuth();
  const [confirming, setConfirming] = useState(false);
  const [fault, setFault] = useState(false);
  const [lastSet, setLastSet] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const reset = async () => {
    if (!token) return;
    setBusy(true); setError(''); setStatus('');
    try { await api.resetDemo(token); setFault(false); setLastSet(null); setStatus('Demo reset. Fault switch is off.'); setConfirming(false); }
    catch (cause) { setError(describe(cause)); setConfirming(false); }
    finally { setBusy(false); }
  };
  const toggle = async () => {
    if (!token) return;
    setBusy(true); setError(''); setStatus('');
    try { await api.setFaults(token, { wms_silent_hold_failure: !fault }); setFault(!fault); setLastSet(new Date().toLocaleString()); setStatus(`WMS silent hold failure ${!fault ? 'on' : 'off'}.`); }
    catch (cause) { setError(describe(cause)); }
    finally { setBusy(false); }
  };
  return <main className={styles.page}><span className={styles.eyebrow}>NORTHFIELD QA / ADMIN</span><h1>Settings</h1><p>Demo controls for the Northfield sandbox.</p>
    {error && <p className={styles.error} role="alert">{error}</p>}{status && <p className={styles.success} role="status">{status}</p>}
    <section className={styles.section}><h2>Demo controls</h2><h3>Reset demo</h3><p>Reload the warehouse and start a clean demo.</p><button disabled={busy} onClick={() => setConfirming(true)}>Reset demo</button><h3>Fault switch</h3><p>WMS silently fails holds: <strong>{fault ? 'on' : 'off (after reset)'}</strong></p><button type="button" role="switch" aria-checked={fault} aria-label="WMS silently fails holds" disabled={busy} onClick={() => void toggle()}>{fault ? 'Turn fault off' : 'Turn fault on'}</button>{lastSet && <p className={styles.muted}>Last set at {lastSet}</p>}<p className={styles.muted}>The server has no endpoint to read the current fault state. This indicator reflects actions in this page since it opened.</p></section>
    <section className={styles.section}><h2>Demo script</h2><ol><li>Reset demo.</li><li>Run the golden path.</li><li>Approve shipment removal.</li><li>Turn the fault on.</li><li>Run another case and inspect verification failure.</li><li>Reset demo.</li></ol></section><section className={styles.section}><h2>More settings</h2><p>Rules, roles and adapters: Coming later.</p></section>
    {confirming && <div role="dialog" aria-modal="true" aria-labelledby="reset-title" className={styles.confirm} onKeyDown={e => { if (e.key === 'Escape' && !busy) setConfirming(false); }}><h2 id="reset-title">Confirm demo reset</h2><p>All cases, notices, actions and audit events are deleted and the simulated warehouse is reloaded from seed data; the fault switch turns off. Logged benchmark runs are kept.</p><div className={styles.buttons}><button autoFocus disabled={busy} onClick={() => setConfirming(false)}>Cancel</button><button className={styles.primary} disabled={busy} onClick={() => void reset()}>{busy ? 'Resetting…' : 'Confirm reset'}</button></div></div>}
  </main>;
}
