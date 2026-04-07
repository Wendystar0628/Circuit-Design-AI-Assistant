from domain.llm.llm_message_builder import LLMMessageBuilder
from domain.llm.attachment_references import build_inline_attachment_marker
from domain.llm.message_helpers import create_human_message
from domain.llm.message_types import Attachment
from presentation.panels.conversation.inline_attachment_text_edit import InlineAttachmentTextEdit
from infrastructure.llm_adapters.qwen.qwen_client import QwenClient
from shared.model_registry import ModelRegistry
import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_llm_message_builder_expands_file_attachment_into_user_content(tmp_path, monkeypatch):
    file_path = tmp_path / "token_monitor.py"
    file_path.write_text("print('hello')\n", encoding="utf-8")
    monkeypatch.setattr(
        "domain.llm.llm_message_builder.extract_attachment_text",
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


def test_llm_message_builder_reads_csv_attachment_text(tmp_path):
    csv_path = tmp_path / "dataset.csv"
    csv_path.write_text("time,value\n0,1\n1,2\n", encoding="utf-8")
    message = create_human_message(
        "请分析表格",
        attachments=[
            Attachment(
                type="file",
                path=str(csv_path),
                name="dataset.csv",
                mime_type="text/csv",
                size=csv_path.stat().st_size,
            )
        ],
    )

    payload = LLMMessageBuilder().build_message(message)

    assert isinstance(payload["content"], str)
    assert "[附件 dataset.csv]" in payload["content"]
    assert "time,value" in payload["content"]


def test_llm_message_builder_expands_inline_file_reference_in_place(tmp_path, monkeypatch):
    file_path = tmp_path / "design_notes.txt"
    file_path.write_text("line-1\nline-2\n", encoding="utf-8")
    monkeypatch.setattr(
        "domain.llm.llm_message_builder.extract_attachment_text",
        lambda path: "line-1\nline-2",
    )
    attachment = Attachment(
        type="file",
        path=str(file_path),
        name="design_notes.txt",
        mime_type="text/plain",
        size=file_path.stat().st_size,
        placement="inline",
        reference_id="ref_design_notes",
    )
    marker = build_inline_attachment_marker(attachment.reference_id, attachment.name)
    message = create_human_message(
        f"请先分析前文 {marker} 再继续后文。",
        attachments=[attachment],
    )

    payload = LLMMessageBuilder().build_message(message)

    assert isinstance(payload["content"], str)
    assert payload["content"].startswith("请先分析前文")
    assert "[附件 design_notes.txt]" in payload["content"]
    assert payload["content"].index("[附件 design_notes.txt]") < payload["content"].index("再继续后文")


def test_inline_attachment_text_edit_keeps_following_text_outside_attachment(qapp):
    editor = InlineAttachmentTextEdit()
    attachment = Attachment(
        type="file",
        path="C:/tmp/output_log.txt",
        name="output_log.txt",
        mime_type="text/plain",
        size=0,
        placement="inline",
        reference_id="ref_output_log",
    )

    editor.insert_inline_attachment(attachment)
    editor.insertPlainText("讲解这个输出日志文件")

    assert editor.toPlainText() == "[output_log.txt] 讲解这个输出日志文件"
    assert editor.serialize_content() == "[[attachment:ref_output_log|output_log.txt]] 讲解这个输出日志文件"


@pytest.mark.parametrize(
    ("filename", "content_fragment"),
    [
        ("notes.txt", "plain text"),
        ("config.json", '"name": "demo"'),
        ("solver.cpp", "int main()"),
        ("circuit.spice", ".tran 1n 1u"),
        ("script.py", "print('hello')"),
    ],
)
def test_llm_message_builder_reads_supported_text_like_attachments(tmp_path, filename, content_fragment):
    file_path = tmp_path / filename
    file_path.write_text(content_fragment + "\n", encoding="utf-8")
    message = create_human_message(
        "请分析附件",
        attachments=[
            Attachment(
                type="file",
                path=str(file_path),
                name=filename,
                mime_type="text/plain",
                size=file_path.stat().st_size,
            )
        ],
    )

    payload = LLMMessageBuilder().build_message(message)

    assert isinstance(payload["content"], str)
    assert f"[附件 {filename}]" in payload["content"]
    assert content_fragment in payload["content"]


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


def test_llm_message_builder_upgrades_image_file_attachment_to_image_parts(tmp_path):
    image_path = tmp_path / "selected_as_file.jpeg"
    image_path.write_bytes(b"fake-image-bytes")
    message = create_human_message(
        "请分析附件图片",
        attachments=[
            Attachment(
                type="file",
                path=str(image_path),
                name="selected_as_file.jpeg",
                mime_type="image/jpeg",
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
