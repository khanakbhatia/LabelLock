/**
 * Off-camera setup through the product's own HTTP API (no database edits): reset, submit, run, approve.
 * Each clip starts from clean seed data and is brought to its starting point the same way a user would.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export const API = 'http://localhost:8000/api';
export const SIM = 'http://localhost:8000/sim';
export const SIM_KEY = 'dev-sim-key';
const NOTICES = fileURLToPath(new URL('../../backend/tests/fixtures/notices/', import.meta.url));
export const NOTICE = {
  subject: 'Lecithin source change from lot VL-2291',
  body: readFileSync(`${NOTICES}vl2291_body.txt`, 'utf-8'),
  pdfPath: `${NOTICES}RM-114_spec_rev4.pdf`,
};

const tokens = new Map<string, string>();

async function call(method: string, path: string, user?: string, body?: unknown, raw = false) {
  const headers: Record<string, string> = {};
  if (user) headers.Authorization = `Bearer ${await token(user)}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  const res = await fetch(`${API}${path}`, { method, headers, body: payload });
  if (raw) return res;
  const data = res.status === 204 ? null : await res.json();
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status} ${JSON.stringify(data)}`);
  return data;
}

export async function token(user: string): Promise<string> {
  if (!tokens.has(user)) {
    const res = await fetch(`${API}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: user, password: 'demo' }) });
    tokens.set(user, (await res.json()).token);
  }
  return tokens.get(user)!;
}

export const reset = () => call('POST', '/demo/reset', 'admin');
export const setFault = (on: boolean) => call('PUT', '/demo/faults', 'admin', { wms_silent_hold_failure: on });
export const getCase = (id: string) => call('GET', `/cases/${id}`, 'priya.qa');
export const approvals = () => call('GET', '/approvals?status=PENDING_APPROVAL', 'daniel.qam');
export const approve = (id: string, comment: string) => call('POST', `/actions/${id}/approve`, 'daniel.qam', { comment });
/** The raw HTTP response, unprocessed, for showing the server's own answer on camera. */
export const rawCall = (method: string, path: string, user: string, body?: unknown) => call(method, path, user, body, true) as Promise<Response>;

export async function submitNotice(): Promise<string> {
  const form = new FormData();
  form.set('subject', NOTICE.subject);
  form.set('body', NOTICE.body);
  form.set('attachment', new Blob([readFileSync(NOTICE.pdfPath)], { type: 'application/pdf' }), 'RM-114_spec_rev4.pdf');
  return (await call('POST', '/notices', 'valley.ingredients', form)).case_id;
}

/** Waits for the agent to finish a run (POST /run is asynchronous). */
export async function waitForRun(id: string, timeoutMs = 90000) {
  const end = Date.now() + timeoutMs;
  for (;;) {
    const c = await getCase(id);
    if (!['RECEIVED', 'ANALYZING'].includes(c.status)) return c;
    if (Date.now() > end) throw new Error(`case ${id} still ${c.status}`);
    await new Promise(r => setTimeout(r, 700));
  }
}

export async function runCase(id: string) {
  await call('POST', `/cases/${id}/run`, 'priya.qa');
  return waitForRun(id);
}

/** The golden-path outcome every story clip relies on; a live run that differs is a bad take. */
export function assertGolden(c: { status: string; batch_decisions: { batch_id: string; decision: string }[] }) {
  const d = Object.fromEntries(c.batch_decisions.map(x => [x.batch_id, x.decision]));
  const want = { 'FG-1040': 'NO_IMPACT', 'FG-1041': 'HOLD_RELABEL', 'FG-1042': 'HOLD_RELABEL', 'FG-1043': 'CLAIM_CONFLICT' };
  if (c.status !== 'AWAITING_APPROVAL' || JSON.stringify(d) !== JSON.stringify(want)) {
    throw new Error(`not a clean golden-path take: ${c.status} ${JSON.stringify(d)}`);
  }
}

export async function simInventory(batch: string) {
  const res = await fetch(`${SIM}/wms/inventory?batch_id=${batch}`, { headers: { 'X-Sim-Key': SIM_KEY } });
  return res.json();
}
