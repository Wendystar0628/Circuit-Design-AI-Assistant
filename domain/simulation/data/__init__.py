"""Simulation data-processing package.

The package boundary is intentionally side-effect free. Import concrete
services and helpers from their defining modules so loading a data model never
instantiates unrelated services or creates circular dependencies.
"""

__all__: list[str] = []
