import type { Director } from '../lib/overlay.ts';
import { approvals, rawCall } from '../lib/api.ts';
import { APP, analysedCase, signedIn, tab } from '../lib/flows.ts';

export const setup = analysedCase;

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');

export default async function (d: Director, { caseId }: Record<string, string>) {
  const p = d.page;
  await signedIn(d, 'priya.qa', '/approvals');
  await d.caption('07a', async () => {
    await p.getByText('A QA manager must approve or reject these actions.').waitFor();
    await d.spotlight(p.getByRole('region', { name: /Action / }).first(), 'No approve button for a QA specialist');
    await d.hold(3000);
    await d.clearSpotlight();
  });
  await d.caption('07b', async () => {
    // The real HTTP response from the server, shown verbatim on a page labelled as not part of the product.
    const [removal] = await approvals();
    const path = `/api/actions/${removal.id}/approve`;
    const res = await rawCall('POST', `/actions/${removal.id}/approve`, 'priya.qa', { comment: 'approve' });
    const body = JSON.stringify(await res.json(), null, 2);
    await p.setContent(`<!doctype html><html><head><style>
      body{margin:0;background:#0c1014;color:#e8eef0;font:20px/1.5 'IBM Plex Mono',ui-monospace,monospace;padding:90px 120px}
      .tag{display:inline-block;background:#f0a443;color:#0c1014;font:600 18px 'IBM Plex Sans',sans-serif;padding:6px 12px;border-radius:6px}
      h1{font:600 30px 'IBM Plex Sans',sans-serif;margin:22px 0 8px} .req{color:#62d2b4}
      pre{background:#141b20;padding:22px;border-radius:10px;white-space:pre-wrap} .st{color:#ff8a7a;font-weight:600}
      #tick{position:fixed;right:0;bottom:0;width:1px;height:1px;background:#000;animation:t .5s infinite alternate} @keyframes t{from{opacity:.01}to{opacity:.02}}
      </style></head><body><div id="tick"></div>
      <span class="tag">Direct API call · not a LabelLock screen</span>
      <h1>Signed in as priya.qa (QA specialist)</h1>
      <div class="req">POST ${esc(path)}</div>
      <div class="st">HTTP ${res.status} ${esc(res.statusText)}</div>
      <pre id="resp">${esc(body)}</pre></body></html>`);
    await d.hold(300);
    await d.spotlight(p.locator('#resp'), 'The real server response');
    await d.hold(3000);
    await d.clearSpotlight();
  });
  await d.caption('07c', async () => {
    await p.goto(`${APP}/inbox`);  // back to the app (still signed in as priya.qa), then sign out properly
    await d.logout();
    await d.login('marco.ship');
    await p.goto(`${APP}/cases/${caseId}`);
    await tab(d, 'Actions');
    const reason = p.locator('#release-reason-FG-1041');
    await d.scrollTo(reason);
    await d.type(reason, 'Relabelled, ready to ship');
    await d.click(reason.locator('xpath=following-sibling::button'));
    const refusal = p.getByRole('alert').filter({ hasText: 'POLICY_VIOLATION' });
    await refusal.waitFor();
    await d.spotlight(refusal, 'Refused by policy');
    await d.hold(3000);
    await d.clearSpotlight();
  });
}
