from __future__ import annotations

import os
from pathlib import Path

from infrastructure.utils import ngspice_config


def test_system_discovery_returns_the_verified_library_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_root = tmp_path / "Spice64"
    dll = install_root / "bin-dll" / "ngspice.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"test")
    monkeypatch.setattr(
        ngspice_config,
        "_system_library_candidates",
        lambda _platform: iter((dll,)),
    )

    discovered = ngspice_config._discover_system(
        ngspice_config.PLATFORM_WINDOWS
    )

    assert discovered == (dll.resolve(), install_root.resolve())


def test_path_setup_uses_exact_entries_not_substring_matches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    dll_dir = tmp_path / "dll"
    lookalike = tmp_path / "dll-extra"
    dll_dir.mkdir()
    lookalike.mkdir()
    monkeypatch.setenv("PATH", str(lookalike))

    ngspice_config._prepend_path_entry(dll_dir)
    ngspice_config._prepend_path_entry(dll_dir)

    entries = os.environ["PATH"].split(os.pathsep)
    assert Path(entries[0]).resolve() == dll_dir.resolve()
    assert sum(Path(entry).resolve() == dll_dir.resolve() for entry in entries) == 1
