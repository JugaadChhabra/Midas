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
    const bad = c.quarantined_count || 0;

    // Stopped: it will not start again by itself. This is its own group and
    // leads, because it is the only state where nothing at all is happening
    // and only a person can change that.
    if (c.autopilot_paused_reason) {
      return { key: 'paused', group: 'stopped', lamp: 'lamp--fault',
               why: `<b>Stopped</b> — ${escapeHtml(reasonInWords(c.autopilot_paused_reason))}`,
               action: 'Resume' };
    }
    if (!c.video_count) {
      return { key: 'setup', group: 'attention', lamp: 'lamp--warn',
               why: '<b>Never set up</b> — no videos fetched from YouTube yet',
               action: 'Sync' };
    }
    // Stale outranks off: turning autopilot on against a 12-day-old copy of the
    // channel doesn't make it running, it makes it wrong.
    if (hours == null || hours > STALE_HOURS) {
      return { key: 'stale', group: 'attention', lamp: 'lamp--warn',
               why: `<b>Channel data ${days} days old</b> — autopilot won't run`,
               action: 'Sync' };
    }
    // Bad output is the state the board could not see before: it ran, it did
    // work, and the work is unusable. Ranked below stale because the channel is
    // still moving — but above "running", because it is quietly wasting quota.
    if (bad) {
      return { key: 'bad', group: 'attention', lamp: 'lamp--warn',
               why: `<b>${fmt(bad)} rewrite${bad === 1 ? '' : 's'} came back unusable</b>`
                  + ` — ${lastRun(c).toLowerCase()}`,
               action: 'Try again' };
    }
    if (!c.autopilot_enabled) {
      return { key: 'off', group: 'off', lamp: '',
               why: 'Autopilot off · data is current', action: 'Start' };
    }
    return { key: 'run', group: 'run', lamp: 'lamp--run',
             why: `${lastRun(c)} · ${fmt(c.applied_today || 0)} of ${fmt(c.autopilot_daily_cap || 0)} rewritten today`,
             action: '' };
  }

  const lastRun = (c) => c.autopilot_last_tick_at
    ? `Ran ${c.autopilot_last_tick_at.slice(11, 16)}` : 'Has not run';

  // Pause reasons are persisted enum-ish strings written for the log. On the
  // board they are the whole explanation, so they get read out in words.
  const REASONS = {
    token_expired:    'Google sign-in expired',
    quota_exhausted:  'ran out of YouTube quota',
    daily_cap:        'hit the daily limit',
    daily_cap_hit:    'hit the daily limit',
    consecutive_failures: 'too many failures in a row',
  };
  const reasonInWords = (r) => REASONS[r] || String(r || '').replace(/_/g, ' ');

  const GROUPS = [
    ['stopped',   'Stopped'],
    ['attention', 'Needs attention'],
    ['run',       'Running'],
    ['off',       'Off'],
  ];

  const fmt = (n) => Number(n || 0).toLocaleString();
  const escapeHtml = (s) => (s ?? '').toString().replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* ── Rows ────────────────────────────────────────────────────────── */
  // Seven real days from the API, or nothing. The earlier version padded
  // today's count with six zeros, which drew six days of "nothing happened"
  // that had never been measured — the same fabrication as any other number we
  // don't have. An absent strip is honest; an invented flatline is not.
  function beatFor(c) {
    const days = c.applied_by_day;
    return Array.isArray(days) && days.length ? days.join(',') : '';
  }

  function rowHTML(c, beatMax, prefixLen) {
    const st = stateOf(c);
    const beat = beatFor(c);
    const figure = c.pending_count
      ? `${fmt(c.pending_count)} waiting`
      : (c.video_count ? `${fmt(c.video_count)} videos` : '—');
    return `<a class="frow" href="/channel?id=${encodeURIComponent(c.id)}">
      <span class="lamp ${st.lamp}"></span>
      <span class="nm" title="${escapeHtml(c.name || c.id)}">${escapeHtml(
        Sidebar.shortLabel(c.name || c.id, prefixLen))}</span>
      <span class="why">${st.why}</span>
      ${beat ? `<span class="beat" data-spark data-values="${beat}" data-max="${beatMax}"
            data-label="rewrites put live, last ${beat.split(',').length} days"></span>`
              : '<span></span>'}
      <span class="fig">${figure}</span>
      <span class="act">${!st.action ? ''
        : st.action === 'Try again'
        ? `<button type="button" class="btn btn-sm hold" data-hold data-ms="900"
                   data-label="Hold to retry" data-done-label="Started"
                   data-run-action="${st.action}" data-channel="${escapeHtml(c.id)}"
             ><span class="fill"></span><span class="txt">Hold to retry</span></button>`
        : `<span class="btn btn-sm" data-run-action="${st.action}" data-channel="${escapeHtml(c.id)}">${st.action}</span>`
      }</span>
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

    // A channel producing bad output IS running — it just isn't producing
    // anything usable. Counting it as "not running" would overstate the
    // headline and understate the real problem, which the meta line names.
    const working = (buckets.run || []).length
                  + (buckets.attention || []).filter(c => stateOf(c).key === 'bad').length;
    const notRunning = channels.length - working;
    const badTotal = channels.reduce((n, c) => n + (c.quarantined_count || 0), 0);
    const beatMax = Math.max(1, ...channels.flatMap(
      c => Array.isArray(c.applied_by_day) ? c.applied_by_day : [c.applied_today || 0]));
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
      badTotal ? `${fmt(badTotal)} came back unusable` : null,
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
    // A countdown alone doesn't say whether the reset lands before or after you
    // stop looking at this; the clock time does.
    const at = new Date(Date.now() + (q.reset_in_seconds || 0) * 1000)
      .toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const spark = (q.sparkline || []).map(d => d.units);
    const dead = spark.filter(u => !u).length;

    el.innerHTML = `
      <div>
        <div class="quota-fig">${fmt(q.remaining)}</div>
        <div class="quota-l">YouTube quota left today</div>
      </div>
      <div class="meter ok" data-meter data-pct="${pct.toFixed(1)}"></div>
      <div style="text-align:right">
        <div class="quota-l">resets in ${resetH}h ${resetM}m · ${at}</div>
        <div class="quota-l">${fmt(q.used_today)} used today${
          dead ? ` · none used on ${dead} of the last ${spark.length} days` : ''}</div>
      </div>
      ${spark.length ? `<span class="beat beat--neutral" data-spark data-values="${spark.join(',')}"
            data-label="quota spent per day"></span>` : ''}`;
  }

  global.Running = { stateOf, render, STALE_HOURS };
})(window);
