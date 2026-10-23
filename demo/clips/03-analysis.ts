import type { Director } from '../lib/overlay.ts';
import { assertGolden, getCase, submitNotice } from '../lib/api.ts';
import { openCase } from '../lib/flows.ts';

export const setup = async () => ({ caseId: await submitNotice() });

export default async function (d: Director, { caseId }: Record<string, string>) {
  const p = d.page;
  await openCase(d, 'priya.qa', caseId);
  await d.caption('03a', async () => {
    await d.click(p.getByRole('button', { name: 'Run agent' }));
    await p.getByText(/Agent finished/).waitFor({ timeout: 90000 });
    assertGolden(await getCase(caseId));
    await d.hold(1500);
  });
  const panel = p.getByRole('tabpanel');
  await d.caption('03b', async () => {
    const table = panel.locator('table');
    await d.scrollTo(table);
    await d.spotlight(table, 'Value · status · exact quote · source');
    await d.hold(3000);
    await d.spotlight(panel.locator('tr').filter({ hasText: /may contain/i }), 'Not stated → MISSING, not guessed');
    await d.hold(3000);
  });
  await d.caption('03c', async () => {
    const rule = panel.getByText(/Rule ALG-/).first();
    await d.scrollTo(rule);
    await d.spotlight(rule, 'Soy, mapped by a named rule');
    await d.hold(3000);
    await d.clearSpotlight();
  });
}
