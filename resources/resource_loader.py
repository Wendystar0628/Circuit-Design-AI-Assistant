"""Pure filesystem locations for bundled application resources."""

from pathlib import Path


def get_resources_dir() -> Path:
    """Return the application resource directory."""
    return Path(__file__).parent


def get_spice_models_dir() -> Path:
    """Return the bundled SPICE model root."""
    return get_resources_dir() / "models"


def get_spice_cmp_dir() -> Path:
    """Return the directory containing bundled ``.model`` definitions."""
    return get_spice_models_dir() / "cmp"


def get_spice_sub_dir() -> Path:
    """Return the directory containing bundled subcircuit definitions."""
    return get_spice_models_dir() / "sub"


def get_spice_sym_dir() -> Path:
    """Return the directory containing bundled LTspice symbols."""
    return get_spice_models_dir() / "sym"


__all__ = [
    "get_resources_dir",
    "get_spice_cmp_dir",
    "get_spice_models_dir",
    "get_spice_sub_dir",
    "get_spice_sym_dir",
]
