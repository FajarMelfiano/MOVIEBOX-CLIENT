"""Textual TUI package."""


def run_interactive_tui(*args, **kwargs):
    from moviebox_api.tui.app import run_interactive_tui as _run_interactive_tui

    return _run_interactive_tui(*args, **kwargs)


__all__ = ["run_interactive_tui"]
