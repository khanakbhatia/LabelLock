import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../api';
import { useAuth } from '../auth';
import styles from './Roi.module.css';

const describe = (cause: unknown) => cause instanceof ApiError ? cause.status === 404 ? 'Demo controls are disabled on this server (DEMO_MODE=false)' : `${cause.code}: ${cause.message}${cause.request_id ? ` · Request ID: ${cause.request_id}` : ''}` : 'Could not reach the server. Please retry.';
export function Settings() {
  const { token } = useAuth();
  const [confirming, setConfirming] = useState(false);
  const [fault, setFault] = useState<boolean | null>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const readFault = useCallback(async () => {
    if (!token) throw new Error('Not signed in');
    const current = await api.getFaults(token);
    setFault(current.wms_silent_hold_failure);
    setCheckedAt(new Date().toLocaleString());
    return current.wms_silent_hold_failure;
  }, [token]);
  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try { await readFault(); }
    catch (cause) { setFault(null); setError(describe(cause)); }
    finally { setLoading(false); }
  }, [readFault]);
  useEffect(() => { void refresh(); }, [refresh]);
  const reset = async () => {
    if (!token) return;
    setBusy(true); setError(''); setStatus('');
    try {
      await api.resetDemo(token);
      const observed = await readFault();
      if (observed) setError('Reset completed, but the server still reports WMS silently fails holds is on.');
      else setStatus('Demo reset. Server confirms the fault switch is off.');
    } catch (cause) { setError(describe(cause)); }
    finally { setConfirming(false); setBusy(false); }
  };
  const toggle = async () => {
    if (!token || fault === null) return;
    const requested = !fault;
    setBusy(true); setError(''); setStatus('');
    try {
      await api.setFaults(token, { wms_silent_hold_failure: requested });
      const observed = await readFault();
      if (observed !== requested) setError(`Fault update did not match the server read-back: expected ${requested ? 'on' : 'off'}, server reports ${observed ? 'on' : 'off'}.`);
      else setStatus(`Server confirms WMS silent hold failure ${observed ? 'on' : 'off'}.`);
    } catch (cause) { setError(describe(cause)); }
    finally { setBusy(false); }
  };
  return <main className={styles.page}><span className={styles.eyebrow}>NORTHFIELD QA / ADMIN</span><h1>Settings</h1><p>Demo controls for the Northfield sandbox.</p>
    {loading && <p role="status">Checking demo fault state…</p>}{error && <p className={styles.error} role="alert">{error} <button onClick={() => void refresh()} disabled={loading || busy}>Retry</button></p>}{status && <p className={styles.success} role="status">{status}</p>}
    <section className={styles.section}><h2>Demo controls</h2><h3>Reset demo</h3><p>Reload the warehouse and start a clean demo.</p><button disabled={busy || loading || fault === null} onClick={() => setConfirming(true)}>Reset demo</button><h3>Fault switch</h3><p>WMS silently fails holds: <strong>{fault === null ? 'Unknown until checked' : fault ? 'on' : 'off'}</strong></p><button type="button" role="switch" aria-checked={fault ?? false} aria-label="WMS silently fails holds" disabled={busy || loading || fault === null} onClick={() => void toggle()}>{fault ? 'Turn fault off' : 'Turn fault on'}</button>{checkedAt && <p className={styles.muted}>Checked at {checkedAt}</p>}</section>
    <section className={styles.section}><h2>Demo script</h2><ol><li>Reset demo.</li><li>Run the golden path.</li><li>Approve shipment removal.</li><li>Turn the fault on.</li><li>Run another case and inspect verification failure.</li><li>Reset demo.</li></ol></section><section className={styles.section}><h2>More settings</h2><p>Rules, roles and adapters: Coming later.</p></section>
    {confirming && <div role="dialog" aria-modal="true" aria-labelledby="reset-title" className={styles.confirm} onKeyDown={e => { if (e.key === 'Escape' && !busy) setConfirming(false); }}><h2 id="reset-title">Confirm demo reset</h2><p>All cases, notices, actions and audit events are deleted and the simulated warehouse is reloaded from seed data; the fault switch turns off.</p><div className={styles.buttons}><button autoFocus disabled={busy} onClick={() => setConfirming(false)}>Cancel</button><button className={styles.primary} disabled={busy} onClick={() => void reset()}>{busy ? 'Resetting…' : 'Confirm reset'}</button></div></div>}
  </main>;
}
