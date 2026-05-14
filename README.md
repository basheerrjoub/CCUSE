# Claude Usage Indicator

A tiny Ubuntu top-bar indicator that shows your real Claude Code usage —
the same numbers `/usage` displays inside `claude`. It calls Anthropic's
`/api/oauth/usage` endpoint directly using the OAuth token Claude Code
already stores, so the percentages are authoritative rather than estimated.

![what it looks like — bar + percentage in the GNOME top bar]

## What it shows

- **Top bar:** a 10-cell unicode bar + the 5-hour-window percentage, e.g.
  `███░░░░░░░ 29%`
- **Dropdown:**
  - 5-hour window % and reset countdown
  - Weekly (7-day) % and reset countdown
  - Extra-usage spend (only when pay-as-you-go is enabled)
  - Last-update timestamp
  - Refresh / Quit

The data is fetched every 60 seconds and on demand via *Refresh now*.

## Requirements

- Ubuntu (tested on 24.04, GNOME 46)
- Python 3 (already present)
- The Ayatana AppIndicator GIR binding (one apt package)
- The `gnome-shell-extension-appindicator` extension (default on Ubuntu)
- A working `claude` login — the indicator reads
  `~/.claude/.credentials.json` for the OAuth token.

## Install

```bash
# 1. System dependency (one-time)
sudo apt install gir1.2-ayatanaappindicator3-0.1

# 2. Place indicator.py wherever you like; this project keeps it at:
#    /home/brjoub/Desktop/CCUSE/indicator.py

# 3. Install + enable the user service
mkdir -p ~/.config/systemd/user
cp claude-usage-indicator.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now claude-usage-indicator.service
```

The service file in this repo points at
`/home/brjoub/Desktop/CCUSE/indicator.py`. If you put `indicator.py`
somewhere else, edit `ExecStart=` in the unit before enabling.

## Auto-start on boot

The systemd user unit is wired to `graphical-session.target`, so it
starts automatically the moment you log in to GNOME and stops when you
log out. `Restart=on-failure` means a crash gets it back up within five
seconds. No login-shell tricks, no `.desktop` files in `~/.config/autostart`.

Verify it's enabled:

```bash
systemctl --user is-enabled claude-usage-indicator.service   # → enabled
systemctl --user is-active  claude-usage-indicator.service   # → active
```

## Managing it

```bash
# Status (one-shot)
systemctl --user status claude-usage-indicator.service

# Live logs
journalctl --user -u claude-usage-indicator.service -f

# Restart after editing indicator.py
systemctl --user restart claude-usage-indicator.service

# Stop / start
systemctl --user stop    claude-usage-indicator.service
systemctl --user start   claude-usage-indicator.service

# Disable autostart (but leave the file in place)
systemctl --user disable claude-usage-indicator.service
```

## How it works

1. On every tick the script re-reads `~/.claude/.credentials.json` to
   grab the current OAuth access token.
2. It issues
   `GET https://api.anthropic.com/api/oauth/usage`
   with headers `Authorization: Bearer <token>` and
   `anthropic-beta: oauth-2025-04-20`.
3. The response contains:
   ```json
   {
     "five_hour": { "utilization": 29.0, "resets_at": "..." },
     "seven_day": { "utilization": 10.0, "resets_at": "..." },
     "extra_usage": { "is_enabled": false, ... }
   }
   ```
4. Those values are rendered into the top-bar label and the menu.

Because the credentials file is rewritten by `claude` whenever it
refreshes the OAuth token, the indicator picks up new tokens
automatically — no refresh logic of its own.

## Troubleshooting

| Top-bar shows | Meaning | Fix |
|---|---|---|
| `auth?` | 401 from the endpoint — token expired | Run `claude` once; the credentials file gets refreshed and the next tick recovers. |
| `auth` | Couldn't read `~/.claude/.credentials.json` | Log in via `claude` so the file is created. |
| `offline` | Network error reaching `api.anthropic.com` | Check connectivity. |
| `err` | Other HTTP error | Open the dropdown — the status line shows the code. |
| *No icon at all* | AppIndicator extension is disabled | `gnome-extensions enable ubuntu-appindicators@ubuntu.com` and log out/in. |

If the `anthropic-beta` header or `User-Agent` ever start being
rejected after a Claude Code update, bump the two constants at the
top of `indicator.py` (`ANTHROPIC_BETA`, `USER_AGENT`) to match
`claude --version`.

## Uninstall

```bash
systemctl --user disable --now claude-usage-indicator.service
rm ~/.config/systemd/user/claude-usage-indicator.service
systemctl --user daemon-reload
# Optional: remove the apt dependency if nothing else uses it
# sudo apt remove gir1.2-ayatanaappindicator3-0.1
```

## Files in this project

- `indicator.py` — the GTK AppIndicator script
- `claude-usage-indicator.service` — systemd user unit (copy of what's
  installed to `~/.config/systemd/user/`)
- `README.md` — this file

## Privacy / safety notes

- The indicator only reads its own machine's `~/.claude/.credentials.json`
  and talks to `api.anthropic.com`. Nothing is sent anywhere else.
- The OAuth access token is held in memory only for the duration of
  each HTTP request; it's never logged or printed.
