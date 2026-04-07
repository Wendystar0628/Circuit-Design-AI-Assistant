# Web Search Tool - Provider-Native Web Search Executor
"""
联网搜索工具

职责：
- 统一封装当前对话模型的原生联网搜索能力
- 复用当前对话 runtime 的 provider / model / API Key
- 产出结构化搜索结果供 Agent 与 UI 使用

设计约束：
- 仅保留大模型厂商原生联网搜索
- 不再支持独立外部搜索提供商
- 当前运行时由 LLMRuntimeConfigManager 解析
"""

import asyncio
from dataclasses import dataclass
from functools import partial
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from infrastructure.utils.json_utils import extract_json_from_text


# ============================================================
# 常量定义
# ============================================================

DEFAULT_MAX_RESULTS = 5
PLACEHOLDER_SOURCE_HOSTS = {
    "example.com",
    "www.example.com",
    "example.org",
    "www.example.org",
    "example.net",
    "www.example.net",
    "localhost",
    "127.0.0.1",
}


# ============================================================
# 数据结构
# ============================================================

@dataclass
class SearchResult:
    """搜索结果项"""
    title: str
    snippet: str
    url: str
    date: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "title": self.title,
            "snippet": self.snippet,
            "url": self.url,
            "date": self.date,
        }


class SearchError(Exception):
    """搜索错误基类"""
    pass


class SearchCapabilityError(SearchError):
    """原生联网搜索能力不可用"""
    pass


class SearchExecutionError(SearchError):
    """原生联网搜索执行失败"""
    pass


@dataclass
class SearchCapability:
    """当前运行时的联网搜索能力快照"""
    provider: str
    model: str
    available: bool
    reason: str = ""



# ============================================================
# 联网搜索工具类
# ============================================================

class WebSearchTool:
    """
    联网搜索工具
    
    统一封装当前对话模型的原生联网搜索能力。
    """
    
    def __init__(self):
        """
        初始化搜索工具
        
        注意：遵循延迟获取原则，不在 __init__ 中获取 ServiceLocator 服务
        """
        self._logger = None
    
    @property
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("web_search_tool")
            except Exception:
                pass
        return self._logger

    def _get_runtime_config_manager(self):
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_LLM_RUNTIME_CONFIG_MANAGER

            return ServiceLocator.get_optional(SVC_LLM_RUNTIME_CONFIG_MANAGER)
        except Exception:
            return None

    def _get_active_llm_client(self):
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_LLM_CLIENT

            return ServiceLocator.get_optional(SVC_LLM_CLIENT)
        except Exception:
            return None
    
    # ============================================================
    # 核心搜索方法
    # ============================================================
    
    def resolve_capability(self) -> SearchCapability:
        runtime_manager = self._get_runtime_config_manager()
        if runtime_manager is None:
            return SearchCapability(
                provider="",
                model="",
                available=False,
                reason="LLM runtime config manager is unavailable.",
            )

        active_config = runtime_manager.resolve_active_config()
        provider = str(active_config.provider or "").strip()
        model = str(active_config.model or "").strip()

        if not provider or not model:
            return SearchCapability(
                provider=provider,
                model=model,
                available=False,
                reason="No active chat provider/model is configured.",
            )

        if not str(active_config.api_key or "").strip():
            return SearchCapability(
                provider=provider,
                model=model,
                available=False,
                reason="The active chat model API key is missing.",
            )

        if self._get_active_llm_client() is None:
            return SearchCapability(
                provider=provider,
                model=model,
                available=False,
                reason="The active chat client has not been initialized.",
            )

        try:
            from shared.model_registry import ModelRegistry

            ModelRegistry.initialize()
            model_config = ModelRegistry.get_model_by_name(provider, model)
            provider_config = ModelRegistry.get_provider(provider)
        except Exception:
            model_config = None
            provider_config = None

        supports_web_search = False
        if model_config is not None:
            supports_web_search = bool(model_config.supports_web_search)
        elif provider_config is not None:
            supports_web_search = bool(provider_config.supports_web_search)

        if not supports_web_search:
            return SearchCapability(
                provider=provider,
                model=model,
                available=False,
                reason=(
                    f"The active chat model '{provider}:{model}' does not support provider-native web search."
                ),
            )

        return SearchCapability(
            provider=provider,
            model=model,
            available=True,
            reason="",
        )

    def get_search_config(self) -> Dict[str, Any]:
        capability = self.resolve_capability()
        return {
            "provider": capability.provider,
            "model": capability.model,
            "available": capability.available,
            "reason": capability.reason,
        }

    async def search_with_current_model(
        self,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> List[SearchResult]:
        if not query or not query.strip():
            return []

        capability = self.resolve_capability()
        if not capability.available:
            raise SearchCapabilityError(capability.reason or "Provider-native web search is unavailable.")

        client = self._get_active_llm_client()
        if client is None:
            raise SearchCapabilityError("The active chat client is unavailable.")

        prompt_messages = self._build_native_search_messages(query.strip(), max_results)

        try:
            response = await asyncio.to_thread(
                partial(
                    client.chat,
                    messages=prompt_messages,
                    model=capability.model,
                    streaming=False,
                    tools=[self._build_native_web_search_tool(max_results)],
                    thinking=False,
                    response_format={"type": "json_object"},
                )
            )
        except Exception as exc:
            raise SearchExecutionError(str(exc)) from exc

        results = self._extract_search_results(response, max_results)
        self._log_info(
            f"Provider-native web search completed: provider={capability.provider}, "
            f"model={capability.model}, result_count={len(results)}"
        )
        return results

    def _extract_search_results(
        self,
        response: Any,
        max_results: int,
    ) -> List[SearchResult]:
        metadata = getattr(response, "metadata", None)
        if isinstance(metadata, dict):
            raw_results = metadata.get("web_search_results")
            parsed = self._parse_provider_metadata_results(raw_results, max_results)
            if parsed:
                return parsed

        return self._parse_native_search_results(getattr(response, "content", ""), max_results)

    def _build_native_web_search_tool(self, max_results: int) -> Dict[str, Any]:
        return {
            "type": "web_search",
            "web_search": {
                "enable": True,
                "search_result": True,
                "count": max(1, int(max_results)),
            },
        }

    def _parse_provider_metadata_results(
        self,
        raw_results: Any,
        max_results: int,
    ) -> List[SearchResult]:
        if not isinstance(raw_results, list):
            return []

        results: List[SearchResult] = []
        for item in raw_results[: max(1, int(max_results))]:
            if not isinstance(item, dict):
                continue

            url = self._normalize_source_url(item.get("link", ""))
            title = str(item.get("title", "") or "").strip()
            snippet = str(item.get("content", "") or item.get("snippet", "") or "").strip()
            date = str(item.get("publish_date", "") or item.get("date", "") or "").strip() or None

            if not title and not snippet and not url:
                continue

            results.append(
                SearchResult(
                    title=title,
                    snippet=snippet,
                    url=url,
                    date=date,
                )
            )

        return results

    def _build_native_search_messages(
        self,
        query: str,
        max_results: int,
    ) -> List[Dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "You are a web search extraction helper. Always use the provider-native web search "
                    "capability available in this request. Return only a JSON object with the shape "
                    '{"summary": string, "results": [{"title": string, "snippet": string, "url": string, "date": string}]}. '
                    "Use absolute URLs. Keep snippets concise. If no useful results are found, return an empty results list."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Search query: {query}\n"
                    f"Maximum results: {max(1, int(max_results))}\n"
                    "Return JSON only."
                ),
            },
        ]

    def _parse_native_search_results(
        self,
        response_text: str,
        max_results: int,
    ) -> List[SearchResult]:
        payload = extract_json_from_text(response_text or "")
        if not isinstance(payload, dict):
            self._log_warning("Provider-native web search returned no parseable JSON payload")
            return []

        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            return []

        results: List[SearchResult] = []
        for item in raw_results[: max(1, int(max_results))]:
            if not isinstance(item, dict):
                continue

            title = str(item.get("title", "") or "").strip()
            snippet = str(item.get("snippet", "") or "").strip()
            url = self._normalize_source_url(item.get("url", ""))
            date = str(item.get("date", "") or "").strip() or None

            if not title and not snippet and not url:
                continue

            results.append(
                SearchResult(
                    title=title,
                    snippet=snippet,
                    url=url,
                    date=date,
                )
            )

        return results

    def _normalize_source_url(self, value: Any) -> str:
        url = str(value or "").strip()
        if not url:
            return ""

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return ""

        hostname = (parsed.netloc or "").lower()
        if hostname in PLACEHOLDER_SOURCE_HOSTS:
            return ""

        return url

    
    # ============================================================
    # 辅助方法
    # ============================================================

    def format_search_results(self, results: List[SearchResult]) -> str:
        """
        格式化搜索结果为 Prompt 注入格式
        
        Args:
            results: 搜索结果列表
            
        Returns:
            格式化后的字符串
        """
        if not results:
            return ""
        
        formatted_lines = []
        for i, result in enumerate(results, 1):
            line = f"[webpage {i}] 标题: {result.title} | 摘要: {result.snippet} | URL: {result.url}"
            if result.date:
                line += f" | 日期: {result.date}"
            formatted_lines.append(line)
        
        return "\n".join(formatted_lines)
    
    # ============================================================
    # 日志辅助方法
    # ============================================================
    
    def _log_info(self, message: str) -> None:
        """记录信息日志"""
        if self.logger:
            self.logger.info(message)
    
    def _log_warning(self, message: str) -> None:
        """记录警告日志"""
        if self.logger:
            self.logger.warning(message)
    
    def _log_error(self, message: str) -> None:
        """记录错误日志"""
        if self.logger:
            self.logger.error(message)


# ============================================================
# 便捷函数
# ============================================================

# 全局单例实例
_web_search_tool: Optional[WebSearchTool] = None


def get_web_search_tool() -> WebSearchTool:
    """
    获取 WebSearchTool 单例实例
    
    Returns:
        WebSearchTool 实例
    """
    global _web_search_tool
    if _web_search_tool is None:
        _web_search_tool = WebSearchTool()
    return _web_search_tool


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "DEFAULT_MAX_RESULTS",
    # 数据结构
    "SearchResult",
    "SearchError",
    "SearchCapability",
    "SearchCapabilityError",
    "SearchExecutionError",
    # 类
    "WebSearchTool",
    # 便捷函数
    "get_web_search_tool",
]
