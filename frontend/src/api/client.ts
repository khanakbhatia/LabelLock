import { ApiError, type ErrorResponse, type LabelLockApi } from './types';

const baseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api').replace(/\/$/, '');

async function request<T>(path: string, token?: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  let response: Response;
  try { response = await fetch(`${baseUrl}${path}`, { ...init, headers }); }
  catch { throw new ApiError(0, { error: { code: 'UPSTREAM_FAILED', message: 'Network request failed. Check the backend connection.', request_id: '' } }); }
  if (!response.ok) {
    let payload: ErrorResponse;
    try { payload = await response.json() as ErrorResponse; }
    catch { payload = { error: { code: 'INTERNAL_ERROR', message: `Request failed (${response.status})`, request_id: '' } }; }
    throw new ApiError(response.status, payload);
  }
  return response.json() as Promise<T>;
}

export const client: LabelLockApi = {
  login: (username, password) => request('/auth/login', undefined, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) }),
  me: token => request('/auth/me', token),
  createNotice: (token, input) => {
    const form = new FormData();
    form.set('subject', input.subject);
    form.set('body', input.body);
    form.set('attachment', input.attachment);
    return request('/notices', token, { method: 'POST', body: form });
  },
  listMyNotices: token => request('/notices?mine=true', token),
  getInbox: token => request('/inbox', token),
  getNotice: (token, id) => request(`/notices/${encodeURIComponent(id)}`, token),
  getCaseByMessage: (token, id) => request(`/cases/by-message/${encodeURIComponent(id)}`, token),
  ingestEmail: (token, input) => request('/notices/ingest-email', token, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) }),
  getCase: (token, id) => request(`/cases/${encodeURIComponent(id)}`, token),
  runCase: (token, id) => request(`/cases/${encodeURIComponent(id)}/run`, token, { method: 'POST' }),
  listApprovals: token => request('/approvals?status=PENDING_APPROVAL', token),
  approveAction: (token, id, comment) => request(`/actions/${encodeURIComponent(id)}/approve`, token, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ comment }) }),
  rejectAction: (token, id, reason) => request(`/actions/${encodeURIComponent(id)}/reject`, token, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason }) }),
};
