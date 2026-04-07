from typing import Any, Dict, List, Optional

from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from infrastructure.utils.web_search_tool import get_web_search_tool


class WebSearchTool(BaseTool):
    @property
    def name(self) -> str:
        return "web_search"

    @property
    def label(self) -> str:
        return "Web Search"

    @property
    def description(self) -> str:
        return (
            "Search the web for recent or external information and return structured results "
            "including titles, snippets, and source URLs. Use this when the answer depends "
            "on current facts, public documentation, or websites outside the project files."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query text describing what to look up on the web.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of search results to retrieve (default: 5).",
                },
            },
            "required": ["query"],
        }

    @property
    def prompt_snippet(self) -> Optional[str]:
        return "Search the public web for recent or external information with source links"

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            "Use web_search when the task needs current information, vendor documentation, public references, or facts not guaranteed to exist in the project.",
            "Prefer concise, targeted queries and cite returned sources in the final answer when relevant.",
        ]

    async def execute(
        self,
        tool_call_id: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        query = str(params.get("query", "") or "").strip()
        max_results_raw = params.get("max_results", 5)

        if not query:
            return ToolResult(
                content="Error: 'query' parameter is required and cannot be empty.",
                is_error=True,
            )

        try:
            max_results = max(1, int(max_results_raw))
        except (TypeError, ValueError):
            max_results = 5

        web_search = get_web_search_tool()
        search_config = web_search.get_search_config()
        provider = str(search_config.get("provider", "") or "").strip()
        model = str(search_config.get("model", "") or "").strip()

        if not search_config.get("available", False):
            return ToolResult(
                content=(
                    "Provider-native web search is unavailable for the current chat runtime. "
                    + str(search_config.get("reason", "") or "")
                ),
                is_error=True,
                details={
                    "query": query,
                    "provider": provider,
                    "model": model,
                    "reason": str(search_config.get("reason", "") or ""),
                    "results": [],
                    "result_count": 0,
                },
            )

        try:
            results = await web_search.search_with_current_model(query, max_results=max_results)
        except Exception as exc:
            return ToolResult(
                content=f"Web search failed: {exc}",
                is_error=True,
                details={
                    "query": query,
                    "provider": provider,
                    "model": model,
                    "results": [],
                    "result_count": 0,
                },
            )

        results_payload = [result.to_dict() for result in results]

        if not results_payload:
            return ToolResult(
                content=f"No web results found for query: \"{query}\"",
                details={
                    "query": query,
                    "provider": provider,
                    "model": model,
                    "results": [],
                    "result_count": 0,
                },
            )

        formatted = web_search.format_search_results(results)
        return ToolResult(
            content=(
                f"Web search provider: {provider}\n"
                f"Web search model: {model}\n"
                f"Results: {len(results_payload)}\n\n"
                f"{formatted}"
            ),
            details={
                "query": query,
                "provider": provider,
                "model": model,
                "results": results_payload,
                "result_count": len(results_payload),
            },
        )
