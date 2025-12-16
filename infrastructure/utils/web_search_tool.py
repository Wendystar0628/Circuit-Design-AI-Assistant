# Web Search Tool - Unified Web Search API Wrapper
"""
联网搜索工具 - 统一封装多个搜索 API

职责：
- 统一封装厂商专属搜索和通用搜索 API
- 为 LLM 提供联网搜索能力
- 格式化搜索结果供 Prompt 注入

搜索类型：
- 厂商专属搜索：与特定 LLM 厂商深度集成（如智谱内置搜索）
- 通用搜索：独立于 LLM 厂商（Google/Bing）

互斥约束：
- 厂商专属搜索与通用搜索只能启用其一
- 由 ConfigManager 和 UI 层保证互斥

被调用方：prompt_builder.py（构建 Prompt 时注入搜索结果）
"""

from typing import Any, Dict, List, Optional, Literal
from dataclasses import dataclass
from enum import Enum

import httpx

from infrastructure.config.settings import (
    LLM_PROVIDER_ZHIPU,
    PROVIDER_DEFAULTS,
    WEB_SEARCH_GOOGLE,
    WEB_SEARCH_BING,
)


# ============================================================
# 常量定义
# ============================================================

# 搜索类型
SEARCH_TYPE_PROVIDER = "provider"  # 厂商专属搜索
SEARCH_TYPE_GENERAL = "general"    # 通用搜索

# 默认配置
DEFAULT_MAX_RESULTS = 5
DEFAULT_TIMEOUT = 10  # 搜索请求超时秒数

# API 端点
GOOGLE_SEARCH_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
BING_SEARCH_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"


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


class SearchConfigError(SearchError):
    """搜索配置错误"""
    pass


class SearchAPIError(SearchError):
    """搜索 API 调用错误"""
    pass



# ============================================================
# 联网搜索工具类
# ============================================================

class WebSearchTool:
    """
    联网搜索工具
    
    统一封装厂商专属搜索和通用搜索 API。
    """
    
    def __init__(self):
        """
        初始化搜索工具
        
        注意：遵循延迟获取原则，不在 __init__ 中获取 ServiceLocator 服务
        """
        self._config_manager = None
        self._credential_manager = None
        self._logger = None
        self._http_client: Optional[httpx.Client] = None
    
    # ============================================================
    # 延迟获取服务
    # ============================================================
    
    @property
    def config_manager(self):
        """延迟获取 ConfigManager"""
        if self._config_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONFIG_MANAGER
                self._config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
            except Exception:
                pass
        return self._config_manager
    
    @property
    def credential_manager(self):
        """延迟获取 CredentialManager"""
        if self._credential_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CREDENTIAL_MANAGER
                self._credential_manager = ServiceLocator.get_optional(SVC_CREDENTIAL_MANAGER)
            except Exception:
                pass
        return self._credential_manager
    
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
    
    @property
    def http_client(self) -> httpx.Client:
        """获取 HTTP 客户端（延迟创建）"""
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=DEFAULT_TIMEOUT)
        return self._http_client
    
    def close(self):
        """关闭资源"""
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None
    
    # ============================================================
    # 核心搜索方法
    # ============================================================
    
    def search(
        self,
        query: str,
        search_type: str = SEARCH_TYPE_GENERAL,
        provider: Optional[str] = None,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> List[SearchResult]:
        """
        执行搜索
        
        Args:
            query: 搜索查询
            search_type: 搜索类型（provider/general）
            provider: 搜索提供商标识（厂商专属搜索时为 LLM 厂商，通用搜索时为 google/bing）
            max_results: 最大返回结果数
            
        Returns:
            搜索结果列表
            
        Raises:
            SearchConfigError: 配置错误
            SearchAPIError: API 调用错误
        """
        if not query or not query.strip():
            return []
        
        query = query.strip()
        
        try:
            if search_type == SEARCH_TYPE_PROVIDER:
                return self._search_provider(query, provider, max_results)
            elif search_type == SEARCH_TYPE_GENERAL:
                return self._search_general(query, provider, max_results)
            else:
                self._log_warning(f"未知的搜索类型: {search_type}")
                return []
        except SearchError:
            raise
        except Exception as e:
            self._log_error(f"搜索执行失败: {e}")
            return []
    
    def _search_provider(
        self,
        query: str,
        llm_provider: Optional[str],
        max_results: int,
    ) -> List[SearchResult]:
        """
        执行厂商专属搜索
        
        Args:
            query: 搜索查询
            llm_provider: LLM 厂商标识
            max_results: 最大返回结果数
            
        Returns:
            搜索结果列表
        """
        if not llm_provider:
            # 从配置获取当前 LLM 厂商
            if self.config_manager:
                from infrastructure.config.settings import CONFIG_LLM_PROVIDER
                llm_provider = self.config_manager.get(CONFIG_LLM_PROVIDER, "")
        
        if not llm_provider:
            self._log_warning("未配置 LLM 厂商，无法执行厂商专属搜索")
            return []
        
        # 检查厂商是否支持专属搜索
        if not self.is_provider_search_available(llm_provider):
            self._log_warning(f"厂商 {llm_provider} 不支持专属联网搜索")
            return []
        
        # 根据厂商调用对应的搜索实现
        if llm_provider == LLM_PROVIDER_ZHIPU:
            return self._search_zhipu(query, max_results)
        else:
            self._log_warning(f"厂商 {llm_provider} 的专属搜索尚未实现")
            return []
    
    def _search_general(
        self,
        query: str,
        search_provider: Optional[str],
        max_results: int,
    ) -> List[SearchResult]:
        """
        执行通用搜索
        
        Args:
            query: 搜索查询
            search_provider: 搜索提供商（google/bing）
            max_results: 最大返回结果数
            
        Returns:
            搜索结果列表
        """
        if not search_provider:
            # 从配置获取当前搜索提供商
            if self.config_manager:
                from infrastructure.config.settings import CONFIG_GENERAL_WEB_SEARCH_PROVIDER
                search_provider = self.config_manager.get(CONFIG_GENERAL_WEB_SEARCH_PROVIDER, WEB_SEARCH_GOOGLE)
        
        if not search_provider:
            search_provider = WEB_SEARCH_GOOGLE
        
        # 获取凭证
        credential = None
        if self.credential_manager:
            credential = self.credential_manager.get_search_credential(search_provider)
        
        if not credential or not credential.get("api_key"):
            self._log_warning(f"未配置 {search_provider} 搜索凭证")
            return []
        
        # 根据提供商调用对应的搜索实现
        if search_provider == WEB_SEARCH_GOOGLE:
            api_key = credential.get("api_key", "")
            cx = credential.get("cx", "")
            if not cx:
                self._log_warning("Google 搜索缺少搜索引擎 ID (cx)")
                return []
            return self._search_google(query, api_key, cx, max_results)
        elif search_provider == WEB_SEARCH_BING:
            api_key = credential.get("api_key", "")
            return self._search_bing(query, api_key, max_results)
        else:
            self._log_warning(f"未知的搜索提供商: {search_provider}")
            return []

    
    # ============================================================
    # 厂商专属搜索实现
    # ============================================================
    
    def _search_zhipu(self, query: str, max_results: int) -> List[SearchResult]:
        """
        智谱联网搜索实现
        
        说明：智谱 GLM 模型内置的联网搜索工具，通过 LLM 请求中的 tools 参数启用。
        此方法返回空列表，实际搜索由 LLM 请求时的 web_search 工具完成。
        
        Args:
            query: 搜索查询
            max_results: 最大返回结果数
            
        Returns:
            空列表（智谱搜索由 LLM 工具调用完成）
        """
        # 智谱的联网搜索是通过 LLM 请求中的 tools 参数启用的
        # 不需要单独调用搜索 API，搜索结果会包含在 LLM 响应中
        # 此方法仅作为占位，实际逻辑在 zhipu_request_builder.py 中处理
        self._log_info("智谱联网搜索通过 LLM 工具调用实现，无需单独搜索")
        return []
    
    # ============================================================
    # 通用搜索实现
    # ============================================================
    
    def _search_google(
        self,
        query: str,
        api_key: str,
        cx: str,
        max_results: int,
    ) -> List[SearchResult]:
        """
        Google Custom Search API 搜索实现
        
        Args:
            query: 搜索查询
            api_key: Google API Key
            cx: 搜索引擎 ID
            max_results: 最大返回结果数
            
        Returns:
            搜索结果列表
        """
        try:
            params = {
                "key": api_key,
                "cx": cx,
                "q": query,
                "num": min(max_results, 10),  # Google API 最多返回 10 条
            }
            
            response = self.http_client.get(GOOGLE_SEARCH_ENDPOINT, params=params)
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            for item in data.get("items", []):
                result = SearchResult(
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    url=item.get("link", ""),
                    date=item.get("pagemap", {}).get("metatags", [{}])[0].get("article:published_time"),
                )
                results.append(result)
            
            self._log_info(f"Google 搜索完成，返回 {len(results)} 条结果")
            return results
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                self._log_warning("Google API Key 无效或已达到配额限制")
            elif e.response.status_code == 400:
                self._log_warning("Google 搜索请求参数错误")
            else:
                self._log_error(f"Google 搜索 HTTP 错误: {e.response.status_code}")
            return []
        except httpx.TimeoutException:
            self._log_warning("Google 搜索请求超时")
            return []
        except Exception as e:
            self._log_error(f"Google 搜索失败: {e}")
            return []
    
    def _search_bing(
        self,
        query: str,
        api_key: str,
        max_results: int,
    ) -> List[SearchResult]:
        """
        Bing Web Search API 搜索实现
        
        Args:
            query: 搜索查询
            api_key: Bing API Key
            max_results: 最大返回结果数
            
        Returns:
            搜索结果列表
        """
        try:
            headers = {
                "Ocp-Apim-Subscription-Key": api_key,
            }
            params = {
                "q": query,
                "count": min(max_results, 50),  # Bing API 最多返回 50 条
                "mkt": "en-US",  # 市场设置
            }
            
            response = self.http_client.get(
                BING_SEARCH_ENDPOINT,
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            for item in data.get("webPages", {}).get("value", []):
                result = SearchResult(
                    title=item.get("name", ""),
                    snippet=item.get("snippet", ""),
                    url=item.get("url", ""),
                    date=item.get("dateLastCrawled"),
                )
                results.append(result)
            
            self._log_info(f"Bing 搜索完成，返回 {len(results)} 条结果")
            return results
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                self._log_warning("Bing API Key 无效")
            elif e.response.status_code == 403:
                self._log_warning("Bing API 已达到配额限制")
            else:
                self._log_error(f"Bing 搜索 HTTP 错误: {e.response.status_code}")
            return []
        except httpx.TimeoutException:
            self._log_warning("Bing 搜索请求超时")
            return []
        except Exception as e:
            self._log_error(f"Bing 搜索失败: {e}")
            return []

    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def is_provider_search_available(self, llm_provider: str) -> bool:
        """
        检查厂商专属搜索是否可用
        
        Args:
            llm_provider: LLM 厂商标识
            
        Returns:
            是否支持厂商专属搜索
        """
        defaults = PROVIDER_DEFAULTS.get(llm_provider, {})
        implemented = defaults.get("implemented", False)
        supports_web_search = defaults.get("supports_web_search", False)
        return implemented and supports_web_search
    
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
    
    def get_search_config(self) -> Dict[str, Any]:
        """
        获取当前搜索配置
        
        Returns:
            搜索配置字典
        """
        config = {
            "provider_search_enabled": False,
            "general_search_enabled": False,
            "llm_provider": "",
            "search_provider": "",
        }
        
        if self.config_manager:
            from infrastructure.config.settings import (
                CONFIG_ENABLE_PROVIDER_WEB_SEARCH,
                CONFIG_ENABLE_GENERAL_WEB_SEARCH,
                CONFIG_LLM_PROVIDER,
                CONFIG_GENERAL_WEB_SEARCH_PROVIDER,
            )
            config["provider_search_enabled"] = self.config_manager.get(
                CONFIG_ENABLE_PROVIDER_WEB_SEARCH, False
            )
            config["general_search_enabled"] = self.config_manager.get(
                CONFIG_ENABLE_GENERAL_WEB_SEARCH, False
            )
            config["llm_provider"] = self.config_manager.get(CONFIG_LLM_PROVIDER, "")
            config["search_provider"] = self.config_manager.get(
                CONFIG_GENERAL_WEB_SEARCH_PROVIDER, WEB_SEARCH_GOOGLE
            )
        
        return config
    
    def search_with_config(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> List[SearchResult]:
        """
        根据当前配置执行搜索
        
        自动判断使用厂商专属搜索还是通用搜索。
        
        Args:
            query: 搜索查询
            max_results: 最大返回结果数
            
        Returns:
            搜索结果列表
        """
        config = self.get_search_config()
        
        # 互斥检查：优先使用厂商专属搜索
        if config["provider_search_enabled"]:
            return self.search(
                query=query,
                search_type=SEARCH_TYPE_PROVIDER,
                provider=config["llm_provider"],
                max_results=max_results,
            )
        elif config["general_search_enabled"]:
            return self.search(
                query=query,
                search_type=SEARCH_TYPE_GENERAL,
                provider=config["search_provider"],
                max_results=max_results,
            )
        else:
            # 未启用任何搜索
            return []
    
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


def search(
    query: str,
    search_type: str = SEARCH_TYPE_GENERAL,
    provider: Optional[str] = None,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> List[SearchResult]:
    """
    执行搜索（便捷函数）
    
    Args:
        query: 搜索查询
        search_type: 搜索类型（provider/general）
        provider: 搜索提供商标识
        max_results: 最大返回结果数
        
    Returns:
        搜索结果列表
    """
    return get_web_search_tool().search(query, search_type, provider, max_results)


def search_with_config(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> List[SearchResult]:
    """
    根据当前配置执行搜索（便捷函数）
    
    Args:
        query: 搜索查询
        max_results: 最大返回结果数
        
    Returns:
        搜索结果列表
    """
    return get_web_search_tool().search_with_config(query, max_results)


def format_search_results(results: List[SearchResult]) -> str:
    """
    格式化搜索结果（便捷函数）
    
    Args:
        results: 搜索结果列表
        
    Returns:
        格式化后的字符串
    """
    return get_web_search_tool().format_search_results(results)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 常量
    "SEARCH_TYPE_PROVIDER",
    "SEARCH_TYPE_GENERAL",
    "DEFAULT_MAX_RESULTS",
    # 数据结构
    "SearchResult",
    "SearchError",
    "SearchConfigError",
    "SearchAPIError",
    # 类
    "WebSearchTool",
    # 便捷函数
    "get_web_search_tool",
    "search",
    "search_with_config",
    "format_search_results",
]
