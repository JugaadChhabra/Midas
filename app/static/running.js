/* Midas — the Running board.
 *
 * The page you open to answer one question: is everything still running?
 * Rows are grouped by what needs you and ordered worst-first, not
 * alphabetically, because the whole point is that trouble surfaces without
 * being hunted for.
 */
(function (global) {
  'use strict';

  const STALE_HOURS = 48;   // beyond this, autopilot is working from an old mirror

  /* ── State ───────────────────────────────────────────────────────────
   * ONE definition of what a channel's state is. The channel page reads this
   * too — if "why did this stop?" were computed in two places they would drift,
   * which is exactly how the old UI ended up with a paused-count on the
   * dashboard that never agreed with the reason inside the channel.
   *
   * Order matters. Stale outranks off: turning autopilot on against a 12-day-old
   * copy of the channel doesn't make it running, it makes it wrong.
   */
  function stateOf(c) {
    const hours = c.hours_since_sync;
    const days = hours == null ? null : Math.round(hours / 24);

    if (!c.video_count) {
      return { key: 'setup', group: 'setup', lamp: '',
               why: '<b>Never set up</b> — no videos fetched from YouTube yet',
               action: 'Sync' };
    }
    if (hours == null || hours > STALE_HOURS) {
      return { key: 'stale', group: 'stale', lamp: 'lamp--fault',
               why: `<b>Channel data ${days} days old</b> — autopilot won't run`,
               action: 'Sync' };
    }
    if (c.autopilot_paused_reason) {
      return { key: 'paused', group: 'stale', lamp: 'lamp--warn',
               why: `<b>Stopped</b> — ${escapeHtml(c.autopilot_paused_reason)}`,
               action: 'Resume' };
    }
    if (!c.autopilot_enabled) {
      return { key: 'off', group: 'off', lamp: '',
               why: 'Autopilot off · data is current', action: 'Start' };
    }
    const tick = c.autopilot_last_tick_at
      ? c.autopilot_last_tick_at.slice(11, 16) : '—';
    return { key: 'run', group: 'run', lamp: 'lamp--run',
             why: `Ran ${tick} · ${fmt(c.applied_today || 0)} of ${fmt(c.autopilot_daily_cap || 0)} rewritten today`,
             action: '' };
  }

  const GROUPS = [
    ['stale', 'Not running'],
    ['setup', 'Never set up'],
    ['off',   'Off'],
    ['run',   'Running'],
  ];

  const fmt = (n) => Number(n || 0).toLocaleString();
  const escapeHtml = (s) => (s ?? '').toString().replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* ── Rows ────────────────────────────────────────────────────────── */
  // Daily history isn't exposed per channel yet, so the strip carries what we
  // do have: today's applies. It still answers "did anything happen today?"
  // across 13 rows, and gains six days of shape when the API grows one.
  function beatFor(c) {
    return [0, 0, 0, 0, 0, 0, c.applied_today || 0].join(',');
  }

  function rowHTML(c, beatMax, prefixLen) {
    const st = stateOf(c);
    const figure = c.pending_count
      ? `${fmt(c.pending_count)} waiting`
      : (c.video_count ? `${fmt(c.video_count)} videos` : '—');
    return `<a class="frow" href="/channel?id=${encodeURIComponent(c.id)}">
      <span class="lamp ${st.lamp}"></span>
      <span class="nm" title="${escapeHtml(c.name || c.id)}">${escapeHtml(
        Sidebar.shortLabel(c.name || c.id, prefixLen))}</span>
      <span class="why">${st.why}</span>
      <span class="beat" data-spark data-values="${beatFor(c)}" data-max="${beatMax}"
            data-label="rewrites put live, last 7 days"></span>
      <span class="fig">${figure}</span>
      <span class="act">${st.action
        ? `<span class="btn btn-sm" data-run-action="${st.action}" data-channel="${escapeHtml(c.id)}">${st.action}</span>`
        : ''}</span>
    </a>`;
  }

  /* ── Render ──────────────────────────────────────────────────────── */
  function render(payload, els) {
    const channels = (payload.channels || []).slice();
    const quota = payload.quota || {};
    const kpis = payload.kpis || {};

    const buckets = {};
    channels.forEach(c => {
      const g = stateOf(c).group;
      (buckets[g] = buckets[g] || []).push(c);
    });
    // Worst sync first inside a group, so the longest-broken channel leads.
    Object.values(buckets).forEach(list =>
      list.sort((a, b) => (b.hours_since_sync || 0) - (a.hours_since_sync || 0)));

    const notRunning = channels.length - (buckets.run || []).length;
    const beatMax = Math.max(1, ...channels.map(c => c.applied_today || 0));
    // These channels are one show in many languages, so the distinguishing part
    // is the tail — same treatment the switcher gives them.
    const prefixLen = Sidebar.commonWordPrefix(channels.map(c => c.name));

    els.lede.innerHTML = notRunning
      ? `${fmt(notRunning)} of ${fmt(channels.length)} channels <span class="u">aren't running</span>`
      : `All ${fmt(channels.length)} channels <span class="u">are running</span>`;

    const worst = Math.max(0, ...channels.map(c => c.hours_since_sync || 0));
    els.meta.textContent = [
      `${fmt(kpis.pending_total)} finished rewrites waiting to go live`,
      `${fmt(kpis.audited_today)} rewritten today`,
      worst ? `oldest channel data ${Math.round(worst / 24)} days old` : null,
    ].filter(Boolean).join(' · ');

    els.groups.innerHTML = GROUPS.map(([key, title]) => {
      const list = buckets[key];
      if (!list || !list.length) return '';
      return `<div class="group">
        <div class="group-head">${title}<span class="n">${list.length}</span><span class="rule"></span></div>
        ${list.map(c => rowHTML(c, beatMax, prefixLen)).join('')}
      </div>`;
    }).join('');

    renderQuota(quota, els.quota);
    Components.init(els.groups);
    Components.init(els.quota);
  }

  function renderQuota(q, el) {
    if (q.remaining == null) { el.innerHTML = ''; return; }
    const usable = Math.max(1, (q.limit || 0) - (q.safety_buffer || 0));
    const pct = Math.max(0, Math.min(100, q.remaining / usable * 100));
    const resetH = Math.floor((q.reset_in_seconds || 0) / 3600);
    const resetM = Math.floor(((q.reset_in_seconds || 0) % 3600) / 60);
    const spark = (q.sparkline || []).map(d => d.units);
    const dead = spark.filter(u => !u).length;

    el.innerHTML = `
      <div>
        <div class="quota-fig">${fmt(q.remaining)}</div>
        <div class="quota-l">YouTube quota left today</div>
      </div>
      <div class="meter ok" data-meter data-pct="${pct.toFixed(1)}"></div>
      <div style="text-align:right">
        <div class="quota-l">resets in ${resetH}h ${resetM}m</div>
        <div class="quota-l" style="color:var(--ink-4)">${fmt(q.used_today)} used today${
          dead ? ` · none used on ${dead} of the last ${spark.length} days` : ''}</div>
      </div>
      ${spark.length ? `<span class="beat beat--neutral" data-spark data-values="${spark.join(',')}"
            data-label="quota spent per day"></span>` : ''}`;
  }

  global.Running = { stateOf, render, STALE_HOURS };
})(window);
