"""The retired ``tools.lazy_deps.install_specs`` outside an update.

Out-of-tree plugins still call it at runtime: the pinned hindsight catalog
plugin does from ``is_available()`` on every agent init when its embedded
runtime is missing. Handing that call to the update takeover ran an update
and exited every ``hermes`` launch and cron job. Outside an update command it
must refuse the way the original's gated path did: never install, never exit.
Beneath one it still hands the retained-module updater to the fresh child.
"""

import subprocess

import pytest

from tests.compat.old_updater_support import (
    fresh_child as fresh_child,
    no_external_work as no_external_work,
)


def _beneath(module_name, entry, call):
    """Run *call* beneath a frame shaped like *module_name*.*entry*."""
    namespace = {"__name__": module_name, "call": call}
    exec(f"def {entry}():\n    return call()\n", namespace)
    return namespace[entry]()


@pytest.mark.parametrize("module_name,entry", [
    ("hermes_cli.main", "cmd_update"),
    ("hermes_cli.update_cmd", "_cmd_update_impl"),
    ("hermes_cli.update_cmd", "_run_update_phase_inline"),
    ("hermes_cli.update_cmd_zip", "_update_via_zip"),
])
@pytest.mark.parametrize("specs", [[], ["honcho-ai"]])
def test_install_specs_beneath_an_update_hands_off(module_name, entry, specs, fresh_child):
    from tools.lazy_deps import install_specs

    with fresh_child.exits():
        _beneath(module_name, entry, lambda: install_specs(specs, timeout=120))


@pytest.mark.parametrize("module_name,entry", [
    (None, None),
    # `hermes plugins update` and `hermes pm update` share the name, not the checkout swap.
    ("hermes_cli.plugins_cmd_update", "cmd_update"),
    ("pm.cli", "cmd_update"),
])
def test_runtime_install_specs_refuses_without_update_takeover(module_name, entry, monkeypatch):
    from hermes_cli import _old_updater
    from tools.lazy_deps import install_specs

    monkeypatch.setattr(_old_updater, "_result", None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail(f"spawned {a!r}"))

    def call():
        return install_specs(["hindsight-all"], timeout=600)

    outcome = call() if module_name is None else _beneath(module_name, entry, call)

    assert (outcome.ok, outcome.blocked) == (False, True)
    assert outcome.reason
    assert isinstance(outcome.stderr, str)
    assert _old_updater._result is None
