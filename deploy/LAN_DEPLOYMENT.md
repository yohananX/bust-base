# LAN Deployment Guide — Grace House School System

Goal: the portal is reachable from any phone/laptop/tablet on the school Wi-Fi as
`http://portal.ghis.sch` (no port).

## Architecture

```
phone/laptop/tablet  →  router DHCP hands out our DNS  →  Technitium DNS (this PC)
                                                    ↓  resolves portal.ghis.sch → 192.168.0.50
                                                    ↓
device browser  →  http://portal.ghis.sch  →  Caddy :80  →  Waitress :8000 (one Django app)
```

- **ONE Django instance, one SQLite DB, ONE URL (`portal.ghis.sch`).** The app is
  multi-tenant and routes by role *after login* (`PostLoginRedirectView`): ADMIN →
  `/admin/`, TEACHER → `/teacher/`, STUDENT → `/student/`, PARENT → `/parent/`.
  Everyone logs in at the same URL and lands in their own portal.
- Plain HTTP on purpose: it's a private LAN. Keep `DEBUG=True` in `.env` — the
  production guard in `school/settings.py` refuses plain-HTTP boots otherwise.

## What is already prepared (committed to the repo)

| File | Purpose |
|---|---|
| `Caddyfile` | Reverse proxy: `http://portal.ghis.sch` + LAN IP → `127.0.0.1:8000` |
| `scripts/start_lan.bat` | Starts Django-Q2 `qcluster` + Waitress on `0.0.0.0:8000` |
| `scripts/open_firewall.bat` | Admin script: opens TCP 80, TCP 8000, TCP/UDP 53 |
| `.env` | `ALLOWED_HOSTS` + `CSRF_TRUSTED_ORIGINS` already include `portal.ghis.sch` and `192.168.0.50` |
| `requirements.txt` | `waitress` added (gunicorn is Linux-only) |
| `staticfiles/` | `collectstatic` already run (Whitenoise serves static) |

## Part A — on the school network (do once)

1. **Fixed IP on this PC** — Settings → Network & internet → (Ethernet/Wi-Fi) →
   Edit IP assignment → Manual → IPv4:
   - IP: `192.168.0.50` (outside the router's DHCP range)
   - Mask: `255.255.255.0` · Gateway: `192.168.0.1` (HyNetFlex default)
   - Preferred DNS: `127.0.0.1` · Alternate: `1.1.1.1`
   - If you change the IP, update `.env` (`ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`),
     `Caddyfile`, and the DNS A records below.

2. **Install Technitium DNS Server** — https://technitium.com/dns/ (Windows build).
   - Web panel: `http://localhost:5380`, set a strong password.
   - **Zones → Add Zone** → Primary Zone → name `ghis.sch`.
   - In the zone add an **A record**:
     | Name | Type | Value |
     |---|---|---|
     | portal | A | 192.168.0.50 |
   - Settings → General: listen on all interfaces; port 53.

3. **Windows Firewall** — run `scripts\open_firewall.bat` as Administrator
   (opens 80, 8000, 53). Verify: `netsh advfirewall firewall show rule name="GHSS*"`.

4. **Router (MTN HyNetFlex)** — `http://192.168.0.1`, find the LAN/DHCP DNS setting
   (may be called "DNS Server", "Primary DNS", or "DNS Proxy"):
   - Primary DNS: `192.168.0.50` · Secondary: `1.1.1.1` (internet keeps working
     if this PC is off). Save/apply, restart the router or Wi-Fi clients.

5. **Caddy** — download `caddy.exe` from https://caddyserver.com/download
   (Windows amd64, no plugins needed). Options:
   - Foreground (test): `caddy run --config C:\Users\pasto\bust-base\Caddyfile`
   - Background: `caddy start --config C:\Users\pasto\bust-base\Caddyfile`
   - As a service (survives reboot/logout), from an **admin** prompt:
     ```
     sc.exe create Caddy binPath= "C:\caddy\caddy.exe run --config C:\Users\pasto\bust-base\Caddyfile" start= auto
     sc.exe start Caddy
     ```

6. **Start the app** — double-click `scripts\start_lan.bat` (keep the window open).
   Two processes: `qcluster` (notifications/bell) and Waitress on :8000.

## Part B — testing (from any device)

1. On the PC: `nslookup portal.ghis.sch` → must return `192.168.0.50`.
2. From a phone/laptop on the same Wi-Fi: forget + rejoin the network
   (or `ipconfig /renew`), then browse `http://portal.ghis.sch` — you'll see the
   login page; logging in routes you to your role's portal.
   - If the name doesn't resolve, try `http://192.168.0.50` — if that works, the
     DNS/router step is the problem, not the app.

## Known limits & notes

- **`.sch` is a real public TLD** (Singapore). Devices that ignore the router DNS
  (mobile data, DNS-over-HTTPS browsers) will not resolve the name. If some
  devices misbehave, switch the zone to `portal.ghis.lan` (2-minute change: zone
  name + `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS`/Caddyfile).
- **Paystack webhook** (internet → LAN) cannot reach the school network without a
  tunnel (ngrok/cloudflared). Card payments still confirm via the return-page
  verify fallback; bank transfers are confirmed manually by the admin. Add a
  tunnel later if webhook-first confirmation is required.
- **Debug stays on** — acceptable for a private school LAN; never expose this
  machine to the public internet as-is.
- **Backups** — SQLite DB is `db.sqlite3`; back it up regularly, or migrate to
  Postgres (`DATABASE_URL`) when the school grows.