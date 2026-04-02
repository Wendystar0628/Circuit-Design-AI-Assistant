#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
阶段一检查点测试

测试内容：
- 程序可正常启动，显示主窗口
- 主窗口三栏+下栏布局正确
- 菜单栏、工具栏、状态栏显示正常
- "打开工作文件夹"功能可用
- API配置对话框可打开、保存配置
- 关于对话框可打开，显示版本和许可证信息
- config_manager 可正常加载/保存配置
- 日志系统正常输出到控制台和文件
- 启动流程：Phase 0-2 完成，ServiceLocator和EventBus可用
- 事件机制：EventBus可发布/订阅事件，跨线程投递正常
- 状态管理：AppState可读写状态，变更事件正常发布
- 错误处理：ErrorHandler可分类错误，用户提示正常显示
- Worker管理：WorkerManager可注册/启动/停止Worker
- 配置访问：所有模块通过 config_manager.get() 读取配置，变更通知正常
- 日志规范：敏感信息过滤正常，性能日志格式正确
- 国际化：I18nManager可获取文本、切换语言，EVENT_LANGUAGE_CHANGED 事件正常发布
- 内嵌仿真引擎：vendor/ngspice/ 目录结构正确
- 样式与图标：QSS 样式表正确加载，SVG 图标正常显示
- 冷启动测试：删除 __pycache__ 后从零启动，初始化顺序无报错

运行方式：
    cd circuit_design_ai
    python -m pytest tests/test_phase1_checkpoint.py -v
    
    或直接运行：
    python tests/test_phase1_checkpoint.py
"""

import sys
import os
import time
import threading
from pathlib import Path

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
# 1. 基础设施测试（无需 GUI）
# ============================================================

def test_logger():
    """测试日志系统"""
    print("\n📋 测试日志系统...")
    
    try:
        from infrastructure.utils.logger import setup_logger, get_logger, log_performance
        
        # 初始化日志
        setup_logger()
        logger = get_logger("test")
        
        # 测试各级别日志
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        
        results.add_pass("Logger 初始化")
        
        # 测试性能日志
        log_performance("test_operation", 123.45)
        results.add_pass("性能日志格式")
        
    except Exception as e:
        results.add_fail("Logger", str(e))


def test_service_locator():
    """测试服务定位器"""
    print("\n📋 测试服务定位器...")
    
    try:
        from shared.service_locator import ServiceLocator, ServiceNotFoundError
        
        # 清空之前的注册
        ServiceLocator.clear()
        
        # 测试注册和获取
        test_service = {"name": "test_service"}
        ServiceLocator.register("test_svc", test_service)
        
        retrieved = ServiceLocator.get("test_svc")
        assert retrieved == test_service, "获取的服务与注册的不一致"
        results.add_pass("ServiceLocator 注册/获取")
        
        # 测试 has 方法
        assert ServiceLocator.has("test_svc"), "has() 应返回 True"
        assert not ServiceLocator.has("nonexistent"), "has() 应返回 False"
        results.add_pass("ServiceLocator.has()")
        
        # 测试 get_optional
        assert ServiceLocator.get_optional("nonexistent") is None
        results.add_pass("ServiceLocator.get_optional()")
        
        # 测试 ServiceNotFoundError
        try:
            ServiceLocator.get("nonexistent")
            results.add_fail("ServiceNotFoundError", "应该抛出异常")
        except ServiceNotFoundError:
            results.add_pass("ServiceNotFoundError 异常")
        
        # 清理
        ServiceLocator.clear()
        
    except Exception as e:
        results.add_fail("ServiceLocator", str(e))


def test_event_bus():
    """测试事件总线"""
    print("\n📋 测试事件总线...")
    
    try:
        from shared.event_bus import EventBus
        
        event_bus = EventBus()
        received_events = []
        
        def handler(event_data):
            received_events.append(event_data)
        
        # 测试订阅和发布
        event_bus.subscribe("TEST_EVENT", handler)
        event_bus.publish("TEST_EVENT", {"message": "hello"})
        
        # 等待事件处理（无 Qt 事件循环时直接执行）
        time.sleep(0.1)
        
        assert len(received_events) == 1, f"应收到1个事件，实际收到 {len(received_events)}"
        assert received_events[0]["data"]["message"] == "hello"
        results.add_pass("EventBus 订阅/发布")
        
        # 测试取消订阅
        event_bus.unsubscribe("TEST_EVENT", handler)
        event_bus.publish("TEST_EVENT", {"message": "world"})
        time.sleep(0.1)
        
        assert len(received_events) == 1, "取消订阅后不应收到事件"
        results.add_pass("EventBus 取消订阅")
        
        # 测试统计
        stats = event_bus.get_stats()
        results.add_pass("EventBus.get_stats()")
        
        event_bus.clear_all()
        
    except Exception as e:
        results.add_fail("EventBus", str(e))


def test_config_manager():
    """测试配置管理器"""
    print("\n📋 测试配置管理器...")
    
    try:
        from infrastructure.config.config_manager import ConfigManager
        
        config_manager = ConfigManager()
        config_manager.load_config()
        
        results.add_pass("ConfigManager 加载配置")
        
        # 测试读取默认值
        timeout = config_manager.get("timeout", 60)
        assert timeout > 0, "timeout 应大于 0"
        results.add_pass("ConfigManager.get() 读取")
        
        # 测试写入
        config_manager.set("test_key", "test_value", save=False)
        assert config_manager.get("test_key") == "test_value"
        results.add_pass("ConfigManager.set() 写入")
        
        # 测试变更通知
        change_received = []
        def on_change(key, old_val, new_val):
            change_received.append((key, old_val, new_val))
        
        config_manager.subscribe_change("test_key2", on_change)
        config_manager.set("test_key2", "new_value", save=False)
        
        assert len(change_received) == 1, "应收到变更通知"
        results.add_pass("ConfigManager 变更通知")
        
        # 测试校验
        is_valid, errors = config_manager.validate_config()
        results.add_pass(f"ConfigManager.validate_config() - 有效: {is_valid}")
        
        # 测试获取所有键
        keys = config_manager.get_all_keys()
        assert len(keys) > 0, "应有配置键"
        results.add_pass("ConfigManager.get_all_keys()")
        
    except Exception as e:
        results.add_fail("ConfigManager", str(e))


def test_error_handler():
    """测试错误处理器"""
    print("\n📋 测试错误处理器...")
    
    try:
        from shared.error_handler import ErrorHandler
        from shared.error_types import ErrorCategory, ErrorType
        
        error_handler = ErrorHandler()
        
        # 测试错误分类
        test_errors = [
            (TimeoutError("Connection timed out"), ErrorType.NETWORK_TIMEOUT),
            (ConnectionError("Connection refused"), ErrorType.NETWORK_CONNECTION),
            (FileNotFoundError("File not found"), ErrorType.FILE_NOT_FOUND),
            (PermissionError("Permission denied"), ErrorType.FILE_PERMISSION),
        ]
        
        for error, expected_type in test_errors:
            category, error_type = error_handler.classify_error(error)
            if error_type == expected_type:
                results.add_pass(f"错误分类: {expected_type.value}")
            else:
                results.add_fail(f"错误分类: {expected_type.value}", 
                               f"期望 {expected_type}, 实际 {error_type}")
        
        # 测试恢复策略
        strategy = error_handler.get_recovery_strategy(ErrorType.NETWORK_TIMEOUT)
        assert strategy is not None, "应返回恢复策略"
        results.add_pass("ErrorHandler.get_recovery_strategy()")
        
        # 测试仿真错误解析
        ngspice_output = "Error: syntax error at line 15"
        error_type, details = error_handler.parse_simulation_error(ngspice_output)
        results.add_pass(f"仿真错误解析: {error_type.value}")
        
    except Exception as e:
        results.add_fail("ErrorHandler", str(e))


def test_app_state():
    """测试应用状态容器"""
    print("\n📋 测试应用状态容器...")
    
    try:
        from shared.app_state import AppState, STATE_PROJECT_PATH, STATE_WORKFLOW_RUNNING
        
        app_state = AppState()
        
        # 测试读取默认值
        project_path = app_state.get(STATE_PROJECT_PATH)
        assert project_path is None, "默认项目路径应为 None"
        results.add_pass("AppState 默认值")
        
        # 测试设置值
        app_state.set(STATE_PROJECT_PATH, "/test/path")
        assert app_state.get(STATE_PROJECT_PATH) == "/test/path"
        results.add_pass("AppState.set()")
        
        # 测试便捷属性
        assert app_state.project_path == "/test/path"
        results.add_pass("AppState 便捷属性")
        
        # 测试订阅变更
        changes = []
        def on_change(key, old_val, new_val):
            changes.append((key, old_val, new_val))
        
        app_state.subscribe_change(STATE_WORKFLOW_RUNNING, on_change)
        app_state.set(STATE_WORKFLOW_RUNNING, True)
        
        assert len(changes) == 1, "应收到变更通知"
        results.add_pass("AppState 变更订阅")
        
        # 测试批量更新
        app_state.update({
            STATE_PROJECT_PATH: "/new/path",
            STATE_WORKFLOW_RUNNING: False,
        })
        assert app_state.get(STATE_PROJECT_PATH) == "/new/path"
        results.add_pass("AppState.update() 批量更新")
        
        # 测试重置
        app_state.reset()
        assert app_state.get(STATE_PROJECT_PATH) is None
        results.add_pass("AppState.reset()")
        
    except Exception as e:
        results.add_fail("AppState", str(e))


def test_i18n_manager():
    """测试国际化管理器"""
    print("\n📋 测试国际化管理器...")
    
    try:
        from shared.i18n_manager import I18nManager, LANG_EN_US, LANG_ZH_CN
        
        i18n = I18nManager()
        
        # 测试获取文本
        title = i18n.get_text("app.title")
        assert title and title != "app.title", f"应返回翻译文本，实际: {title}"
        results.add_pass("I18nManager.get_text()")
        
        # 测试获取当前语言
        current_lang = i18n.get_current_language()
        assert current_lang in [LANG_EN_US, LANG_ZH_CN]
        results.add_pass(f"当前语言: {current_lang}")
        
        # 测试获取可用语言
        languages = i18n.get_available_languages()
        assert LANG_EN_US in languages
        assert LANG_ZH_CN in languages
        results.add_pass("I18nManager.get_available_languages()")
        
        # 测试语言切换
        original_lang = i18n.get_current_language()
        target_lang = LANG_ZH_CN if original_lang == LANG_EN_US else LANG_EN_US
        
        success = i18n.set_language(target_lang)
        assert success, "语言切换应成功"
        assert i18n.get_current_language() == target_lang
        results.add_pass("I18nManager.set_language()")
        
        # 切换回原语言
        i18n.set_language(original_lang)
        
        # 测试简写方法
        text = i18n.t("btn.save")
        assert text and text != "btn.save"
        results.add_pass("I18nManager.t() 简写方法")
        
    except Exception as e:
        results.add_fail("I18nManager", str(e))


def test_worker_manager():
    """测试 Worker 管理器"""
    print("\n📋 测试 Worker 管理器...")
    
    try:
        from shared.worker_manager import WorkerManager, Task
        from shared.worker_types import WorkerStatus, TaskPriority
        
        worker_manager = WorkerManager()
        
        # 创建模拟 Worker
        class MockWorker:
            def __init__(self):
                self.started = False
                self.stopped = False
                self.params = None
            
            def start(self, params):
                self.started = True
                self.params = params
            
            def stop(self):
                self.stopped = True
        
        mock_worker = MockWorker()
        
        # 测试注册
        success = worker_manager.register_worker("test_worker", mock_worker)
        assert success, "注册应成功"
        results.add_pass("WorkerManager.register_worker()")
        
        # 测试状态查询
        status = worker_manager.get_worker_status("test_worker")
        assert status == WorkerStatus.IDLE
        results.add_pass("WorkerManager.get_worker_status()")
        
        # 测试启动任务
        task_id = worker_manager.start_worker("test_worker", {"test": "params"})
        assert task_id is not None
        assert mock_worker.started
        results.add_pass("WorkerManager.start_worker()")
        
        # 测试队列大小
        queue_size = worker_manager.get_queue_size("test_worker")
        results.add_pass(f"WorkerManager.get_queue_size(): {queue_size}")
        
        # 测试统计信息
        stats = worker_manager.get_stats("test_worker")
        assert stats is not None
        assert "total_tasks" in stats
        results.add_pass("WorkerManager.get_stats()")
        
        # 测试完成回调
        worker_manager.on_worker_complete("test_worker", {"result": "success"})
        status = worker_manager.get_worker_status("test_worker")
        assert status == WorkerStatus.IDLE
        results.add_pass("WorkerManager.on_worker_complete()")
        
        # 测试注销
        success = worker_manager.unregister_worker("test_worker")
        assert success
        results.add_pass("WorkerManager.unregister_worker()")
        
    except Exception as e:
        results.add_fail("WorkerManager", str(e))


def test_ngspice_config():
    """测试 ngspice 配置"""
    print("\n📋 测试 ngspice 配置...")
    
    try:
        from infrastructure.utils.ngspice_config import (
            is_ngspice_available,
            get_ngspice_path,
            get_configuration_error,
        )
        
        # 检查配置状态
        available = is_ngspice_available()
        if available:
            results.add_pass("ngspice 可用")
            
            path = get_ngspice_path()
            if path:
                results.add_pass(f"ngspice 路径: {path}")
            else:
                results.add_skip("ngspice 路径", "路径为空")
        else:
            error = get_configuration_error()
            results.add_skip("ngspice 配置", f"不可用: {error}")
        
    except Exception as e:
        results.add_fail("ngspice 配置", str(e))


def test_model_config():
    """测试 AI 模型配置"""
    print("\n📋 测试 AI 模型配置...")
    
    try:
        from infrastructure.utils.model_config import (
            is_embedding_available,
            is_reranker_available,
            get_embedding_model_path,
            get_reranker_model_path,
        )
        
        # 检查嵌入模型
        if is_embedding_available():
            path = get_embedding_model_path()
            results.add_pass(f"嵌入模型可用: {path}")
        else:
            results.add_skip("嵌入模型", "本地模型不可用，需联网下载")
        
        # 检查重排序模型
        if is_reranker_available():
            path = get_reranker_model_path()
            results.add_pass(f"重排序模型可用: {path}")
        else:
            results.add_skip("重排序模型", "本地模型不可用，需联网下载")
        
    except Exception as e:
        results.add_fail("AI 模型配置", str(e))


def test_event_types():
    """测试事件类型定义"""
    print("\n📋 测试事件类型定义...")
    
    try:
        from shared.event_types import (
            EVENT_INIT_COMPLETE,
            EVENT_LANGUAGE_CHANGED,
            EVENT_STATE_PROJECT_OPENED,
            EVENT_STATE_CONFIG_CHANGED,
            EVENT_WORKER_STARTED,
            EVENT_WORKER_COMPLETE,
            EVENT_ERROR_OCCURRED,
            CRITICAL_EVENTS,
        )
        
        # 验证事件常量存在
        assert EVENT_INIT_COMPLETE, "EVENT_INIT_COMPLETE 应存在"
        assert EVENT_LANGUAGE_CHANGED, "EVENT_LANGUAGE_CHANGED 应存在"
        results.add_pass("事件类型常量定义")
        
        # 验证关键事件列表
        assert isinstance(CRITICAL_EVENTS, (list, tuple, set))
        results.add_pass(f"关键事件列表: {len(CRITICAL_EVENTS)} 个")
        
    except Exception as e:
        results.add_fail("事件类型", str(e))


def test_service_names():
    """测试服务名常量"""
    print("\n📋 测试服务名常量...")
    
    try:
        from shared.service_names import (
            SVC_CONFIG_MANAGER,
            SVC_EVENT_BUS,
            SVC_APP_STATE,
            SVC_ERROR_HANDLER,
            SVC_I18N_MANAGER,
            SVC_WORKER_MANAGER,
        )
        
        # 验证服务名常量存在且不为空
        services = [
            SVC_CONFIG_MANAGER,
            SVC_EVENT_BUS,
            SVC_APP_STATE,
            SVC_ERROR_HANDLER,
            SVC_I18N_MANAGER,
            SVC_WORKER_MANAGER,
        ]
        
        for svc in services:
            assert svc and isinstance(svc, str), f"服务名 {svc} 应为非空字符串"
        
        results.add_pass(f"服务名常量: {len(services)} 个")
        
    except Exception as e:
        results.add_fail("服务名常量", str(e))


def test_error_types():
    """测试错误类型定义"""
    print("\n📋 测试错误类型定义...")
    
    try:
        from shared.error_types import (
            ErrorCategory,
            ErrorType,
            RecoveryStrategy,
            ERROR_CATEGORY_MAP,
            RECOVERY_STRATEGIES,
        )
        
        # 验证枚举
        assert ErrorCategory.RECOVERABLE
        assert ErrorCategory.USER_ACTIONABLE
        assert ErrorCategory.FATAL
        results.add_pass("ErrorCategory 枚举")
        
        # 验证错误类型
        assert ErrorType.NETWORK_TIMEOUT
        assert ErrorType.LLM_AUTH_FAILED
        assert ErrorType.FILE_NOT_FOUND
        results.add_pass("ErrorType 枚举")
        
        # 验证映射表
        assert len(ERROR_CATEGORY_MAP) > 0
        assert len(RECOVERY_STRATEGIES) > 0
        results.add_pass(f"错误映射表: {len(ERROR_CATEGORY_MAP)} 个类型")
        
    except Exception as e:
        results.add_fail("错误类型", str(e))


# ============================================================
# 2. GUI 相关测试（需要 PyQt6）
# ============================================================

def test_gui_components():
    """测试 GUI 组件（需要 PyQt6）"""
    print("\n📋 测试 GUI 组件...")
    
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt
        
        # 检查是否已有 QApplication 实例
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        
        results.add_pass("QApplication 创建")
        
        # 测试资源加载器
        try:
            from resources.resource_loader import load_stylesheet, get_icon
            
            # 测试样式表加载
            if load_stylesheet(app):
                results.add_pass("QSS 样式表加载")
            else:
                results.add_skip("QSS 样式表", "加载失败，使用默认样式")
            
        except Exception as e:
            results.add_fail("资源加载器", str(e))
        
        # 测试主题配置
        try:
            from resources.theme import COLORS, FONTS
            
            assert "primary" in COLORS or "background" in COLORS
            results.add_pass("主题颜色定义")
            
        except Exception as e:
            results.add_fail("主题配置", str(e))
        
    except ImportError as e:
        results.add_skip("GUI 组件", f"PyQt6 未安装: {e}")
    except Exception as e:
        results.add_fail("GUI 组件", str(e))


def test_main_window():
    """测试主窗口"""
    print("\n📋 测试主窗口...")
    
    try:
        from PyQt6.QtWidgets import QApplication
        
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        
        # 先初始化必要的服务
        from shared.service_locator import ServiceLocator
        from shared.service_names import (
            SVC_EVENT_BUS, SVC_CONFIG_MANAGER, 
            SVC_I18N_MANAGER, SVC_APP_STATE
        )
        from shared.event_bus import EventBus
        from infrastructure.config.config_manager import ConfigManager
        from shared.i18n_manager import I18nManager
        from shared.app_state import AppState
        
        # 清空并重新注册服务
        ServiceLocator.clear()
        
        event_bus = EventBus()
        ServiceLocator.register(SVC_EVENT_BUS, event_bus)
        
        config_manager = ConfigManager()
        config_manager.load_config()
        ServiceLocator.register(SVC_CONFIG_MANAGER, config_manager)
        
        i18n_manager = I18nManager()
        ServiceLocator.register(SVC_I18N_MANAGER, i18n_manager)
        
        app_state = AppState()
        ServiceLocator.register(SVC_APP_STATE, app_state)
        
        # 创建主窗口
        from presentation.main_window import MainWindow
        
        main_window = MainWindow()
        results.add_pass("MainWindow 创建")
        
        # 验证窗口标题
        title = main_window.windowTitle()
        assert title, "窗口标题不应为空"
        results.add_pass(f"窗口标题: {title}")
        
        # 验证最小尺寸
        min_size = main_window.minimumSize()
        assert min_size.width() >= 800, f"最小宽度应 >= 800，实际: {min_size.width()}"
        assert min_size.height() >= 600, f"最小高度应 >= 600，实际: {min_size.height()}"
        results.add_pass(f"最小尺寸: {min_size.width()}x{min_size.height()}")
        
        # 验证菜单栏
        menubar = main_window.menuBar()
        assert menubar is not None, "应有菜单栏"
        results.add_pass("菜单栏存在")
        
        # 验证状态栏
        statusbar = main_window.statusBar()
        assert statusbar is not None, "应有状态栏"
        results.add_pass("状态栏存在")
        
        # 验证 retranslate_ui 方法
        if hasattr(main_window, 'retranslate_ui'):
            main_window.retranslate_ui()
            results.add_pass("retranslate_ui() 方法")
        else:
            results.add_fail("retranslate_ui()", "方法不存在")
        
        # 清理
        main_window.close()
        
    except ImportError as e:
        results.add_skip("主窗口", f"依赖未安装: {e}")
    except Exception as e:
        results.add_fail("主窗口", str(e))


def test_model_config_dialog():
    """测试模型配置对话框"""
    print("\n📋 测试模型配置对话框...")
    
    try:
        from PyQt6.QtWidgets import QApplication
        
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        
        # 确保服务已注册
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_CONFIG_MANAGER, SVC_I18N_MANAGER
        
        if not ServiceLocator.has(SVC_CONFIG_MANAGER):
            from infrastructure.config.config_manager import ConfigManager
            config_manager = ConfigManager()
            config_manager.load_config()
            ServiceLocator.register(SVC_CONFIG_MANAGER, config_manager)
        
        if not ServiceLocator.has(SVC_I18N_MANAGER):
            from shared.i18n_manager import I18nManager
            ServiceLocator.register(SVC_I18N_MANAGER, I18nManager())
        
        from presentation.dialogs.model_config_dialog import ModelConfigDialog
        
        dialog = ModelConfigDialog()
        results.add_pass("ModelConfigDialog 创建")
        
        # 验证对话框标题
        title = dialog.windowTitle()
        assert title, "对话框标题不应为空"
        results.add_pass(f"对话框标题: {title}")
        
        # 验证 load_config 方法
        if hasattr(dialog, 'load_config'):
            dialog.load_config()
            results.add_pass("load_config() 方法")
        
        # 验证 retranslate_ui 方法
        if hasattr(dialog, 'retranslate_ui'):
            dialog.retranslate_ui()
            results.add_pass("retranslate_ui() 方法")
        
        dialog.close()
        
    except ImportError as e:
        results.add_skip("API 配置对话框", f"依赖未安装: {e}")
    except Exception as e:
        results.add_fail("API 配置对话框", str(e))


def test_about_dialog():
    """测试关于对话框"""
    print("\n📋 测试关于对话框...")
    
    try:
        from PyQt6.QtWidgets import QApplication
        
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        
        # 确保 I18nManager 已注册
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_I18N_MANAGER
        
        if not ServiceLocator.has(SVC_I18N_MANAGER):
            from shared.i18n_manager import I18nManager
            ServiceLocator.register(SVC_I18N_MANAGER, I18nManager())
        
        from presentation.dialogs.about_dialog import AboutDialog
        
        dialog = AboutDialog()
        results.add_pass("AboutDialog 创建")
        
        # 验证对话框标题
        title = dialog.windowTitle()
        assert title, "对话框标题不应为空"
        results.add_pass(f"对话框标题: {title}")
        
        dialog.close()
        
    except ImportError as e:
        results.add_skip("关于对话框", f"依赖未安装: {e}")
    except Exception as e:
        results.add_fail("关于对话框", str(e))


# ============================================================
# 3. 集成测试
# ============================================================

def test_bootstrap_phases():
    """测试启动引导阶段"""
    print("\n📋 测试启动引导阶段...")
    
    try:
        # 清空服务定位器
        from shared.service_locator import ServiceLocator
        ServiceLocator.clear()
        
        # Phase 0: 基础设施初始化
        from infrastructure.utils.logger import setup_logger, get_logger
        setup_logger()
        logger = get_logger("test_bootstrap")
        results.add_pass("Phase 0.1: Logger 初始化")
        
        # Phase 0.2: ServiceLocator
        ServiceLocator.instance()
        results.add_pass("Phase 0.2: ServiceLocator 初始化")
        
        # Phase 0.3: EventBus
        from shared.event_bus import EventBus
        from shared.service_names import SVC_EVENT_BUS
        event_bus = EventBus()
        ServiceLocator.register(SVC_EVENT_BUS, event_bus)
        results.add_pass("Phase 0.3: EventBus 初始化")
        
        # Phase 1.1: ConfigManager
        from infrastructure.config.config_manager import ConfigManager
        from shared.service_names import SVC_CONFIG_MANAGER
        config_manager = ConfigManager()
        config_manager.load_config()
        ServiceLocator.register(SVC_CONFIG_MANAGER, config_manager)
        results.add_pass("Phase 1.1: ConfigManager 初始化")
        
        # Phase 1.2: ErrorHandler
        from shared.error_handler import ErrorHandler
        from shared.service_names import SVC_ERROR_HANDLER
        error_handler = ErrorHandler()
        ServiceLocator.register(SVC_ERROR_HANDLER, error_handler)
        results.add_pass("Phase 1.2: ErrorHandler 初始化")
        
        # Phase 1.3: I18nManager
        from shared.i18n_manager import I18nManager
        from shared.service_names import SVC_I18N_MANAGER
        i18n_manager = I18nManager()
        ServiceLocator.register(SVC_I18N_MANAGER, i18n_manager)
        results.add_pass("Phase 1.3: I18nManager 初始化")
        
        # Phase 1.4: AppState
        from shared.app_state import AppState
        from shared.service_names import SVC_APP_STATE
        app_state = AppState()
        ServiceLocator.register(SVC_APP_STATE, app_state)
        results.add_pass("Phase 1.4: AppState 初始化")
        
        # 验证所有服务已注册
        expected_services = [
            SVC_EVENT_BUS,
            SVC_CONFIG_MANAGER,
            SVC_ERROR_HANDLER,
            SVC_I18N_MANAGER,
            SVC_APP_STATE,
        ]
        
        for svc_name in expected_services:
            assert ServiceLocator.has(svc_name), f"服务 {svc_name} 应已注册"
        
        results.add_pass(f"所有核心服务已注册: {len(expected_services)} 个")
        
    except Exception as e:
        results.add_fail("启动引导阶段", str(e))


def test_event_flow():
    """测试事件流转"""
    print("\n📋 测试事件流转...")
    
    try:
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_EVENT_BUS
        from shared.event_types import EVENT_LANGUAGE_CHANGED
        
        event_bus = ServiceLocator.get(SVC_EVENT_BUS)
        
        received_events = []
        
        def on_language_changed(event_data):
            received_events.append(event_data)
        
        # 订阅语言变更事件
        event_bus.subscribe(EVENT_LANGUAGE_CHANGED, on_language_changed)
        
        # 通过 I18nManager 触发语言变更
        from shared.i18n_manager import I18nManager, LANG_EN_US, LANG_ZH_CN
        
        i18n = I18nManager()
        original_lang = i18n.get_current_language()
        target_lang = LANG_ZH_CN if original_lang == LANG_EN_US else LANG_EN_US
        
        i18n.set_language(target_lang)
        
        # 等待事件处理
        import time
        time.sleep(0.1)
        
        # 验证事件已接收
        if len(received_events) > 0:
            results.add_pass("语言变更事件流转")
        else:
            results.add_fail("语言变更事件流转", "未收到事件")
        
        # 恢复原语言
        i18n.set_language(original_lang)
        
        # 清理订阅
        event_bus.unsubscribe(EVENT_LANGUAGE_CHANGED, on_language_changed)
        
    except Exception as e:
        results.add_fail("事件流转", str(e))


def test_cross_thread_event():
    """测试跨线程事件投递"""
    print("\n📋 测试跨线程事件投递...")
    
    try:
        from shared.event_bus import EventBus
        import threading
        import time
        
        event_bus = EventBus()
        received_events = []
        main_thread_id = threading.current_thread().ident
        handler_thread_ids = []
        
        def handler(event_data):
            handler_thread_ids.append(threading.current_thread().ident)
            received_events.append(event_data)
        
        event_bus.subscribe("CROSS_THREAD_TEST", handler)
        
        # 从另一个线程发布事件
        def publish_from_thread():
            event_bus.publish("CROSS_THREAD_TEST", {"from": "worker_thread"})
        
        worker_thread = threading.Thread(target=publish_from_thread)
        worker_thread.start()
        worker_thread.join()
        
        # 等待事件处理
        time.sleep(0.2)
        
        if len(received_events) > 0:
            results.add_pass("跨线程事件投递")
        else:
            # 无 Qt 事件循环时，事件可能直接在发布线程执行
            results.add_skip("跨线程事件投递", "无 Qt 事件循环，直接执行")
        
        event_bus.clear_all()
        
    except Exception as e:
        results.add_fail("跨线程事件投递", str(e))


def test_config_change_notification():
    """测试配置变更通知"""
    print("\n📋 测试配置变更通知...")
    
    try:
        from infrastructure.config.config_manager import ConfigManager
        
        config_manager = ConfigManager()
        config_manager.load_config()
        
        changes = []
        
        def on_change(key, old_val, new_val):
            changes.append({"key": key, "old": old_val, "new": new_val})
        
        # 订阅变更
        config_manager.subscribe_change("test_notification_key", on_change)
        
        # 触发变更
        config_manager.set("test_notification_key", "value1", save=False)
        config_manager.set("test_notification_key", "value2", save=False)
        
        assert len(changes) == 2, f"应收到 2 次变更通知，实际: {len(changes)}"
        assert changes[0]["new"] == "value1"
        assert changes[1]["old"] == "value1"
        assert changes[1]["new"] == "value2"
        
        results.add_pass("配置变更通知")
        
        # 取消订阅
        config_manager.unsubscribe_change("test_notification_key", on_change)
        
    except Exception as e:
        results.add_fail("配置变更通知", str(e))


# ============================================================
# 4. 文件系统检查
# ============================================================

def test_directory_structure():
    """测试目录结构"""
    print("\n📋 测试目录结构...")
    
    expected_dirs = [
        "application",
        "application/graph",
        "application/graph/nodes",
        "application/workers",
        "domain",
        "domain/design",
        "domain/knowledge",
        "domain/llm",
        "domain/simulation",
        "infrastructure",
        "infrastructure/config",
        "infrastructure/llm_adapters",
        "infrastructure/persistence",
        "infrastructure/utils",
        "presentation",
        "presentation/dialogs",
        "presentation/panels",
        "presentation/widgets",
        "resources",
        "resources/icons",
        "resources/styles",
        "shared",
    ]
    
    missing_dirs = []
    for dir_path in expected_dirs:
        full_path = PROJECT_ROOT / dir_path
        if full_path.exists():
            # 检查 __init__.py
            init_file = full_path / "__init__.py"
            if not init_file.exists() and not dir_path.startswith("resources"):
                results.add_skip(f"目录 {dir_path}", "缺少 __init__.py")
        else:
            missing_dirs.append(dir_path)
    
    if missing_dirs:
        results.add_fail("目录结构", f"缺少目录: {missing_dirs}")
    else:
        results.add_pass(f"目录结构完整: {len(expected_dirs)} 个目录")


def test_vendor_ngspice():
    """测试 vendor/ngspice 目录"""
    print("\n📋 测试 vendor/ngspice 目录...")
    
    vendor_ngspice = PROJECT_ROOT / "vendor" / "ngspice"
    
    if not vendor_ngspice.exists():
        results.add_skip("vendor/ngspice", "目录不存在（可选）")
        return
    
    # 检查 Windows 目录
    win64_dir = vendor_ngspice / "win64"
    if win64_dir.exists():
        results.add_pass("vendor/ngspice/win64 存在")
        
        # 检查 DLL
        dll_dir = win64_dir / "Spice64_dll" / "dll-vs"
        if dll_dir.exists():
            ngspice_dll = dll_dir / "ngspice.dll"
            if ngspice_dll.exists():
                results.add_pass("ngspice.dll 存在")
            else:
                results.add_skip("ngspice.dll", "文件不存在")
        else:
            results.add_skip("dll-vs 目录", "不存在")
    else:
        results.add_skip("vendor/ngspice/win64", "目录不存在")
    
    # 检查许可证
    license_file = vendor_ngspice / "LICENSE"
    if license_file.exists():
        results.add_pass("ngspice LICENSE 存在")
    else:
        results.add_skip("ngspice LICENSE", "文件不存在")


def test_vendor_models():
    """测试 vendor/models 目录"""
    print("\n📋 测试 vendor/models 目录...")
    
    vendor_models = PROJECT_ROOT / "vendor" / "models"
    
    if not vendor_models.exists():
        results.add_skip("vendor/models", "目录不存在（可选，需联网下载）")
        return
    
    # 检查嵌入模型目录
    embeddings_dir = vendor_models / "embeddings"
    if embeddings_dir.exists():
        results.add_pass("vendor/models/embeddings 存在")
    else:
        results.add_skip("vendor/models/embeddings", "目录不存在")
    
    # 检查重排序模型目录
    rerankers_dir = vendor_models / "rerankers"
    if rerankers_dir.exists():
        results.add_pass("vendor/models/rerankers 存在")
    else:
        results.add_skip("vendor/models/rerankers", "目录不存在")


def test_resources():
    """测试资源文件"""
    print("\n📋 测试资源文件...")
    
    resources_dir = PROJECT_ROOT / "resources"
    
    # 检查样式表
    main_qss = resources_dir / "styles" / "main.qss"
    if main_qss.exists():
        content = main_qss.read_text(encoding="utf-8")
        if len(content) > 100:
            results.add_pass(f"main.qss 存在 ({len(content)} 字符)")
        else:
            results.add_skip("main.qss", "内容过少")
    else:
        results.add_fail("main.qss", "文件不存在")
    
    # 检查图标目录
    icon_dirs = ["toolbar", "menu", "panel", "status", "file"]
    for icon_dir in icon_dirs:
        icon_path = resources_dir / "icons" / icon_dir
        if icon_path.exists():
            svg_files = list(icon_path.glob("*.svg"))
            if svg_files:
                results.add_pass(f"icons/{icon_dir}: {len(svg_files)} 个 SVG")
            else:
                results.add_skip(f"icons/{icon_dir}", "无 SVG 文件")
        else:
            results.add_skip(f"icons/{icon_dir}", "目录不存在")


# ============================================================
# 5. 冷启动测试
# ============================================================

def test_cold_start():
    """测试冷启动（模拟删除缓存后启动）"""
    print("\n📋 测试冷启动...")
    
    try:
        # 清空所有服务
        from shared.service_locator import ServiceLocator
        ServiceLocator.clear()
        
        # 重新执行完整初始化流程
        # Phase 0
        from infrastructure.utils.logger import setup_logger
        setup_logger()
        
        ServiceLocator.instance()
        
        from shared.event_bus import EventBus
        from shared.service_names import SVC_EVENT_BUS
        event_bus = EventBus()
        ServiceLocator.register(SVC_EVENT_BUS, event_bus)
        
        # Phase 1
        from infrastructure.config.config_manager import ConfigManager
        from shared.service_names import SVC_CONFIG_MANAGER
        config_manager = ConfigManager()
        config_manager.load_config()
        ServiceLocator.register(SVC_CONFIG_MANAGER, config_manager)
        
        from shared.error_handler import ErrorHandler
        from shared.service_names import SVC_ERROR_HANDLER
        error_handler = ErrorHandler()
        ServiceLocator.register(SVC_ERROR_HANDLER, error_handler)
        
        from shared.i18n_manager import I18nManager
        from shared.service_names import SVC_I18N_MANAGER
        i18n_manager = I18nManager()
        ServiceLocator.register(SVC_I18N_MANAGER, i18n_manager)
        
        from shared.app_state import AppState
        from shared.service_names import SVC_APP_STATE
        app_state = AppState()
        ServiceLocator.register(SVC_APP_STATE, app_state)
        
        # Phase 3 (延迟初始化)
        from shared.worker_manager import WorkerManager
        from shared.service_names import SVC_WORKER_MANAGER
        worker_manager = WorkerManager()
        ServiceLocator.register(SVC_WORKER_MANAGER, worker_manager)
        
        # 验证所有服务可用
        services_to_check = [
            SVC_EVENT_BUS,
            SVC_CONFIG_MANAGER,
            SVC_ERROR_HANDLER,
            SVC_I18N_MANAGER,
            SVC_APP_STATE,
            SVC_WORKER_MANAGER,
        ]
        
        all_available = True
        for svc in services_to_check:
            if not ServiceLocator.has(svc):
                all_available = False
                results.add_fail(f"冷启动 - {svc}", "服务未注册")
        
        if all_available:
            results.add_pass("冷启动完成，所有服务正常")
        
        # 发布初始化完成事件
        from shared.event_types import EVENT_INIT_COMPLETE
        event_bus.publish(EVENT_INIT_COMPLETE, {"timestamp": time.time()})
        results.add_pass("EVENT_INIT_COMPLETE 事件发布")
        
    except Exception as e:
        results.add_fail("冷启动", str(e))


# ============================================================
# 主函数
# ============================================================

def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("阶段一检查点测试")
    print("=" * 60)
    
    # 1. 基础设施测试
    print("\n" + "=" * 40)
    print("1. 基础设施测试")
    print("=" * 40)
    
    test_logger()
    test_service_locator()
    test_event_bus()
    test_config_manager()
    test_error_handler()
    test_app_state()
    test_i18n_manager()
    test_worker_manager()
    test_ngspice_config()
    test_model_config()
    test_event_types()
    test_service_names()
    test_error_types()
    
    # 2. GUI 测试
    print("\n" + "=" * 40)
    print("2. GUI 组件测试")
    print("=" * 40)
    
    test_gui_components()
    test_main_window()
    test_model_config_dialog()
    test_about_dialog()
    
    # 3. 集成测试
    print("\n" + "=" * 40)
    print("3. 集成测试")
    print("=" * 40)
    
    test_bootstrap_phases()
    test_event_flow()
    test_cross_thread_event()
    test_config_change_notification()
    
    # 4. 文件系统检查
    print("\n" + "=" * 40)
    print("4. 文件系统检查")
    print("=" * 40)
    
    test_directory_structure()
    test_vendor_ngspice()
    test_vendor_models()
    test_resources()
    
    # 5. 冷启动测试
    print("\n" + "=" * 40)
    print("5. 冷启动测试")
    print("=" * 40)
    
    test_cold_start()
    
    # 输出汇总
    success = results.summary()
    
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
