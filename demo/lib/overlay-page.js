// In-page presentation layer for the demo recording (plain JS: injected verbatim with addInitScript).
// Drawn on top of the real app with pointer-events:none; it never changes what the app shows or does.
(() => {
  if (window.__ll) return;
  const css = `
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500&family=IBM+Plex+Sans:wght@500;600&display=swap');
    #ll-layer{position:fixed;inset:0;pointer-events:none;z-index:2147483646}
    #ll-chip{position:absolute;top:84px;left:250px;padding:8px 14px;border-radius:8px;background:rgba(12,16,20,.86);
      color:#62d2b4;font:500 15px 'IBM Plex Mono',ui-monospace,monospace;letter-spacing:.14em;opacity:0;transition:opacity .25s}
    #ll-ring{position:absolute;border:2px solid #f0a443;border-radius:8px;opacity:0;transition:all .3s;
      box-shadow:0 0 0 9999px rgba(8,12,16,.55)}
    #ll-label{position:absolute;padding:6px 12px;border-radius:8px;background:#f0a443;color:#0c1014;
      font:600 17px 'IBM Plex Sans',system-ui,sans-serif;opacity:0;transition:opacity .3s;max-width:440px}
    #ll-cursor{position:absolute;left:0;top:0;width:24px;height:24px;transform:translate(-3px,-2px);opacity:0;
      filter:drop-shadow(0 1px 2px rgba(0,0,0,.35))}
    .ll-ripple{position:absolute;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;border:3px solid #f0a443;
      animation:llr .55s ease-out forwards}
    @keyframes llr{to{transform:scale(3.4);opacity:0}}
    #ll-tick{position:absolute;right:0;bottom:0;width:1px;height:1px;background:#000;animation:llt .5s infinite alternate}
    @keyframes llt{from{opacity:.01}to{opacity:.02}}`;
  const byId = id => document.getElementById(id);
  const remember = patch => {
    const s = JSON.parse(sessionStorage.getItem('ll-state') || '{}');
    sessionStorage.setItem('ll-state', JSON.stringify(Object.assign(s, patch)));
  };
  const api = {
    chip(text) {
      const c = byId('ll-chip'); if (!c) return;
      c.textContent = text; c.style.opacity = text ? '1' : '0'; remember({ chip: text });
    },
    cursorAt(x, y) {
      const c = byId('ll-cursor'); if (!c) return;
      c.style.opacity = '1'; c.style.left = x + 'px'; c.style.top = y + 'px'; remember({ x, y });
    },
    moveTo(x, y, ms) {
      const c = byId('ll-cursor'); if (!c) return Promise.resolve();
      const sx = parseFloat(c.style.left || String(innerWidth / 2)), sy = parseFloat(c.style.top || String(innerHeight / 2));
      const t0 = performance.now();
      return new Promise(done => {
        function tick(now) {
          const k = Math.min(1, (now - t0) / ms), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
          api.cursorAt(sx + (x - sx) * e, sy + (y - sy) * e);
          if (k < 1) requestAnimationFrame(tick); else done();
        }
        requestAnimationFrame(tick);
      });
    },
    ripple(x, y) {
      const r = document.createElement('div'); r.className = 'll-ripple'; r.style.left = x + 'px'; r.style.top = y + 'px';
      const layer = byId('ll-layer'); if (layer) layer.appendChild(r); setTimeout(() => r.remove(), 600);
    },
    spotlight(rect, label) {
      const ring = byId('ll-ring'), lab = byId('ll-label'); if (!ring) return;
      if (!rect) { ring.style.opacity = '0'; lab.style.opacity = '0'; return; }
      const pad = 8;
      Object.assign(ring.style, { left: (rect.x - pad) + 'px', top: (rect.y - pad) + 'px',
        width: (rect.width + 2 * pad) + 'px', height: (rect.height + 2 * pad) + 'px', opacity: '1' });
      lab.textContent = label || ''; lab.style.opacity = label ? '1' : '0';
      const right = rect.x + rect.width + pad + 14, below = rect.y + rect.height + pad + 12;
      if (right + 380 < innerWidth) { lab.style.left = right + 'px'; lab.style.top = Math.max(12, rect.y) + 'px'; }
      else { lab.style.left = Math.max(12, rect.x) + 'px'; lab.style.top = (below + 40 > innerHeight ? Math.max(12, rect.y - 52) : below) + 'px'; }
    },
  };
  window.__ll = api;
  function build() {
    if (byId('ll-layer')) return;
    const style = document.createElement('style'); style.textContent = css; document.head.appendChild(style);
    const layer = document.createElement('div'); layer.id = 'll-layer';
    layer.innerHTML = '<div id="ll-tick"></div><div id="ll-ring"></div><div id="ll-label"></div><div id="ll-chip"></div>'
      + '<svg id="ll-cursor" viewBox="0 0 22 22"><path d="M2 2 L2 18 L6.5 13.8 L9.6 20.5 L12.6 19.2 L9.6 12.6 L16 12.6 Z"'
      + ' fill="#fff" stroke="#0c1014" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    document.body.appendChild(layer);
    const saved = sessionStorage.getItem('ll-state');
    if (saved) { const s = JSON.parse(saved); api.chip(s.chip || ''); if (s.x != null) api.cursorAt(s.x, s.y); }
  }
  if (document.body) build(); else document.addEventListener('DOMContentLoaded', build);
})();
