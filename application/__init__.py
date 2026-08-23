"""Application-layer package.

The package initializer is intentionally side-effect free. Import concrete
modules such as ``application.project_service`` or ``application.runtime``
instead of relying on a barrel of re-exports.

Keeping this file light is important: importing an application service must
not configure ngspice, mutate process environment variables, start worker
threads, or eagerly construct runtime services.
"""

__all__: list[str] = []
