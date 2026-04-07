from infrastructure.llm_adapters.openai_compatible_client import OpenAICompatibleClient
from infrastructure.utils.web_search_tool import WebSearchTool, SearchRuntime


class _FakeRuntimeConfig:
    def __init__(self, provider: str, model: str, api_key: str, base_url: str = "https://example.com"):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url


class _FakeRuntimeManager:
    def __init__(self, runtime: _FakeRuntimeConfig):
        self._runtime = runtime

    def resolve_active_config(self):
        return self._runtime


class _StubWebSearchTool(WebSearchTool):
    def __init__(self, runtime_manager):
        super().__init__()
        self._runtime_manager = runtime_manager

    def _get_runtime_config_manager(self):
        return self._runtime_manager

    def _get_active_llm_client(self):
        return object()


def test_qwen_search_runtime_is_available_for_supported_model():
    tool = _StubWebSearchTool(
        _FakeRuntimeManager(_FakeRuntimeConfig(provider="qwen", model="qwen3-max", api_key="sk-test-qwen"))
    )

    runtime = tool.resolve_search_runtime()

    assert runtime.available is True
    assert runtime.provider == "qwen"
    assert runtime.model == "qwen3-max"


def test_qwen_search_execution_plan_uses_enable_search_request():
    tool = WebSearchTool()
    runtime = SearchRuntime(
        provider="qwen",
        model="qwen3-max",
        api_key="sk-test-qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        available=True,
    )

    plan = tool._build_execution_plan(runtime, "latest qwen docs", 3)

    assert plan.tools is None
    assert plan.request_kwargs["enable_search"] is True
    assert plan.request_kwargs["search_options"]["forced_search"] is True
    assert plan.request_kwargs["response_format"] == {"type": "json_object"}


def test_openai_compatible_client_parses_search_info_metadata():
    client = OpenAICompatibleClient(
        provider_id="qwen",
        api_key="sk-test-qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3-max",
    )

    response = client._parse_chat_response(
        {
            "choices": [
                {
                    "message": {"content": '{"results": []}'},
                    "finish_reason": "stop",
                }
            ],
            "search_info": {
                "search_results": [
                    {
                        "title": "Qwen Docs",
                        "url": "https://help.aliyun.com/zh/model-studio/web-search",
                        "snippet": "web search",
                    }
                ]
            },
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    assert response.metadata is not None
    assert response.metadata["web_search_results"][0]["title"] == "Qwen Docs"
