/** Small, reusable on-camera flows. All of them drive the real UI. */
import type { Page } from 'playwright';
import type { Director } from './overlay.ts';
import * as api from './api.ts';

export const APP = 'http://localhost:5173';

export const DISCLOSURE = 'Northfield Snacks, suppliers, products, batches and enterprise systems are fictional. ERP, WMS and label systems are simulated by us; their state is real and changes on every action.';

/** Signs in through the real login page before the clip starts (trimmed), then the clip opens on the page. */
export async function signedIn(d: Director, user: string, path: string) {
  await d.page.goto(`${APP}/login`);
  await d.login(user);
  await d.page.goto(`${APP}${path}`);
  await d.page.waitForLoadState('networkidle');
  d.start();
  await d.hold(700);
}

export async function openCase(d: Director, user: string, caseId: string) {
  await signedIn(d, user, `/cases/${caseId}`);
  await d.page.getByRole('tablist', { name: 'Case views' }).waitFor();
}

export async function tab(d: Director, name: string) {
  await d.click(d.page.getByRole('tab', { name }));
}

/** Setup used by most story clips: a clean golden-path case, analysed live by the agent. */
export async function analysedCase() {
  const caseId = await api.submitNotice();
  api.assertGolden(await api.runCase(caseId));
  return { caseId };
}

export async function card(page: Page, d: Director, title: string, subtitle: string, seconds: number) {
  await page.setContent(`<!doctype html><html><head>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500&family=IBM+Plex+Sans:wght@400;600&display=swap" rel="stylesheet">
    <style>html,body{margin:0;height:100%;background:#0c1014;color:#e8eef0;font-family:'IBM Plex Sans',sans-serif}
    main{height:100%;display:flex;flex-direction:column;justify-content:center;padding:0 140px;box-sizing:border-box}
    .k{font:500 18px 'IBM Plex Mono',monospace;letter-spacing:.24em;color:#62d2b4;margin-bottom:26px}
    h1{font-weight:600;font-size:${title.length > 60 ? 46 : 64}px;line-height:1.15;margin:0;max-width:1250px}
    .s{margin-top:22px;font-size:24px;color:#62d2b4}
    .d{position:absolute;left:140px;right:140px;bottom:56px;font-size:17px;line-height:1.5;color:#93a3a8;border-top:1px solid #23302f;padding-top:18px}
    #tick{position:fixed;right:0;bottom:0;width:1px;height:1px;background:#000;animation:t .5s infinite alternate}
    @keyframes t{from{opacity:.01}to{opacity:.02}}
    </style></head><body><div id="tick"></div><main><div class="k">LABELLOCK</div><h1>${title}</h1>${subtitle ? `<div class="s">${subtitle}</div>` : ''}</main>
    <div class="d">${DISCLOSURE}</div></body></html>`);
  await page.waitForLoadState('networkidle');
  await page.evaluate(() => document.fonts.ready);
  d.start();
  await d.hold(seconds * 1000);
}
