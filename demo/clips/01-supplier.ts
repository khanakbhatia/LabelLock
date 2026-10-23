import type { Director } from '../lib/overlay.ts';
import { NOTICE } from '../lib/api.ts';
import { APP } from '../lib/flows.ts';

export default async function (d: Director) {
  const p = d.page;
  await p.goto(`${APP}/login`);
  d.start();
  await d.caption('01a', async () => {
    await d.login('valley.ingredients');
    await p.getByLabel('Subject').waitFor();
    await d.type(p.getByLabel('Subject'), NOTICE.subject);
    await d.type(p.getByLabel('Message body'), NOTICE.body);
  });
  await d.caption('01b', async () => {
    const file = p.locator('input[type=file]');
    await d.moveTo(file);
    await file.setInputFiles(NOTICE.pdfPath);
    await d.hold(1200);
    await d.click(p.getByRole('button', { name: 'Submit notice' }));
    const done = p.getByRole('status').filter({ hasText: /Received|n_/ }).first();
    await done.waitFor({ timeout: 15000 });
    await d.spotlight(done, 'Received by Northfield QA');
    await d.hold(3000);
    await d.clearSpotlight();
  });
}
