"""LLM and conversation domain package.

The package boundary is intentionally side-effect free.  Runtime code imports
the concrete module that owns a capability, for example
``domain.llm.context_manager`` or ``domain.llm.context_compression_service``.
Keeping the initializer empty avoids constructing an accidental second public
API and prevents a utility import from eagerly loading every provider, Agent
tool, and session service.
"""

__all__: list[str] = []
