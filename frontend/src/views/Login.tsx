import { classes } from '../styles';
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '../api';
import { homeFor, useAuth } from '../auth';

const demos = [
  { username: 'valley.ingredients', role: 'Supplier' }, { username: 'priya.qa', role: 'QA specialist' },
  { username: 'daniel.qam', role: 'QA manager' }, { username: 'marco.ship', role: 'Shipping supervisor' },
  { username: 'admin', role: 'Admin' },
];
export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { const user = await login(username.trim(), password); navigate(homeFor(user.role), { replace: true }); }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : 'Unable to sign in. Please try again.'); }
    finally { setBusy(false); }
  }
  return <main className={classes("login-shell")}><div className={classes("login-intro")}><div className={classes("login-brand")}><span className={classes("brand-mark")} aria-hidden="true">L</span> LabelLock</div><span className={classes("eyebrow")}>AGENT OPERATIONS / NORTHFIELD SNACKS</span><h1>Every change,<br /><em>accounted for.</em></h1><p>Trace supplier changes to the batches they touch. Keep decisions, actions and evidence in one accountable workspace.</p><div className={classes("intro-line")}><span>01</span> NOTICE <span>→</span> TRACE <span>→</span> CONTAIN</div></div><div className={classes("login-panel")}><div className={classes("login-card")}><span className={classes("eyebrow")}>WELCOME BACK</span><h2>Sign in to LabelLock</h2><p>Enter your demo credentials to open your workspace.</p><form onSubmit={submit}><label htmlFor="username">Username</label><input id="username" value={username} onChange={e => setUsername(e.target.value)} autoComplete="username" required /><label htmlFor="password">Password</label><input id="password" type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" required />{error && <p className={classes("alert error")} role="alert">{error}</p>}<button className={classes("button primary full")} disabled={busy} type="submit">{busy ? 'Signing in…' : 'Sign in'} <span aria-hidden="true">→</span></button></form><div className={classes("demo-users")}><div className={classes("demo-heading")}><strong>Demo users</strong><span>Password: <code>demo</code></span></div><div className={classes("demo-grid")}>{demos.map(d => <button type="button" key={d.username} onClick={() => { setUsername(d.username); setPassword('demo'); setError(''); }}><span>{d.username}</span><small>{d.role}</small></button>)}</div></div></div><p className={classes("demo-disclosure")}>Demo environment. All companies, products, batches and enterprise systems are synthetic.</p></div></main>;
}
