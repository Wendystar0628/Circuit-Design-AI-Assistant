from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from domain.simulation.spice.bundled_subcircuit_catalog import load_bundled_subcircuit_path_index
from resources.resource_loader import get_spice_cmp_dir


@dataclass(frozen=True)
class BundledModelBlock:
    name: str
    source_file: Path
    text: str


class BundledSpiceLibraryInjector:
    _DEVICE_MODEL_START_INDEX = {
        "Q": 4,
        "M": 5,
        "D": 3,
        "J": 4,
    }

    def __init__(self, logger):
        self._logger = logger
        self._cmp_index: Optional[Dict[str, BundledModelBlock]] = None
        self._subckt_index: Optional[Dict[str, Path]] = None

    def inject(self, netlist: str, circuit_dir: Path) -> str:
        cmp_index = self._build_cmp_index()
        subckt_index = self._build_subckt_index()
        if not cmp_index and not subckt_index:
            return netlist

        existing_paths = self._get_existing_lib_paths(netlist)
        defined_models = self._extract_defined_models(netlist)
        referenced_models = self._extract_referenced_models(netlist, cmp_index.keys())
        missing_models = sorted(referenced_models - defined_models)

        injected_lines: List[str] = []
        injected_model_names: Set[str] = set()
        for model_name in missing_models:
            block = cmp_index.get(model_name)
            if block is None:
                continue
            norm = str(block.source_file).replace('\\', '/').lower()
            if any(norm.endswith(path) for path in existing_paths):
                continue
            if model_name in injected_model_names:
                continue
            injected_lines.extend(block.text.splitlines())
            injected_model_names.add(model_name)

        defined_subckts = self._extract_defined_subckts(netlist)
        invoked_subckts = self._extract_invoked_subckts(netlist) - defined_subckts
        for subckt_name in sorted(invoked_subckts):
            model_file = subckt_index.get(subckt_name)
            if model_file is None:
                continue
            norm = str(model_file).replace('\\', '/').lower()
            if any(norm.endswith(path) for path in existing_paths):
                continue
            spice_path = self._build_spice_path(model_file, circuit_dir)
            injected_lines.append(f'.include "{spice_path}"')

        if not injected_lines:
            return netlist

        lines = netlist.splitlines()
        if not lines:
            return netlist

        insertion_index = 1
        for idx, line in enumerate(lines[1:], start=1):
            stripped = line.strip().lower()
            if stripped == '.title' or stripped.startswith('.title '):
                insertion_index = idx + 1
                break
            if stripped and not stripped.startswith('*') and not stripped.startswith(';'):
                break

        return '\n'.join(lines[:insertion_index] + injected_lines + lines[insertion_index:])

    def _build_cmp_index(self) -> Dict[str, BundledModelBlock]:
        if self._cmp_index is not None:
            return self._cmp_index

        index: Dict[str, BundledModelBlock] = {}
        cmp_dir = get_spice_cmp_dir()
        if not cmp_dir.exists():
            self._cmp_index = index
            return index

        for model_file in sorted(path for path in cmp_dir.iterdir() if path.is_file()):
            content = self._read_text(model_file)
            if not content:
                continue
            for block in self._iter_model_blocks(content):
                match = re.match(r'^\s*\.model\s+([^\s]+)', block, re.IGNORECASE)
                if not match:
                    continue
                model_name = match.group(1).strip().lower()
                index.setdefault(
                    model_name,
                    BundledModelBlock(
                        name=model_name,
                        source_file=model_file,
                        text=self._sanitize_model_block(block),
                    ),
                )

        self._cmp_index = index
        return index

    def _build_subckt_index(self) -> Dict[str, Path]:
        if self._subckt_index is not None:
            return self._subckt_index

        self._subckt_index = dict(load_bundled_subcircuit_path_index())
        return self._subckt_index

    def _read_text(self, file_path: Path) -> str:
        for encoding in ('utf-8', 'latin1'):
            try:
                return file_path.read_text(encoding=encoding, errors='ignore')
            except Exception:
                continue
        self._logger.warning(f'读取内置模型文件失败，已跳过: {file_path}')
        return ''

    def _iter_model_blocks(self, content: str) -> Iterable[str]:
        current: List[str] = []
        for line in content.splitlines():
            stripped = line.lstrip()
            if re.match(r'^\.model\s+', stripped, re.IGNORECASE):
                if current:
                    yield '\n'.join(current)
                current = [line]
                continue
            if current and stripped.startswith('+'):
                current.append(line)
                continue
            if current:
                yield '\n'.join(current)
                current = []
        if current:
            yield '\n'.join(current)

    # LTspice-only metadata keys per device type that ngspice does not recognise.
    # VDMOS is excluded because ngspice's VDMOS handler accepts mfg/Vds/Ron/Qg.
    _SANITIZE_RULES: List[tuple] = [
        # (model-type pattern,            keys to strip)
        (re.compile(r'\b(?:NPN|PNP)\b',   re.IGNORECASE), ('mfg', 'icrating', 'vceo')),
        (re.compile(r'\bD\b',             re.IGNORECASE), ('mfg', 'type', 'iave', 'vpk')),
        (re.compile(r'\b(?:NJF|PJF)\b',   re.IGNORECASE), ('mfg',)),
    ]

    def _sanitize_model_block(self, block: str) -> str:
        keys_to_strip: List[str] = []
        for pattern, keys in self._SANITIZE_RULES:
            if pattern.search(block):
                keys_to_strip.extend(keys)
                break
        if not keys_to_strip:
            return block

        key_pattern = '|'.join(re.escape(k) for k in keys_to_strip)
        sanitized_lines: List[str] = []
        for line in block.splitlines():
            sanitized = re.sub(
                rf'\s+(?:{key_pattern})\s*=\s*[^)\s]+', '', line, flags=re.IGNORECASE
            )
            sanitized = re.sub(r'\s+\)', ')', sanitized)
            sanitized_lines.append(sanitized.rstrip())
        return '\n'.join(sanitized_lines)

    def _extract_referenced_models(self, netlist: str, available_model_names: Iterable[str]) -> Set[str]:
        available = {name.lower() for name in available_model_names}
        found: Set[str] = set()
        for index, line in enumerate(netlist.splitlines()):
            if index == 0:
                continue
            stripped = line.strip()
            if not stripped or stripped[0] in ('*', ';', '.', '+'):
                continue
            device_type = stripped[0].upper()
            start_index = self._DEVICE_MODEL_START_INDEX.get(device_type)
            if start_index is None:
                continue
            tokens = stripped.split()
            if len(tokens) <= start_index:
                continue
            for token in tokens[start_index:]:
                if '=' in token:
                    continue
                candidate = token.strip().lower()
                if candidate in available:
                    found.add(candidate)
                    break
        return found

    def _extract_defined_models(self, netlist: str) -> Set[str]:
        return {
            match.group(1).strip().lower()
            for match in re.finditer(r'^\s*\.model\s+([^\s]+)', netlist, re.IGNORECASE | re.MULTILINE)
        }

    def _extract_defined_subckts(self, netlist: str) -> Set[str]:
        return {
            match.group(1).strip().lower()
            for match in re.finditer(r'^\s*\.subckt\s+([^\s(]+)', netlist, re.IGNORECASE | re.MULTILINE)
        }

    def _extract_invoked_subckts(self, netlist: str) -> Set[str]:
        found: Set[str] = set()
        for index, line in enumerate(netlist.splitlines()):
            if index == 0:
                continue
            stripped = line.strip()
            if not stripped or stripped[0] in ('*', ';', '.', '+'):
                continue
            if stripped[0].upper() != 'X':
                continue
            tokens = stripped.split()
            if len(tokens) < 3:
                continue
            for token in reversed(tokens[1:]):
                if '=' in token:
                    continue
                found.add(token.strip().lower())
                break
        return found

    def _get_existing_lib_paths(self, netlist: str) -> Set[str]:
        paths: Set[str] = set()
        for line in netlist.splitlines():
            stripped = line.strip()
            lower = stripped.lower()
            if lower.startswith('.lib ') or lower.startswith('.include '):
                parts = stripped.split(None, 1)
                if len(parts) == 2:
                    raw = parts[1].strip().strip('"').strip("'")
                    paths.add(raw.replace('\\', '/').lower())
        return paths

    def _build_spice_path(self, target_path: Path, circuit_dir: Path) -> str:
        return os.path.relpath(target_path, circuit_dir).replace('\\', '/')


__all__ = ['BundledSpiceLibraryInjector']
