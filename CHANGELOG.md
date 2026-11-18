# Changelog

## 1.0.0 — 2026-11-18

First release (day 1 of the 30-day portfolio challenge).

- Two-sided debts: a debt, payment, correction or write-off counts only after the other side confirms it.
- Append-only per-pair hash chain with visible seals and a "verify chain" check that points to the broken link;
  balances come only from the verified part of the chain.
- Share links for people who are not in the bot yet (single-use, 7 days, stored as SHA-256).
- Balances per person and per currency; reminders 3 days before, on the day and when overdue, stored in SQLite.
- aiogram 3 bot (buttons only, Uzbek and Russian), aiohttp Mini App API with initData HMAC + freshness checks,
  rate limits, CSP; plain HTML/CSS/JS Mini App that re-verifies chains on the phone.
- JS port of the core with shared test vectors (pytest + `node --test`), Playwright demo test, Docker (non-root), CI.
- GitHub Pages demo: two phones side by side, guided story, "+1 day" to see reminders fire.
