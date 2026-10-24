import { useCallback, useEffect, useState } from 'react';
import { api, ApiError, type RoiSummary } from '../api';
import { useAuth } from '../auth';
import styles from './Roi.module.css';

const scenarios = Array.from({ length: 20 }, (_, i) => `S${String(i + 1).padStart(2, '0')}`);
const message = (cause: unknown) => {
  if (!(cause instanceof ApiError)) return 'The request failed. Please retry.';
  const fields = cause.status === 422 && Array.isArray(cause.details?.fields) ? cause.details.fields as { field?: string; message?: string }[] : [];
  return `${cause.code}: ${fields.map(field => `${field.field ?? 'Field'}: ${field.message ?? cause.message}`).join('; ') || cause.message}${cause.request_id ? ` · Request ID: ${cause.request_id}` : ''}`;
};
const percent = (value: number | null | undefined) => value == null ? 'Unavailable' : `${(value * 100).toFixed(1)}%`;
const elapsedLabel = (ms: number) => `${String(Math.floor(ms / 60000)).padStart(2, '0')}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;
const currency = (value: number) => new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);

export function Roi() {
  const { token, user } = useAuth();
  const [data, setData] = useState<RoiSummary | null>(null);
  const [assumptions, setAssumptions] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [success, setSuccess] = useState('');
  const [scenario, setScenario] = useState('S01');
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [batches, setBatches] = useState('');
  const [falseHolds, setFalseHolds] = useState('');
  const [operator, setOperator] = useState(user?.name ?? '');
  const [submitting, setSubmitting] = useState(false);
  const [stopped, setStopped] = useState(false);
  const load = useCallback(async (keepEdits = false) => {
    if (!token) return;
    setLoading(true); setError('');
    try {
      const next = await api.getRoi(token);
      setData(next);
      if (!keepEdits) setAssumptions(Object.fromEntries(next.assumptions.map(a => [a.key, a.value])));
    } catch (cause) { setError(message(cause)); }
    finally { setLoading(false); }
  }, [token]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (startedAt === null) return;
    const tick = () => setElapsed(Date.now() - startedAt);
    tick();
    const interval = window.setInterval(tick, 250);
    return () => window.clearInterval(interval);
  }, [startedAt]);
  const resetTimer = () => { setStartedAt(null); setElapsed(0); setStopped(false); setSubmitError(''); };
  const manual = data?.measured.manual_median_seconds;
  const agent = data?.measured.agent_median_seconds;
  const both = manual != null && agent != null;
  const hours = both ? (manual - agent) / 3600 * (assumptions.change_notices_per_month ?? 0) : null;
  const submit = async () => {
    if (!token || !stopped) return;
    setSubmitError(''); setSuccess('');
    if (batches.trim() === '' || falseHolds.trim() === '' || !Number.isInteger(Number(batches)) || Number(batches) < 0 || !Number.isInteger(Number(falseHolds)) || Number(falseHolds) < 0 || !operator.trim()) {
      setSubmitError('Enter non-negative whole numbers for batches found and false holds, and an operator name.'); return;
    }
    setSubmitting(true);
    try {
      const logged = await api.logBenchmark(token, { scenario_id: scenario, mode: 'manual', seconds: elapsed / 1000, batches_found: Number(batches), false_holds: Number(falseHolds), operator: operator.trim() });
      setSuccess(`Manual run ${logged.id} logged for ${scenario}.`);
      resetTimer(); setBatches(''); setFalseHolds('');
      await load(true);
    } catch (cause) { setSubmitError(message(cause)); }
    finally { setSubmitting(false); }
  };
  return <main className={styles.page}>
    <div className={styles.intro}><div><span className={styles.eyebrow}>NORTHFIELD QA / EVIDENCE</span><h1>ROI &amp; benchmarks</h1><p>Measured outcomes and editable planning assumptions.</p></div><button onClick={() => void load(true)} disabled={loading}>Refresh</button></div>
    {loading && !data ? <p role="status">Loading ROI metrics…</p> : error ? <div role="alert" className={styles.error}>{error} <button onClick={() => void load(true)}>Retry</button></div> : !data ? <section className={styles.section}>No ROI measurements yet.</section> : <>
      <section className={styles.section} aria-label="Measured results"><h2>Measured</h2>{!data.measured.eval.scenarios && !data.measured.manual_runs && !data.measured.agent_runs ? <p>No measured ROI data yet. Log a manual run below to begin.</p> : <><div className={styles.tiles}>
        <div className={styles.tile}><strong>{data.measured.eval.passed ?? '—'} / {data.measured.eval.scenarios ?? '—'}</strong><span>Scenarios passed</span></div>
        <div className={`${styles.tile} ${styles.highlight}`}><strong>{data.measured.eval.false_holds ?? '—'}</strong><span>False holds</span></div>
        <div className={styles.tile}><strong>{percent(data.measured.eval.batch_recall)}</strong><span>Batch recall</span></div>
        <div className={styles.tile}><strong>{percent(data.measured.eval.decision_accuracy)}</strong><span>Decision accuracy</span></div>
        <div className={styles.tile}><strong>{percent(data.measured.eval.escalation_accuracy)}</strong><span>Escalation accuracy</span></div>
        <div className={styles.tile}><strong>{data.measured.eval.known_gaps ?? '—'}</strong><span>Known gaps</span></div>
      </div><h3>Timed comparison</h3><div className={styles.comparison}>
        <div><strong>{agent == null ? 'Unavailable' : `${agent.toFixed(1)} s`}</strong><span>Agent median · {data.measured.agent_runs} live runs</span></div>
        <div><strong>{manual == null ? 'No manual runs logged yet - use the timer below' : `${manual.toFixed(1)} s`}</strong><span>Manual median · {data.measured.manual_runs} runs</span></div>
        {both && agent > 0 && <div><strong>{(manual / agent).toFixed(1)} x faster</strong><span>Measured median comparison</span></div>}
      </div></>}<p className={styles.method}><strong>Method.</strong> 20 scenarios in backend/scenarios have expected outcomes. Extractions were recorded once from Claude and replayed. Agent time uses live Claude runs only; manual time uses timed runs logged on this page. Known gaps are recorded in docs/decisions.md.</p></section>
      <section className={styles.section} aria-label="Assumptions"><div className={styles.sectionHeader}><h2>Assumptions</h2><button onClick={() => setAssumptions(Object.fromEntries(data.assumptions.map(a => [a.key, a.value])))}>Reset to defaults</button></div><p className={styles.muted}>These are editable inputs for this page only, not measured results. The default values are illustrative placeholders, not sourced figures: replace them with your own.</p><div className={styles.fields}>{data.assumptions.map(a => <label className={styles.field} key={a.key}>{a.label}<small>{a.unit}</small><input type="number" min="0" step="any" value={assumptions[a.key] ?? a.value} onChange={event => setAssumptions(current => ({ ...current, [a.key]: Math.max(0, Number(event.target.value)) }))} /></label>)}</div>
        <div className={styles.estimate}><h3>Estimate from assumptions</h3>{hours === null ? <p>Log a manual run to calculate a time and cost estimate.</p> : <><strong>{hours.toFixed(1)} QA hours saved per month</strong><p>Estimated QA time cost: {currency(hours * (assumptions.qa_hourly_cost ?? 0))} per month.</p><small>Method: (manual median − agent median) ÷ 3600 × change notices per month; multiply hours by loaded QA hourly cost. A negative result means the agent took longer.</small></>}</div>
      </section>
    </>}
    <section className={styles.section} aria-label="Manual benchmark timer"><h2>Manual benchmark timer</h2><p className={styles.muted}>Time a manual scenario run, then record your results.</p><div className={styles.fields}><label className={styles.field}>Scenario<select value={scenario} onChange={event => { setScenario(event.target.value); resetTimer(); }}>{scenarios.map(id => <option key={id}>{id}</option>)}</select></label></div><div className={styles.timer} role="timer" aria-label="Elapsed time">{elapsedLabel(elapsed)}</div><div className={styles.buttons}><button className={styles.primary} disabled={startedAt !== null} onClick={() => { setStartedAt(Date.now() - elapsed); setStopped(false); setSuccess(''); }}>Start</button><button disabled={startedAt === null} onClick={() => { setElapsed(Date.now() - startedAt!); setStartedAt(null); setStopped(true); }}>Stop</button><button onClick={resetTimer}>Reset</button></div>
      {stopped && <div className={styles.fields}><label className={styles.field}>Batches found<input type="number" min="0" step="1" required value={batches} onChange={e => setBatches(e.target.value)} /></label><label className={styles.field}>False holds<input type="number" min="0" step="1" required value={falseHolds} onChange={e => setFalseHolds(e.target.value)} /></label><label className={styles.field}>Operator<input required value={operator} onChange={e => setOperator(e.target.value)} /></label></div>}
      {stopped && <p>Mode: manual · Duration: {(elapsed / 1000).toFixed(1)} seconds</p>}{stopped && <button className={styles.primary} disabled={submitting} onClick={() => void submit()}>{submitting ? 'Submitting…' : 'Log manual run'}</button>}{submitError && <p className={styles.error} role="alert">{submitError}</p>}{success && <p className={styles.success} role="status">{success}</p>}
    </section>
  </main>;
}
