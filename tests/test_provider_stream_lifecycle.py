import asyncio

from infrastructure.llm_adapters.base_client import StreamChunk
from infrastructure.llm_adapters.zhipu.zhipu_stream_handler import ZhipuStreamHandler


class _FakeResponse:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.drained = False

    async def aiter_text(self):
        for chunk in self._chunks:
            yield chunk
        self.drained = True


async def _collect_chunks(response):
    handler = ZhipuStreamHandler()
    result = []
    async for chunk in handler.create_stream_iterator(response):
        result.append(chunk)
    return result


def test_zhipu_stream_handler_drains_http_response_after_finish_marker():
    response = _FakeResponse([
        'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\n',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":1}}\n',
        'data: [DONE]\n',
    ])

    chunks = asyncio.run(_collect_chunks(response))

    assert response.drained is True
    assert any(chunk.content == 'hello' for chunk in chunks)
    assert any(chunk.is_finished for chunk in chunks)
