import { classes } from '../styles';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError, type NoticeSummary } from '../api';
import { useAuth } from '../auth';

type FormState = 'idle' | 'validating' | 'submitting' | 'success' | 'error';
const formatTime = (date: string) => new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(date));
export function Supplier() {
  const { token } = useAuth();
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [state, setState] = useState<FormState>('idle');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [result, setResult] = useState('');
  const [apiError, setApiError] = useState<ApiError | null>(null);
  const [notices, setNotices] = useState<NoticeSummary[]>([]);
  const [listError, setListError] = useState('');
  const [listLoading, setListLoading] = useState(true);
  const fileInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!token) return;
    let active = true;
    api.listMyNotices(token).then(data => { if (active) setNotices(data); }).catch(() => { if (active) setListError('Could not load your notices.'); }).finally(() => { if (active) setListLoading(false); });
    return () => { active = false; };
  }, [token]);
  function validate() {
    const next: Record<string, string> = {};
    if (!subject.trim()) next.subject = 'Enter a subject.';
    if (!body.trim()) next.body = 'Enter a message.';
    if (!file) next.attachment = 'Attach a PDF.';
    else if (file.type !== 'application/pdf' || !file.name.toLowerCase().endsWith('.pdf')) next.attachment = 'Choose a PDF file.';
    else if (file.size > 5 * 1024 * 1024) next.attachment = 'PDF must be 5 MB or smaller.';
    setErrors(next);
    return !Object.keys(next).length;
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); setState('validating'); setApiError(null);
    if (!validate() || !token || !file) return;
    setState('submitting');
    try {
      const created = await api.createNotice(token, { subject: subject.trim(), body: body.trim(), attachment: file });
      setResult(created.notice_id); setState('success'); setSubject(''); setBody(''); setFile(null); setErrors({});
      if (fileInput.current) fileInput.current.value = '';
      setNotices(await api.listMyNotices(token)); setListError('');
    } catch (reason) {
      setApiError(reason instanceof ApiError ? reason : new ApiError(0, { error: { code: 'INTERNAL_ERROR', message: 'Could not submit the notice.', request_id: '' } }));
      setState('error');
    }
  }
  return <main className={classes("page")}><div className={classes("page-heading")}><span className={classes("eyebrow")}>SUPPLIER / NOTICES</span><h1>Supplier portal</h1><p>Share a product or specification change with Northfield QA.</p></div><div className={classes("portal-grid")}><section className={classes("card form-card")} aria-labelledby="new-notice"><div className={classes("card-title")}><div><span className={classes("step-number")}>01 / SUBMISSION</span><h2 id="new-notice">New change notice</h2></div><span className={classes("subtle-tag")}>Secure intake</span></div><p className={classes("section-help")}>Include the change and its effective lot in your message. Attach the updated PDF specification.</p>{state === 'success' && <div className={classes("alert success")} role="status"><strong>Received by Northfield QA</strong><span>Notice ID: <code>{result}</code>. Your submission is now in the QA queue.</span></div>}{state === 'error' && apiError && <div className={classes("alert error")} role="alert"><strong>Submission failed</strong><span>{apiError.message}{apiError.request_id && <> · Request ID: <code>{apiError.request_id}</code></>}</span></div>}<form onSubmit={submit} noValidate><label htmlFor="subject">Subject <span aria-hidden="true">*</span></label><input id="subject" value={subject} onChange={e => setSubject(e.target.value)} placeholder="e.g. Lecithin source change from lot VL-2291" aria-invalid={!!errors.subject} aria-describedby={errors.subject ? 'subject-error' : undefined} />{errors.subject && <span className={classes("field-error")} id="subject-error">{errors.subject}</span>}<label htmlFor="message">Message body <span aria-hidden="true">*</span></label><textarea id="message" rows={7} value={body} onChange={e => setBody(e.target.value)} placeholder="Describe what changed, when it takes effect, and the affected lots." aria-invalid={!!errors.body} aria-describedby={errors.body ? 'body-error' : undefined} />{errors.body && <span className={classes("field-error")} id="body-error">{errors.body}</span>}<label htmlFor="attachment">Specification PDF <span aria-hidden="true">*</span></label><div className={classes("upload-box")}><span className={classes("upload-icon")} aria-hidden="true">↥</span><input ref={fileInput} id="attachment" type="file" accept="application/pdf,.pdf" onChange={e => setFile(e.target.files?.[0] ?? null)} aria-invalid={!!errors.attachment} aria-describedby={errors.attachment ? 'attachment-error attachment-hint' : 'attachment-hint'} /><small id="attachment-hint">PDF only · Maximum 5 MB</small></div>{errors.attachment && <span className={classes("field-error")} id="attachment-error">{errors.attachment}</span>}<div className={classes("form-actions")}><span>Fields marked * are required</span><button className={classes("button primary")} type="submit" disabled={state === 'submitting'}>{state === 'submitting' ? 'Submitting…' : 'Submit notice'} <span aria-hidden="true">→</span></button></div></form></section><aside className={classes("process-card")}><span className={classes("eyebrow")}>WHAT HAPPENS NEXT</span><h2>From notice to action</h2><ol><li><span>1</span><div><strong>QA receives your notice</strong><p>The change appears in Northfield’s inbox.</p></div></li><li><span>2</span><div><strong>A case is opened</strong><p>The team reviews the specification and affected lots.</p></div></li><li><span>3</span><div><strong>Impact is tracked</strong><p>Decisions and outcomes are recorded against the case.</p></div></li></ol><div className={classes("privacy-note")}>Your portal shows only notices submitted by your supplier account.</div></aside></div><section className={classes("card list-card")} aria-labelledby="my-notices"><div className={classes("card-title")}><div><span className={classes("step-number")}>02 / HISTORY</span><h2 id="my-notices">My notices</h2></div><span className={classes("count-pill")}>{notices.length}</span></div>{listLoading ? <p role="status">Loading your notices…</p> : listError ? <p className={classes("alert error")} role="alert">{listError}</p> : notices.length === 0 ? <div className={classes("empty-mini")}>No notices yet. Your submissions will appear here.</div> : <ul className={classes("notice-list")}>{notices.map(notice => <li key={notice.id}><div className={classes("notice-icon")} aria-hidden="true">▤</div><div className={classes("notice-main")}><strong>{notice.subject}</strong><span>{notice.id} · {formatTime(notice.received_at)} {notice.has_attachment && '· PDF attached'}</span></div><span className={classes("status-chip received")}>{notice.case_status.replaceAll('_', ' ')}</span></li>)}</ul>}</section></main>;
}
