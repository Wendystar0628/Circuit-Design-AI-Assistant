from pathlib import Path
from typing import Union

SPICE_EXTENSIONS = {
    ".cir",
    ".sp",
    ".spice",
    ".lib",
    ".sub",
    ".inc",
    ".mod",
    ".net",
}
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
WORD_EXTENSIONS = {".docx"}
PDF_EXTENSIONS = {".pdf"}
TABULAR_EXTENSIONS = {".csv", ".tsv"}
IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".webp",
    ".svg",
    ".ico",
}
EDITABLE_TEXT_EXTENSIONS = SPICE_EXTENSIONS | {
    ".json",
    ".txt",
    ".py",
    ".md",
    ".markdown",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".xml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".diff",
    ".patch",
    ".log",
}
DOCUMENT_PREVIEW_EXTENSIONS = WORD_EXTENSIONS | PDF_EXTENSIONS | TABULAR_EXTENSIONS
WORKSPACE_HIDDEN_DIRECTORIES = {
    ".circuit_ai",
    "__pycache__",
    ".git",
    ".vscode",
    ".idea",
    "node_modules",
    ".venv",
    "venv",
}
WORKSPACE_HIDDEN_FILE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}


PathLike = Union[str, Path]


def get_extension(path_or_ext: PathLike) -> str:
    value = str(path_or_ext or "")
    if not value:
        return ""
    if value.startswith(".") and "/" not in value and "\\" not in value:
        return value.lower()
    return Path(value).suffix.lower()


def is_hidden_workspace_entry(name: str, is_directory: bool) -> bool:
    entry_name = str(name or "")
    if not entry_name:
        return False
    if is_directory:
        return entry_name in WORKSPACE_HIDDEN_DIRECTORIES
    return entry_name in WORKSPACE_HIDDEN_FILE_NAMES


def is_editable_text_extension(path_or_ext: PathLike) -> bool:
    return get_extension(path_or_ext) in EDITABLE_TEXT_EXTENSIONS


def is_image_extension(path_or_ext: PathLike) -> bool:
    return get_extension(path_or_ext) in IMAGE_EXTENSIONS


def is_markdown_extension(path_or_ext: PathLike) -> bool:
    return get_extension(path_or_ext) in MARKDOWN_EXTENSIONS


def is_word_extension(path_or_ext: PathLike) -> bool:
    return get_extension(path_or_ext) in WORD_EXTENSIONS


def is_pdf_extension(path_or_ext: PathLike) -> bool:
    return get_extension(path_or_ext) in PDF_EXTENSIONS


def is_tabular_extension(path_or_ext: PathLike) -> bool:
    return get_extension(path_or_ext) in TABULAR_EXTENSIONS


def is_document_preview_extension(path_or_ext: PathLike) -> bool:
    return get_extension(path_or_ext) in DOCUMENT_PREVIEW_EXTENSIONS


def language_for_extension(path_or_ext: PathLike) -> str:
    extension = get_extension(path_or_ext)
    language_map = {
        ".py": "python",
        ".json": "json",
        ".md": "markdown",
        ".markdown": "markdown",
        ".txt": "plaintext",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "ini",
        ".ini": "ini",
        ".cfg": "ini",
        ".xml": "xml",
        ".html": "html",
        ".css": "css",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".csv": "plaintext",
        ".tsv": "plaintext",
        ".cir": "plaintext",
        ".sp": "plaintext",
        ".spice": "plaintext",
        ".lib": "plaintext",
        ".sub": "plaintext",
        ".inc": "plaintext",
        ".mod": "plaintext",
        ".net": "plaintext",
        ".diff": "diff",
        ".patch": "diff",
        ".log": "plaintext",
    }
    return language_map.get(extension, "plaintext")


def file_type_label(path_or_ext: PathLike) -> str:
    extension = get_extension(path_or_ext)
    labels = {
        ".cir": "SPICE",
        ".sp": "SPICE",
        ".spice": "SPICE",
        ".lib": "SPICE Library",
        ".sub": "SPICE Subcircuit",
        ".inc": "SPICE Include",
        ".mod": "SPICE Model",
        ".net": "Netlist",
        ".json": "JSON",
        ".txt": "Plain Text",
        ".py": "Python",
        ".md": "Markdown",
        ".markdown": "Markdown",
        ".csv": "CSV Table",
        ".tsv": "TSV Table",
        ".docx": "Word Document",
        ".pdf": "PDF Document",
        ".png": "PNG Image",
        ".jpg": "JPEG Image",
        ".jpeg": "JPEG Image",
        ".gif": "GIF Image",
        ".bmp": "Bitmap Image",
        ".webp": "WebP Image",
        ".svg": "SVG Image",
        ".ico": "Icon Image",
        ".yaml": "YAML",
        ".yml": "YAML",
        ".toml": "TOML",
        ".ini": "INI",
        ".cfg": "Config",
        ".xml": "XML",
        ".html": "HTML",
        ".css": "CSS",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".jsx": "JavaScript",
        ".diff": "Diff",
        ".patch": "Patch",
        ".log": "Log",
    }
    return labels.get(extension, "File")


__all__ = [
    "SPICE_EXTENSIONS",
    "MARKDOWN_EXTENSIONS",
    "WORD_EXTENSIONS",
    "PDF_EXTENSIONS",
    "TABULAR_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "EDITABLE_TEXT_EXTENSIONS",
    "DOCUMENT_PREVIEW_EXTENSIONS",
    "WORKSPACE_HIDDEN_DIRECTORIES",
    "WORKSPACE_HIDDEN_FILE_NAMES",
    "get_extension",
    "is_hidden_workspace_entry",
    "is_editable_text_extension",
    "is_image_extension",
    "is_markdown_extension",
    "is_word_extension",
    "is_pdf_extension",
    "is_tabular_extension",
    "is_document_preview_extension",
    "language_for_extension",
    "file_type_label",
]
