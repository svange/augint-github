"""Theme definitions and display metadata for the panel dashboard."""

from __future__ import annotations

from dataclasses import dataclass

from textual.theme import Theme


@dataclass(frozen=True)
class DashboardThemeSpec:
    """Theme styling metadata used by the Textual app and Rich cards."""

    theme: Theme
    card_background: str
    card_text: str
    dim_text: str
    card_border: str
    card_warning: str
    card_error: str
    card_success: str
    card_selected: str


THEME_SPECS: list[DashboardThemeSpec] = [
    DashboardThemeSpec(
        theme=Theme(
            name="default",
            primary="#4e8cff",
            secondary="#888888",
            accent="#ffa500",
            background="#1a1b26",
            surface="#24283b",
            panel="#292e42",
            error="#f7768e",
            warning="#e0af68",
            success="#9ece6a",
            dark=True,
        ),
        card_background="#24283b",
        card_text="#f7f7fb",
        dim_text="#8a90a6",
        card_border="#4e8cff",
        card_warning="#e0af68",
        card_error="#b54b63",
        card_success="#9ece6a",
        card_selected="#7dcfff",
    ),
    DashboardThemeSpec(
        theme=Theme(
            name="cyber",
            primary="#00ff88",
            secondary="#00ccff",
            accent="#ff00ff",
            background="#0a0a0f",
            surface="#0f0f1a",
            panel="#141428",
            error="#ff2255",
            warning="#ffcc00",
            success="#00ff00",
            dark=True,
        ),
        card_background="#10131c",
        card_text="#d8ffef",
        dim_text="#6da893",
        card_border="#00ccff",
        card_warning="#ffcc00",
        card_error="#b33a58",
        card_success="#00ff88",
        card_selected="#ff00ff",
    ),
    DashboardThemeSpec(
        theme=Theme(
            name="minimal",
            primary="#c0c0c0",
            secondary="#808080",
            accent="#ffffff",
            background="#0c0c0c",
            surface="#161616",
            panel="#1c1c1c",
            error="#ff6b6b",
            warning="#ffd93d",
            success="#6bff6b",
            dark=True,
        ),
        card_background="#161616",
        card_text="#f0f0f0",
        dim_text="#8f8f8f",
        card_border="#c0c0c0",
        card_warning="#ffd93d",
        card_error="#b45c5c",
        card_success="#6bff6b",
        card_selected="#ffffff",
    ),
    DashboardThemeSpec(
        theme=Theme(
            name="matrix",
            primary="#39ff14",
            secondary="#1f8f3a",
            accent="#b6ff8a",
            background="#020602",
            surface="#071107",
            panel="#0a150a",
            error="#ff4466",
            warning="#d6ff66",
            success="#39ff14",
            dark=True,
        ),
        card_background="#071107",
        card_text="#d6ffd8",
        dim_text="#5f8f67",
        card_border="#1f8f3a",
        card_warning="#d6ff66",
        card_error="#a53a4e",
        card_success="#39ff14",
        card_selected="#b6ff8a",
    ),
]

THEMES: list[Theme] = [spec.theme for spec in THEME_SPECS]
THEME_NAMES = [spec.theme.name for spec in THEME_SPECS]
THEME_BY_NAME = {spec.theme.name: spec for spec in THEME_SPECS}


def get_theme_spec(name: str) -> DashboardThemeSpec:
    """Return dashboard metadata for a theme name, defaulting safely."""

    return THEME_BY_NAME.get(name, THEME_BY_NAME["default"])
