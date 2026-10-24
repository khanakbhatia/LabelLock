import type { Director } from '../lib/overlay.ts';
import { getCase, setFault, submitNotice } from '../lib/api.ts';
import { openCase, tab } from '../lib/flows.ts';

// The recorder resets with the fault off before every clip; this one needs it on, as switched in clip 09.
export const setup = async () => { await setFault(true); return { caseId: await submitNotice() }; };

export default async function (d: Director, { caseId }: Record<string, string>) {
  const p = d.page;
  await openCase(d, 'priya.qa', caseId);
  await d.caption('10a', async () => {
    await d.click(p.getByRole('button', { name: 'Run agent' }));
    await p.getByText(/Agent finished/).waitFor({ timeout: 90000 });
    const c = await getCase(caseId);
    if (c.status !== 'ESCALATED' || !c.actions.some((a: { status: string }) => a.status === 'VERIFY_FAILED')) {
      throw new Error(`fault take not clean: ${c.status}`);
    }
  });
  await d.caption('10b', async () => {
    await tab(d, 'Actions');
    await d.spotlight(p.getByRole('row').filter({ hasText: 'Hold FG-1041 at DC-EAST' }), 'WMS said OK · re-check: still AVAILABLE · retried once');
    await d.hold(3000);
    await d.clearSpotlight();
  });
  await d.caption('10c', async () => {
    await p.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
    await d.hold(600);
    await d.spotlight(p.getByText('ESCALATED').first(), 'Escalated · not contained');
    await d.hold(3000);
    await d.clearSpotlight();
  });
}
