/* 缓存 Chart.js 与字体，避免再次打开页面时被外链挡住。 */
var SHELL = '10etf-shell-v1';
var CDN_HOSTS = {
    'cdn.jsdelivr.net': true,
    'fonts.googleapis.com': true,
    'fonts.gstatic.com': true
};

self.addEventListener('install', function (event) {
    self.skipWaiting();
    event.waitUntil(Promise.resolve());
});

self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches.keys().then(function (keys) {
            return Promise.all(keys.map(function (key) {
                if (key.indexOf('10etf-shell-') === 0 && key !== SHELL) return caches.delete(key);
            }));
        }).then(function () { return self.clients.claim(); })
    );
});

function isCdn(url) {
    return !!CDN_HOSTS[url.hostname];
}

self.addEventListener('fetch', function (event) {
    var req = event.request;
    if (req.method !== 'GET') return;
    var url;
    try { url = new URL(req.url); } catch (e) { return; }
    if (!isCdn(url)) return;

    var cacheP = caches.open(SHELL);
    var updateP = cacheP.then(function (cache) {
        return fetch(req).then(function (res) {
            if (res && (res.ok || res.type === 'opaque')) {
                return cache.put(req, res.clone()).catch(function () {}).then(function () { return res; });
            }
            return res;
        }).catch(function () { return null; });
    });
    event.waitUntil(updateP.then(function () {}));
    event.respondWith(cacheP.then(function (cache) {
        return cache.match(req);
    }).then(function (cached) {
        if (cached) return cached;
        return updateP.then(function (res) {
            return res || new Response('', { status: 504, statusText: 'offline' });
        });
    }));
});
