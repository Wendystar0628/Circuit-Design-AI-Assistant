"""Shared-kernel package with a side-effect-free initializer.

Consumers should import the concrete module that owns a contract, such as
``shared.event_bus`` or ``shared.service_locator``. Package import alone does
not initialize Qt, registries, event loops, or runtime services.
"""

__all__: list[str] = []
