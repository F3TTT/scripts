# ultracc-stock-watch

Alerts on Discord when a bigger Ultra.cc seedbox plan comes back in stock in Canada.
The user is on the 4TB plan (3,725 GB quota), it's nearly full, and the 6TB+ "Metaliux - Canada" plans
have been sold out for a long time and sell out fast when they do restock. Created 2026-10-06.

- **Runs on the seedbox** (always on), not the laptop: `~/ultracc-stock-watch/stock_watch.py`, cron `*/10 * * * *`.
- **Source of truth:** this folder. To deploy, copy `stock_watch.py` to the seedbox with `scp`.
- **Config:** `~/ultracc-stock-watch/config.json` on the seedbox (chmod 600, not in git). It holds the Discord
  webhook, which is the same "Discord - seedbox alerts" webhook Uptime Kuma uses, so alerts land in the same
  channel. Also `categories` (default `["metaliux-canada"]`), `min_tb` (default 6), and `fail_alert_after` (default 6 runs).
- **Alerts:** a watched plan going from 0 to >0 available posts the plan, size, count, price and order link.
  If the store page can't be fetched or parsed for about an hour, it posts a warning, so a site redesign can't
  silently stop it. Every run logs to `stock_watch.log`.
- **Test:** `python3 ~/ultracc-stock-watch/stock_watch.py --test` posts the current counts to Discord.
- **Retire it** once upgraded: remove the cron line and delete `~/ultracc-stock-watch/`.
