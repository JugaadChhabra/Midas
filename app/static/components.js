/* Midas — shared component behaviours.
 *
 * Every component reads its config from data-* on the element, so markup can be
 * rendered server-side or by a page's own template and the behaviour attaches
 * afterwards. Call Components.init() once on load, and again on any subtree you
 * re-render — init is idempotent (it marks what it has wired).
 *
 * Styling for all of these lives in /static/theme.css.
 */
(function (global) {
  'use strict';

  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  // ── Hold to confirm ──────────────────────────────────────────────────
  // For anything that changes something on YouTube. A click is one event and
  // can be a slip; a sustained press can't be. The button IS the progress bar —
  // .fill sits behind the label and sweeps across as you hold.
  //
  //   <button class="btn hold" data-hold data-ms="900"
  //           data-label="Hold to apply 6" data-done-label="6 applied">
  //     <span class="fill"></span><span class="txt">Hold to apply 6</span>
  //   </button>
  //
  // Fires a bubbling `confirm` event on completion. The page does the work in
  // that handler — this component never performs the action itself.
  function hold(btn) {
    const ms = Number(btn.dataset.ms || 800);
    const fill = btn.querySelector('.fill');
    const txt = btn.querySelector('.txt');
    let raf = null, start = 0;

    const stop = () => {
      cancelAnimationFrame(raf); raf = null;
      btn.dataset.holding = 'false';
      if (fill) fill.style.width = '0';
    };
    const finish = () => {
      stop();
      btn.dataset.done = 'true';
      if (txt && btn.dataset.doneLabel) txt.textContent = btn.dataset.doneLabel;
      btn.dispatchEvent(new CustomEvent('confirm', { bubbles: true }));
      setTimeout(() => {
        btn.dataset.done = 'false';
        if (txt && btn.dataset.label) txt.textContent = btn.dataset.label;
      }, 1900);
    };
    const tick = (now) => {
      const p = Math.min(1, (now - start) / ms);
      if (fill) fill.style.width = (p * 100) + '%';
      if (p >= 1) finish(); else raf = requestAnimationFrame(tick);
    };
    const begin = (e) => {
      if (btn.disabled || btn.dataset.done === 'true' || raf) return;
      if (e.type === 'keydown' && e.key !== ' ' && e.key !== 'Enter') return;
      if (e.type === 'keydown') e.preventDefault();
      e.stopPropagation();
      btn.dataset.holding = 'true';
      start = performance.now();
      raf = requestAnimationFrame(tick);
    };

    btn.addEventListener('pointerdown', begin);
    btn.addEventListener('keydown', begin);
    ['pointerup', 'pointerleave', 'pointercancel', 'keyup', 'blur']
      .forEach(ev => btn.addEventListener(ev, stop));
    // Swallow the click entirely: a slip must not reach the page or any
    // ancestor row handler.
    btn.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); });
    btn.setAttribute('aria-description',
      `Press and hold for ${(ms / 1000).toFixed(1)} seconds to confirm`);
  }

  // ── Heartbeat / sparkline ────────────────────────────────────────────
  // data-values is a comma list; data-max is shared across a set of strips so
  // rows stay comparable. Without a shared max, one apply on a quiet channel
  // renders as tall as ten on a busy one.
  function spark(el) {
    const vals = (el.dataset.values || '').split(',').filter(s => s !== '').map(Number);
    const max = Number(el.dataset.max) || Math.max(1, ...vals);
    el.innerHTML = vals.map((v, i) => {
      const h = v ? Math.max(4, Math.round(v / max * 17)) : 0;
      const cls = [v ? '' : 'zero', i === vals.length - 1 ? 'now' : ''].filter(Boolean).join(' ');
      return `<i class="${cls}"${v ? ` style="height:${h}px"` : ''}></i>`;
    }).join('');
    el.setAttribute('role', 'img');
    el.setAttribute('aria-label', el.dataset.label || `${vals.length} days: ${vals.join(', ')}`);
  }

  // ── Meter ────────────────────────────────────────────────────────────
  // Animates from zero on the next frame so the fill visibly travels rather
  // than snapping to its final width.
  function meter(el) {
    const pct = Math.max(0, Math.min(100, Number(el.dataset.pct || 0)));
    el.innerHTML = '<i></i>';
    const bar = el.firstElementChild;
    el.setAttribute('role', 'progressbar');
    el.setAttribute('aria-valuenow', String(Math.round(pct)));
    el.setAttribute('aria-valuemin', '0');
    el.setAttribute('aria-valuemax', '100');
    requestAnimationFrame(() => { bar.style.width = pct + '%'; });
  }

  // ── Skeleton ─────────────────────────────────────────────────────────
  // Mirrors the real row grid so nothing jumps when the data lands.
  function skeleton(el) {
    const rows = Number(el.dataset.rows || 4);
    el.setAttribute('aria-hidden', 'true');
    el.innerHTML = Array.from({ length: rows }, (_, i) => `
      <div class="skel-row">
        <div class="skel-box thumb"></div>
        <div class="skel-box" style="width:${[72, 54, 63, 48, 68][i % 5]}%"></div>
        <div class="skel-box"></div>
        <div class="skel-box"></div>
      </div>`).join('');
  }

  // ── Copy ─────────────────────────────────────────────────────────────
  function copy(btn) {
    const txt = btn.querySelector('.txt');
    const original = txt ? txt.textContent : null;
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const value = btn.dataset.copy;
      try {
        await navigator.clipboard.writeText(value);
      } catch {
        // clipboard API needs a secure context — fall back to a temp selection
        const ta = document.createElement('textarea');
        ta.value = value; ta.setAttribute('readonly', '');
        ta.style.cssText = 'position:fixed;opacity:0';
        document.body.appendChild(ta); ta.select();
        document.execCommand('copy'); ta.remove();
      }
      btn.dataset.copied = 'true';
      if (txt) txt.textContent = 'Copied';
      clearTimeout(btn._copyT);
      btn._copyT = setTimeout(() => {
        btn.dataset.copied = 'false';
        if (txt) txt.textContent = original;
      }, 2000);
    });
  }

  // ── Init ─────────────────────────────────────────────────────────────
  const WIRED = 'cmpWired';
  const KINDS = [
    ['[data-hold]', hold],
    ['[data-spark]', spark],
    ['[data-meter]', meter],
    ['[data-skeleton]', skeleton],
    ['[data-copy]', copy],
  ];

  function init(root) {
    KINDS.forEach(([sel, fn]) => {
      $$(sel, root).forEach(el => {
        if (el.dataset[WIRED]) return;
        el.dataset[WIRED] = '1';
        fn(el);
      });
    });
  }

  global.Components = { init, hold, spark, meter, skeleton, copy };
})(window);
