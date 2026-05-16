#!/usr/bin/env python3
"""
Claude Code usage indicator for the Ubuntu top bar.

Calls the same /api/oauth/usage endpoint that Claude Code's /usage panel uses,
so the percentages are the exact values Anthropic reports (no estimating). The
OAuth access token is read from ~/.claude/.credentials.json and refreshed
automatically whenever you run `claude`.

One-time install:
    sudo apt install gir1.2-ayatanaappindicator3-0.1

Run:
    python3 indicator.py
"""

import json
import os
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, GLib, Pango, PangoCairo  # noqa: E402
from gi.repository import AyatanaAppIndicator3 as AppIndicator3  # noqa: E402


CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
ANTHROPIC_BETA = "oauth-2025-04-20"
USER_AGENT = "claude-cli/2.1.142"
REFRESH_SECONDS = 120
HTTP_TIMEOUT = 15
BAR_WIDTH = 10

ICON_DIR = Path(tempfile.gettempdir()) / f"claude-usage-indicator-{os.getuid()}"
ICON_DIR.mkdir(exist_ok=True)
ICON_HEIGHT = 22
ICON_FONT = "Monospace Bold 11"
# Claude Code orange (#DE7356).
ICON_RGBA = (0xDE / 255, 0x73 / 255, 0x56 / 255, 1.0)


class AuthError(Exception):
    pass


def read_access_token() -> str:
    try:
        data = json.loads(CREDENTIALS_PATH.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise AuthError(f"can't read {CREDENTIALS_PATH}: {e}") from e
    tok = (data.get("claudeAiOauth") or {}).get("accessToken")
    if not tok:
        raise AuthError("no accessToken in credentials file")
    return tok


def fetch_usage() -> dict:
    token = read_access_token()
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": ANTHROPIC_BETA,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read().decode())


def render_bar(pct: float, width: int = BAR_WIDTH) -> str:
    filled = max(0, min(width, int(round(pct / 100 * width))))
    return "█" * filled + "░" * (width - filled)


def render_text_icon(text: str, slot: int) -> str:
    """Render `text` to a PNG sized to the text and return its absolute path.
    `slot` toggles between two filenames so AppIndicator notices the change."""
    # Measure first on a scratch surface.
    scratch = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
    ctx = cairo.Context(scratch)
    layout = PangoCairo.create_layout(ctx)
    layout.set_font_description(Pango.FontDescription(ICON_FONT))
    layout.set_text(text, -1)
    tw, th = layout.get_pixel_size()

    width = max(ICON_HEIGHT, tw + 6)
    height = ICON_HEIGHT
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    ctx.set_operator(cairo.OPERATOR_CLEAR)
    ctx.paint()
    ctx.set_operator(cairo.OPERATOR_OVER)
    ctx.set_source_rgba(*ICON_RGBA)
    layout = PangoCairo.create_layout(ctx)
    layout.set_font_description(Pango.FontDescription(ICON_FONT))
    layout.set_text(text, -1)
    tw, th = layout.get_pixel_size()
    ctx.move_to((width - tw) / 2, (height - th) / 2)
    PangoCairo.show_layout(ctx, layout)

    path = ICON_DIR / f"icon-{slot}.png"
    surface.write_to_png(str(path))
    return str(path)


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def format_remaining(target: datetime) -> str:
    secs = max(0, int((target - datetime.now(timezone.utc)).total_seconds()))
    h, rem = divmod(secs, 3600)
    m = rem // 60
    if h >= 24:
        d, h = divmod(h, 24)
        return f"{d}d {h}h"
    return f"{h}h {m}m"


class Indicator:
    def __init__(self) -> None:
        self.icon_slot = 0
        self.indicator = AppIndicator3.Indicator.new(
            "claude-usage-indicator",
            "utilities-system-monitor-symbolic",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        self.menu = Gtk.Menu()
        self.five_hour_item = self._info_item("Loading…")
        self.five_hour_reset_item = self._info_item("")
        self.seven_day_item = self._info_item("")
        self.seven_day_reset_item = self._info_item("")
        self.extra_item = self._info_item("")
        self.status_item = self._info_item("")
        for it in (
            self.five_hour_item,
            self.five_hour_reset_item,
            Gtk.SeparatorMenuItem(),
            self.seven_day_item,
            self.seven_day_reset_item,
            Gtk.SeparatorMenuItem(),
            self.extra_item,
            self.status_item,
        ):
            self.menu.append(it)

        self.menu.append(Gtk.SeparatorMenuItem())
        refresh = Gtk.MenuItem(label="Refresh now")
        refresh.connect("activate", lambda _: self.refresh())
        self.menu.append(refresh)
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _: Gtk.main_quit())
        self.menu.append(quit_item)

        self.menu.show_all()
        self.indicator.set_menu(self.menu)
        self.extra_item.hide()

        self.refresh()
        GLib.timeout_add_seconds(REFRESH_SECONDS, self._tick)

    @staticmethod
    def _info_item(text: str) -> Gtk.MenuItem:
        item = Gtk.MenuItem(label=text)
        item.set_sensitive(False)
        return item

    def _tick(self) -> bool:
        self.refresh()
        return True

    def refresh(self) -> None:
        try:
            data = fetch_usage()
        except AuthError as e:
            self._set_error("auth", str(e))
            return
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self._set_error("auth?", "401 — run `claude` to refresh token")
            else:
                self._set_error("err", f"HTTP {e.code}")
            return
        except (urllib.error.URLError, TimeoutError) as e:
            self._set_error("offline", f"network: {e}")
            return
        except Exception as e:  # noqa: BLE001
            self._set_error("err", f"{type(e).__name__}: {e}")
            return

        five = data.get("five_hour") or {}
        seven = data.get("seven_day") or {}
        extra = data.get("extra_usage") or {}

        five_pct = float(five.get("utilization") or 0.0)
        seven_pct = float(seven.get("utilization") or 0.0)

        self._set_icon_text(f"{render_bar(five_pct)} {five_pct:.0f}%")

        self.five_hour_item.set_label(f"5-hour window: {five_pct:.1f}%")
        five_reset = five.get("resets_at")
        self.five_hour_reset_item.set_label(
            f"  resets in {format_remaining(parse_iso(five_reset))}"
            if five_reset
            else "  no reset info"
        )

        self.seven_day_item.set_label(f"Weekly: {seven_pct:.1f}%")
        seven_reset = seven.get("resets_at")
        self.seven_day_reset_item.set_label(
            f"  resets in {format_remaining(parse_iso(seven_reset))}"
            if seven_reset
            else "  no reset info"
        )

        if extra.get("is_enabled"):
            used = extra.get("used_credits") or 0
            limit = extra.get("monthly_limit") or 0
            currency = extra.get("currency") or ""
            self.extra_item.set_label(
                f"Extra usage: {used} / {limit} {currency}".strip()
            )
            self.extra_item.show()
        else:
            self.extra_item.hide()

        self.status_item.set_label(
            f"Updated {datetime.now().strftime('%H:%M:%S')}"
        )

    def _set_icon_text(self, text: str) -> None:
        self.icon_slot ^= 1
        try:
            path = render_text_icon(text, self.icon_slot)
        except Exception:  # noqa: BLE001
            # If rendering fails, fall back to the symbolic icon.
            self.indicator.set_icon_full(
                "utilities-system-monitor-symbolic", text
            )
            return
        self.indicator.set_icon_full(path, text)

    def _set_error(self, label: str, detail: str) -> None:
        self._set_icon_text(label)
        self.five_hour_item.set_label("5-hour window: —")
        self.five_hour_reset_item.set_label("")
        self.seven_day_item.set_label("Weekly: —")
        self.seven_day_reset_item.set_label("")
        self.extra_item.hide()
        self.status_item.set_label(detail)


def main() -> None:
    Indicator()
    Gtk.main()


if __name__ == "__main__":
    main()
