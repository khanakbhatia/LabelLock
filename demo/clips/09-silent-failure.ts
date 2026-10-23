import type { Director } from '../lib/overlay.ts';
import { getCase, submitNotice } from '../lib/api.ts';
import { APP, signedIn, tab } from '../lib/flows.ts';

export const setup = async () => ({ caseId: await submitNotice() });

export default async function (d: Director, { caseId }: Record<string, string>) {
  const p = d.page;
  await signedIn(d, 'admin', '/settings');
  await d.caption('09a', async () => {
    const sw = p.getByRole('switch', { name: 'WMS silently fails holds' });
    await sw.waitFor();
    await d.spotlight(sw, 'Test fault, injected by us');
    await d.hold(1200);
    await d.click(sw);
    await p.waitForFunction(() => document.querySelector('[role=switch]')?.getAttribute('aria-checked') === 'true');
    await d.hold(2000);
    await d.clearSpotlight();
  });
  await d.caption('09b', async () => {
    await d.logout();
    await d.login('priya.qa');
    await p.goto(`${APP}/cases/${caseId}`);
    await d.click(p.getByRole('button', { name: 'Run agent' }));
    await p.getByText(/Agent finished/).waitFor({ timeout: 90000 });
    const c = await getCase(caseId);
    if (c.status !== 'ESCALATED' || !c.actions.some((a: { status: string }) => a.status === 'VERIFY_FAILED')) {
      throw new Error(`fault take not clean: ${c.status}`);
    }
  });
  await d.caption('09c', async () => {
    await tab(d, 'Actions');
    await d.spotlight(p.getByRole('row').filter({ hasText: 'Hold FG-1041 at DC-EAST' }), 'WMS said OK · re-check: still AVAILABLE · retried once');
    await d.hold(3000);
    await d.clearSpotlight();
    await tab(d, 'Timeline');
    await d.click(p.getByRole('button', { name: 'Escalations' }));
    await d.spotlight(p.getByRole('tabpanel').locator('article').first(), 'VERIFY_FAILED → ESCALATED');
    await d.hold(3000);
  });
  await d.caption('09d', async () => {
    await p.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
    await d.hold(600);
    await d.spotlight(p.getByText('ESCALATED').first(), 'Escalated · not contained');
    await d.hold(3000);
    await d.clearSpotlight();
  });
}
