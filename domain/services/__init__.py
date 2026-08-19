"""Domain-service package boundary.

Import concrete modules explicitly, for example
``from domain.services import context_service``. Eagerly importing every
service here used to construct a misleading aggregate API and pulled snapshot,
simulation, context, and recovery dependencies into unrelated imports.
"""

__all__: list[str] = []
