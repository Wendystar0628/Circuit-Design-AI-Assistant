from pathlib import Path
from typing import Union

SPICE_EXTENSIONS = {
    ".cir",
    ".sp",
    ".spice",
    ".ckt",
    ".lib",
    ".sub",
    ".inc",
    ".mod",
    ".net",
}
SIMULATABLE_CIRCUIT_EXTENSIONS = {".cir", ".sp", ".spice", ".net", ".ckt"}
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
WORD_EXTENSIONS = {".docx"}
PDF_EXTENSIONS = {".pdf"}
TABULAR_EXTENSIONS = {".csv", ".tsv"}
NETLIST_EXTENSIONS = {".net"}
JSON_EXTENSIONS = {".json"}
PYTHON_EXTENSIONS = {".py"}
JAVASCRIPT_EXTENSIONS = {".js", ".jsx"}
TYPESCRIPT_EXTENSIONS = {".ts", ".tsx"}
HTML_EXTENSIONS = {".html"}
CSS_EXTENSIONS = {".css"}
XML_EXTENSIONS = {".xml"}
YAML_EXTENSIONS = {".yaml", ".yml"}
TOML_EXTENSIONS = {".toml"}
SETTINGS_EXTENSIONS = {".ini", ".cfg"}
CONFIG_EXTENSIONS = YAML_EXTENSIONS | TOML_EXTENSIONS | SETTINGS_EXTENSIONS
TEXT_EXTENSIONS = {".txt"}
LOG_EXTENSIONS = {".log"}
DIFF_EXTENSIONS = {".diff", ".patch"}
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
    ".log",
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


def is_spice_extension(path_or_ext: PathLike) -> bool:
    return get_extension(path_or_ext) in SPICE_EXTENSIONS


def is_simulatable_circuit_extension(path_or_ext: PathLike) -> bool:
    return get_extension(path_or_ext) in SIMULATABLE_CIRCUIT_EXTENSIONS


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
        ".ckt": "plaintext",
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


def file_type_label_key(path_or_ext: PathLike) -> str:
    extension = get_extension(path_or_ext)
    keys = {
        ".cir": "file_type.spice",
        ".sp": "file_type.spice",
        ".spice": "file_type.spice",
        ".ckt": "file_type.spice",
        ".lib": "file_type.spice_library",
        ".sub": "file_type.spice_subcircuit",
        ".inc": "file_type.spice_include",
        ".mod": "file_type.spice_model",
        ".net": "file_type.netlist",
        ".json": "file_type.json",
        ".txt": "file_type.plain_text",
        ".py": "file_type.python",
        ".md": "file_type.markdown",
        ".markdown": "file_type.markdown",
        ".csv": "file_type.csv_table",
        ".tsv": "file_type.tsv_table",
        ".docx": "file_type.word_document",
        ".pdf": "file_type.pdf_document",
        ".png": "file_type.png_image",
        ".jpg": "file_type.jpeg_image",
        ".jpeg": "file_type.jpeg_image",
        ".gif": "file_type.gif_image",
        ".bmp": "file_type.bitmap_image",
        ".webp": "file_type.webp_image",
        ".svg": "file_type.svg_image",
        ".ico": "file_type.icon_image",
        ".yaml": "file_type.yaml",
        ".yml": "file_type.yaml",
        ".toml": "file_type.toml",
        ".ini": "file_type.ini",
        ".cfg": "file_type.config",
        ".xml": "file_type.xml",
        ".html": "file_type.html",
        ".css": "file_type.css",
        ".js": "file_type.javascript",
        ".ts": "file_type.typescript",
        ".tsx": "file_type.typescript",
        ".jsx": "file_type.javascript",
        ".diff": "file_type.diff",
        ".patch": "file_type.patch",
        ".log": "file_type.log",
    }
    return keys.get(extension, "file_type.file")


def file_type_label(path_or_ext: PathLike) -> str:
    extension = get_extension(path_or_ext)
    labels = {
        ".cir": "SPICE",
        ".sp": "SPICE",
        ".spice": "SPICE",
        ".ckt": "SPICE",
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


def workspace_entry_icon_name(path_or_ext: PathLike, is_directory: bool = False) -> str:
    if is_directory:
        return "folder"
    extension = get_extension(path_or_ext)
    if extension in NETLIST_EXTENSIONS:
        return "netlist"
    if extension in SPICE_EXTENSIONS:
        return "circuit"
    if extension in PYTHON_EXTENSIONS:
        return "python"
    if extension in JSON_EXTENSIONS:
        return "json"
    if extension in MARKDOWN_EXTENSIONS:
        return "markdown"
    if extension in JAVASCRIPT_EXTENSIONS:
        return "javascript"
    if extension in TYPESCRIPT_EXTENSIONS:
        return "typescript"
    if extension in HTML_EXTENSIONS:
        return "html"
    if extension in CSS_EXTENSIONS:
        return "css"
    if extension in XML_EXTENSIONS:
        return "xml"
    if extension in YAML_EXTENSIONS:
        return "yaml"
    if extension in TOML_EXTENSIONS:
        return "toml"
    if extension in SETTINGS_EXTENSIONS:
        return "settings"
    if extension in WORD_EXTENSIONS:
        return "word"
    if extension in PDF_EXTENSIONS:
        return "pdf"
    if extension in TABULAR_EXTENSIONS:
        return "table"
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in DIFF_EXTENSIONS:
        return "diff"
    if extension in LOG_EXTENSIONS:
        return "log"
    if extension in TEXT_EXTENSIONS:
        return "text"
    return "file"


def workspace_entry_open_icon_name(path_or_ext: PathLike, is_directory: bool = False) -> str:
    if is_directory:
        return "folder-open"
    return workspace_entry_icon_name(path_or_ext, is_directory=False)


__all__ = [
    "SPICE_EXTENSIONS",
    "SIMULATABLE_CIRCUIT_EXTENSIONS",
    "MARKDOWN_EXTENSIONS",
    "WORD_EXTENSIONS",
    "PDF_EXTENSIONS",
    "TABULAR_EXTENSIONS",
    "NETLIST_EXTENSIONS",
    "JSON_EXTENSIONS",
    "PYTHON_EXTENSIONS",
    "JAVASCRIPT_EXTENSIONS",
    "TYPESCRIPT_EXTENSIONS",
    "HTML_EXTENSIONS",
    "CSS_EXTENSIONS",
    "XML_EXTENSIONS",
    "YAML_EXTENSIONS",
    "TOML_EXTENSIONS",
    "SETTINGS_EXTENSIONS",
    "CONFIG_EXTENSIONS",
    "TEXT_EXTENSIONS",
    "LOG_EXTENSIONS",
    "DIFF_EXTENSIONS",
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
    "is_spice_extension",
    "is_simulatable_circuit_extension",
    "is_word_extension",
    "is_pdf_extension",
    "is_tabular_extension",
    "is_document_preview_extension",
    "language_for_extension",
    "file_type_label_key",
    "file_type_label",
    "workspace_entry_icon_name",
    "workspace_entry_open_icon_name",
]
