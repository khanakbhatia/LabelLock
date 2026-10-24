import type { Director } from '../lib/overlay.ts';
import { card } from '../lib/flows.ts';

export default async function (d: Director) {
  await card(d.page, d, "LabelLock doesn't just detect risk. It helps stop it, verifies the outcome, and turns responsible AI into measurable business value.", '', 8);
}
