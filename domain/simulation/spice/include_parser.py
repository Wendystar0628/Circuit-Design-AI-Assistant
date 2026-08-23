"""Parser for ngspice file-reference statements."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


_REFERENCE_PREFIX = re.compile(r"^\s*\.(include|inc|incpslt|lib)\b(.*)$", re.IGNORECASE)


@dataclass
class ParsedInclude:
    """A parsed SPICE file reference."""

    line_number: int
    statement_type: str
    raw_path: str
    is_quoted: bool = False
    library_section: str = ""
    resolved_path: Optional[str] = None
    exists: bool = False

    def resolve_path(self, base_dir: Path, project_root: Path) -> None:
        """Resolve the reference relative to the file containing the card."""

        candidate = Path(self.raw_path).expanduser()
        absolute_path = candidate.resolve() if candidate.is_absolute() else (base_dir / candidate).resolve()
        self.exists = absolute_path.is_file()
        self.resolved_path = None
        if not self.exists:
            return
        try:
            self.resolved_path = str(absolute_path.relative_to(project_root))
        except ValueError:
            self.resolved_path = str(absolute_path)


class IncludeParser:
    """Parse ``.include``/``.inc``/``.incpslt`` and file-selecting ``.lib`` cards.

    A one-argument ``.lib section`` inside a library file starts a section; it
    is not a file dependency.  A file reference is only returned for the
    official two-argument form ``.lib filename section``.
    """

    def parse_file(self, file_path: str) -> List[ParsedInclude]:
        try:
            path = Path(file_path)
            if not path.is_file():
                return []
            content = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError, TypeError):
            return []
        return self.parse_content(content)

    def parse_line(self, line: str, line_number: int) -> Optional[ParsedInclude]:
        stripped = str(line or "").strip()
        if not stripped or stripped.startswith(("*", ";", "$", "//")):
            return None
        match = _REFERENCE_PREFIX.match(line)
        if match is None:
            return None

        statement_type = match.group(1).lower()
        path_token, is_quoted, remainder = _parse_first_argument(match.group(2))
        if not path_token:
            return None
        remainder = _strip_comment(remainder).strip()

        library_section = ""
        if statement_type == "lib":
            section_tokens = remainder.split()
            if len(section_tokens) != 1:
                return None
            library_section = section_tokens[0]
        elif remainder:
            # Extra non-comment arguments make .include/.incpslt malformed.
            return None

        return ParsedInclude(
            line_number=int(line_number),
            statement_type="include" if statement_type in {"include", "inc"} else statement_type,
            raw_path=path_token,
            is_quoted=is_quoted,
            library_section=library_section,
        )

    def parse_content(self, content: str) -> List[ParsedInclude]:
        results: List[ParsedInclude] = []
        for line_number, line in enumerate(str(content or "").splitlines(), start=1):
            parsed = self.parse_line(line, line_number)
            if parsed is not None:
                results.append(parsed)
        return results


def _parse_first_argument(text: str) -> Tuple[str, bool, str]:
    remainder = str(text or "").lstrip()
    if not remainder:
        return "", False, ""
    if remainder[0] in {'"', "'"}:
        quote = remainder[0]
        end = remainder.find(quote, 1)
        if end < 0:
            return "", True, ""
        return remainder[1:end], True, remainder[end + 1:]
    match = re.match(r"([^\s;$]+)(.*)$", remainder)
    if match is None:
        return "", False, ""
    return match.group(1), False, match.group(2)


def _strip_comment(text: str) -> str:
    value = str(text or "")
    comment_positions = [position for marker in (";", "$", "//") if (position := value.find(marker)) >= 0]
    return value[:min(comment_positions)] if comment_positions else value


__all__ = ["IncludeParser", "ParsedInclude"]
