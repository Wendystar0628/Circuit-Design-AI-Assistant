# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-file build for the Electron desktop sidecar."""

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    copy_metadata,
)


ROOT = Path(SPECPATH)


def collect_tree(relative_path: str) -> list[tuple[str, str]]:
    """Collect one runtime data tree while excluding Python cache files."""

    source_root = ROOT / relative_path
    if not source_root.is_dir():
        raise FileNotFoundError(f"Required packaged resource is missing: {source_root}")

    collected: list[tuple[str, str]] = []
    for source in source_root.rglob("*"):
        if not source.is_file():
            continue
        if "__pycache__" in source.parts or source.suffix in {".pyc", ".pyo"}:
            continue
        destination = source.relative_to(ROOT).parent.as_posix()
        collected.append((str(source), destination))
    return collected


datas = [
    *collect_tree("vendor/ngspice"),
    *collect_tree("resources/models"),
    *collect_data_files("chromadb"),
    *copy_metadata("chromadb", recursive=True),
]

# Chroma resolves these embedded-client components from configuration strings.
# Uvicorn's standard PyInstaller hook owns its protocol/loop imports.
hiddenimports = [
    "chromadb.api.rust",
    "chromadb.quota.simple_quota_enforcer",
    "chromadb.rate_limit.simple_rate_limit",
    "chromadb.telemetry.product.posthog",
]

analysis = Analysis(
    [str(ROOT / "desktop_backend" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "jupyter",
        "matplotlib",
        "notebook",
        "pandas",
        "pytest",
        "PyQt6",
        "pyqtgraph",
        "qasync",
        "scipy",
        "sentence_transformers",
        "tensorflow",
        "torch",
        "torchvision",
        "transformers",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="desktop_backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
