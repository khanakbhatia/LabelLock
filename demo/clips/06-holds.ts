import type { Director } from '../lib/overlay.ts';
import { SIM, SIM_KEY } from '../lib/api.ts';
import { APP, analysedCase, openCase, tab } from '../lib/flows.ts';

export const setup = analysedCase;

export default async function (d: Director, { caseId }: Record<string, string>) {
  const p = d.page;
  await openCase(d, 'priya.qa', caseId);
  await d.caption('06a', async () => {
    await tab(d, 'Actions');
    await d.spotlight(p.getByRole('row').filter({ hasText: 'Hold FG-1041 at DC-EAST' }), 'Placed automatically · VERIFIED');
    await d.hold(3000);
  });
  await d.caption('06b', async () => {
    await d.clearSpotlight();
    // The warehouse is a separate (simulated) system. Read it directly at this moment and show the response verbatim
    // on a page labelled as not part of the product.
    const url = `${SIM}/wms/inventory?batch_id=FG-1041`;
    const res = await fetch(url, { headers: { 'X-Sim-Key': SIM_KEY } });
    const body = JSON.stringify(await res.json(), null, 2);
    await p.setContent(`<!doctype html><html><head><style>
      body{margin:0;background:#0c1014;color:#e8eef0;font:24px/1.5 'IBM Plex Mono',ui-monospace,monospace;padding:90px 120px}
      .tag{display:inline-block;background:#f0a443;color:#0c1014;font:600 18px 'IBM Plex Sans',sans-serif;padding:6px 12px;border-radius:6px}
      h1{font:600 30px 'IBM Plex Sans',sans-serif;margin:22px 0 8px} .req{color:#62d2b4;font-size:20px}
      pre{background:#141b20;padding:24px;border-radius:10px} .st{color:#62d2b4;font-size:20px}
      #tick{position:fixed;right:0;bottom:0;width:1px;height:1px;background:#000;animation:t .5s infinite alternate} @keyframes t{from{opacity:.01}to{opacity:.02}}
      </style></head><body><div id="tick"></div>
      <span class="tag">Direct read of the simulated warehouse (WMS) API · not a LabelLock screen</span>
      <h1>Warehouse stock record for batch FG-1041</h1>
      <div class="req">GET ${url.replace(SIM, '/sim')}</div><div class="st">HTTP ${res.status}</div>
      <pre id="resp">${body.replace(/&/g, '&amp;').replace(/</g, '&lt;')}</pre></body></html>`);
    await d.hold(600);
    await d.spotlight(p.locator('#resp'), 'status: HELD, in the warehouse system');
    await d.hold(3500);
    await d.clearSpotlight();
  });
  await d.caption('06c', async () => {
    await p.goto(`${APP}/cases/${caseId}`);
    await tab(d, 'Actions');
    await d.spotlight(p.getByRole('row').filter({ hasText: 'Remove FG-1043 from shipment L-552' }), 'PENDING APPROVAL · QA manager only');
    await d.hold(3000);
    await d.clearSpotlight();
  });
}
