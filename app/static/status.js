/* Canonical status vocabularies for pills.
 *
 * One source of truth for what each state looks like (a tint colour role, keyed
 * to the `.pill--*` modifiers in theme.css) and reads as (its label). Linked by
 * every dashboard page like swr.js, replacing the per-page STATE_META copies
 * that had drifted.
 *
 * Colour roles: ok=green, info=blue, warn=amber, err=red, neutral=grey.
 *
 * SHORTS_STATUS mirrors the backend's single owner, app/shorts/status.py. No
 * shorts pill is rendered in the UI yet (the shorts card shows a count), but the
 * mapping lives here so it's canonical the moment one is.
 */
(function (global) {
  const AUDIT_STATUS = {
    applied:     { cls: 'pill--ok',      label: 'Applied' },
    pending:     { cls: 'pill--info',    label: 'Pending' },
    approved:    { cls: 'pill--info',    label: 'Approved' },
    quarantined: { cls: 'pill--warn',    label: 'Bad output' },
    failed:      { cls: 'pill--err',     label: 'Failed' },
    rejected:    { cls: 'pill--neutral', label: 'Rejected' },
    reverted:    { cls: 'pill--neutral', label: 'Reverted' },
    none:        { cls: 'pill--neutral', label: 'Not audited' },
  };

  const SHORTS_STATUS = {
    CREATED:     { cls: 'pill--info',    label: 'Queued' },
    DOWNLOADING: { cls: 'pill--info',    label: 'Downloading' },
    ANALYSING:   { cls: 'pill--info',    label: 'Analysing' },
    RENDERING:   { cls: 'pill--info',    label: 'Rendering' },
    UPLOADING:   { cls: 'pill--info',    label: 'Uploading' },
    DONE:        { cls: 'pill--ok',      label: 'Shorts done' },
    UPLOADED:    { cls: 'pill--ok',      label: 'Uploaded' },
    FAILED:      { cls: 'pill--err',     label: 'Failed' },
    PENDING:     { cls: 'pill--neutral', label: 'Pending' },
  };

  const esc = (s) => (s ?? '').toString().replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // Render a status pill. kind: 'audit' (default) | 'shorts'. size: '' | 'sm'.
  // Unknown statuses fall back to a neutral pill showing the raw value.
  function statusPill(status, kind, size) {
    const map = kind === 'shorts' ? SHORTS_STATUS : AUDIT_STATUS;
    // Falsy audit status (a not-yet-audited video) resolves to 'none' → "Not audited".
    const m = map[status || 'none'] || { cls: 'pill--neutral', label: status };
    const sz = size === 'sm' ? ' pill--sm' : '';
    return `<span class="pill ${m.cls}${sz}">${esc(m.label)}</span>`;
  }

  global.Status = { statusPill, AUDIT_STATUS, SHORTS_STATUS };
  global.statusPill = statusPill;
})(window);
