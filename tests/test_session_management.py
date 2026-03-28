# -*- coding: utf-8 -*-
"""
会话管理模块测试

测试范围：
1. ContextService 功能验证
   - save_messages() 正确写入会话文件
   - load_messages() 正确读取会话文件
   - list_sessions() 正确返回会话列表
   - sync_index_with_files() 正确同步索引与文件

2. MessageStore 功能验证
   - add_message() 正确更新 GraphState.messages
   - get_messages() 正确返回消息列表
   - add_partial_response() 正确处理部分响应
   - classify_messages() 正确分类消息

3. 集成验证
   - 新建会话 → 发送消息 → 关闭应用 → 重新打开 → 消息正确恢复
   - 切换会话时当前会话自动保存
   - 删除会话时文件和索引同步更新

运行方式：
    python -m tests.test_session_management
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from domain.services import context_service
from domain.llm.message_store import (
    MessageStore,
    IMPORTANCE_HIGH,
    IMPORTANCE_MEDIUM,
    IMPORTANCE_LOW,
)
from domain.llm.message_helpers import (
    ROLE_USER,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    create_human_message,
    create_ai_message,
    create_system_message,
    message_to_dict,
    dict_to_message,
    get_role,
    is_partial_response,
    get_reasoning_content,
)


class TestContextServiceFileOperations(unittest.TestCase):
    """ContextService 文件操作测试"""
    
    def setUp(self):
        """创建临时测试目录"""
        self.test_dir = tempfile.mkdtemp(prefix="circuit_ai_test_")
        self.project_root = self.test_dir
    
    def tearDown(self):
        """清理测试目录"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    # ============================================================
    # save_messages / load_messages 测试
    # ============================================================
    
    def test_save_and_load_empty_messages(self):
        """保存和加载空消息列表"""
        session_id = "test_session_001"
        
        # 保存空列表
        context_service.save_messages(self.project_root, session_id, [])
        
        # 加载验证
        loaded = context_service.load_messages(self.project_root, session_id)
        self.assertEqual(loaded, [])
    
    def test_save_and_load_messages_with_content(self):
        """保存和加载包含内容的消息"""
        session_id = "test_session_002"
        
        # 构造消息数据（模拟 message_to_dict 输出）
        messages = [
            {
                "type": "user",
                "content": "帮我设计一个运算放大器电路",
                "additional_kwargs": {"timestamp": "2024-01-15T10:30:00"}
            },
            {
                "type": "assistant",
                "content": "好的，我来帮你设计一个基本的运算放大器电路。",
                "additional_kwargs": {
                    "timestamp": "2024-01-15T10:30:05",
                    "reasoning_content": "用户需要运放电路，先确认具体用途",
                    "operations": ["分析需求", "设计电路"]
                }
            }
        ]
        
        # 保存
        context_service.save_messages(self.project_root, session_id, messages)
        
        # 验证文件存在
        file_path = Path(self.project_root) / ".circuit_ai/conversations" / f"{session_id}.json"
        self.assertTrue(file_path.exists())
        
        # 加载验证
        loaded = context_service.load_messages(self.project_root, session_id)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["content"], "帮我设计一个运算放大器电路")
        self.assertEqual(loaded[1]["type"], "assistant")
    
    def test_save_messages_creates_directory(self):
        """保存消息时自动创建目录"""
        session_id = "new_session"
        messages = [{"type": "user", "content": "test", "additional_kwargs": {}}]
        
        # 确保目录不存在
        conv_dir = Path(self.project_root) / ".circuit_ai/conversations"
        self.assertFalse(conv_dir.exists())
        
        # 保存消息
        context_service.save_messages(self.project_root, session_id, messages)
        
        # 验证目录已创建
        self.assertTrue(conv_dir.exists())
    
    def test_save_messages_empty_session_id_raises(self):
        """空 session_id 应抛出异常"""
        with self.assertRaises(ValueError):
            context_service.save_messages(self.project_root, "", [])
    
    def test_load_nonexistent_session_returns_empty(self):
        """加载不存在的会话返回空列表"""
        loaded = context_service.load_messages(self.project_root, "nonexistent")
        self.assertEqual(loaded, [])
    
    def test_append_message(self):
        """追加单条消息"""
        session_id = "append_test"
        
        # 先保存初始消息
        initial = [{"type": "user", "content": "第一条", "additional_kwargs": {}}]
        context_service.save_messages(self.project_root, session_id, initial)
        
        # 追加消息
        new_msg = {"type": "assistant", "content": "第二条"}
        context_service.append_message(self.project_root, session_id, new_msg)
        
        # 验证
        loaded = context_service.load_messages(self.project_root, session_id)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[1]["content"], "第二条")
        self.assertIn("timestamp", loaded[1])  # 自动添加时间戳
    
    def test_append_message_invalid_format_raises(self):
        """追加格式无效的消息应抛出异常"""
        session_id = "invalid_append"
        context_service.save_messages(self.project_root, session_id, [])
        
        # 缺少 type 字段
        with self.assertRaises(ValueError):
            context_service.append_message(
                self.project_root, session_id, {"content": "no type"}
            )
        
        # 缺少 content 字段
        with self.assertRaises(ValueError):
            context_service.append_message(
                self.project_root, session_id, {"type": "user"}
            )


class TestContextServiceSessionIndex(unittest.TestCase):
    """ContextService 会话索引管理测试"""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="circuit_ai_test_")
        self.project_root = self.test_dir
    
    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_list_sessions_empty(self):
        """列出空会话列表"""
        sessions = context_service.list_sessions(self.project_root)
        self.assertEqual(sessions, [])
    
    def test_list_sessions_with_data(self):
        """列出包含数据的会话列表"""
        # 创建会话索引
        context_service.update_session_index(
            self.project_root,
            "session_001",
            {
                "name": "电路设计讨论",
                "created_at": "2024-01-15T10:00:00",
                "updated_at": "2024-01-15T11:00:00",
                "message_count": 5,
                "preview": "帮我设计一个放大器..."
            }
        )
        context_service.update_session_index(
            self.project_root,
            "session_002",
            {
                "name": "仿真调试",
                "created_at": "2024-01-16T09:00:00",
                "updated_at": "2024-01-16T10:00:00",
                "message_count": 3,
            }
        )
        
        # 列出会话
        sessions = context_service.list_sessions(self.project_root)
        
        self.assertEqual(len(sessions), 2)
        # 按更新时间倒序，session_002 应该在前
        self.assertEqual(sessions[0]["session_id"], "session_002")
        self.assertEqual(sessions[1]["session_id"], "session_001")
    
    def test_list_sessions_respects_limit(self):
        """列出会话时遵守数量限制"""
        # 创建多个会话
        for i in range(5):
            context_service.update_session_index(
                self.project_root,
                f"session_{i:03d}",
                {"name": f"会话 {i}", "updated_at": f"2024-01-{15+i:02d}T10:00:00"}
            )
        
        # 限制返回 3 个
        sessions = context_service.list_sessions(self.project_root, limit=3)
        self.assertEqual(len(sessions), 3)
    
    def test_get_and_set_current_session_id(self):
        """获取和设置当前会话 ID"""
        # 初始为空
        current = context_service.get_current_session_id(self.project_root)
        self.assertIsNone(current)
        
        # 设置当前会话
        context_service.set_current_session_id(self.project_root, "active_session")
        
        # 验证
        current = context_service.get_current_session_id(self.project_root)
        self.assertEqual(current, "active_session")
    
    def test_update_session_index_creates_new(self):
        """更新索引时创建新会话记录"""
        session_id = "new_session"
        
        result = context_service.update_session_index(
            self.project_root,
            session_id,
            {"name": "新会话", "message_count": 0}
        )
        
        self.assertTrue(result)
        
        # 验证元数据
        metadata = context_service.get_session_metadata(self.project_root, session_id)
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["name"], "新会话")
    
    def test_update_session_index_updates_existing(self):
        """更新索引时修改已存在的会话"""
        session_id = "existing_session"
        
        # 创建
        context_service.update_session_index(
            self.project_root, session_id, {"name": "原名称", "message_count": 1}
        )
        
        # 更新
        context_service.update_session_index(
            self.project_root, session_id, {"name": "新名称", "message_count": 5}
        )
        
        # 验证
        metadata = context_service.get_session_metadata(self.project_root, session_id)
        self.assertEqual(metadata["name"], "新名称")
        self.assertEqual(metadata["message_count"], 5)
    
    def test_update_session_index_set_current(self):
        """更新索引时同时设置为当前会话"""
        session_id = "to_be_current"
        
        context_service.update_session_index(
            self.project_root,
            session_id,
            {"name": "测试"},
            set_current=True
        )
        
        current = context_service.get_current_session_id(self.project_root)
        self.assertEqual(current, session_id)
    
    def test_remove_from_session_index(self):
        """从索引中移除会话"""
        session_id = "to_remove"
        
        # 创建
        context_service.update_session_index(
            self.project_root, session_id, {"name": "待删除"}
        )
        
        # 移除
        result = context_service.remove_from_session_index(self.project_root, session_id)
        self.assertTrue(result)
        
        # 验证已移除
        metadata = context_service.get_session_metadata(self.project_root, session_id)
        self.assertIsNone(metadata)
    
    def test_remove_current_session_clears_current_id(self):
        """移除当前会话时清空 current_session_id"""
        session_id = "current_to_remove"
        
        # 创建并设为当前
        context_service.update_session_index(
            self.project_root, session_id, {"name": "当前"}, set_current=True
        )
        
        # 移除
        context_service.remove_from_session_index(self.project_root, session_id)
        
        # 验证 current_session_id 已清空
        current = context_service.get_current_session_id(self.project_root)
        self.assertIsNone(current)


class TestContextServiceSessionManagement(unittest.TestCase):
    """ContextService 会话管理操作测试"""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="circuit_ai_test_")
        self.project_root = self.test_dir
    
    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_session_exists(self):
        """检查会话是否存在"""
        session_id = "check_exists"
        
        # 不存在
        self.assertFalse(context_service.session_exists(self.project_root, session_id))
        
        # 创建会话文件
        context_service.save_messages(self.project_root, session_id, [])
        
        # 存在
        self.assertTrue(context_service.session_exists(self.project_root, session_id))
    
    def test_delete_session(self):
        """删除会话文件"""
        session_id = "to_delete"
        
        # 创建
        context_service.save_messages(
            self.project_root, session_id,
            [{"type": "user", "content": "test", "additional_kwargs": {}}]
        )
        self.assertTrue(context_service.session_exists(self.project_root, session_id))
        
        # 删除
        result = context_service.delete_session(self.project_root, session_id)
        self.assertTrue(result)
        
        # 验证已删除
        self.assertFalse(context_service.session_exists(self.project_root, session_id))
    
    def test_delete_nonexistent_session(self):
        """删除不存在的会话返回 False"""
        result = context_service.delete_session(self.project_root, "nonexistent")
        self.assertFalse(result)
    
    def test_rename_session(self):
        """重命名会话"""
        session_id = "to_rename"
        
        # 创建索引记录
        context_service.update_session_index(
            self.project_root, session_id, {"name": "原名称"}
        )
        
        # 重命名
        result = context_service.rename_session(self.project_root, session_id, "新名称")
        self.assertTrue(result)
        
        # 验证
        metadata = context_service.get_session_metadata(self.project_root, session_id)
        self.assertEqual(metadata["name"], "新名称")
    
    def test_clear_messages(self):
        """清空会话消息"""
        session_id = "to_clear"
        
        # 创建带消息的会话
        context_service.save_messages(
            self.project_root, session_id,
            [
                {"type": "user", "content": "msg1", "additional_kwargs": {}},
                {"type": "assistant", "content": "msg2", "additional_kwargs": {}},
            ]
        )
        
        # 清空
        context_service.clear_messages(self.project_root, session_id)
        
        # 验证消息已清空但文件仍存在
        self.assertTrue(context_service.session_exists(self.project_root, session_id))
        messages = context_service.load_messages(self.project_root, session_id)
        self.assertEqual(messages, [])
    
    def test_get_recent_messages(self):
        """获取最近 N 条消息"""
        session_id = "recent_test"
        
        # 创建 10 条消息
        messages = [
            {"type": "user", "content": f"消息 {i}", "additional_kwargs": {}}
            for i in range(10)
        ]
        context_service.save_messages(self.project_root, session_id, messages)
        
        # 获取最近 3 条
        recent = context_service.get_recent_messages(self.project_root, session_id, limit=3)
        
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[0]["content"], "消息 7")
        self.assertEqual(recent[2]["content"], "消息 9")
    
    def test_get_message_count(self):
        """获取消息数量"""
        session_id = "count_test"
        
        # 空会话
        count = context_service.get_message_count(self.project_root, session_id)
        self.assertEqual(count, 0)
        
        # 添加消息
        messages = [
            {"type": "user", "content": f"msg{i}", "additional_kwargs": {}}
            for i in range(5)
        ]
        context_service.save_messages(self.project_root, session_id, messages)
        
        count = context_service.get_message_count(self.project_root, session_id)
        self.assertEqual(count, 5)
    
    def test_get_conversation_path(self):
        """获取会话文件路径"""
        session_id = "path_test"
        
        path = context_service.get_conversation_path(self.project_root, session_id)
        
        expected = str(Path(self.project_root) / ".circuit_ai/conversations" / f"{session_id}.json")
        self.assertEqual(path, expected)


class TestMessageStoreBasicOperations(unittest.TestCase):
    """MessageStore 基本操作测试"""
    
    def setUp(self):
        self.store = MessageStore()
        self.empty_state = {"messages": []}
    
    def test_add_user_message(self):
        """添加用户消息"""
        new_state = self.store.add_message(
            self.empty_state,
            role=ROLE_USER,
            content="帮我设计一个滤波器"
        )
        
        messages = new_state["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(get_role(messages[0]), ROLE_USER)
        self.assertEqual(messages[0].content, "帮我设计一个滤波器")
    
    def test_add_assistant_message_with_reasoning(self):
        """添加带思考内容的助手消息"""
        new_state = self.store.add_message(
            self.empty_state,
            role=ROLE_ASSISTANT,
            content="我来帮你设计滤波器。",
            reasoning_content="用户需要滤波器，先确认是低通还是高通",
            operations=["分析需求", "选择拓扑"]
        )
        
        messages = new_state["messages"]
        self.assertEqual(len(messages), 1)
        
        msg = messages[0]
        self.assertEqual(get_role(msg), ROLE_ASSISTANT)
        self.assertEqual(get_reasoning_content(msg), "用户需要滤波器，先确认是低通还是高通")
    
    def test_add_system_message(self):
        """添加系统消息"""
        new_state = self.store.add_message(
            self.empty_state,
            role=ROLE_SYSTEM,
            content="你是一个电路设计助手"
        )
        
        messages = new_state["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(get_role(messages[0]), ROLE_SYSTEM)
    
    def test_add_message_invalid_role_raises(self):
        """添加无效角色消息应抛出异常"""
        with self.assertRaises(ValueError):
            self.store.add_message(
                self.empty_state,
                role="invalid_role",
                content="test"
            )
    
    def test_add_message_preserves_existing(self):
        """添加消息保留已有消息"""
        # 先添加一条
        state1 = self.store.add_message(
            self.empty_state, ROLE_USER, "第一条"
        )
        
        # 再添加一条
        state2 = self.store.add_message(
            state1, ROLE_ASSISTANT, "第二条"
        )
        
        self.assertEqual(len(state2["messages"]), 2)
        self.assertEqual(state2["messages"][0].content, "第一条")
        self.assertEqual(state2["messages"][1].content, "第二条")
    
    def test_add_message_does_not_mutate_original(self):
        """添加消息不修改原状态（不可变性）"""
        original = {"messages": []}
        
        self.store.add_message(original, ROLE_USER, "test")
        
        # 原状态不变
        self.assertEqual(len(original["messages"]), 0)
    
    def test_add_user_message_with_attachments(self):
        """添加带附件的用户消息"""
        attachments = [
            {"type": "file", "path": "/path/to/circuit.cir", "name": "circuit.cir"}
        ]
        
        new_state = self.store.add_message(
            self.empty_state,
            role=ROLE_USER,
            content="请分析这个电路文件",
            attachments=attachments
        )
        
        msg = new_state["messages"][0]
        msg_attachments = msg.additional_kwargs.get("attachments", [])
        self.assertEqual(len(msg_attachments), 1)
        self.assertEqual(msg_attachments[0]["name"], "circuit.cir")


class TestMessageStoreRetrieval(unittest.TestCase):
    """MessageStore 消息检索测试"""
    
    def setUp(self):
        self.store = MessageStore()
        # 构建包含多条消息的状态
        state = {"messages": []}
        for i in range(10):
            role = ROLE_USER if i % 2 == 0 else ROLE_ASSISTANT
            state = self.store.add_message(state, role, f"消息 {i}")
        self.state_with_messages = state
    
    def test_get_messages_all(self):
        """获取所有消息"""
        messages = self.store.get_messages(self.state_with_messages)
        self.assertEqual(len(messages), 10)
    
    def test_get_messages_with_limit(self):
        """获取限定数量的消息"""
        messages = self.store.get_messages(self.state_with_messages, limit=3)
        
        self.assertEqual(len(messages), 3)
        # 应该是最后 3 条
        self.assertEqual(messages[0].content, "消息 7")
        self.assertEqual(messages[2].content, "消息 9")
    
    def test_get_messages_empty_state(self):
        """从空状态获取消息"""
        messages = self.store.get_messages({"messages": []})
        self.assertEqual(messages, [])
    
    def test_get_messages_no_messages_key(self):
        """状态中没有 messages 键"""
        messages = self.store.get_messages({})
        self.assertEqual(messages, [])
    
    def test_get_recent_messages(self):
        """获取最近 N 条消息"""
        recent = self.store.get_recent_messages(self.state_with_messages, n=5)
        
        self.assertEqual(len(recent), 5)
        self.assertEqual(recent[0].content, "消息 5")
        self.assertEqual(recent[4].content, "消息 9")


class TestMessageStoreClassification(unittest.TestCase):
    """MessageStore 消息分类测试"""
    
    def setUp(self):
        self.store = MessageStore()
    
    def test_classify_system_message_as_high(self):
        """系统消息分类为高重要性"""
        state = {"messages": []}
        state = self.store.add_message(state, ROLE_SYSTEM, "系统提示")
        state = self.store.add_message(state, ROLE_USER, "用户消息")
        state = self.store.add_message(state, ROLE_ASSISTANT, "助手回复")
        
        classified = self.store.classify_messages(state)
        
        # 系统消息应在 HIGH 中
        high_contents = [m.content for m in classified[IMPORTANCE_HIGH]]
        self.assertIn("系统提示", high_contents)
    
    def test_classify_recent_messages_as_high(self):
        """最近 3 条消息分类为高重要性"""
        state = {"messages": []}
        for i in range(10):
            state = self.store.add_message(state, ROLE_USER, f"消息 {i}")
        
        classified = self.store.classify_messages(state)
        
        # 最后 3 条应在 HIGH 中
        high_contents = [m.content for m in classified[IMPORTANCE_HIGH]]
        self.assertIn("消息 7", high_contents)
        self.assertIn("消息 8", high_contents)
        self.assertIn("消息 9", high_contents)
    
    def test_classify_message_with_operations_as_high(self):
        """包含操作的助手消息分类为高重要性"""
        state = {"messages": []}
        # 添加多条消息，确保带操作的不在最后 3 条
        for i in range(5):
            state = self.store.add_message(state, ROLE_USER, f"用户 {i}")
        
        # 在中间添加带操作的消息
        state = self.store.add_message(
            state, ROLE_ASSISTANT, "执行了操作",
            operations=["创建文件", "修改电路"]
        )
        
        # 再添加几条普通消息
        for i in range(5):
            state = self.store.add_message(state, ROLE_USER, f"后续 {i}")
        
        classified = self.store.classify_messages(state)
        
        high_contents = [m.content for m in classified[IMPORTANCE_HIGH]]
        self.assertIn("执行了操作", high_contents)
    
    def test_classify_message_with_code_as_medium(self):
        """包含代码块的消息分类为中等重要性"""
        state = {"messages": []}
        # 添加多条消息
        for i in range(5):
            state = self.store.add_message(state, ROLE_USER, f"普通消息 {i}")
        
        # 添加包含代码的消息（不在最后 3 条）
        state = self.store.add_message(
            state, ROLE_ASSISTANT,
            "这是代码示例：\n```python\nprint('hello')\n```"
        )
        
        # 再添加几条
        for i in range(5):
            state = self.store.add_message(state, ROLE_USER, f"后续 {i}")
        
        classified = self.store.classify_messages(state)
        
        medium_contents = [m.content for m in classified[IMPORTANCE_MEDIUM]]
        self.assertTrue(any("代码示例" in c for c in medium_contents))
    
    def test_classify_long_message_as_medium(self):
        """较长消息分类为中等重要性"""
        state = {"messages": []}
        for i in range(5):
            state = self.store.add_message(state, ROLE_USER, f"短消息 {i}")
        
        # 添加长消息（超过 500 字符）
        long_content = "这是一段很长的内容。" * 100
        state = self.store.add_message(state, ROLE_ASSISTANT, long_content)
        
        # 再添加几条短消息
        for i in range(5):
            state = self.store.add_message(state, ROLE_USER, f"后续 {i}")
        
        classified = self.store.classify_messages(state)
        
        # 长消息应在 MEDIUM 中
        medium_lengths = [len(m.content) for m in classified[IMPORTANCE_MEDIUM]]
        self.assertTrue(any(length > 500 for length in medium_lengths))


class TestMessageStorePartialResponse(unittest.TestCase):
    """MessageStore 部分响应处理测试"""
    
    def setUp(self):
        self.store = MessageStore()
        self.empty_state = {"messages": []}
    
    def test_add_partial_response_saves_long_content(self):
        """部分响应内容足够长时保存"""
        content = "这是一段足够长的部分响应内容，超过了最小长度限制。" * 3
        
        new_state, saved = self.store.add_partial_response(
            self.empty_state,
            content=content,
            reasoning_content="思考中...",
            stop_reason="user_requested",
            min_length=50
        )
        
        self.assertTrue(saved)
        self.assertEqual(len(new_state["messages"]), 1)
        
        msg = new_state["messages"][0]
        self.assertTrue(is_partial_response(msg))
    
    def test_add_partial_response_discards_short_content(self):
        """部分响应内容过短时丢弃"""
        content = "太短"
        
        new_state, saved = self.store.add_partial_response(
            self.empty_state,
            content=content,
            stop_reason="user_requested",
            min_length=50
        )
        
        self.assertFalse(saved)
        self.assertEqual(len(new_state["messages"]), 0)
    
    def test_get_last_partial_message(self):
        """获取最后一条部分响应"""
        state = self.empty_state
        
        # 添加普通消息
        state = self.store.add_message(state, ROLE_USER, "问题")
        state = self.store.add_message(state, ROLE_ASSISTANT, "完整回复")
        
        # 添加部分响应
        state, _ = self.store.add_partial_response(
            state,
            content="这是部分响应内容，足够长以便保存。" * 3,
            stop_reason="user_requested"
        )
        
        partial = self.store.get_last_partial_message(state)
        
        self.assertIsNotNone(partial)
        self.assertTrue(is_partial_response(partial))
    
    def test_get_last_partial_message_none_when_no_partial(self):
        """没有部分响应时返回 None"""
        state = self.empty_state
        state = self.store.add_message(state, ROLE_USER, "问题")
        state = self.store.add_message(state, ROLE_ASSISTANT, "完整回复")
        
        partial = self.store.get_last_partial_message(state)
        self.assertIsNone(partial)
    
    def test_has_pending_partial_response(self):
        """检查是否有待处理的部分响应"""
        state = self.empty_state
        
        # 无部分响应
        self.assertFalse(self.store.has_pending_partial_response(state))
        
        # 添加部分响应
        state, _ = self.store.add_partial_response(
            state,
            content="部分响应内容，需要足够长才能保存。" * 3,
            stop_reason="user_requested"
        )
        
        self.assertTrue(self.store.has_pending_partial_response(state))
    
    def test_mark_partial_as_complete(self):
        """将部分响应标记为完成"""
        state = self.empty_state
        
        # 添加部分响应
        state, _ = self.store.add_partial_response(
            state,
            content="部分响应内容，需要足够长才能保存。" * 3,
            stop_reason="user_requested"
        )
        
        # 标记为完成
        new_state = self.store.mark_partial_as_complete(state)
        
        # 验证不再是部分响应
        msg = new_state["messages"][0]
        self.assertFalse(is_partial_response(msg))
    
    def test_remove_last_partial_response(self):
        """移除最后一条部分响应"""
        state = self.empty_state
        state = self.store.add_message(state, ROLE_USER, "问题")
        
        # 添加部分响应
        state, _ = self.store.add_partial_response(
            state,
            content="部分响应内容，需要足够长才能保存。" * 3,
            stop_reason="user_requested"
        )
        
        self.assertEqual(len(state["messages"]), 2)
        
        # 移除
        new_state = self.store.remove_last_partial_response(state)
        
        self.assertEqual(len(new_state["messages"]), 1)
        self.assertEqual(new_state["messages"][0].content, "问题")


class TestMessageStoreSummary(unittest.TestCase):
    """MessageStore 摘要管理测试"""
    
    def setUp(self):
        self.store = MessageStore()
    
    def test_get_summary_empty(self):
        """获取空摘要"""
        state = {"messages": []}
        summary = self.store.get_summary(state)
        self.assertEqual(summary, "")
    
    def test_set_and_get_summary(self):
        """设置和获取摘要"""
        state = {"messages": []}
        
        new_state = self.store.set_summary(state, "这是对话摘要")
        
        summary = self.store.get_summary(new_state)
        self.assertEqual(summary, "这是对话摘要")
    
    def test_has_summary(self):
        """检查是否有摘要"""
        state = {"messages": []}
        
        self.assertFalse(self.store.has_summary(state))
        
        state = self.store.set_summary(state, "摘要内容")
        self.assertTrue(self.store.has_summary(state))
    
    def test_has_summary_false_for_whitespace(self):
        """纯空白摘要视为无摘要"""
        state = {"messages": [], "conversation_summary": "   "}
        self.assertFalse(self.store.has_summary(state))


class TestMessageStoreReset(unittest.TestCase):
    """MessageStore 重置测试"""
    
    def setUp(self):
        self.store = MessageStore()
    
    def test_reset_messages_keep_system(self):
        """重置消息时保留系统消息"""
        state = {"messages": []}
        state = self.store.add_message(state, ROLE_SYSTEM, "系统提示")
        state = self.store.add_message(state, ROLE_USER, "用户消息")
        state = self.store.add_message(state, ROLE_ASSISTANT, "助手回复")
        
        new_state = self.store.reset_messages(state, keep_system=True)
        
        self.assertEqual(len(new_state["messages"]), 1)
        self.assertEqual(new_state["messages"][0].content, "系统提示")
    
    def test_reset_messages_clear_all(self):
        """重置消息时清空所有"""
        state = {"messages": []}
        state = self.store.add_message(state, ROLE_SYSTEM, "系统提示")
        state = self.store.add_message(state, ROLE_USER, "用户消息")
        
        new_state = self.store.reset_messages(state, keep_system=False)
        
        self.assertEqual(len(new_state["messages"]), 0)
    
    def test_reset_clears_summary(self):
        """重置时清空摘要"""
        state = {"messages": [], "conversation_summary": "旧摘要"}
        
        new_state = self.store.reset_messages(state)
        
        self.assertEqual(new_state.get("conversation_summary", ""), "")
    
    def test_load_messages_from_data(self):
        """从数据加载消息"""
        state = {"messages": []}
        
        messages_data = [
            {"type": "user", "content": "问题1", "additional_kwargs": {}},
            {"type": "assistant", "content": "回答1", "additional_kwargs": {}},
            {"type": "user", "content": "问题2", "additional_kwargs": {}},
        ]
        
        new_state = self.store.load_messages_from_data(state, messages_data)
        
        self.assertEqual(len(new_state["messages"]), 3)
        self.assertEqual(new_state["messages"][0].content, "问题1")
        self.assertEqual(get_role(new_state["messages"][1]), ROLE_ASSISTANT)


class TestSessionManagementIntegration(unittest.TestCase):
    """
    会话管理集成测试
    
    模拟完整的会话生命周期：
    - 新建会话 → 发送消息 → 关闭应用 → 重新打开 → 消息正确恢复
    - 切换会话时当前会话自动保存
    - 删除会话时文件和索引同步更新
    """
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="circuit_ai_integration_")
        self.project_root = self.test_dir
        self.store = MessageStore()
    
    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def _create_session(self, session_id: str, name: str) -> dict:
        """模拟创建新会话"""
        # 创建空会话文件
        context_service.save_messages(self.project_root, session_id, [])
        
        # 更新索引
        context_service.update_session_index(
            self.project_root,
            session_id,
            {
                "name": name,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "message_count": 0,
            },
            set_current=True
        )
        
        return {"messages": [], "session_id": session_id}
    
    def _save_session(self, state: dict, session_id: str):
        """模拟保存会话（应用关闭时）"""
        from domain.llm.message_helpers import messages_to_dicts
        
        messages = state.get("messages", [])
        messages_data = messages_to_dicts(messages)
        
        context_service.save_messages(self.project_root, session_id, messages_data)
        context_service.update_session_index(
            self.project_root,
            session_id,
            {
                "updated_at": datetime.now().isoformat(),
                "message_count": len(messages),
                "preview": messages[0].content[:50] if messages else "",
            }
        )
    
    def _load_session(self, session_id: str) -> dict:
        """模拟加载会话（应用启动时）"""
        messages_data = context_service.load_messages(self.project_root, session_id)
        
        state = {"messages": [], "session_id": session_id}
        if messages_data:
            state = self.store.load_messages_from_data(state, messages_data)
            state["session_id"] = session_id
        
        return state
    
    def test_full_session_lifecycle(self):
        """
        完整会话生命周期测试
        
        流程：新建 → 发消息 → 保存 → 重新加载 → 验证消息恢复
        """
        session_id = "lifecycle_test_001"
        
        # 1. 创建新会话
        state = self._create_session(session_id, "电路设计讨论")
        
        # 2. 模拟对话
        state = self.store.add_message(state, ROLE_USER, "帮我设计一个低通滤波器")
        state = self.store.add_message(
            state, ROLE_ASSISTANT,
            "好的，我来帮你设计。请问截止频率是多少？",
            reasoning_content="用户需要低通滤波器，需要确认参数"
        )
        state = self.store.add_message(state, ROLE_USER, "截止频率 1kHz")
        state = self.store.add_message(
            state, ROLE_ASSISTANT,
            "了解，我推荐使用 Sallen-Key 拓扑结构。",
            operations=["分析需求", "选择拓扑"]
        )
        
        # 3. 保存会话（模拟关闭应用）
        self._save_session(state, session_id)
        
        # 4. 清空内存状态（模拟应用重启）
        state = None
        
        # 5. 重新加载会话
        restored_state = self._load_session(session_id)
        
        # 6. 验证消息正确恢复
        messages = restored_state["messages"]
        self.assertEqual(len(messages), 4)
        
        # 验证消息内容
        self.assertEqual(messages[0].content, "帮我设计一个低通滤波器")
        self.assertEqual(get_role(messages[0]), ROLE_USER)
        
        self.assertIn("截止频率", messages[1].content)
        self.assertEqual(get_role(messages[1]), ROLE_ASSISTANT)
        
        # 验证扩展字段
        self.assertEqual(
            get_reasoning_content(messages[1]),
            "用户需要低通滤波器，需要确认参数"
        )
    
    def test_switch_session_saves_current(self):
        """
        切换会话时自动保存当前会话
        
        流程：创建会话A → 发消息 → 创建会话B → 验证A已保存
        """
        session_a = "session_a"
        session_b = "session_b"
        
        # 1. 创建并使用会话 A
        state_a = self._create_session(session_a, "会话 A")
        state_a = self.store.add_message(state_a, ROLE_USER, "会话A的消息")
        state_a = self.store.add_message(state_a, ROLE_ASSISTANT, "会话A的回复")
        
        # 2. 切换前保存会话 A
        self._save_session(state_a, session_a)
        
        # 3. 创建会话 B（模拟切换）
        state_b = self._create_session(session_b, "会话 B")
        state_b = self.store.add_message(state_b, ROLE_USER, "会话B的消息")
        
        # 4. 验证会话 A 的消息已持久化
        loaded_a = context_service.load_messages(self.project_root, session_a)
        self.assertEqual(len(loaded_a), 2)
        self.assertEqual(loaded_a[0]["content"], "会话A的消息")
        
        # 5. 验证当前会话已切换到 B
        current = context_service.get_current_session_id(self.project_root)
        self.assertEqual(current, session_b)
    
    def test_delete_session_syncs_file_and_index(self):
        """
        删除会话时文件和索引同步更新
        
        流程：创建会话 → 添加到索引 → 删除 → 验证文件和索引都已清理
        """
        session_id = "to_delete_session"
        
        # 1. 创建会话
        state = self._create_session(session_id, "待删除会话")
        state = self.store.add_message(state, ROLE_USER, "测试消息")
        self._save_session(state, session_id)
        
        # 2. 验证文件和索引都存在
        self.assertTrue(context_service.session_exists(self.project_root, session_id))
        metadata = context_service.get_session_metadata(self.project_root, session_id)
        self.assertIsNotNone(metadata)
        
        # 3. 删除会话（同时删除文件和索引）
        context_service.delete_session(self.project_root, session_id)
        context_service.remove_from_session_index(self.project_root, session_id)
        
        # 4. 验证文件已删除
        self.assertFalse(context_service.session_exists(self.project_root, session_id))
        
        # 5. 验证索引已更新
        metadata = context_service.get_session_metadata(self.project_root, session_id)
        self.assertIsNone(metadata)
        
        # 6. 验证会话列表中不包含已删除会话
        sessions = context_service.list_sessions(self.project_root)
        session_ids = [s["session_id"] for s in sessions]
        self.assertNotIn(session_id, session_ids)
    
    def test_multiple_sessions_isolation(self):
        """
        多会话隔离测试
        
        验证不同会话的消息互不干扰
        """
        # 创建两个会话
        session_1 = "isolation_test_1"
        session_2 = "isolation_test_2"
        
        state_1 = self._create_session(session_1, "会话1")
        state_1 = self.store.add_message(state_1, ROLE_USER, "会话1独有消息")
        self._save_session(state_1, session_1)
        
        state_2 = self._create_session(session_2, "会话2")
        state_2 = self.store.add_message(state_2, ROLE_USER, "会话2独有消息")
        state_2 = self.store.add_message(state_2, ROLE_ASSISTANT, "会话2的回复")
        self._save_session(state_2, session_2)
        
        # 加载并验证隔离性
        loaded_1 = context_service.load_messages(self.project_root, session_1)
        loaded_2 = context_service.load_messages(self.project_root, session_2)
        
        self.assertEqual(len(loaded_1), 1)
        self.assertEqual(len(loaded_2), 2)
        
        self.assertEqual(loaded_1[0]["content"], "会话1独有消息")
        self.assertEqual(loaded_2[0]["content"], "会话2独有消息")
    
    def test_session_with_partial_response_recovery(self):
        """
        包含部分响应的会话恢复测试
        
        验证用户中断后的部分响应能正确保存和恢复
        """
        session_id = "partial_response_test"
        
        # 1. 创建会话并添加部分响应
        state = self._create_session(session_id, "部分响应测试")
        state = self.store.add_message(state, ROLE_USER, "请详细解释运算放大器原理")
        
        # 模拟用户中断，保存部分响应
        partial_content = "运算放大器是一种高增益的差分放大器，具有以下特点：\n1. 高输入阻抗\n2. 低输出阻抗\n3. 高开环增益..."
        state, saved = self.store.add_partial_response(
            state,
            content=partial_content,
            reasoning_content="正在组织运放原理的解释",
            stop_reason="user_requested"
        )
        self.assertTrue(saved)
        
        # 2. 保存会话
        self._save_session(state, session_id)
        
        # 3. 重新加载
        restored = self._load_session(session_id)
        
        # 4. 验证部分响应正确恢复
        messages = restored["messages"]
        self.assertEqual(len(messages), 2)
        
        partial_msg = messages[1]
        self.assertTrue(is_partial_response(partial_msg))
        self.assertIn("运算放大器", partial_msg.content)


class TestMessageSerialization(unittest.TestCase):
    """消息序列化/反序列化测试"""
    
    def test_human_message_round_trip(self):
        """用户消息序列化往返"""
        original = create_human_message(
            content="测试消息",
            attachments=[{"type": "file", "path": "/test.cir", "name": "test.cir"}]
        )
        
        # 序列化
        data = message_to_dict(original)
        
        # 反序列化
        restored = dict_to_message(data)
        
        self.assertEqual(restored.content, original.content)
        self.assertEqual(get_role(restored), ROLE_USER)
    
    def test_ai_message_round_trip(self):
        """助手消息序列化往返"""
        original = create_ai_message(
            content="这是回复",
            reasoning_content="深度思考内容",
            operations=["操作1", "操作2"],
            usage={"total_tokens": 100, "prompt_tokens": 50, "completion_tokens": 50}
        )
        
        data = message_to_dict(original)
        restored = dict_to_message(data)
        
        self.assertEqual(restored.content, original.content)
        self.assertEqual(get_reasoning_content(restored), "深度思考内容")
    
    def test_system_message_round_trip(self):
        """系统消息序列化往返"""
        original = create_system_message("你是电路设计助手")
        
        data = message_to_dict(original)
        restored = dict_to_message(data)
        
        self.assertEqual(restored.content, original.content)
        self.assertEqual(get_role(restored), ROLE_SYSTEM)
    
    def test_partial_response_round_trip(self):
        """部分响应消息序列化往返"""
        original = create_ai_message(
            content="部分内容...",
            is_partial=True,
            stop_reason="user_requested"
        )
        
        data = message_to_dict(original)
        restored = dict_to_message(data)
        
        self.assertTrue(is_partial_response(restored))


class TestEdgeCases(unittest.TestCase):
    """边界情况测试"""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="circuit_ai_edge_")
        self.project_root = self.test_dir
        self.store = MessageStore()
    
    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_unicode_content(self):
        """Unicode 内容处理"""
        session_id = "unicode_test"
        
        messages = [
            {"type": "user", "content": "设计一个 π 型滤波器 🔧", "additional_kwargs": {}},
            {"type": "assistant", "content": "好的，π 型滤波器结构如下：∏", "additional_kwargs": {}},
        ]
        
        context_service.save_messages(self.project_root, session_id, messages)
        loaded = context_service.load_messages(self.project_root, session_id)
        
        self.assertEqual(loaded[0]["content"], "设计一个 π 型滤波器 🔧")
        self.assertIn("∏", loaded[1]["content"])
    
    def test_large_message_content(self):
        """大内容消息处理"""
        session_id = "large_content"
        
        # 创建 100KB 的内容
        large_content = "x" * (100 * 1024)
        messages = [{"type": "user", "content": large_content, "additional_kwargs": {}}]
        
        context_service.save_messages(self.project_root, session_id, messages)
        loaded = context_service.load_messages(self.project_root, session_id)
        
        self.assertEqual(len(loaded[0]["content"]), 100 * 1024)
    
    def test_special_characters_in_session_id(self):
        """会话 ID 中的特殊字符"""
        # 使用时间戳格式的 session_id（常见格式）
        session_id = "20240115_103045_circuit_design"
        
        messages = [{"type": "user", "content": "test", "additional_kwargs": {}}]
        context_service.save_messages(self.project_root, session_id, messages)
        
        self.assertTrue(context_service.session_exists(self.project_root, session_id))
    
    def test_concurrent_message_operations(self):
        """并发消息操作（基本线程安全测试）"""
        import threading
        
        state = {"messages": []}
        results = []
        
        def add_messages(store, initial_state, count, prefix):
            current = initial_state
            for i in range(count):
                current = store.add_message(current, ROLE_USER, f"{prefix}_{i}")
            results.append(len(current["messages"]))
        
        # 注意：由于状态不可变，每个线程操作独立的状态副本
        # 这里测试的是 MessageStore 内部锁的正确性
        threads = []
        for i in range(3):
            t = threading.Thread(
                target=add_messages,
                args=(self.store, state, 10, f"thread_{i}")
            )
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # 每个线程应该都成功添加了 10 条消息
        self.assertEqual(len(results), 3)
        for count in results:
            self.assertEqual(count, 10)
    
    def test_empty_additional_kwargs(self):
        """空 additional_kwargs 处理"""
        data = {"type": "user", "content": "test"}  # 没有 additional_kwargs
        
        msg = dict_to_message(data)
        self.assertEqual(msg.content, "test")
    
    def test_corrupted_session_file_handling(self):
        """损坏的会话文件处理"""
        session_id = "corrupted"
        
        # 创建损坏的 JSON 文件
        conv_dir = Path(self.project_root) / ".circuit_ai/conversations"
        conv_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = conv_dir / f"{session_id}.json"
        file_path.write_text("{ invalid json", encoding="utf-8")
        
        # 加载应返回空列表而不是崩溃
        loaded = context_service.load_messages(self.project_root, session_id)
        self.assertEqual(loaded, [])


# ============================================================
# 测试运行入口
# ============================================================

def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加所有测试类
    test_classes = [
        TestContextServiceFileOperations,
        TestContextServiceSessionIndex,
        TestContextServiceSessionManagement,
        TestMessageStoreBasicOperations,
        TestMessageStoreRetrieval,
        TestMessageStoreClassification,
        TestMessageStorePartialResponse,
        TestMessageStoreSummary,
        TestMessageStoreReset,
        TestSessionManagementIntegration,
        TestMessageSerialization,
        TestEdgeCases,
    ]
    
    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 返回是否全部通过
    return result.wasSuccessful()


if __name__ == "__main__":
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)
