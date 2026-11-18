// Mini App entry inside Telegram: validate nothing here (the server does), just pass initData along.
import { httpApi } from './api.js';
import { mountApp } from './ui.js';
import { h, loadCatalogs } from './util.js';

const tg = window.Telegram?.WebApp;
const root = document.getElementById('app');
const catalogs = await loadCatalogs();

if (!tg?.initData) {
  root.replaceChildren(h('p', { class: 'pq-outside' }, catalogs.uz['app.open_in_telegram']),
    h('p', { class: 'pq-outside' }, catalogs.ru['app.open_in_telegram']));
} else {
  tg.ready();
  tg.expand();
  const lang = tg.initDataUnsafe?.user?.language_code?.startsWith('ru') ? 'ru' : 'uz';
  mountApp(root, { api: httpApi(tg.initData), catalogs, lang, tg });
}
