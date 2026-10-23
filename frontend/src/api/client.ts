import { ApiError, type ErrorResponse, type LabelLockApi } from './types';

const baseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api').replace(/\/$/, '');

async function request<T>(path: string, token?: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers });
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
};
