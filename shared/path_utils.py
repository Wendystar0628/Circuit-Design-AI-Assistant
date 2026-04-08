import os


def normalize_absolute_path(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


def normalize_identity_path(path: str) -> str:
    return os.path.normcase(normalize_absolute_path(path))


__all__ = ["normalize_absolute_path", "normalize_identity_path"]
