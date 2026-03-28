#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
3.0.10/3.0.11 数据稳定性保证测试

测试内容：
- 停止超时保护机制（5秒超时）
- 部分响应处理策略（>50字符保存，≤50字符丢弃）
- 会话状态一致性（中断点记录与恢复）
- 消息历史完整性（is_partial、stop_reason、tool_calls_pending）
- 资源清理机制（ResourceCleanupManager）
- 边界情况测试（快速连续停止、生成刚开始/即将完成时停止）

运行方式：
    cd circuit_design_ai
    python -m pytest tests/test_data_stability.py -v
    
    或直接运行：
    python tests/test_data_stability.py
"""

import asyncio
import sys
import os
import time
import tempfile
import threading
from pathlib import Path
from typing import Dict, Any, List

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# 测试结果收集器
# ============================================================

class TestResults:
    """测试结果收集器"""
    
    def __init__(self):
        self.passed = []
        self.failed = []
        self.skipped = []
    
    def add_pass(self, name: str, message: str = ""):
        self.passed.append((name, message))
        print(f"  ✅ {name}" + (f" - {message}" if message else ""))
    
    def add_fail(self, name: str, message: str):
        self.failed.append((name, message))
        print(f"  ❌ {name} - {message}")
    
    def add_skip(self, name: str, reason: str):
        self.skipped.append((name, reason))
        print(f"  ⏭️ {name} - 跳过: {reason}")
    
    def summary(self):
        total = len(self.passed) + len(self.failed) + len(self.skipped)
        print("\n" + "=" * 60)
        print(f"测试结果汇总: {len(self.passed)}/{total} 通过")
        print(f"  通过: {len(self.passed)}")
        print(f"  失败: {len(self.failed)}")
        print(f"  跳过: {len(self.skipped)}")
        
        if self.failed:
            print("\n失败的测试:")
            for name, msg in self.failed:
                print(f"  - {name}: {msg}")
        
        print("=" * 60)
        return len(self.failed) == 0


results = TestResults()


# ============================================================
# 1. StopController 超时保护测试
# ============================================================

def test_stop_controller_timeout_constants():
    """测试停止超时常量定义"""
    print("\n📋 测试停止超时常量...")
    
    try:
        from shared.stop_controller import (
            STOP_TIMEOUT_SECONDS,
            FORCE_STOP_WARNING_THRESHOLD
        )
        
        if STOP_TIMEOUT_SECONDS == 5.0:
            results.add_pass("STOP_TIMEOUT_SECONDS = 5.0")
        else:
            results.add_fail("STOP_TIMEOUT_SECONDS", f"期望 5.0，实际 {STOP_TIMEOUT_SECONDS}")
        
        if FORCE_STOP_WARNING_THRESHOLD == 4.0:
            results.add_pass("FORCE_STOP_WARNING_THRESHOLD = 4.0")
        else:
            results.add_fail("FORCE_STOP_WARNING_THRESHOLD", 
                           f"期望 4.0，实际 {FORCE_STOP_WARNING_THRESHOLD}")
            
    except Exception as e:
        results.add_fail("停止超时常量", str(e))


def test_stop_controller_timeout_signal():
    """测试停止超时信号"""
    print("\n📋 测试停止超时信号...")
    
    try:
        from shared.stop_controller import StopController, StopReason, StopState
        
        controller = StopController()
        
        # 检查 stop_timeout 信号存在
        if hasattr(controller, 'stop_timeout'):
            results.add_pass("stop_timeout 信号存在")
        else:
            results.add_fail("stop_timeout 信号", "信号不存在")
            return
        
        # 检查超时定时器相关方法
        if hasattr(controller, '_start_timeout_timer'):
            results.add_pass("_start_timeout_timer 方法存在")
        else:
            results.add_fail("_start_timeout_timer", "方法不存在")
        
        if hasattr(controller, '_cancel_timeout_timer'):
            results.add_pass("_cancel_timeout_timer 方法存在")
        else:
            results.add_fail("_cancel_timeout_timer", "方法不存在")
        
        if hasattr(controller, '_handle_stop_timeout'):
            results.add_pass("_handle_stop_timeout 方法存在")
        else:
            results.add_fail("_handle_stop_timeout", "方法不存在")
            
    except Exception as e:
        results.add_fail("停止超时信号", str(e))


def test_stop_controller_cleanup_callbacks():
    """测试资源清理回调注册"""
    print("\n📋 测试资源清理回调...")
    
    try:
        from shared.stop_controller import StopController
        
        controller = StopController()
        
        # 测试回调注册
        callback_called = [False]
        
        def test_callback():
            callback_called[0] = True
        
        controller.register_cleanup_callback(test_callback)
        results.add_pass("清理回调注册成功")
        
        # 测试回调注销
        controller.unregister_cleanup_callback(test_callback)
        results.add_pass("清理回调注销成功")
        
        # 测试 is_force_stopped 方法
        if hasattr(controller, 'is_force_stopped'):
            is_forced = controller.is_force_stopped()
            if is_forced == False:
                results.add_pass("is_force_stopped 初始值为 False")
            else:
                results.add_fail("is_force_stopped", f"初始值应为 False，实际 {is_forced}")
        else:
            results.add_fail("is_force_stopped", "方法不存在")
            
    except Exception as e:
        results.add_fail("资源清理回调", str(e))


def test_stop_controller_state_transitions():
    """测试停止控制器状态转换"""
    print("\n📋 测试停止状态转换...")
    
    try:
        from shared.stop_controller import StopController, StopReason, StopState
        
        controller = StopController()
        
        # 初始状态应为 IDLE
        if controller.get_state() == StopState.IDLE:
            results.add_pass("初始状态为 IDLE")
        else:
            results.add_fail("初始状态", f"期望 IDLE，实际 {controller.get_state()}")
        
        # 注册任务
        success = controller.register_task("test_task_1")
        if success and controller.get_state() == StopState.RUNNING:
            results.add_pass("注册任务后状态为 RUNNING")
        else:
            results.add_fail("注册任务", f"状态 {controller.get_state()}")
        
        # 请求停止
        success = controller.request_stop(StopReason.USER_REQUESTED)
        if success and controller.get_state() == StopState.STOP_REQUESTED:
            results.add_pass("请求停止后状态为 STOP_REQUESTED")
        else:
            results.add_fail("请求停止", f"状态 {controller.get_state()}")
        
        # 标记正在停止
        controller.mark_stopping()
        if controller.get_state() == StopState.STOPPING:
            results.add_pass("标记停止中后状态为 STOPPING")
        else:
            results.add_fail("标记停止中", f"状态 {controller.get_state()}")
        
        # 标记停止完成
        controller.mark_stopped({"is_partial": True, "cleanup_success": True})
        if controller.get_state() == StopState.STOPPED:
            results.add_pass("标记停止完成后状态为 STOPPED")
        else:
            results.add_fail("标记停止完成", f"状态 {controller.get_state()}")
        
        # 重置
        controller.reset()
        if controller.get_state() == StopState.IDLE:
            results.add_pass("重置后状态为 IDLE")
        else:
            results.add_fail("重置", f"状态 {controller.get_state()}")
            
    except Exception as e:
        results.add_fail("停止状态转换", str(e))


def test_stop_controller_rapid_stop_requests():
    """测试快速连续停止请求（边界情况）"""
    print("\n📋 测试快速连续停止请求...")
    
    try:
        from shared.stop_controller import StopController, StopReason, StopState
        
        controller = StopController()
        
        # 注册任务
        controller.register_task("rapid_test")
        
        # 第一次停止请求应成功
        result1 = controller.request_stop(StopReason.USER_REQUESTED)
        if result1:
            results.add_pass("第一次停止请求成功")
        else:
            results.add_fail("第一次停止请求", "返回 False")
        
        # 第二次停止请求应失败（已在停止中）
        result2 = controller.request_stop(StopReason.USER_REQUESTED)
        if not result2:
            results.add_pass("重复停止请求正确拒绝")
        else:
            results.add_fail("重复停止请求", "应返回 False")
        
        # 清理
        controller.mark_stopping()
        controller.mark_stopped({})
        controller.reset()
        
    except Exception as e:
        results.add_fail("快速连续停止请求", str(e))


# ============================================================
# 2. Message 数据稳定性字段测试
# ============================================================

def test_message_partial_fields():
    """测试 Message 类的部分响应字段"""
    print("\n📋 测试 Message 部分响应字段...")
    
    try:
        from domain.llm.message_types import (
            Message, create_assistant_message, ROLE_ASSISTANT
        )
        
        # 测试 is_partial 字段
        msg = create_assistant_message(
            content="部分内容",
            is_partial=True,
            stop_reason="user_requested"
        )
        
        if msg.is_partial == True:
            results.add_pass("is_partial 字段设置正确")
        else:
            results.add_fail("is_partial", f"期望 True，实际 {msg.is_partial}")
        
        if msg.stop_reason == "user_requested":
            results.add_pass("stop_reason 字段设置正确")
        else:
            results.add_fail("stop_reason", f"期望 user_requested，实际 {msg.stop_reason}")
        
        # 测试 tool_calls_pending 字段
        pending_tools = [{"name": "search", "args": {"query": "test"}}]
        msg2 = create_assistant_message(
            content="工具调用中断",
            is_partial=True,
            tool_calls_pending=pending_tools
        )
        
        if msg2.tool_calls_pending == pending_tools:
            results.add_pass("tool_calls_pending 字段设置正确")
        else:
            results.add_fail("tool_calls_pending", "字段值不匹配")
            
    except Exception as e:
        results.add_fail("Message 部分响应字段", str(e))


def test_message_serialization():
    """测试 Message 序列化/反序列化保留部分响应字段"""
    print("\n📋 测试 Message 序列化...")
    
    try:
        from domain.llm.message_types import Message, create_assistant_message
        
        # 创建带部分响应字段的消息
        original = create_assistant_message(
            content="测试内容",
            reasoning_content="思考过程",
            is_partial=True,
            stop_reason="timeout",
            tool_calls_pending=[{"name": "tool1"}]
        )
        
        # 序列化
        data = original.to_dict()
        
        # 检查序列化结果
        if data.get("is_partial") == True:
            results.add_pass("序列化保留 is_partial")
        else:
            results.add_fail("序列化 is_partial", "字段丢失或值错误")
        
        if data.get("stop_reason") == "timeout":
            results.add_pass("序列化保留 stop_reason")
        else:
            results.add_fail("序列化 stop_reason", "字段丢失或值错误")
        
        if data.get("tool_calls_pending") == [{"name": "tool1"}]:
            results.add_pass("序列化保留 tool_calls_pending")
        else:
            results.add_fail("序列化 tool_calls_pending", "字段丢失或值错误")
        
        # 反序列化
        restored = Message.from_dict(data)
        
        if restored.is_partial == True:
            results.add_pass("反序列化恢复 is_partial")
        else:
            results.add_fail("反序列化 is_partial", f"值为 {restored.is_partial}")
        
        if restored.stop_reason == "timeout":
            results.add_pass("反序列化恢复 stop_reason")
        else:
            results.add_fail("反序列化 stop_reason", f"值为 {restored.stop_reason}")
            
    except Exception as e:
        results.add_fail("Message 序列化", str(e))


# ============================================================
# 3. MessageStore 部分响应处理测试
# ============================================================

def test_message_store_partial_response_threshold():
    """测试部分响应保存阈值（>50字符保存，≤50字符丢弃）"""
    print("\n📋 测试部分响应保存阈值...")
    
    try:
        from domain.llm.message_store import MessageStore
        
        store = MessageStore()
        state = {"messages": []}
        
        # 测试短内容（≤50字符）应丢弃
        short_content = "短内容" * 5  # 15 字符
        new_state, saved = store.add_partial_response(
            state=state,
            content=short_content,
            stop_reason="user_requested",
            min_length=50
        )
        
        if not saved:
            results.add_pass(f"短内容 ({len(short_content)} 字符) 正确丢弃")
        else:
            results.add_fail("短内容处理", "应丢弃但被保存")
        
        # 测试长内容（>50字符）应保存
        long_content = "这是一段较长的内容，用于测试部分响应保存功能。" * 3  # >50 字符
        new_state2, saved2 = store.add_partial_response(
            state=state,
            content=long_content,
            stop_reason="user_requested",
            min_length=50
        )
        
        if saved2:
            results.add_pass(f"长内容 ({len(long_content)} 字符) 正确保存")
        else:
            results.add_fail("长内容处理", "应保存但被丢弃")
            
    except Exception as e:
        results.add_fail("部分响应保存阈值", str(e))


def test_message_store_partial_response_methods():
    """测试 MessageStore 部分响应相关方法"""
    print("\n📋 测试 MessageStore 部分响应方法...")
    
    try:
        from domain.llm.message_store import MessageStore
        from domain.llm.message_types import ROLE_ASSISTANT
        
        store = MessageStore()
        state = {"messages": []}
        
        # 添加部分响应
        content = "这是一段测试内容，长度超过50字符，用于测试部分响应功能的正确性。这里需要更多的文字来确保字符串长度足够长。"
        new_state, _ = store.add_partial_response(
            state=state,
            content=content,
            reasoning_content="思考过程",
            stop_reason="user_requested"
        )
        
        # 测试 get_last_partial_message
        partial_msg = store.get_last_partial_message(new_state)
        if partial_msg and partial_msg.is_partial:
            results.add_pass("get_last_partial_message 正确返回部分响应")
        else:
            results.add_fail("get_last_partial_message", "未返回部分响应")
        
        # 测试 has_pending_partial_response
        has_partial = store.has_pending_partial_response(new_state)
        if has_partial:
            results.add_pass("has_pending_partial_response 返回 True")
        else:
            results.add_fail("has_pending_partial_response", "应返回 True")
        
        # 测试 mark_partial_as_complete
        completed_state = store.mark_partial_as_complete(new_state, " 追加内容")
        partial_after = store.get_last_partial_message(completed_state)
        if partial_after is None or not partial_after.is_partial:
            results.add_pass("mark_partial_as_complete 正确标记完成")
        else:
            results.add_fail("mark_partial_as_complete", "消息仍标记为部分")
        
        # 测试 remove_last_partial_response
        state2 = {"messages": []}
        state2, _ = store.add_partial_response(state2, content, stop_reason="test")
        removed_state = store.remove_last_partial_response(state2)
        if not store.has_pending_partial_response(removed_state):
            results.add_pass("remove_last_partial_response 正确移除")
        else:
            results.add_fail("remove_last_partial_response", "消息未移除")
            
    except Exception as e:
        results.add_fail("MessageStore 部分响应方法", str(e))


# ============================================================
# 4. 会话持久化中断点测试
# ============================================================

def test_session_interruption_state_save():
    """测试会话保存时记录中断点"""
    print("\n📋 测试会话中断点保存...")
    
    try:
        from domain.llm.message_store import MessageStore
        import json
        
        store = MessageStore()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建包含部分响应的状态
            state = {"messages": [], "conversation_summary": ""}
            content = "这是一段测试内容，长度超过50字符，用于测试会话中断点保存功能。这里需要更多的文字来确保字符串长度足够长。"
            state, _ = store.add_partial_response(
                state=state,
                content=content,
                stop_reason="user_requested",
                tool_calls_pending=[{"name": "search"}]
            )
            
            # 保存会话
            success, msg = store.save_session(state, temp_dir, "test_session")
            
            if success:
                results.add_pass("会话保存成功")
                
                # 读取会话文件检查中断点信息
                session_file = store._get_session_file_path(temp_dir, "test_session")
                data = json.loads(session_file.read_text(encoding="utf-8"))
                
                interruption = data.get("interruption_state")
                if interruption and interruption.get("has_partial_response"):
                    results.add_pass("中断点信息已记录")
                    
                    partial_info = interruption.get("partial_info")
                    if partial_info:
                        if partial_info.get("stop_reason") == "user_requested":
                            results.add_pass("stop_reason 正确记录")
                        if partial_info.get("has_pending_tools") == True:
                            results.add_pass("has_pending_tools 正确记录")
                else:
                    results.add_fail("中断点信息", "未记录或格式错误")
            else:
                results.add_fail("会话保存", msg)
                
    except Exception as e:
        results.add_fail("会话中断点保存", str(e))


def test_session_interruption_state_restore():
    """测试会话加载时恢复中断状态"""
    print("\n📋 测试会话中断点恢复...")
    
    try:
        from domain.llm.message_store import MessageStore
        
        store = MessageStore()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建并保存包含部分响应的会话
            state = {"messages": [], "conversation_summary": ""}
            content = "这是一段测试内容，长度超过50字符，用于测试会话中断点恢复功能。这里需要更多的文字来确保字符串长度足够长。"
            state, _ = store.add_partial_response(
                state=state,
                content=content,
                stop_reason="timeout"
            )
            store.save_session(state, temp_dir, "restore_test")
            
            # 加载会话
            empty_state = {"messages": [], "conversation_summary": ""}
            loaded_state, success, msg, metadata = store.load_session(
                temp_dir, "restore_test", empty_state
            )
            
            if success:
                results.add_pass("会话加载成功")
                
                # 检查元数据中的中断状态
                if metadata and metadata.get("has_partial_response"):
                    results.add_pass("中断状态正确恢复")
                else:
                    results.add_fail("中断状态恢复", "metadata 中无中断信息")
                
                # 检查消息中的部分响应标记
                partial = store.get_last_partial_message(loaded_state)
                if partial and partial.is_partial:
                    results.add_pass("部分响应消息正确恢复")
                else:
                    results.add_fail("部分响应消息", "未正确恢复")
            else:
                results.add_fail("会话加载", msg)
                
    except Exception as e:
        results.add_fail("会话中断点恢复", str(e))


# ============================================================
# 5. ResourceCleanupManager 测试
# ============================================================

def test_resource_cleanup_manager_registration():
    """测试资源清理管理器资源注册"""
    print("\n📋 测试资源清理管理器注册...")
    
    try:
        from shared.resource_cleanup import (
            ResourceCleanupManager, ResourceType
        )
        
        manager = ResourceCleanupManager()
        
        # 测试注册不同类型的资源
        # 1. 内存缓冲
        buffer = []
        rid1 = manager.register_memory_buffer(buffer, "test_buffer")
        if rid1:
            results.add_pass("内存缓冲注册成功")
        else:
            results.add_fail("内存缓冲注册", "返回空 ID")
        
        # 2. 临时文件
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name
        rid2 = manager.register_temp_file(temp_path, "test_temp")
        if rid2:
            results.add_pass("临时文件注册成功")
        else:
            results.add_fail("临时文件注册", "返回空 ID")
        
        # 3. 自定义资源
        custom_cleaned = [False]
        def custom_cleanup():
            custom_cleaned[0] = True
        
        rid3 = manager.register_custom(None, "test_custom", custom_cleanup)
        if rid3:
            results.add_pass("自定义资源注册成功")
        else:
            results.add_fail("自定义资源注册", "返回空 ID")
        
        # 检查资源计数
        count = manager.get_resource_count()
        if count == 3:
            results.add_pass(f"资源计数正确: {count}")
        else:
            results.add_fail("资源计数", f"期望 3，实际 {count}")
        
        # 清理
        os.unlink(temp_path) if os.path.exists(temp_path) else None
            
    except Exception as e:
        results.add_fail("资源清理管理器注册", str(e))


def test_resource_cleanup_manager_cleanup():
    """测试资源清理管理器清理功能"""
    print("\n📋 测试资源清理管理器清理...")
    
    try:
        from shared.resource_cleanup import ResourceCleanupManager
        
        manager = ResourceCleanupManager()
        
        # 注册可清理的资源
        cleaned_flags = {"buffer": False, "custom": False}
        
        buffer = []
        manager.register_memory_buffer(buffer, "cleanup_buffer")
        
        def custom_cleanup():
            cleaned_flags["custom"] = True
        manager.register_custom(None, "cleanup_custom", custom_cleanup)
        
        # 同步清理
        result = manager.cleanup_all_sync()
        
        if result.total == 2:
            results.add_pass(f"清理总数正确: {result.total}")
        else:
            results.add_fail("清理总数", f"期望 2，实际 {result.total}")
        
        if result.success >= 1:
            results.add_pass(f"清理成功数: {result.success}")
        else:
            results.add_fail("清理成功数", f"期望 >=1，实际 {result.success}")
        
        if cleaned_flags["custom"]:
            results.add_pass("自定义清理回调已执行")
        else:
            results.add_fail("自定义清理回调", "未执行")
        
        # 清理后资源计数应为 0
        if manager.get_resource_count() == 0:
            results.add_pass("清理后资源计数为 0")
        else:
            results.add_fail("清理后资源计数", f"应为 0，实际 {manager.get_resource_count()}")
            
    except Exception as e:
        results.add_fail("资源清理管理器清理", str(e))


def test_resource_cleanup_manager_unregister():
    """测试资源注销"""
    print("\n📋 测试资源注销...")
    
    try:
        from shared.resource_cleanup import ResourceCleanupManager
        
        manager = ResourceCleanupManager()
        
        # 注册资源
        rid = manager.register_memory_buffer([], "unregister_test")
        
        # 注销资源
        success = manager.unregister(rid)
        if success:
            results.add_pass("资源注销成功")
        else:
            results.add_fail("资源注销", "返回 False")
        
        # 再次注销应失败
        success2 = manager.unregister(rid)
        if not success2:
            results.add_pass("重复注销正确返回 False")
        else:
            results.add_fail("重复注销", "应返回 False")
        
        # 按名称注销
        manager.register_memory_buffer([], "name_test")
        manager.register_memory_buffer([], "name_test")
        count = manager.unregister_by_name("name_test")
        if count == 2:
            results.add_pass(f"按名称注销 {count} 个资源")
        else:
            results.add_fail("按名称注销", f"期望 2，实际 {count}")
            
    except Exception as e:
        results.add_fail("资源注销", str(e))


# ============================================================
# 6. LLMExecutor 资源清理集成测试
# ============================================================

def test_llm_executor_resource_cleanup_property():
    """测试 LLMExecutor 资源清理属性"""
    print("\n📋 测试 LLMExecutor 资源清理属性...")
    
    try:
        from domain.llm.llm_executor import LLMExecutor
        
        executor = LLMExecutor()
        
        # 检查 resource_cleanup 属性
        if hasattr(executor, 'resource_cleanup'):
            results.add_pass("resource_cleanup 属性存在")
            
            # 获取属性（会触发延迟初始化）
            cleanup = executor.resource_cleanup
            if cleanup is not None:
                results.add_pass("ResourceCleanupManager 初始化成功")
            else:
                results.add_skip("ResourceCleanupManager", "初始化返回 None")
        else:
            results.add_fail("resource_cleanup 属性", "属性不存在")
            
    except Exception as e:
        results.add_fail("LLMExecutor 资源清理属性", str(e))


# ============================================================
# 7. 边界情况测试
# ============================================================

def test_stop_idle_state():
    """测试空闲状态下停止请求"""
    print("\n📋 测试空闲状态停止请求...")
    
    try:
        from shared.stop_controller import StopController, StopReason
        
        controller = StopController()
        
        # 空闲状态下请求停止应返回 False
        result = controller.request_stop(StopReason.USER_REQUESTED)
        if not result:
            results.add_pass("空闲状态停止请求正确返回 False")
        else:
            results.add_fail("空闲状态停止", "应返回 False")
            
    except Exception as e:
        results.add_fail("空闲状态停止请求", str(e))


def test_empty_content_partial_response():
    """测试空内容部分响应"""
    print("\n📋 测试空内容部分响应...")
    
    try:
        from domain.llm.message_store import MessageStore
        
        store = MessageStore()
        state = {"messages": []}
        
        # 空内容应丢弃
        new_state, saved = store.add_partial_response(
            state=state,
            content="",
            stop_reason="user_requested"
        )
        
        if not saved:
            results.add_pass("空内容正确丢弃")
        else:
            results.add_fail("空内容处理", "应丢弃但被保存")
            
    except Exception as e:
        results.add_fail("空内容部分响应", str(e))


def test_exactly_threshold_content():
    """测试恰好等于阈值的内容"""
    print("\n📋 测试阈值边界内容...")
    
    try:
        from domain.llm.message_store import MessageStore
        
        store = MessageStore()
        state = {"messages": []}
        
        # 恰好 50 字符应丢弃（≤50）
        content_50 = "a" * 50
        _, saved = store.add_partial_response(
            state=state,
            content=content_50,
            stop_reason="test",
            min_length=50
        )
        
        if not saved:
            results.add_pass("50 字符内容正确丢弃")
        else:
            results.add_fail("50 字符内容", "应丢弃但被保存")
        
        # 51 字符应保存（>50）
        content_51 = "a" * 51
        _, saved2 = store.add_partial_response(
            state=state,
            content=content_51,
            stop_reason="test",
            min_length=50
        )
        
        if saved2:
            results.add_pass("51 字符内容正确保存")
        else:
            results.add_fail("51 字符内容", "应保存但被丢弃")
            
    except Exception as e:
        results.add_fail("阈值边界内容", str(e))


# ============================================================
# 8. 服务名称常量测试
# ============================================================

def test_service_names():
    """测试服务名称常量"""
    print("\n📋 测试服务名称常量...")
    
    try:
        from shared.service_names import SVC_RESOURCE_CLEANUP
        
        if SVC_RESOURCE_CLEANUP == "resource_cleanup":
            results.add_pass("SVC_RESOURCE_CLEANUP 常量正确")
        else:
            results.add_fail("SVC_RESOURCE_CLEANUP", f"值为 {SVC_RESOURCE_CLEANUP}")
            
    except ImportError as e:
        results.add_fail("服务名称常量", f"导入失败: {e}")
    except Exception as e:
        results.add_fail("服务名称常量", str(e))


# ============================================================
# 主函数
# ============================================================

def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("3.0.10/3.0.11 数据稳定性保证测试")
    print("=" * 60)
    
    # 1. StopController 超时保护测试
    test_stop_controller_timeout_constants()
    test_stop_controller_timeout_signal()
    test_stop_controller_cleanup_callbacks()
    test_stop_controller_state_transitions()
    test_stop_controller_rapid_stop_requests()
    
    # 2. Message 数据稳定性字段测试
    test_message_partial_fields()
    test_message_serialization()
    
    # 3. MessageStore 部分响应处理测试
    test_message_store_partial_response_threshold()
    test_message_store_partial_response_methods()
    
    # 4. 会话持久化中断点测试
    test_session_interruption_state_save()
    test_session_interruption_state_restore()
    
    # 5. ResourceCleanupManager 测试
    test_resource_cleanup_manager_registration()
    test_resource_cleanup_manager_cleanup()
    test_resource_cleanup_manager_unregister()
    
    # 6. LLMExecutor 资源清理集成测试
    test_llm_executor_resource_cleanup_property()
    
    # 7. 边界情况测试
    test_stop_idle_state()
    test_empty_content_partial_response()
    test_exactly_threshold_content()
    
    # 8. 服务名称常量测试
    test_service_names()
    
    # 输出汇总
    return results.summary()


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
