from __future__ import annotations

import argparse
import fnmatch
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

DEFAULT_MODELS_ROOT = Path("resources/models")

KEEP_EXACT = {
    "res.asy",
    "res2.asy",
    "cap.asy",
    "polcap.asy",
    "ind.asy",
    "ind2.asy",
    "voltage.asy",
    "current.asy",
    "diode.asy",
    "zener.asy",
    "schottky.asy",
    "led.asy",
    "tvsdiode.asy",
    "njf.asy",
    "pjf.asy",
    "sw.asy",
    "csw.asy",
    "f.asy",
    "h.asy",
    "bv.asy",
    "opamps/opamp.asy",
    "opamps/opamp2.asy",
    "opamps/universalopamp2.asy",
    "opamps/lm741.asy",
    "opamps/lm324.asy",
    "opamps/lt1001.asy",
    "misc/battery.asy",
    "misc/cell.asy",
    "misc/xtal.asy",
    "misc/ne555.asy",
}

KEEP_GLOBS = (
    "npn*.asy",
    "pnp*.asy",
    "nmos*.asy",
    "pmos*.asy",
    "e*.asy",
    "g*.asy",
    "bi*.asy",
)

KEEP_DIR_PREFIXES = (
    "comparators/",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-root", type=Path, default=DEFAULT_MODELS_ROOT)
    parser.add_argument("--mode", choices=("rebuild", "prune"), default="rebuild")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--list-kept", action="store_true")
    parser.add_argument("--list-removed", action="store_true")
    parser.add_argument("--max-list", type=int, default=60)
    return parser.parse_args()


def normalize_relative(path: Path) -> str:
    return path.as_posix().lower()


def should_keep(relative_path: Path) -> bool:
    rel = normalize_relative(relative_path)
    if rel in KEEP_EXACT:
        return True
    if any(rel.startswith(prefix) for prefix in KEEP_DIR_PREFIXES):
        return True
    return any(fnmatch.fnmatchcase(rel, pattern) for pattern in KEEP_GLOBS)


def top_group(relative_path: Path) -> str:
    parts = relative_path.parts
    if len(parts) == 1:
        return "<sym-root>"
    return parts[0]


def collect_symbol_plan(sym_root: Path) -> tuple[list[Path], list[Path], list[Path], list[Path]]:
    asy_files = sorted(
        path for path in sym_root.rglob("*") if path.is_file() and path.suffix.lower() == ".asy"
    )
    other_files = sorted(
        path for path in sym_root.rglob("*") if path.is_file() and path.suffix.lower() != ".asy"
    )
    kept: list[Path] = []
    removed: list[Path] = []
    for path in asy_files:
        rel = path.relative_to(sym_root)
        if should_keep(rel):
            kept.append(path)
        else:
            removed.append(path)
    return asy_files, other_files, kept, removed


def print_group_counts(title: str, files: list[Path], sym_root: Path) -> None:
    counter = Counter(top_group(path.relative_to(sym_root)) for path in files)
    print(title)
    for group_name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {group_name}: {count}")


def print_sample(title: str, files: list[Path], sym_root: Path, max_list: int) -> None:
    print(title)
    for path in files[:max_list]:
        print(f"  {path.relative_to(sym_root).as_posix()}")
    if len(files) > max_list:
        print(f"  ... ({len(files) - max_list} more)")


def ensure_paths(models_root: Path) -> Path:
    sym_root = models_root / "sym"
    if not models_root.is_dir():
        raise FileNotFoundError(f"models root does not exist: {models_root}")
    if not sym_root.is_dir():
        raise FileNotFoundError(f"sym directory does not exist: {sym_root}")
    return sym_root


def copy_preserving_relative(files: list[Path], source_root: Path, target_root: Path) -> None:
    for source_path in files:
        relative_path = source_path.relative_to(source_root)
        target_path = target_root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)


def prune_empty_directories(sym_root: Path) -> int:
    removed_count = 0
    for directory in sorted((path for path in sym_root.rglob("*") if path.is_dir()), reverse=True):
        try:
            directory.rmdir()
            removed_count += 1
        except OSError:
            pass
    return removed_count


def apply_rebuild(models_root: Path, sym_root: Path, kept: list[Path], other_files: list[Path]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = models_root / f"sym_backup_before_prune_{timestamp}"
    stage_dir = models_root / f"sym_keep_stage_{timestamp}"
    stage_dir.mkdir(parents=True, exist_ok=False)
    try:
        copy_preserving_relative(kept, sym_root, stage_dir)
        copy_preserving_relative(other_files, sym_root, stage_dir)
        shutil.move(str(sym_root), str(backup_dir))
        try:
            shutil.move(str(stage_dir), str(sym_root))
        except Exception:
            if not sym_root.exists() and backup_dir.exists():
                shutil.move(str(backup_dir), str(sym_root))
            raise
    finally:
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
    return backup_dir


def apply_prune(models_root: Path, sym_root: Path, removed: list[Path]) -> tuple[Path, int]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = models_root / f"sym_backup_before_prune_{timestamp}"
    shutil.copytree(sym_root, backup_dir)
    for path in removed:
        path.unlink()
    empty_dir_count = prune_empty_directories(sym_root)
    return backup_dir, empty_dir_count


def main() -> int:
    args = parse_args()
    models_root = args.models_root.resolve()
    try:
        sym_root = ensure_paths(models_root)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    all_asy, other_files, kept, removed = collect_symbol_plan(sym_root)

    print(f"models_root: {models_root.as_posix()}")
    print(f"sym_root: {sym_root.as_posix()}")
    print(f"asy_total: {len(all_asy)}")
    print(f"asy_kept: {len(kept)}")
    print(f"asy_removed: {len(removed)}")
    print(f"non_asy_preserved: {len(other_files)}")
    print(f"mode: {args.mode}")
    print_group_counts("keep groups:", kept, sym_root)
    print_group_counts("remove groups:", removed, sym_root)

    if args.list_kept:
        print_sample("kept files:", kept, sym_root, args.max_list)
    if args.list_removed:
        print_sample("removed files:", removed, sym_root, args.max_list)

    if not args.apply:
        print("dry-run only; rerun with --apply to modify files")
        return 0

    if args.mode == "rebuild":
        backup_dir = apply_rebuild(models_root, sym_root, kept, other_files)
        print(f"rebuilt sym directory with kept whitelist only")
        print(f"backup saved at: {backup_dir.as_posix()}")
        return 0

    backup_dir, empty_dir_count = apply_prune(models_root, sym_root, removed)
    print(f"deleted {len(removed)} .asy files")
    print(f"removed {empty_dir_count} empty directories")
    print(f"backup saved at: {backup_dir.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
