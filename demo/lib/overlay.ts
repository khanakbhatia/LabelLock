/**
 * Presentation layer for the demo recording. Everything here is drawn ON TOP of the real app
 * (pointer-events: none, fixed position). It never changes what the app shows or does: clicks and
 * typing go to the real UI through Playwright, and captions are composited later at render time.
 */
import type { Locator, Page } from 'playwright';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export const CAPTIONS_PATH = fileURLToPath(new URL('../captions.json', import.meta.url));

export interface Caption {
  clip: string; id: string; step?: string; text: string; position?: 'top' | 'bottom'; pin?: 'top' | 'bottom';
  action?: string; voice?: string; start?: number; end?: number; hold?: number;
}

export const loadCaptions = (): Caption[] => JSON.parse(readFileSync(CAPTIONS_PATH, 'utf-8'));

/** Reading time: about 1 s per 12 characters, at least 2.5 s. */
export const readSeconds = (text: string) => Math.max(2.5, text.length / 12);

type Box = { x: number; y: number; width: number; height: number };

export class Director {
  t0 = 0;
  timings: { id: string; start: number; end: number; position: 'top' | 'bottom' }[] = [];
  /** Spotlit regions (viewport px) with clip time, so captions can be placed where they cover nothing explained. */
  private spots: { t: number; top: number; bottom: number }[] = [];
  private captions: Map<string, Caption>;

  constructor(public page: Page, public clip: string) {
    this.captions = new Map(loadCaptions().filter(c => c.clip === clip).map(c => [c.id, c]));
  }

  /** The in-page layer is plain JS (lib/overlay-page.js) so the TS toolchain cannot rewrite it. */
  static async attach(page: Page) { await page.addInitScript({ path: fileURLToPath(new URL('./overlay-page.js', import.meta.url)) }); }

  /** Clip time zero = the moment the video starts showing the first real frame we care about. */
  start() { this.t0 = Date.now(); }
  now() { return (Date.now() - this.t0) / 1000; }
  hold = (ms: number) => this.page.waitForTimeout(ms);

  private ll<T>(fn: string, ...args: unknown[]): Promise<T> {
    return this.page.evaluate(([f, a]) => {
      const api = (window as unknown as { __ll?: Record<string, (...x: unknown[]) => unknown> }).__ll;
      return api?.[f as string]?.(...(a as unknown[])) as T;
    }, [fn, args] as const);
  }

  async step(text: string) { await this.ll('chip', text); }

  /**
   * Shows caption `id` (drawn later at render time) while `during` runs, and keeps it up for at least
   * its reading time. Records the real start/end so the render and SRT match the picture.
   */
  async caption(id: string, during?: () => Promise<unknown>) {
    const c = this.captions.get(id);
    if (!c) throw new Error(`caption ${this.clip}/${id} missing from captions.json`);
    if (c.step) await this.step(c.step);
    const start = this.now();
    if (during) await during();
    const min = (c.hold ?? readSeconds(c.text)) * 1000, spent = (this.now() - start) * 1000;
    if (spent < min) await this.hold(min - spent);
    const end = this.now();
    this.timings.push({ id, start: +start.toFixed(2), end: +end.toFixed(2), position: c.pin ?? this.placeCaption(start, end) });
  }

  /**
   * Caption bands in the 1600x900 viewport (the 1080p caption is scaled the same way): top 118-240, bottom 728-848.
   * Choose the band that overlaps the spotlit regions least; bottom wins a tie.
   */
  private placeCaption(start: number, end: number): 'top' | 'bottom' {
    const spots = this.spots.filter(s => s.t >= start - 0.2 && s.t <= end);
    const overlap = (a: number, b: number) => spots.reduce((sum, s) => sum + Math.max(0, Math.min(b, s.bottom) - Math.max(a, s.top)), 0);
    return overlap(728, 848) > overlap(118, 240) ? 'top' : 'bottom';
  }

  private async box(target: Locator): Promise<Box> {
    await target.scrollIntoViewIfNeeded();
    const b = await target.boundingBox();
    if (!b) throw new Error('element not visible');
    return b;
  }

  async moveTo(target: Locator) {
    const b = await this.box(target);
    await this.ll('moveTo', b.x + Math.min(b.width / 2, 60), b.y + b.height / 2, 450);
    return b;
  }

  /** Visible cursor glides to the element, ripples, then the real click; then a 1.2 s pause. */
  async click(target: Locator, pause = 1200) {
    const b = await this.moveTo(target);
    await this.ll('ripple', b.x + Math.min(b.width / 2, 60), b.y + b.height / 2);
    await target.click();
    await this.hold(pause);
  }

  /**
   * Types into a real field at ~35 ms per character: real text input in 4-character chunks every 140 ms
   * (one keystroke per round trip is several times slower than 35 ms under recording).
   */
  async type(target: Locator, text: string) {
    await this.click(target, 250);
    for (let i = 0; i < text.length; i += 4) {
      await this.page.keyboard.insertText(text.slice(i, i + 4));
      await this.hold(140);
    }
    await this.hold(400);
  }

  async spotlight(target: Locator, label = '') {
    const b = await this.box(target);
    // ring padding plus the label, which sits beside or just below the element
    this.spots.push({ t: this.now(), top: b.y - 12, bottom: b.y + b.height + 70 });
    await this.ll('spotlight', b, label);
    await this.hold(350);
  }
  async clearSpotlight() { await this.ll('spotlight', null); }

  /** Smooth scroll so the element sits in the middle of the screen. */
  async scrollTo(target: Locator) {
    await target.evaluate(el => el.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    await this.hold(800);
  }

  /** Optional 1.15-1.3x zoom on a region for small text; undo() restores it exactly. */
  async zoom(target: Locator, scale = 1.2) {
    await target.evaluate((el, s) => {
      const e = el as HTMLElement; e.dataset.llZoom = e.style.transform || '';
      e.style.transition = 'transform .35s'; e.style.transformOrigin = 'top left'; e.style.transform = `scale(${s})`;
    }, scale);
    await this.hold(450);
    return { undo: async () => { await target.evaluate(el => { const e = el as HTMLElement; e.style.transform = e.dataset.llZoom || ''; }); await this.hold(400); } };
  }

  /** Real sign-in through the login page. */
  async login(username: string) {
    const p = this.page;
    if (!p.url().includes('/login')) await p.goto('http://localhost:5173/login');
    await p.getByLabel('Username').waitFor();
    await this.type(p.getByLabel('Username'), username);
    await this.type(p.getByLabel('Password'), 'demo');
    await this.click(p.getByRole('button', { name: 'Sign in' }), 300);
    // the next click must not land while the app is still routing and rendering after sign-in
    await p.waitForURL(u => !u.pathname.includes('/login'));
    await p.getByRole('button', { name: 'Log out' }).waitFor();
    await p.waitForLoadState('networkidle');
    await this.hold(900);
  }

  async logout() {
    await this.click(this.page.getByRole('button', { name: 'Log out' }), 800);
  }
}
