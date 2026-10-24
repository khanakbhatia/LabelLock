import type { Director } from '../lib/overlay.ts';
import { NOTICE, submitNotice } from '../lib/api.ts';
import { APP } from '../lib/flows.ts';

export const setup = async () => ({ caseId: await submitNotice() });

export default async function (d: Director, { caseId }: Record<string, string>) {
  const p = d.page;
  await p.goto(`${APP}/login`);
  d.start();
  await d.caption('02a', async () => {
    await d.login('priya.qa');
    await p.getByText(NOTICE.subject).first().waitFor();
    await d.hold(400);
    await d.spotlight(p.locator('tr, li, article').filter({ hasText: NOTICE.subject }).first(), 'New notice · RECEIVED');
    await d.hold(3000);
    await d.clearSpotlight();
  });
  await d.caption('02b', async () => {
    await d.click(p.getByText(NOTICE.subject).first());
    await p.waitForURL(`**/cases/${caseId}`);
    await p.getByRole('tablist', { name: 'Case views' }).waitFor();
  });
}
