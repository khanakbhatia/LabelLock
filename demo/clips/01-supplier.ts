import type { Director } from '../lib/overlay.ts';
import { NOTICE } from '../lib/api.ts';
import { signedIn } from '../lib/flows.ts';

export default async function (d: Director) {
  const p = d.page;
  await signedIn(d, 'valley.ingredients', '/supplier');
  await d.caption('01a', async () => {
    await d.type(p.getByLabel('Subject'), NOTICE.subject);
    await p.getByLabel('Message body').fill(NOTICE.body);  // pasted, not typed
    const file = p.locator('input[type=file]');
    await d.moveTo(file);
    await file.setInputFiles(NOTICE.pdfPath);
    await d.click(p.getByRole('button', { name: 'Submit notice' }), 600);
    const done = p.getByRole('status').filter({ hasText: /Received|n_/ }).first();
    await done.waitFor({ timeout: 15000 });
    await d.spotlight(done, 'Received by Northfield QA');
    await d.hold(3000);
    await d.clearSpotlight();
  });
}
