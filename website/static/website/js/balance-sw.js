/*
 * Service worker /balance/ — Блок 0: только регистрация с пустым fetch-
 * хендлером. Без зарегистрированного SW Chrome на Android не предлагает
 * "beforeinstallprompt" вообще (одно из условий installability наряду с
 * manifest.json и HTTPS) — банер "Добавить на экран" из balance-pwa.js
 * иначе никогда бы не сработал на Android.
 *
 * Реальное кэширование интерфейса/статики и офлайн-очередь IndexedDB —
 * Блок 7 (см. ТЗ, раздел 8.2). Здесь сознательно нет caches.open/fetch-
 * перехвата — это отдельная задача с собственной инвалидацией кэша,
 * не расширять этот файл попутно при правках Блока 0.
 */
self.addEventListener("install", function (event) {
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", function () {
  // Пока не перехватываем — сеть работает как обычно.
});
