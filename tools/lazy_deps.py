"""Shims to suppress old updater work until relaunch. New code must not use these."""

from dataclasses import dataclass
from typing import NoReturn

from hermes_cli._old_updater import stop_for_relaunch, update_on_stack


def ensure(feature: str, *, prompt: bool = True) -> NoReturn:
    # Shim to suppress old updater work until relaunch. Do not claim readiness.
    # Preserve the dependency-unavailable failure without claiming a completed install.
    raise ImportError("Dependencies are unknown to this old updater. Please relaunch Hermes.")


@dataclass(frozen=True)
class InstallSpecsResult:
    """The historical outcome shape; plugins read ``ok``/``blocked``/``reason``/``stderr``."""
    ok: bool
    blocked: bool = False
    reason: str = ""
    command: str = ""
    stdout: str = ""
    stderr: str = ""


def install_specs(specs: list[str] | tuple[str, ...], *, timeout: int = 300) -> InstallSpecsResult:
    # Shim to suppress old updater work until relaunch. Do not install or report success.
    if update_on_stack():
        # Returning would resume the old updater's own fallback on a half-new tree.
        stop_for_relaunch()
    # Out-of-tree plugins still call this at runtime (the pinned hindsight catalog plugin does
    # from is_available() on every agent init). A handoff there ran an update and exited every
    # launch; refuse the way the original's gated path did instead.
    return InstallSpecsResult(
        ok=False, blocked=True,
        reason="runtime installs through tools.lazy_deps are retired; the plugin must declare "
               f"{' '.join(map(str, specs))} in its pyproject.toml so `hermes plugins install` "
               "provisions it through PM",
    )
