import { classes } from './styles';
import { Navigate, NavLink, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { homeFor, useAuth } from './auth';
import type { Role } from './api';
import { Login } from './views/Login';
import { Supplier } from './views/Supplier';
import { Inbox } from './views/Inbox';
import { GmailPanel } from './panel/GmailPanel';
import { CaseWorkspace } from './views/CaseWorkspace';
import { Approvals } from './views/Approvals';
const panel = import.meta.env.VITE_APP_MODE === 'panel';

function Gate({ allowed }: { allowed: Role[] }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className={classes("center-message")} role="status">Checking session…</div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (!allowed.includes(user.role)) return <NotPermitted />;
  return <Outlet />;
}
function NotPermitted() {
  const { user } = useAuth();
  return <main className={classes("page")}><div className={classes("empty-state")}><span className={classes("eyebrow")}>Access restricted</span><h1>Not permitted for your role</h1><p>This area is available to another LabelLock role.</p><NavLink className={classes("button secondary")} to={user ? homeFor(user.role) : '/login'}>Go to your workspace</NavLink></div></main>;
}
function Shell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  if (!user) return null;
  const navigation = user.role === 'supplier' ? [['/supplier', 'Supplier portal']] : user.role === 'shipping_supervisor' ? [['/cases', 'Cases']] : user.role === 'admin' ? [['/settings', 'Settings']] : user.role === 'agent' ? [['/service', 'Service account']] : [['/inbox', 'QA inbox'], ['/approvals', 'Approvals'], ['/roi', 'ROI']];
  if (panel && ['qa_specialist', 'qa_manager', 'shipping_supervisor'].includes(user.role)) navigation.unshift(['/gmail', 'Gmail']);
  return <div className={classes("app-shell")}><header className={classes("topbar")}><NavLink className={classes("brand")} to={homeFor(user.role)} aria-label="LabelLock home"><span className={classes("brand-mark")} aria-hidden="true">L</span><span>LabelLock</span><span className={classes("brand-divider")} /><span className={classes("brand-caption")}>NORTHFIELD QA</span></NavLink><div className={classes("account")}><span className={classes("account-name")}>{user.name}</span><span className={classes("role-badge")}>{user.role.replaceAll('_', ' ')}</span><button className={classes("text-button")} onClick={() => { logout(); navigate('/login'); }}>Log out</button></div></header><div className={classes("shell-body")}><nav className={classes("sidebar")} aria-label="Main navigation"><p className={classes("nav-label")}>WORKSPACE</p>{navigation.map(([path, label]) => <NavLink key={path} to={path} className={({ isActive }) => classes(`nav-link${isActive ? ' active' : ''}`)}>{label}</NavLink>)}<div className={classes("sidebar-note")}><span className={classes("online-dot")} />Demo workspace<br /><small>Synthetic Northfield data</small></div></nav><div className={classes("content")}><Outlet /></div></div></div>;
}
function Placeholder({ title }: { title: string }) {
  return <main className={classes("page")}><div className={classes("page-heading")}><span className={classes("eyebrow")}>LABELLOCK / WORKSPACE</span><h1>{title}</h1><p>This workspace is being prepared for the next milestone.</p></div><section className={classes("empty-state")}><span className={classes("placeholder-icon")} aria-hidden="true">◇</span><h2>Coming in M2</h2><p>The {title.toLowerCase()} view will be available in the next milestone.</p></section></main>;
}
function Landing() { const { user, loading } = useAuth(); return loading ? <div role="status" className={classes("center-message")}>Checking session…</div> : <Navigate to={user ? homeFor(user.role) : '/login'} replace />; }
export function App() {
  const { user, loading } = useAuth();
  return <Routes><Route path="/login" element={loading ? <div role="status">Checking session…</div> : user ? <Navigate to={homeFor(user.role)} replace /> : <Login />} /><Route path="/" element={<Landing />} /><Route element={<Gate allowed={['supplier', 'qa_specialist', 'qa_manager', 'shipping_supervisor', 'admin', 'agent']} />}><Route element={<Shell />}><Route element={<Gate allowed={['supplier']} />}><Route path="/supplier" element={<Supplier />} /></Route><Route element={<Gate allowed={['qa_specialist', 'qa_manager']} />}><Route path="/inbox" element={<Inbox />} /><Route path="/approvals" element={<Approvals />} /><Route path="/roi" element={<Placeholder title="ROI dashboard" />} /></Route><Route element={<Gate allowed={['qa_specialist', 'qa_manager', 'shipping_supervisor']} />}><Route path="/cases" element={<Placeholder title="Cases" />} /><Route path="/gmail" element={panel ? <GmailPanel /> : <NotPermitted />} /><Route path="/cases/:id" element={<CaseWorkspace />} /></Route><Route element={<Gate allowed={['admin']} />}><Route path="/settings" element={<Placeholder title="Settings" />} /></Route><Route element={<Gate allowed={['agent']} />}><Route path="/service" element={<Placeholder title="Service account" />} /></Route></Route></Route><Route path="*" element={<Navigate to="/" replace />} /></Routes>;
}
