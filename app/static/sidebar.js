/* Midas — the app rail.
 *
 * Every page renders the same sidebar, so it lives here rather than being
 * copy-pasted into each one. A page supplies its section list and says which is
 * active; the rail owns everything else — brand, collapse state, and the
 * channel switcher.
 *
 * Sections come in two flavours. An item with `href` is a link (used by the
 * dashboard); an item without one is a button that calls `onSelect` (used by
 * the channel page, whose sections are in-page panels rather than navigations).
 * Both render as `.snav`, so a page's own active-state code works either way.
 *
 * Usage:
 *   Sidebar.mount({ items, activeId, onSelect, channelId });
 *   Sidebar.setChannels(allChannels, currentChannelId);   // null = All channels
 */
(function () {
  'use strict';

  const COLLAPSE_KEY = 'midas.sidebar.collapsed';

  const esc = (s) => (s ?? '').toString().replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ── Icons ────────────────────────────────────────────────────────────
  const stroke = (inner, size) =>
    `<svg viewBox="0 0 24 24" width="${size || 18}" height="${size || 18}" fill="none"
          stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
          stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;

  const ICONS = {
    home:        () => stroke('<path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>'),
    videos:      () => stroke('<rect x="3" y="3" width="18" height="18" rx="2"/><path d="m10 8.5 5.5 3.5L10 15.5z"/>'),
    performance: () => stroke('<path d="M3 17.5 9.5 11l4 4L21 7.5"/><path d="M16.5 7.5H21v4.5"/>'),
    autopilot:   () => stroke('<path d="M20.5 12a8.5 8.5 0 1 1-2.5-6"/><path d="M20.5 3.5v6h-6"/>'),
    playlists:   () => stroke('<path d="M3 6h11M3 12h11M3 18h7"/><path d="m16.5 12.5 4.5 2.75-4.5 2.75z"/>'),
    settings:    () => stroke('<circle cx="12" cy="12" r="3"/><path d="M19.1 14.4a1.5 1.5 0 0 0 .3 1.7l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.5 1.5 0 0 0-2.6 1.1v.2a2 2 0 1 1-4 0v-.1a1.5 1.5 0 0 0-2.6-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.5 1.5 0 0 0-1.1-2.6h-.2a2 2 0 1 1 0-4h.1a1.5 1.5 0 0 0 1.1-2.6l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.5 1.5 0 0 0 2.6-1.1V3a2 2 0 1 1 4 0v.1a1.5 1.5 0 0 0 2.6 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.5 1.5 0 0 0 1.1 2.6h.2a2 2 0 1 1 0 4h-.1a1.5 1.5 0 0 0-1.4.9z"/>'),
    panel:       () => stroke('<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/>'),
    caret:       () => stroke('<path d="m7 15 5 5 5-5M7 9l5-5 5 5"/>', 15),
    plus:        () => stroke('<path d="M12 5v14M5 12h14"/>', 14),
    brand: () => `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="3.4" fill="currentColor"/>
        <g stroke="currentColor" stroke-width="1.9" stroke-linecap="round">
          <path d="M12 1.7v3.5M12 18.8v3.5M22.3 12h-3.5M5.2 12H1.7"/>
          <path d="m19.3 4.7-2.5 2.5M7.2 16.8l-2.5 2.5M19.3 19.3l-2.5-2.5M7.2 7.2 4.7 4.7"/>
        </g></svg>`,
  };
  const icon = (name) => (ICONS[name] || ICONS.home)();

  // ── Channel labels ───────────────────────────────────────────────────
  // A Midas account's channels are typically one show in many languages, so
  // their names share a long prefix and differ only at the end. Ellipsising the
  // tail would render every row identical, so the switcher strips the prefix
  // the whole set shares and labels each channel by what's left. The prefix is
  // derived from the data, so a differently named set just keeps full names.
  function commonWordPrefix(names) {
    if (names.length < 2) return 0;
    const split = names.map(n => String(n || '').trim().split(/\s+/));
    const first = split[0];
    let i = 0;
    while (i < first.length - 1 && split.every(w => w[i] === first[i])) i++;
    return i;
  }

  function shortLabel(name, prefixLen) {
    const words = String(name || '').trim().split(/\s+/).filter(Boolean);
    const rest = words.slice(prefixLen);
    return (rest.length ? rest : words).join(' ');
  }

  function initials(label) {
    const words = String(label || '').split(/\s+/)
      .map(w => w.replace(/[^A-Za-z0-9]/g, '')).filter(Boolean);
    if (!words.length) return '··';
    return words.slice(0, 2).map(w => w[0]).join('').toUpperCase();
  }

  // ── Mount ────────────────────────────────────────────────────────────
  let els = null;
  let cfg = {};

  // Where a switcher row points. Deliberately no section hash: picking a
  // channel opens it at its default section. An earlier version carried
  // location.hash across so you'd stay on the same section, but the hrefs are
  // built once at render time, so they froze the hash you happened to arrive
  // with and then dragged it into every channel you opened afterwards.
  // A whole-page override (channelHref) is still honoured — that's how
  // performance.html keeps you on Performance when you switch channel.
  const defaultChannelHref = (id) => `/channel?id=${encodeURIComponent(id)}`;

  function mount(opts) {
    cfg = opts || {};
    const shell = document.getElementById('app-shell');
    if (!shell) throw new Error('Sidebar.mount: no #app-shell on the page');

    const items = (opts.items || []).map(it => {
      const active = it.id === opts.activeId;
      const attrs = `class="snav${active ? ' active' : ''}" data-tab="${esc(it.id)}"
                     role="tab" tabindex="${active ? 0 : -1}" aria-selected="${active}"`;
      const inner = `${icon(it.icon || it.id)}<span class="snav-label">${esc(it.label)}</span>`;
      return it.href
        ? `<a href="${esc(it.href)}" ${attrs}>${inner}</a>`
        : `<button type="button" ${attrs}>${inner}</button>`;
    }).join('');

    const aside = document.createElement('aside');
    aside.className = 'sidebar';
    aside.innerHTML = `
      <div class="sidebar-head">
        <a class="sidebar-brand" href="/" title="Midas — all channels">
          ${icon('brand')}<span>Midas</span>
        </a>
        <button class="sidebar-toggle" id="sidebar-toggle" type="button"
                title="Collapse sidebar (B)" aria-label="Collapse sidebar">${icon('panel')}</button>
      </div>
      <nav class="sidebar-nav" role="tablist" aria-label="Sections">${items}</nav>
      <div class="sidebar-foot">
        <button class="chan-switch" id="chan-switch" type="button"
                aria-haspopup="listbox" aria-expanded="false">
          <span class="chan-avatar" id="chan-avatar">··</span>
          <span class="chan-meta">
            <span class="chan-name" id="chan-name">Loading…</span>
            <span class="chan-handle" id="chan-handle"></span>
          </span>
          ${icon('caret').replace('<svg', '<svg class="chan-caret"')}
        </button>
        <div class="chan-menu" id="chan-menu" role="listbox" aria-label="Switch channel" hidden></div>
      </div>`;
    shell.insertBefore(aside, shell.firstChild);

    els = {
      shell,
      toggle: aside.querySelector('#sidebar-toggle'),
      menu: aside.querySelector('#chan-menu'),
      trigger: aside.querySelector('#chan-switch'),
      avatar: aside.querySelector('#chan-avatar'),
      name: aside.querySelector('#chan-name'),
      handle: aside.querySelector('#chan-handle'),
    };

    // Sections without an href are in-page panels — let the page handle them.
    if (opts.onSelect) {
      aside.querySelectorAll('button.snav').forEach(b => {
        b.onclick = () => opts.onSelect(b.dataset.tab);
      });
    }

    if (localStorage.getItem(COLLAPSE_KEY) === '1') shell.classList.add('collapsed');
    els.toggle.onclick = toggleCollapse;

    els.trigger.addEventListener('click', e => { e.stopPropagation(); setOpen(els.menu.hidden); });
    document.addEventListener('click', e => { if (!els.menu.contains(e.target)) setOpen(false); });

    // Arrow keys walk the open menu. The rows are real links, so Enter comes
    // free — this only has to move focus.
    els.menu.addEventListener('keydown', e => {
      const items = menuItems();
      const i = items.indexOf(document.activeElement);
      if (e.key === 'ArrowDown')    { e.preventDefault(); focusItem(i + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); focusItem(i - 1); }
      else if (e.key === 'Home')    { e.preventDefault(); focusItem(0); }
      else if (e.key === 'End')     { e.preventDefault(); focusItem(items.length - 1); }
    });

    document.addEventListener('keydown', onKeydown);
  }

  function toggleCollapse() {
    const collapsed = els.shell.classList.toggle('collapsed');
    localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0');
    const label = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
    els.toggle.setAttribute('aria-label', label);
    els.toggle.title = `${label} (B)`;
  }

  const menuItems = () => Array.from(els.menu.querySelectorAll('.chan-opt'));

  function focusItem(i) {
    const items = menuItems();
    if (items.length) items[(i + items.length) % items.length].focus();
  }

  function setOpen(open, moveFocus) {
    els.menu.hidden = !open;
    els.trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open && moveFocus) {
      // Land on the current channel so arrows move relative to where you are.
      (els.menu.querySelector('.chan-opt.current') || menuItems()[0])?.focus();
    }
  }

  // ── Shortcuts ────────────────────────────────────────────────────────
  // '/' opens the channel switcher with the keyboard already in it; 'b'
  // collapses the rail. Both stay out of the way while you're typing — the
  // channel page is mostly forms, and swallowing '/' in a prompt textarea
  // would be worse than having no shortcut at all.
  function isTyping(el) {
    if (!el) return false;
    if (el.isContentEditable) return true;
    return ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
  }

  function onKeydown(e) {
    if (e.key === 'Escape') {
      if (!els.menu.hidden) { setOpen(false); els.trigger.focus(); }
      return;
    }
    // Leave browser and OS chords alone, and stay quiet while a confirm modal
    // owns the keyboard — collapsing the rail behind a dialog is just confusing.
    if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
    if (document.querySelector('.modal-backdrop')) return;

    if (e.key === '/') {
      e.preventDefault();
      // Toggle, mirroring 'b'. Opening moves the keyboard into the menu;
      // closing hands focus back to the trigger rather than dropping it.
      const opening = els.menu.hidden;
      setOpen(opening, opening);
      if (!opening) els.trigger.focus();
    } else if (e.key === 'b' || e.key === 'B') {
      e.preventDefault();
      toggleCollapse();
    }
  }

  // ── Switcher contents ────────────────────────────────────────────────
  // Callers pass a channel list they already have (the dashboard payload, or
  // the shared /auth/channels cache), so the rail costs no extra request.
  function setChannels(all, currentId) {
    if (!els) return;
    const channels = (all || []).slice()
      .sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')));
    const prefixLen = commonWordPrefix(channels.map(c => c.name));
    const current = channels.find(c => c.id === currentId);

    if (current) {
      const label = shortLabel(current.name || current.id, prefixLen);
      els.avatar.textContent = initials(label);
      els.name.textContent = label || current.id;
      els.handle.textContent = current.handle || '';
      els.trigger.title = `${current.name || current.id} — switch channel (/)`;
    } else {
      els.avatar.textContent = '◆';
      els.name.textContent = 'All channels';
      els.handle.textContent = channels.length
        ? `${channels.length} connected`
        : 'none connected';
      els.trigger.title = 'All channels — switch channel (/)';
    }

    const hrefFor = cfg.channelHref || defaultChannelHref;
    const rows = channels.map(ch => {
      const label = shortLabel(ch.name || ch.id, prefixLen);
      return `
        <a class="chan-opt${ch.id === currentId ? ' current' : ''}" role="option"
           aria-selected="${ch.id === currentId}" title="${esc(ch.name || ch.id)}"
           href="${esc(hrefFor(ch.id))}">
          <span class="chan-avatar sm">${esc(initials(label))}</span>
          <span class="chan-opt-name">${esc(label || ch.id)}</span>
        </a>`;
    }).join('');

    els.menu.innerHTML =
      '<div class="chan-menu-label">Channels</div>' +
      (rows || '<div class="muted-row">No channels connected.</div>') +
      '<div class="chan-menu-sep"></div>' +
      `<a class="chan-opt${currentId ? '' : ' current'}" href="/">` +
      '<span class="chan-avatar sm">◆</span>' +
      '<span class="chan-opt-name">All channels</span></a>' +
      '<a class="chan-opt" href="/auth/login">' +
      `<span class="chan-avatar sm">${icon('plus')}</span>` +
      '<span class="chan-opt-name">Add channel</span></a>';
  }

  window.Sidebar = { mount, setChannels };
})();
