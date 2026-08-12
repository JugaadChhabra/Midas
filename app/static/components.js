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

  const WIRED = 'cmpWired';   // init() marks what it has already attached to
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const fmt = (n) => Number(n || 0).toLocaleString();
  const esc = (v) => (v == null ? '' : String(v)).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

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

  // ── Dropdown ─────────────────────────────────────────────────────────
  // A real listbox, not a native <select>. Native selects can't be styled to
  // match the rest of the console, can't carry a per-option hint (a count, a
  // "not available yet"), and render as an OS widget that ignores the theme.
  //
  //   <div data-dropdown data-label="Privacy"
  //        data-options='[{"value":"","label":"Any privacy"},…]'></div>
  //
  // Fires a bubbling `change` with detail.value. Keyboard: arrows, Home/End,
  // Escape, Tab-to-close, and type-ahead — the things a native select gives
  // you free and a div never does.
  function dropdown(el) {
    let opts;
    try { opts = JSON.parse(el.dataset.options || '[]'); }
    catch { opts = []; }
    if (!opts.length) return;

    const label = el.dataset.label || 'Select';
    let value = el.dataset.value != null ? el.dataset.value : opts[0].value;
    const id = 'dd' + Math.random().toString(36).slice(2, 8);

    el.classList.add('dd');
    el.innerHTML = `
      <button class="dd-trigger" type="button" aria-haspopup="listbox"
              aria-expanded="false" aria-labelledby="${id}l">
        <span class="dd-lab" id="${id}l">${esc(label)}</span>
        <span class="val"></span>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
      </button>
      <div class="dd-menu" role="listbox" aria-labelledby="${id}l" hidden>
        ${opts.map(o => `
          <button class="dd-opt" type="button" role="option" data-value="${esc(o.value)}"
                  aria-selected="false"${o.disabled ? ' disabled' : ''}>
            <span>${esc(o.label)}</span>
            ${o.hint ? `<span class="hint">${esc(o.hint)}</span>` : ''}
            <svg class="check" width="13" height="13" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2.4" stroke-linecap="round"
                 stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>
          </button>`).join('')}
      </div>`;

    const trigger = el.querySelector('.dd-trigger');
    const menu = el.querySelector('.dd-menu');
    const items = () => $$('.dd-opt:not(:disabled)', menu);

    function paint() {
      const o = opts.find(x => String(x.value) === String(value)) || opts[0];
      el.querySelector('.val').textContent = o.label;
      $$('.dd-opt', menu).forEach(b =>
        b.setAttribute('aria-selected', String(b.dataset.value === String(value))));
    }
    function open() {
      menu.hidden = false;
      el.dataset.open = 'true';
      trigger.setAttribute('aria-expanded', 'true');
      const list = items();
      (list.find(b => b.dataset.value === String(value)) || list[0])?.focus();
    }
    function close(refocus) {
      menu.hidden = true;
      el.dataset.open = 'false';
      trigger.setAttribute('aria-expanded', 'false');
      if (refocus) trigger.focus();
    }
    function pick(v) {
      value = v; el.dataset.value = v; paint(); close(true);
      el.dispatchEvent(new CustomEvent('change', { detail: { value: v }, bubbles: true }));
    }

    trigger.addEventListener('click', () => menu.hidden ? open() : close(false));
    trigger.addEventListener('keydown', (e) => {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) { e.preventDefault(); open(); }
    });
    menu.addEventListener('click', (e) => {
      const b = e.target.closest('.dd-opt');
      if (b && !b.disabled) pick(b.dataset.value);
    });
    menu.addEventListener('keydown', (e) => {
      const list = items(), i = list.indexOf(document.activeElement);
      const go = (n) => { e.preventDefault(); list[(n + list.length) % list.length]?.focus(); };
      if (e.key === 'ArrowDown') go(i + 1);
      else if (e.key === 'ArrowUp') go(i - 1);
      else if (e.key === 'Home') go(0);
      else if (e.key === 'End') go(list.length - 1);
      else if (e.key === 'Escape') { e.preventDefault(); close(true); }
      else if (e.key === 'Tab') close(false);
      else if (e.key.length === 1) {
        const from = i + 1, k = e.key.toLowerCase();
        [...list.slice(from), ...list.slice(0, from)]
          .find(b => b.textContent.trim().toLowerCase().startsWith(k))?.focus();
      }
    });
    document.addEventListener('click', (e) => { if (!el.contains(e.target)) close(false); });
    paint();

    // A page whose options arrive over the network (the drive folders) needs to
    // refill an already-wired dropdown. Exposed on the element rather than
    // returned, so it survives the fire-and-forget init() call.
    el.dd = {
      get value() { return value; },
      set(v, silent) {
        value = v; el.dataset.value = v; paint();
        if (!silent) el.dispatchEvent(new CustomEvent('change', { detail: { value: v }, bubbles: true }));
      },
      setOptions(next, keep) {
        el.dataset.options = JSON.stringify(next);
        delete el.dataset[WIRED];
        el.dataset.value = keep && next.some(o => String(o.value) === String(value))
          ? value : (next[0] ? next[0].value : '');
        dropdown(el);
        el.dataset[WIRED] = '1';
      },
    };
  }

  // ── Show more (clamp) ────────────────────────────────────────────────
  // Collapses a paragraph to N lines with a fade, and adds a toggle — but only
  // when there is genuinely something hidden. A "Show more" that reveals
  // nothing teaches you to stop trusting the control.
  function clamp(el) {
    const body = el.querySelector('.clamp-body');
    if (!body) return;
    const lines = Number(el.dataset.lines || 3);
    const probe = body.firstElementChild || body;
    const lh = parseFloat(getComputedStyle(probe).lineHeight) || 20;
    const collapsed = Math.round(lh * lines);
    if (body.scrollHeight <= collapsed + 4) { el.dataset.expanded = 'n/a'; return; }

    el.dataset.expanded = 'false';
    body.style.maxHeight = collapsed + 'px';
    const btn = document.createElement('button');
    btn.className = 'clamp-toggle';
    btn.type = 'button';
    btn.setAttribute('aria-expanded', 'false');
    btn.textContent = 'Show more';
    el.appendChild(btn);
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = el.dataset.expanded === 'true';
      el.dataset.expanded = String(!open);
      btn.setAttribute('aria-expanded', String(!open));
      btn.textContent = open ? 'Show more' : 'Show less';
      body.style.maxHeight = open ? collapsed + 'px' : body.scrollHeight + 'px';
    });
  }

  // ── Load more ────────────────────────────────────────────────────────
  // Paging over a list the page already holds. The component owns the button,
  // the running count and the "that's all" end state; the page owns rendering
  // and is called back with the new page size.
  //
  //   <div data-loadmore data-page="40" data-total="5175"></div>
  //   el.addEventListener('more', e => renderUpTo(e.detail.shown))
  //
  // The count is the point: "40 of 5,175" tells you the list is a window, which
  // a bare button at the bottom of a table does not.
  function loadmore(el) {
    const page = Number(el.dataset.page || 40);
    const total = Number(el.dataset.total || 0);
    let shown = Math.min(Number(el.dataset.shown || page), total);

    el.classList.add('lm');
    el.innerHTML = '<button class="btn btn-sm" type="button"></button><span class="lm-count"></span>';
    const btn = el.querySelector('button');
    const count = el.querySelector('.lm-count');

    function paint() {
      btn.disabled = shown >= total;
      btn.textContent = shown >= total ? "That's all" : 'Show more';
      count.textContent = `${fmt(shown)} of ${fmt(total)}`;
    }
    btn.addEventListener('click', () => {
      if (shown >= total) return;
      shown = Math.min(shown + page, total);
      el.dataset.shown = String(shown);
      paint();
      el.dispatchEvent(new CustomEvent('more', { detail: { shown }, bubbles: true }));
    });
    paint();
  }

  // ── Progress (labelled meter) ────────────────────────────────────────
  // A meter with its own label and value, so the three parts can't drift out
  // of step — every page that hand-rolled this pairing had to repeat the
  // percentage arithmetic, and one of them rounded differently.
  //
  //   <div data-progress data-label="Videos rewritten" data-done="121" data-total="765"></div>
  function progress(el) {
    const done = Number(el.dataset.done || 0);
    const total = Number(el.dataset.total || 0);
    const pct = el.dataset.pct != null ? Number(el.dataset.pct)
              : (total ? Math.round(done / total * 100) : 0);
    const label = el.dataset.label || '';
    const valueText = el.dataset.valueText
      || (el.dataset.total != null ? `${fmt(done)} / ${fmt(total)} · ${pct}%` : pct + '%');

    el.classList.add('progress');
    el.innerHTML = `
      <div class="progress-top">
        <span class="progress-label">${esc(label)}</span>
        <span class="progress-value">${esc(valueText)}</span>
      </div>
      <div class="meter" role="progressbar" aria-label="${esc(label)}"
           aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><i></i></div>`;
    const bar = el.querySelector('.meter > i');
    requestAnimationFrame(() => { bar.style.width = pct + '%'; });
  }

  // ── Loading ──────────────────────────────────────────────────────────
  // For work that takes long enough that a disabled button looks broken. The
  // elapsed clock is the part that matters: it distinguishes "slow" from
  // "hung", which a spinner never can.
  //
  //   Components.busy(btn, 'Fetching from YouTube');  →  Components.done(btn)
  const CHEVRON = Array.from({ length: 9 }, (_, i) =>
    ((i % 3) + Math.abs(Math.floor(i / 3) - 1)) * 90);

  function loaderHTML(label) {
    return `<span class="loader"><span class="loader-grid" aria-hidden="true">${
      CHEVRON.map(d => `<i style="animation:cell-on 650ms ease-in-out ${d}ms infinite"></i>`).join('')
    }</span><span class="loader-label">${esc(label)}</span>`
    + '<span class="loader-time" aria-hidden="true">0.0s</span></span>';
  }

  function busy(btn, label) {
    // Already working: relabel in place and let the clock keep running. A
    // multi-stage action ("fetching", then "updating counts") is one wait to
    // the person watching it, so restarting the timer would understate it.
    if (btn._busy) {
      const lab = btn.querySelector('.loader-label');
      if (lab) lab.textContent = label || lab.textContent;
      return;
    }
    btn._busy = { html: btn.innerHTML, disabled: btn.disabled };
    btn.disabled = true;
    btn.innerHTML = loaderHTML(label || 'Working');
    btn.setAttribute('aria-busy', 'true');
    const out = btn.querySelector('.loader-time');
    const t0 = performance.now();
    btn._busyTimer = setInterval(() => {
      const s = (performance.now() - t0) / 1000;
      out.textContent = s < 60 ? s.toFixed(1) + 's'
        : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
    }, 100);
  }

  function done(btn) {
    if (!btn._busy) return;
    clearInterval(btn._busyTimer);
    btn.innerHTML = btn._busy.html;
    btn.disabled = btn._busy.disabled;
    btn.removeAttribute('aria-busy');
    btn._busy = null;
  }

  // ── Segmented bar ────────────────────────────────────────────────────
  // A distribution you can act on: each band is sized by its share and doubles
  // as the filter for it. Counts alone don't show proportion; a pie doesn't
  // give you anything to click.
  //
  //   <div data-seg data-segments='[{"key":"applied","label":"Live","n":439,"role":"ok"},…]'></div>
  //
  // Fires a bubbling `pick` with detail.key ('' when the selected band is
  // clicked again, which is how you clear the filter).
  function seg(el) {
    let segs;
    try { segs = JSON.parse(el.dataset.segments || '[]'); }
    catch { segs = []; }
    segs = segs.filter(s => s.n > 0);
    if (!segs.length) { el.innerHTML = ''; return; }

    const total = segs.reduce((a, s) => a + s.n, 0);
    let sel = el.dataset.value || '';

    el.innerHTML = `
      <div class="seg" role="group" aria-label="${esc(el.dataset.label || 'Breakdown')}">
        ${segs.map(s => `<button type="button" data-k="${esc(s.key)}" aria-pressed="false"
            class="seg-${esc(s.role || 'neutral')}"
            aria-label="${esc(s.label)}: ${fmt(s.n)} of ${fmt(total)}"
            style="width:${(s.n / total * 100).toFixed(2)}%"></button>`).join('')}
      </div>
      <div class="seg-legend">
        ${segs.map(s => `<button type="button" data-k="${esc(s.key)}" aria-pressed="false">
            <span class="sw dot--${esc(s.role || 'neutral')}"></span>${esc(s.label)}
            <span class="seg-n">${fmt(s.n)}</span>
          </button>`).join('')}
      </div>`;

    function paint() {
      $$('[data-k]', el).forEach(b =>
        b.setAttribute('aria-pressed', String(b.dataset.k === sel)));
      el.dataset.value = sel;
    }
    el.addEventListener('click', (e) => {
      const b = e.target.closest('[data-k]');
      if (!b) return;
      sel = b.dataset.k === sel ? '' : b.dataset.k;   // click again to clear
      paint();
      el.dispatchEvent(new CustomEvent('pick', { detail: { key: sel }, bubbles: true }));
    });
    paint();
  }

  // ── Init ─────────────────────────────────────────────────────────────
  const KINDS = [
    ['[data-hold]', hold],
    ['[data-spark]', spark],
    ['[data-meter]', meter],
    ['[data-progress]', progress],
    ['[data-skeleton]', skeleton],
    ['[data-copy]', copy],
    ['[data-dropdown]', dropdown],
    ['[data-clamp]', clamp],
    ['[data-loadmore]', loadmore],
    ['[data-seg]', seg],
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

  global.Components = { init, hold, spark, meter, progress, skeleton, copy,
                        dropdown, clamp, loadmore, seg, busy, done };
})(window);
