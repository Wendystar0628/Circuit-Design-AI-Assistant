from domain.llm.llm_message_builder import LLMMessageBuilder
from domain.llm.message_helpers import create_human_message
from domain.llm.message_types import Attachment
from infrastructure.llm_adapters.qwen.qwen_client import QwenClient
from shared.model_registry import ModelRegistry


def test_llm_message_builder_expands_file_attachment_into_user_content(tmp_path, monkeypatch):
    file_path = tmp_path / "token_monitor.py"
    file_path.write_text("print('hello')\n", encoding="utf-8")
    monkeypatch.setattr(
        "domain.llm.llm_message_builder.extract_content",
        lambda path: "提取出的文件内容",
    )
    message = create_human_message(
        "请分析附件",
        attachments=[
            Attachment(
                type="file",
                path=str(file_path),
                name="token_monitor.py",
                mime_type="text/x-python",
                size=123,
            )
        ],
    )

    payload = LLMMessageBuilder().build_message(message)

    assert payload["role"] == "user"
    assert isinstance(payload["content"], str)
    assert "请分析附件" in payload["content"]
    assert "[附件 token_monitor.py]" in payload["content"]
    assert "提取出的文件内容" in payload["content"]


def test_llm_message_builder_emits_image_url_parts(tmp_path):
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"fake-image-bytes")
    message = create_human_message(
        "请看图",
        attachments=[
            Attachment(
                type="image",
                path=str(image_path),
                name="sample.png",
                mime_type="image/png",
                size=image_path.stat().st_size,
            )
        ],
    )

    payload = LLMMessageBuilder().build_message(message)

    assert isinstance(payload["content"], list)
    assert any(item.get("type") == "image_url" for item in payload["content"])


def test_qwen_client_switches_to_vision_fallback_for_image_messages():
    ModelRegistry.clear()
    ModelRegistry.initialize()
    client = QwenClient(api_key="test", model="qwen3-max")

    actual_model = client._resolve_model_for_messages(
        "qwen3-max",
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看图"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            }
        ],
    )

    assert actual_model == "qwen3.6-plus"
