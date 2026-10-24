/**
 * Real-time screen capture through the DevTools screencast. Playwright's recordVideo drops wall-clock time when the
 * page does not repaint, which put captions out of sync; here every frame keeps its timestamp and is shown until the
 * next one arrives, so the video runs exactly as long as the clip did.
 */
import type { CDPSession, Page } from 'playwright';
import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import ffmpegPath from 'ffmpeg-static';

const FF = ffmpegPath as unknown as string;

export class Capture {
  private frames: { file: string; t: number }[] = [];
  private cdp?: CDPSession;
  private pending: Promise<unknown>[] = [];

  constructor(private dir: string) { mkdirSync(dir, { recursive: true }); }

  async start(page: Page) {
    this.cdp = await page.context().newCDPSession(page);
    this.cdp.on('Page.screencastFrame', ({ data, metadata, sessionId }) => {
      const t = metadata.timestamp ? metadata.timestamp * 1000 : Date.now();
      const file = `${this.dir}/f${String(this.frames.length).padStart(6, '0')}.jpg`;
      writeFileSync(file, Buffer.from(data, 'base64'));
      this.frames.push({ file, t });
      this.pending.push(this.cdp!.send('Page.screencastFrameAck', { sessionId }).catch(() => {}));
    });
    await this.cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: 1600, maxHeight: 900, everyNthFrame: 1 });
  }

  async stop() {
    await this.cdp?.send('Page.stopScreencast').catch(() => {});
    await Promise.all(this.pending);
  }

  /** Builds an MP4 covering [startMs, endMs] of wall-clock time: 1920x1080, 30 fps, H.264, no audio. */
  build(out: string, startMs: number, endMs: number) {
    const frames = [...this.frames].sort((a, b) => a.t - b.t);
    if (!frames.length) throw new Error('no frames captured');
    let i = frames.findLastIndex(f => f.t <= startMs);
    if (i < 0) i = 0;
    const lines = ['ffconcat version 1.0'];
    let last = '';
    for (; i < frames.length && frames[i].t < endMs; i++) {
      const from = Math.max(frames[i].t, startMs), to = Math.min(i + 1 < frames.length ? frames[i + 1].t : endMs, endMs);
      if (to <= from) continue;
      last = frames[i].file;
      lines.push(`file '${last.replace(/\\/g, '/')}'`, `duration ${((to - from) / 1000).toFixed(4)}`);
    }
    lines.push(`file '${last.replace(/\\/g, '/')}'`);  // the concat demuxer needs the last file repeated
    const list = `${this.dir}/frames.ffconcat`;
    writeFileSync(list, lines.join('\n') + '\n');
    execFileSync(FF, ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list,
      '-vf', 'fps=30,scale=1920:1080:flags=lanczos,format=yuv420p', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
      '-an', '-t', ((endMs - startMs) / 1000).toFixed(3), out]);
  }
}
