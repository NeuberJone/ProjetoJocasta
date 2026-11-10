"""Run unittest with application data and temporary files inside the repository.

Environment variables must be set before importing any application or test module:
some legacy configuration modules resolve their paths during import.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    test_runs = (repo / "build" / "test-runs").resolve()
    if not test_runs.is_relative_to(repo):
        raise RuntimeError("The test workspace must remain inside the repository.")
    test_runs.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="isolated-", dir=test_runs) as temporary:
        sandbox = Path(temporary).resolve()
        if not sandbox.is_relative_to(test_runs):
            raise RuntimeError("The temporary test directory escaped its workspace.")
        home = sandbox / "home"
        appdata = sandbox / "appdata"
        localappdata = sandbox / "localappdata"
        temp = sandbox / "temp"
        for directory in (home, appdata, localappdata, temp):
            directory.mkdir()
        os.environ.update({
            "APPDATA": str(appdata),
            "LOCALAPPDATA": str(localappdata),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_STATE_HOME": str(home / ".local" / "state"),
            "TEMP": str(temp),
            "TMP": str(temp),
            "TMPDIR": str(temp),
        })
        tempfile.tempdir = str(temp)

        # A normal load_config() also stays inside the sandbox. Individual tests
        # that inject another config path must inject their own base_dir too.
        config = {"base_dir": str(sandbox / "PXCore"), "theme_name": "dark"}
        for path in (appdata / "PXCore" / "config.json", home / ".config" / "PXCore" / "config.json"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(config), encoding="utf-8")

        os.chdir(repo)
        sys.path.insert(0, str(repo))
        program = unittest.main(
            module=None,
            argv=[sys.argv[0], "discover", "-s", str(repo / "tests"), *sys.argv[1:]],
            exit=False,
        )
        return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
