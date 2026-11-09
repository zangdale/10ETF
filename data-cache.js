/* 历史 JSON 缓存：已结束的持仓日、往年 K 线只下载一次。当年 K 线按 info.end 作版本。 */
(function () {
    var CACHE = '10etf-json-v1';
    var FULL_KEY = '10etf-kline-full';
    var inflight = Object.create(null);

    function todayISO() {
        try {
            return new Intl.DateTimeFormat('en-CA', {
                timeZone: 'Asia/Shanghai',
                year: 'numeric',
                month: '2-digit',
                day: '2-digit'
            }).format(new Date());
        } catch (e) {
            var d = new Date();
            var p = function (n) { return String(n).padStart(2, '0'); };
            return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
        }
    }

    function classify(pathname) {
        var hold = pathname.match(/\/etf_hold\/(\d{4}-\d{2}-\d{2})\.json$/);
        if (hold) return hold[1] < todayISO() ? 'frozen' : 'net';
        var kline = pathname.match(/\/kline\/(\d{4})\/[^/]+\.json$/);
        if (kline) return Number(kline[1]) < Number(todayISO().slice(0, 4)) ? 'frozen' : 'year';
        if (pathname.endsWith('/kline/info.json')) return 'info';
        return 'net';
    }

    function cacheKey(abs, revision) {
        if (!revision) return abs.href;
        var u = new URL(abs.href);
        u.searchParams.set('__rev', revision);
        return u.href;
    }

    async function bustKlineIfFull(info) {
        if (!info || info.mode !== 'full' || !info.fetched_at || !('caches' in window)) return;
        var seen = null;
        try { seen = localStorage.getItem(FULL_KEY); } catch (e) { return; }
        if (seen === info.fetched_at) return;
        try { localStorage.setItem(FULL_KEY, info.fetched_at); } catch (e) { /* ignore */ }
        var cache = await caches.open(CACHE);
        var keys = await cache.keys();
        await Promise.all(keys.map(function (req) {
            if (new URL(req.url).pathname.indexOf('/kline/') !== -1) return cache.delete(req);
        }));
    }

    async function remember(abs, key, res) {
        if (!res || !res.ok || !('caches' in window)) return;
        var cache = await caches.open(CACHE);
        if (key.indexOf('__rev=') !== -1) {
            var keys = await cache.keys();
            await Promise.all(keys.map(function (req) {
                var u = new URL(req.url);
                if (u.origin === abs.origin && u.pathname === abs.pathname && req.url !== key) {
                    return cache.delete(req);
                }
            }));
        }
        await cache.put(key, res.clone());
    }

    async function fromNetwork(abs) {
        var res = await fetch(abs.href, { cache: 'no-store' });
        if (classify(abs.pathname) === 'info' && res.ok) {
            try { await bustKlineIfFull(await res.clone().json()); } catch (e) { /* ignore */ }
        }
        return res;
    }

    async function loadCached(abs, key) {
        try {
            var cache = await caches.open(CACHE);
            var hit = await cache.match(key);
            if (hit) return hit;
        } catch (e) {
            return fromNetwork(abs);
        }
        var res = await fromNetwork(abs);
        try { await remember(abs, key, res); } catch (e) { /* ignore */ }
        return res;
    }

    async function etfFetch(input, opts) {
        var revision = opts && opts.revision ? String(opts.revision) : '';
        var abs = new URL(input, location.href);
        var kind = classify(abs.pathname);
        var useCache = kind === 'frozen' || (kind === 'year' && revision);
        if (!useCache || !('caches' in window)) return fromNetwork(abs);

        var key = cacheKey(abs, kind === 'year' ? revision : '');
        try {
            if (!inflight[key]) {
                inflight[key] = loadCached(abs, key).finally(function () { delete inflight[key]; });
            }
            var res = await inflight[key];
            return res.clone();
        } catch (e) {
            return fromNetwork(abs);
        }
    }

    async function mapPool(items, limit, fn) {
        var i = 0;
        async function worker() {
            while (i < items.length) {
                var cur = items[i++];
                try { await fn(cur); } catch (e) { /* ignore */ }
            }
        }
        var n = Math.min(limit, items.length);
        var jobs = [];
        for (var w = 0; w < n; w++) jobs.push(worker());
        await Promise.all(jobs);
    }

    async function warm() {
        try {
            var idxRes = await fetch(new URL('etf_hold/index.json', location.href).href, { cache: 'no-store' });
            if (idxRes.ok) {
                var idx = await idxRes.json();
                var dates = Array.isArray(idx.dates) ? idx.dates : [];
                await mapPool(dates, 6, function (day) {
                    return etfFetch('etf_hold/' + day + '.json');
                });
            }
        } catch (e) { /* ignore */ }
        try {
            var infoRes = await etfFetch('kline/info.json');
            if (!infoRes.ok) return;
            var info = await infoRes.json();
            var items = Array.isArray(info.items) ? info.items : [];
            var files = [];
            items.forEach(function (item) {
                var years = Array.isArray(item.years) ? item.years : [];
                years.forEach(function (year) {
                    files.push({
                        url: 'kline/' + year + '/' + item.code + '.json',
                        revision: item.end || ''
                    });
                });
            });
            await mapPool(files, 4, function (file) {
                return etfFetch(file.url, file.revision ? { revision: file.revision } : undefined);
            });
        } catch (e) { /* ignore */ }
    }

    function scheduleWarm() {
        if (/\/(history|kline|backtest)\.html$/.test(location.pathname)) return;
        window.addEventListener('load', function () {
            var run = function () { warm(); };
            if (typeof requestIdleCallback === 'function') requestIdleCallback(run, { timeout: 2500 });
            else setTimeout(run, 600);
        });
    }

    window.etfFetch = etfFetch;
    scheduleWarm();
})();
