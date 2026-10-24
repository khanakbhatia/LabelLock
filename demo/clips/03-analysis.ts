import type { Director } from '../lib/overlay.ts';
import { NOTICE, assertGolden, getCase, submitNotice } from '../lib/api.ts';
import { signedIn } from '../lib/flows.ts';

export const setup = async () => ({ caseId: await submitNotice() });

export default async function (d: Director, { caseId }: Record<string, string>) {
  const p = d.page;
  await signedIn(d, 'priya.qa', '/inbox');
  await d.caption('03a', async () => {
    await d.click(p.getByText(NOTICE.subject).first(), 600);
    await p.getByRole('tablist', { name: 'Case views' }).waitFor();
    await d.click(p.getByRole('button', { name: 'Run agent' }));
    await p.getByText(/Agent finished/).waitFor({ timeout: 90000 });
    assertGolden(await getCase(caseId));
  });
  await d.caption('03b', async () => {
    const table = p.getByRole('tabpanel').locator('table');
    await d.scrollTo(table);
    await d.spotlight(table, 'Value · status · exact quote · source');
    await d.hold(3000);
    await d.clearSpotlight();
  });
}
