// swr.js — tiny stale-while-revalidate cache for Midas's static pages.
//
// No build step, no dependencies. Include with:
//   <script src="/static/swr.js"></script>
// before the page's own <script>.
//
// The problem it solves: every page previously blocked on the network from a
// blank "Loading…" state on every visit, re-fetching data it had already shown
// seconds earlier. SWR keeps the last successful JSON response per URL in
// localStorage, paints it instantly when the page opens, then revalidates in
// the background and repaints ONLY if the payload actually changed (so no
// flicker, no lost scroll, no collapsed <details> when nothing moved).
//
// Usage:
//   SWR.swr('/dashboard', (data, meta) => render(data), { onError });
//     → onData fires up to twice: once synchronously with cached data
//       (meta.stale === true) if any exists, then again after the network
//       returns fresh data IF it differs (meta.stale === false).
//   SWR.invalidate('/dashboard')            — drop one cache entry
//   SWR.invalidatePrefix('/channels/UC123') — drop every entry whose key
//                                             starts with the prefix
//   SWR.get(url) / SWR.set(url, value)      — direct cache access
//
// Cache invalidation after a mutation: call SWR.invalidate(...) for the URLs
// the mutation changed, then re-run the page's load function. Because swr()
// always revalidates, the repaint happens within one round-trip regardless;
// invalidating just guarantees a later cold visit won't paint now-stale data.

(function (global) {
  'use strict';

  // Bump when a cached payload's shape changes incompatibly — old entries are
  // ignored (treated as a miss) rather than mis-rendered.
  var VERSION = 'v1';
  var PREFIX = 'midas:swr:' + VERSION + ':';
  // Skip caching payloads larger than this (bytes of JSON). localStorage is
  // ~5MB total; a single huge /videos response shouldn't be allowed to evict
  // everything else or blow the quota on write.
  var MAX_ITEM_BYTES = 1_500_000;

  // In-flight fetches, keyed by cache key, so two callers asking for the same
  // URL in the same tick (e.g. the channel page loading /audit-config from both
  // loadConfig and loadReflectionData) share ONE network request.
  var inflight = new Map();

  function storageKey(key) { return PREFIX + key; }

  function get(key) {
    try {
      var raw = localStorage.getItem(storageKey(key));
      if (raw == null) return undefined;
      var parsed = JSON.parse(raw);
      return parsed && 'd' in parsed ? parsed.d : undefined;
    } catch (e) {
      return undefined;
    }
  }

  function set(key, value) {
    var payload;
    try {
      payload = JSON.stringify({ t: nowSafe(), d: value });
    } catch (e) {
      return; // non-serializable — silently skip caching
    }
    if (payload.length > MAX_ITEM_BYTES) return; // too big to cache
    try {
      localStorage.setItem(storageKey(key), payload);
    } catch (e) {
      // Quota exceeded (or private-mode). Evict our own entries and retry once;
      // if it still fails, run without a cache for this write.
      evictAll();
      try { localStorage.setItem(storageKey(key), payload); } catch (e2) { /* give up */ }
    }
  }

  // Date.now() is fine in the browser; wrapped only so a hostile environment
  // that stubs it can't throw us out of a cache write.
  function nowSafe() { try { return Date.now(); } catch (e) { return 0; } }

  function invalidate(key) {
    try { localStorage.removeItem(storageKey(key)); } catch (e) { /* ignore */ }
  }

  function invalidatePrefix() {
    var prefixes = Array.prototype.slice.call(arguments);
    try {
      for (var i = localStorage.length - 1; i >= 0; i--) {
        var k = localStorage.key(i);
        if (k == null || k.indexOf(PREFIX) !== 0) continue;
        var bare = k.slice(PREFIX.length);
        for (var j = 0; j < prefixes.length; j++) {
          if (bare.indexOf(prefixes[j]) === 0) { localStorage.removeItem(k); break; }
        }
      }
    } catch (e) { /* ignore */ }
  }

  function evictAll() {
    try {
      for (var i = localStorage.length - 1; i >= 0; i--) {
        var k = localStorage.key(i);
        if (k != null && k.indexOf(PREFIX) === 0) localStorage.removeItem(k);
      }
    } catch (e) { /* ignore */ }
  }

  // Stable stringify for change detection so key order can't cause a spurious
  // "changed" repaint. Cheap: these payloads are small dashboards, not blobs.
  function stableStringify(value) {
    if (value === undefined) return undefined;
    var seen = [];
    return JSON.stringify(value, function (k, v) {
      if (v && typeof v === 'object' && !Array.isArray(v)) {
        if (seen.indexOf(v) !== -1) return v; // don't reorder cycles
        seen.push(v);
        var sorted = {};
        Object.keys(v).sort().forEach(function (kk) { sorted[kk] = v[kk]; });
        return sorted;
      }
      return v;
    });
  }

  /**
   * Stale-while-revalidate fetch of a JSON endpoint.
   *
   * @param {string} url               endpoint to GET
   * @param {(data:any, meta:{stale:boolean, cached:boolean})=>void} onData
   * @param {object} [opts]
   * @param {string}   [opts.key]      cache key (defaults to url)
   * @param {object}   [opts.fetch]    extra fetch() init
   * @param {(err:any)=>void} [opts.onError]  called if the revalidation fetch
   *                                    fails; stale data (if any) is kept.
   * @returns {{cached:any, fresh:Promise<any>}}
   */
  function swr(url, onData, opts) {
    opts = opts || {};
    var key = opts.key || url;
    var cached = get(key);
    var cachedStr = stableStringify(cached);

    if (cached !== undefined && typeof onData === 'function') {
      try { onData(cached, { stale: true, cached: true }); } catch (e) { logErr(e); }
    }

    var fresh;
    if (inflight.has(key)) {
      // Coalesce with the request already in flight for this key.
      fresh = inflight.get(key);
    } else {
      fresh = fetch(url, opts.fetch || undefined).then(function (r) {
        if (!r.ok) {
          var err = new Error('HTTP ' + r.status);
          err.status = r.status;
          err.response = r;
          throw err;
        }
        return r.json();
      }).then(function (data) {
        set(key, data);
        return data;
      });
      inflight.set(key, fresh);
      // Clear the in-flight slot whichever way it settles.
      fresh.then(clear, clear);
      function clear() { if (inflight.get(key) === fresh) inflight.delete(key); }
    }

    var handled = fresh.then(function (data) {
      var changed = stableStringify(data) !== cachedStr;
      if ((changed || cached === undefined) && typeof onData === 'function') {
        try { onData(data, { stale: false, cached: false }); } catch (e) { logErr(e); }
      }
      return data;
    }, function (err) {
      if (typeof opts.onError === 'function') {
        try { opts.onError(err); } catch (e) { logErr(e); }
      } else {
        logErr(err); // keep whatever stale data we already painted
      }
      throw err;
    });

    // Swallow the rejection on the returned promise unless the caller chains
    // onto it, so an expected network hiccup doesn't surface as an unhandled
    // rejection. Callers that want the value can still await `fresh`/`handled`.
    handled.catch(function () {});

    return { cached: cached, fresh: handled };
  }

  function logErr(e) { try { console.error('[swr]', e); } catch (x) { /* ignore */ } }

  global.SWR = {
    swr: swr,
    get: get,
    set: set,
    invalidate: invalidate,
    invalidatePrefix: invalidatePrefix,
    evictAll: evictAll,
  };
})(window);
