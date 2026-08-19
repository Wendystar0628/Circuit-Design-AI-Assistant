"""Parser for SPICE ``.include`` and ``.lib`` statements."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class ParsedInclude:
    """A parsed SPICE file reference."""

    line_number: int
    statement_type: str
    raw_path: str
    is_quoted: bool = False
    resolved_path: Optional[str] = None
    exists: bool = False

    def resolve_path(self, base_dir: Path, project_root: Path) -> None:
        """Resolve the reference relative to its source file."""
        clean_path = self.raw_path.strip('"').strip("'")
        absolute_path = (base_dir / clean_path).resolve()
        self.exists = absolute_path.exists()
        if not self.exists:
            return
        try:
            self.resolved_path = str(absolute_path.relative_to(project_root))
        except ValueError:
            self.resolved_path = str(absolute_path)


class IncludeParser:
    """Parse SPICE file-reference statements without dependency-scan state."""

    INCLUDE_PATTERN = re.compile(
        r'^\s*\.include\s+["\']?([^"\']+)["\']?\s*$',
        re.IGNORECASE,
    )
    LIB_PATTERN = re.compile(
        r'^\s*\.lib\s+["\']?([^\s"\']+)["\']?(?:\s+\S+)?\s*$',
        re.IGNORECASE,
    )

    def parse_file(self, file_path: str) -> List[ParsedInclude]:
        """Parse references from a UTF-8-compatible SPICE file."""
        try:
            path = Path(file_path)
            if not path.is_file():
                return []
            content = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError, TypeError):
            return []
        return self.parse_content(content)

    def parse_line(self, line: str, line_number: int) -> Optional[ParsedInclude]:
        """Parse one source line, returning ``None`` for non-reference lines."""
        stripped = line.strip()
        if stripped.startswith("*") or stripped.startswith(";"):
            return None

        match = self.INCLUDE_PATTERN.match(stripped)
        if match:
            return ParsedInclude(
                line_number=line_number,
                statement_type="include",
                raw_path=match.group(1).strip(),
                is_quoted='"' in line or "'" in line,
            )

        match = self.LIB_PATTERN.match(stripped)
        if match:
            return ParsedInclude(
                line_number=line_number,
                statement_type="lib",
                raw_path=match.group(1).strip(),
                is_quoted='"' in line or "'" in line,
            )
        return None

    def parse_content(self, content: str) -> List[ParsedInclude]:
        """Parse all reference statements from source text."""
        results: List[ParsedInclude] = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            parsed = self.parse_line(line, line_number)
            if parsed is not None:
                results.append(parsed)
        return results


__all__ = ["IncludeParser", "ParsedInclude"]
