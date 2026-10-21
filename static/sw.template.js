/* Садовод: работа без интернета.
   Страницы, данные и иконки: сначала копия из кэша (приложение открывается сразу, даже без сети или при плохой связи),
   а свежая версия скачивается в фоне. Когда выходит новая версия, страница один раз перезагружается сама.
   Фото с Wikimedia Commons запоминаются после первого просмотра. */
const VERSION = '@@VERSION@@';
const APP_CACHE = 'sadovod-app-' + VERSION;
const PHOTO_CACHE = 'sadovod-photos-v1';
const PHOTO_LIMIT = 60;
const APP_FILES = @@APP_FILES@@;
const PHOTO_HASHES = @@PHOTO_HASHES@@;   // фото: имя → контрольная сумма

self.addEventListener('install', e => {
  e.waitUntil((async () => {
    const cache = await caches.open(APP_CACHE);
    const old = (await caches.keys()).filter(k => k.startsWith('sadovod-app-') && k !== APP_CACHE);
    // фото, которое не изменилось, берём из прошлой версии, а не качаем заново
    const reuse = async f => {
      const h = PHOTO_HASHES[f];
      if(!h) return false;
      for(const k of old){
        const hit = await (await caches.open(k)).match(f, {ignoreSearch: true});
        if(hit && hit.headers.get('x-sadovod-hash') === h){ await cache.put(f, hit); return true; }
      }
      return false;
    };
    // каждый файл отдельно: если один не скачался, остальные всё равно сохранятся
    await Promise.allSettled(APP_FILES.map(async f => {
      if(await reuse(f)) return;
      let res = await fetch(new Request(f, {cache: 'reload'}));
      if(!(res && res.ok)) return;
      if(PHOTO_HASHES[f]){
        const headers = new Headers(res.headers); headers.set('x-sadovod-hash', PHOTO_HASHES[f]);
        res = new Response(await res.blob(), {status: 200, headers});
      }
      await cache.put(f, res);
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== APP_CACHE && k !== PHOTO_CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

const isPhoto = url => /(^|\.)wikimedia\.org$/.test(url.hostname);

async function trimPhotos(){
  const cache = await caches.open(PHOTO_CACHE);
  const keys = await cache.keys();
  for(let i = 0; i < keys.length - PHOTO_LIMIT; i++) await cache.delete(keys[i]);
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if(req.method !== 'GET') return;
  const url = new URL(req.url);

  if(isPhoto(url)){
    e.respondWith((async () => {
      const cache = await caches.open(PHOTO_CACHE);
      const hit = await cache.match(req);
      if(hit) return hit;
      try {
        const res = await fetch(req);
        if(res && (res.ok || res.type === 'opaque')){ cache.put(req, res.clone()); trimPhotos(); }
        return res;
      } catch(err) {
        return Response.error();
      }
    })());
    return;
  }

  if(url.origin === self.location.origin){
    e.respondWith((async () => {
      const cache = await caches.open(APP_CACHE);
      const hit = await cache.match(req, {ignoreSearch: true});
      if(hit && url.pathname.includes('/photos/')) return hit;   // фото меняются только с новой версией
      const refresh = fetch(req)
        .then(res => { if(res && res.ok) cache.put(req, res.clone()); return res; })
        .catch(() => null);
      if(hit){ e.waitUntil(refresh); return hit; }          // из кэша сразу, обновление в фоне
      const res = await refresh;
      if(res) return res;
      if(req.mode === 'navigate') return (await cache.match('index.html')) || (await cache.match('./')) || Response.error();
      return Response.error();
    })());
  }
});
