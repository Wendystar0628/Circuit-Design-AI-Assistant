# Circuit Design AI - Application Bootstrap
"""
应用启动引导器，负责整个应用的初始化编排

职责：
- 集中管理所有初始化逻辑
- 协调各组件的启动顺序
- 处理初始化失败和降级策略

当前状态主线：
- MainWindow/PanelManager/WindowStateManager 管理界面状态
- SessionStateManager/ContextManager 管理会话与消息
- SessionState + SessionStateProjector 提供项目/RAG 状态的轻量 UI 读模型

并发模型架构（qasync 融合事件循环）：
- 使用 qasync 将 asyncio 事件循环挂载到 Qt 事件循环上
- 所有 I/O 密集型任务在主线程协程中执行（通过 @asyncSlot 装饰器）
- 外部进程使用 ProcessManager 管理
- 消除"双循环同步"问题，避免死锁和竞态条件

初始化顺序（严格按此顺序执行）：
- Phase -1: ngspice 和 AI 模型路径配置（必须在所有其他导入之前）
- Phase 0: 基础设施初始化（同步，阻塞式）
  - 0.0 全局配置目录初始化
  - 0.1 Logger 初始化
  - 0.2 ServiceLocator 初始化
  - 0.3 EventBus 初始化
- Phase 1: 核心管理器初始化（同步，阻塞式）
  - 1.0 CredentialManager 初始化
  - 1.1 ConfigManager 初始化
  - 1.2 ErrorHandler 初始化
  - 1.3 I18nManager 初始化
  - 1.4 ModelRegistry 初始化
- Phase 2: GUI 框架初始化（同步，阻塞式）
  - 2.0.1 预导入 WebEngine
  - 2.1 创建 QApplication 实例
  - 2.1.2 初始化 qasync 融合事件循环
  - 2.2 创建 MainWindow 实例
  - 2.3 显示主窗口
  - 2.4 触发延迟初始化
- Phase 3: 延迟初始化（异步，在融合事件循环中执行）
  - 3.2 FileManager 初始化
  - 3.2.1 FileSearchService 初始化（精确搜索引擎）
  - 3.3 ProjectService 初始化
  - 3.4 ContextManager 初始化
  - 3.5 SessionStateManager 初始化
  - 3.5.1 SessionState 初始化（项目/RAG 状态投影容器）
  - 3.5.2 SessionStateProjector 初始化
  - 3.6 LLM 客户端初始化
  - 3.6.1 订阅 EVENT_LLM_CONFIG_CHANGED（应用层响应配置变更，刷新 LLM 运行时）
  - 3.8 RAG 服务初始化（RAGManager + DocumentWatcher）
  - 3.7 发布 EVENT_INIT_COMPLETE 事件
- 应用关闭时：
  - 在 qasync 循环仍可用时停止 LLM、仿真、RAG 和文件监听
  - 关闭项目及 LLM 网络客户端
  - 最后取消遗留 asyncio task 并关闭事件循环

注意：ngspice/模型路径配置只由 ``run()`` 显式执行；导入任意
``application`` 子模块都不会隐式修改进程环境。
"""

import sys
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Optional

# 类型检查时导入（避免运行时循环导入）
if TYPE_CHECKING:
    from PyQt6.QtWidgets import QMainWindow

# Runtime path configuration belongs to the explicit GUI entry point.  Keeping
# it out of module import makes application services safe to reuse from tests,
# command-line helpers, and packaging discovery.
_runtime_paths_configured = False


def _configure_runtime_paths() -> None:
    """Configure native/runtime paths once, as the first action of ``run``."""
    global _runtime_paths_configured
    if _runtime_paths_configured:
        return

    from infrastructure.utils.ngspice_config import (
        configure_ngspice,
        get_configuration_error,
    )
    from infrastructure.utils.model_config import (
        configure_models,
        get_configuration_errors,
        is_embedding_available,
        is_reranker_available,
    )

    if not configure_ngspice():
        print(f"[WARNING] ngspice 配置失败: {get_configuration_error()}")
        print("[WARNING] 仿真功能可能不可用")
    else:
        print("[Phase -1.1] ngspice 配置成功")

    if not configure_models():
        print("[WARNING] AI 模型配置失败，RAG 功能可能需要联网下载模型")
        for error in get_configuration_errors().values():
            print(f"  - {error}")
    else:
        embedding_status = "[OK] 本地可用" if is_embedding_available() else "需联网下载"
        reranker_status = "[OK] 本地可用" if is_reranker_available() else "需联网下载"
        print("[Phase -1.2] AI 模型配置完成")
        print(f"  - 嵌入模型: {embedding_status}")
        print(f"  - 重排序模型: {reranker_status}")

    _runtime_paths_configured = True


# ============================================================
# 模块级变量（用于跨函数访问）
# ============================================================
_logger = None  # 日志器实例，Phase 0.1 后可用
_main_window = None  # 主窗口实例，Phase 2.2 后可用


def _init_phase_0() -> bool:
    """
    Phase 0: 基础设施初始化（同步，阻塞式）
    
    0.0 全局配置目录初始化
    0.1 Logger 初始化（最先，其他模块都需要日志）
    0.2 ServiceLocator 初始化（创建空容器）
    0.3 EventBus 初始化（创建事件总线并注册）
    
    Returns:
        bool: 初始化是否成功
    """
    global _logger

    try:
        # --------------------------------------------------------
        # 0.0 全局配置目录初始化
        # 创建 ~/.circuit_design_ai/ 及其子目录
        # --------------------------------------------------------
        from infrastructure.config.settings import GLOBAL_CONFIG_DIR, GLOBAL_LOG_DIR
        
        # 创建全局配置目录
        GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        # 创建日志目录
        GLOBAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
        
        # 创建 prompts 目录结构
        prompts_system_dir = GLOBAL_CONFIG_DIR / "prompts" / "system"
        prompts_custom_dir = GLOBAL_CONFIG_DIR / "prompts" / "custom"
        prompts_system_dir.mkdir(parents=True, exist_ok=True)
        prompts_custom_dir.mkdir(parents=True, exist_ok=True)
        
        # 复制内置 Prompt 模板到 prompts/system/（若不存在或版本更新）
        _copy_builtin_prompts(prompts_system_dir)
        
        print("[Phase 0.0] 全局配置目录初始化完成")

        # --------------------------------------------------------
        # 0.1 Logger 初始化（最先，其他模块都需要日志）
        # --------------------------------------------------------
        from infrastructure.utils.logger import setup_logger, get_logger
        setup_logger()
        _logger = get_logger("bootstrap")
        _logger.info("Phase 0.1 Logger 初始化完成")

        # --------------------------------------------------------
        # 0.2 ServiceLocator 初始化（创建空容器）
        # --------------------------------------------------------
        from shared.service_locator import ServiceLocator
        ServiceLocator.instance()
        _logger.info("Phase 0.2 ServiceLocator 初始化完成")

        # --------------------------------------------------------
        # 0.3 EventBus 初始化（创建事件总线并注册到 ServiceLocator）
        # --------------------------------------------------------
        from shared.event_bus import EventBus
        from shared.service_names import SVC_EVENT_BUS
        event_bus = EventBus()
        ServiceLocator.register(SVC_EVENT_BUS, event_bus)
        _logger.info("Phase 0.3 EventBus 初始化完成")

        return True

    except Exception as e:
        # Logger 失败时回退到 print() 输出
        print(f"[Phase 0] 初始化失败: {e}")
        traceback.print_exc()
        return False


def _copy_builtin_prompts(target_dir: Path) -> None:
    """
    复制内置 Prompt 模板到全局配置目录
    
    仅在目标文件不存在或版本更新时复制
    
    Args:
        target_dir: 目标目录（~/.circuit_design_ai/prompts/system/）
    """
    import shutil
    import json
    
    # 获取内置 prompts 目录
    base_path = Path(__file__).parent.parent
    builtin_prompts_dir = base_path / "resources" / "prompts"
    
    if not builtin_prompts_dir.exists():
        return
    
    # 检查版本文件
    builtin_version_file = builtin_prompts_dir / "version.json"
    target_version_file = target_dir / "version.json"
    
    need_copy = False
    
    if not target_version_file.exists():
        need_copy = True
    elif builtin_version_file.exists():
        try:
            with open(builtin_version_file, 'r', encoding='utf-8') as f:
                builtin_version = json.load(f).get("version", "0.0.0")
            with open(target_version_file, 'r', encoding='utf-8') as f:
                target_version = json.load(f).get("version", "0.0.0")
            if builtin_version > target_version:
                need_copy = True
        except Exception:
            need_copy = True
    
    if need_copy:
        # 复制所有 prompt 文件
        for file_path in builtin_prompts_dir.glob("*.json"):
            target_file = target_dir / file_path.name
            shutil.copy2(file_path, target_file)



def _init_phase_1() -> bool:
    """
    Phase 1: 核心管理器初始化（同步，阻塞式）
    
    1.0 CredentialManager 初始化（依赖 Logger）
    1.1 ConfigManager 初始化（依赖 Logger、CredentialManager）
    1.2 ErrorHandler 初始化（依赖 Logger、EventBus、ConfigManager）
    1.3 I18nManager 初始化（依赖 ConfigManager）
    1.4 ModelRegistry 初始化（依赖 Logger）
    
    Returns:
        bool: 初始化是否成功
    """
    try:
        # --------------------------------------------------------
        # 1.0 CredentialManager 初始化
        # 依赖：Logger（记录凭证操作日志）
        # 职责：加载凭证
        # --------------------------------------------------------
        from infrastructure.config.credential_manager import CredentialManager
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_CREDENTIAL_MANAGER
        credential_manager = CredentialManager()
        credential_manager.load_credentials()
        ServiceLocator.register(SVC_CREDENTIAL_MANAGER, credential_manager)
        if _logger:
            _logger.info("Phase 1.0 CredentialManager 初始化完成")

        # --------------------------------------------------------
        # 1.1 ConfigManager 初始化
        # 依赖：Logger、CredentialManager（获取凭证）
        # 职责：加载配置，缺失字段使用默认值，校验失败时记录日志
        # --------------------------------------------------------
        from infrastructure.config.config_manager import ConfigManager
        from shared.service_names import SVC_CONFIG_MANAGER
        config_manager = ConfigManager()
        config_manager.load_config()
        ServiceLocator.register(SVC_CONFIG_MANAGER, config_manager)
        if _logger:
            _logger.info("Phase 1.1 ConfigManager 初始化完成")

        # --------------------------------------------------------
        # 1.2 ErrorHandler 初始化
        # 依赖：Logger、EventBus（延迟获取）、ConfigManager
        # 职责：初始化错误分类规则和恢复策略
        # --------------------------------------------------------
        from shared.error_handler import ErrorHandler
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_ERROR_HANDLER
        error_handler = ErrorHandler()
        ServiceLocator.register(SVC_ERROR_HANDLER, error_handler)
        if _logger:
            _logger.info("Phase 1.2 ErrorHandler 初始化完成")

        # --------------------------------------------------------
        # 1.3 I18nManager 初始化
        # 依赖：ConfigManager（读取 language 配置）
        # 职责：加载文本字典，设置当前语言
        # --------------------------------------------------------
        from shared.i18n_manager import I18nManager
        from shared.service_names import SVC_I18N_MANAGER
        i18n_manager = I18nManager()
        ServiceLocator.register(SVC_I18N_MANAGER, i18n_manager)
        if _logger:
            _logger.info(f"Phase 1.3 I18nManager 初始化完成，当前语言: {i18n_manager.get_current_language()}")

        # --------------------------------------------------------
        # 1.4 ModelRegistry 初始化
        # 依赖：Logger
        # 职责：注册所有内置模型配置，作为模型信息的单一信息源
        # --------------------------------------------------------
        from shared.model_registry import ModelRegistry
        from shared.embedding_model_registry import EmbeddingModelRegistry
        from infrastructure.config.llm_runtime_config_manager import LLMRuntimeConfigManager
        from shared.service_names import SVC_LLM_RUNTIME_CONFIG_MANAGER
        ModelRegistry.initialize()
        EmbeddingModelRegistry.initialize()
        ServiceLocator.register(SVC_LLM_RUNTIME_CONFIG_MANAGER, LLMRuntimeConfigManager())
        if _logger:
            _logger.info("Phase 1.4 ModelRegistry / EmbeddingModelRegistry / LLMRuntimeConfigManager 初始化完成")

        return True

    except Exception as e:
        if _logger:
            _logger.error(f"Phase 1 初始化失败: {e}")
        else:
            print(f"[Phase 1] 初始化失败: {e}")
        traceback.print_exc()
        return False


def _init_phase_2(app) -> Optional['QMainWindow']:
    """
    Phase 2: GUI 框架初始化（同步，阻塞式）
    
    2.1 QApplication 实例已在外部创建
    2.2 创建 MainWindow 实例（依赖 ServiceLocator 获取 I18nManager 等）
    2.3 显示主窗口
    2.4 触发延迟初始化
    
    Args:
        app: QApplication 实例
        
    Returns:
        MainWindow: 主窗口实例，失败返回 None
    """
    global _main_window

    try:
        # --------------------------------------------------------
        # 2.2 创建 MainWindow 实例
        # 依赖：ServiceLocator（获取 I18nManager 等）
        # 职责：仅创建布局骨架，不加载数据
        # --------------------------------------------------------
        from presentation.main_window import MainWindow
        main_window = MainWindow()
        if _logger:
            _logger.info("Phase 2.2 MainWindow 创建完成")

        # --------------------------------------------------------
        # 2.3 显示主窗口
        # --------------------------------------------------------
        main_window.show()
        if _logger:
            _logger.info("Phase 2.3 MainWindow 显示")
        else:
            print("[Phase 2.3] MainWindow 显示")

        # --------------------------------------------------------
        # 2.4 触发延迟初始化
        # 使用 QTimer.singleShot(0, ...) 在事件循环中异步执行
        # --------------------------------------------------------
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, _delayed_init)
        if _logger:
            _logger.info("Phase 2.4 延迟初始化已调度")
        else:
            print("[Phase 2.4] 延迟初始化已调度")

        _main_window = main_window
        return main_window

    except Exception as e:
        if _logger:
            _logger.critical(f"Phase 2 初始化失败: {e}")
        else:
            print(f"[Phase 2] 初始化失败: {e}")
        traceback.print_exc()
        # MainWindow 失败是致命错误
        _show_fatal_error(f"主窗口初始化失败: {e}")
        return None



def _delayed_init():
    """
    Phase 3: 延迟初始化（异步，在事件循环中执行）
    
    3.2 FileManager 初始化（依赖 Logger、EventBus）
    3.3 ProjectService 初始化（依赖 FileManager、SessionState、EventBus）
    3.4 ContextManager 初始化（依赖 Logger、EventBus）
    3.5 SessionStateManager 初始化（依赖 Logger、EventBus、ContextManager）
    3.5.1 SessionState 初始化（项目/RAG 状态投影容器）
    3.5.2 SessionStateProjector 初始化
    3.6 LLM 客户端初始化（可选）
    3.7 发布 EVENT_INIT_COMPLETE 事件
    
    此回调在 Qt 主线程执行；耗时工作必须由各专用 manager 提交到
    asyncio/executor，不能在这里同步扫描或预热。
    """
    try:
        from shared.service_locator import ServiceLocator

        # --------------------------------------------------------
        # 3.2 FileManager 初始化
        # 依赖：Logger、EventBus
        # 职责：提供统一文件操作接口（同步底层接口）
        # --------------------------------------------------------
        from infrastructure.persistence.file_manager import FileManager
        from shared.service_names import SVC_FILE_MANAGER
        file_manager = FileManager()
        # 启动时清理过期临时文件
        file_manager.cleanup_temp_files()
        ServiceLocator.register(SVC_FILE_MANAGER, file_manager)
        if _logger:
            _logger.info("Phase 3.2 FileManager 初始化完成")

        # --------------------------------------------------------
        # 3.2.1 FileSearchService 初始化
        # 依赖：FileManager、EventBus
        # 职责：精确搜索引擎（文件名、内容、符号搜索）
        # --------------------------------------------------------
        from infrastructure.file_intelligence.search.file_search_service import FileSearchService
        from shared.service_names import SVC_FILE_SEARCH_SERVICE
        file_search_service = FileSearchService()
        ServiceLocator.register(SVC_FILE_SEARCH_SERVICE, file_search_service)
        if _logger:
            _logger.info("Phase 3.2.1 FileSearchService 初始化完成")

        # UnifiedSearch/InFileSearch are not registered until their semantic
        # and exact branches are real.  Agent search continues to use the
        # working grep/find/RAG tools directly.

        # --------------------------------------------------------
        # 3.5.1 SessionState 初始化（先于 ProjectService）
        # 依赖：EventBus
        # 职责：保存 ProjectService/RAG 投影给 UI 的轻量状态
        # --------------------------------------------------------
        from application.session_state import SessionState
        from shared.service_names import SVC_SESSION_STATE
        session_state = SessionState()
        ServiceLocator.register(SVC_SESSION_STATE, session_state)
        if _logger:
            _logger.info("Phase 3.5.1 SessionState 初始化完成")

        # --------------------------------------------------------
        # 3.5.2 SessionStateProjector 初始化
        # 依赖：SessionState、EventBus
        # 职责：承接 ProjectService/RAG 到轻量 UI 读模型的投影
        # --------------------------------------------------------
        from application.session_state_projector import SessionStateProjector
        from shared.service_names import SVC_EVENT_BUS, SVC_SESSION_STATE_PROJECTOR
        session_state_projector = SessionStateProjector(
            session_state,
            event_bus=ServiceLocator.get_optional(SVC_EVENT_BUS),
        )
        ServiceLocator.register(
            SVC_SESSION_STATE_PROJECTOR,
            session_state_projector,
        )
        if _logger:
            _logger.info("Phase 3.5.2 SessionStateProjector 初始化完成")

        # --------------------------------------------------------
        # 3.3 ProjectService 初始化
        # 依赖：FileManager、SessionStateProjector、EventBus
        # 职责：管理工作文件夹的初始化和状态
        # --------------------------------------------------------
        from application.project_service import ProjectService
        from shared.service_names import SVC_PROJECT_SERVICE
        project_service = ProjectService()
        ServiceLocator.register(SVC_PROJECT_SERVICE, project_service)
        if _logger:
            _logger.info("Phase 3.3 ProjectService 初始化完成")

        # --------------------------------------------------------
        # 3.3.1 FileWatchTask 初始化
        # 依赖：EventBus
        # 职责：监测工作文件夹的文件变化，通知应用层
        # --------------------------------------------------------
        from application.tasks.file_watch_task import FileWatchTask
        from shared.service_names import SVC_FILE_WATCHER
        file_watcher = FileWatchTask()
        ServiceLocator.register(SVC_FILE_WATCHER, file_watcher)
        if _logger:
            _logger.info("Phase 3.3.1 FileWatchTask 初始化完成")

        # --------------------------------------------------------
        # 3.4 ContextManager 初始化
        # 依赖：Logger、EventBus
        # 职责：管理对话消息、Token 监控、上下文压缩
        # --------------------------------------------------------
        from domain.llm.context_manager import ContextManager
        from shared.service_names import SVC_CONTEXT_MANAGER
        context_manager = ContextManager()
        ServiceLocator.register(SVC_CONTEXT_MANAGER, context_manager)
        if _logger:
            _logger.info("Phase 3.4 ContextManager 初始化完成")

        # --------------------------------------------------------
        # 3.5 SessionStateManager 初始化
        # 依赖：Logger、EventBus、ContextManager
        # 职责：会话状态的唯一数据源（Single Source of Truth）
        # --------------------------------------------------------
        from domain.llm.session_state_manager import SessionStateManager
        from shared.service_names import SVC_SESSION_STATE_MANAGER
        session_state_manager = SessionStateManager()
        ServiceLocator.register(SVC_SESSION_STATE_MANAGER, session_state_manager)
        if _logger:
            _logger.info("Phase 3.5 SessionStateManager 初始化完成")

        from domain.llm.conversation_rollback_service import ConversationRollbackService
        from shared.service_names import SVC_CONVERSATION_ROLLBACK_SERVICE
        conversation_rollback_service = ConversationRollbackService()
        ServiceLocator.register(SVC_CONVERSATION_ROLLBACK_SERVICE, conversation_rollback_service)
        if _logger:
            _logger.info("Phase 3.5.0.1 ConversationRollbackService 初始化完成")

        from domain.llm.context_compression_service import ContextCompressionService
        from shared.service_names import SVC_CONTEXT_COMPRESSION_SERVICE
        context_compression_service = ContextCompressionService()
        ServiceLocator.register(SVC_CONTEXT_COMPRESSION_SERVICE, context_compression_service)
        if _logger:
            _logger.info("Phase 3.5.1 ContextCompressionService 初始化完成")

        from application.pending_workspace_edit_service import PendingWorkspaceEditService
        from shared.service_names import SVC_PENDING_WORKSPACE_EDIT_SERVICE
        pending_workspace_edit_service = PendingWorkspaceEditService()
        ServiceLocator.register(SVC_PENDING_WORKSPACE_EDIT_SERVICE, pending_workspace_edit_service)
        if _logger:
            _logger.info("Phase 3.5.2 PendingWorkspaceEditService 初始化完成")

        from application.metric_target_service import MetricTargetService
        from shared.service_names import SVC_METRIC_TARGET_SERVICE
        metric_target_service = MetricTargetService()
        ServiceLocator.register(SVC_METRIC_TARGET_SERVICE, metric_target_service)
        if _logger:
            _logger.info("Phase 3.5.2.1 MetricTargetService 初始化完成")

        # --------------------------------------------------------
        # 3.5.3 SimulationJobManager 初始化
        # 依赖：SpiceExecutor、SimulationService、EventBus
        # 职责：显式装配唯一的 SPICE 仿真栈，并提供唯一的 job 入口
        # --------------------------------------------------------
        _init_simulation_job_manager()

        # --------------------------------------------------------
        # 3.6 LLM 客户端初始化（可选，依赖配置）
        # 依赖：ConfigManager、CredentialManager
        # 职责：提供 LLM API 调用能力
        # --------------------------------------------------------
        _init_llm_client()

        # --------------------------------------------------------
        # 3.6.1 订阅 LLM 配置变更事件
        # 依赖：EventBus
        # 职责：当界面层发布 EVENT_LLM_CONFIG_CHANGED 后，由应用层统一负责
        #       刷新 LLM 运行时，并在模型选择发生变化时统一发布 EVENT_MODEL_CHANGED
        # --------------------------------------------------------
        from shared.service_names import SVC_EVENT_BUS
        from shared.event_types import EVENT_LLM_CONFIG_CHANGED, EVENT_MODEL_CHANGED
        _event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
        if _event_bus:
            def _on_llm_config_changed(data):
                payload = data.get("data", {}) if isinstance(data, dict) else {}
                if not isinstance(payload, dict):
                    payload = {}
                success = refresh_llm_runtime_services()

                old_model_id = payload.get("old_model_id", "") or ""
                provider = ""
                model_name = ""
                new_model_id = ""
                display_name = ""
                supports_thinking = False
                supports_vision = False

                try:
                    from shared.service_names import SVC_LLM_RUNTIME_CONFIG_MANAGER
                    from shared.model_registry import ModelRegistry

                    llm_runtime_config_manager = ServiceLocator.get_optional(SVC_LLM_RUNTIME_CONFIG_MANAGER)
                    if llm_runtime_config_manager:
                        active_config = llm_runtime_config_manager.resolve_active_config()
                        provider = active_config.provider
                        model_name = active_config.model
                        new_model_id = active_config.model_id
                        display_name = active_config.display_name or model_name

                        if new_model_id:
                            model_config = ModelRegistry.get_model(new_model_id)
                            if model_config:
                                supports_thinking = model_config.supports_thinking
                                supports_vision = model_config.supports_vision
                except Exception:
                    pass

                if new_model_id and new_model_id != old_model_id:
                    _event_bus.publish(
                        EVENT_MODEL_CHANGED,
                        data={
                            "new_model_id": new_model_id,
                            "old_model_id": old_model_id,
                            "provider": provider,
                            "model_name": model_name,
                            "display_name": display_name,
                            "supports_thinking": supports_thinking,
                            "supports_vision": supports_vision,
                        },
                        source="bootstrap",
                    )

                if _logger:
                    if success:
                        _logger.info(
                            f"Phase 3.6.1 LLM 运行时已刷新：provider={provider}"
                        )
                    else:
                        _logger.warning(
                            f"Phase 3.6.1 LLM 运行时刷新未完成：provider={provider}"
                        )
            _event_bus.subscribe(EVENT_LLM_CONFIG_CHANGED, _on_llm_config_changed)
            if _logger:
                _logger.info("Phase 3.6.1 已订阅 EVENT_LLM_CONFIG_CHANGED")

        # --------------------------------------------------------
        # 3.8 RAG 服务初始化
        # 依赖：EventBus、ConfigManager、CredentialManager
        # 职责：创建 RAGManager，订阅项目生命周期
        # --------------------------------------------------------
        _init_rag_services()

        # SessionStateProjector 订阅 RAG 事件（投影到 SessionState）
        session_state_projector = ServiceLocator.get_optional(
            SVC_SESSION_STATE_PROJECTOR
        )
        if session_state_projector:
            session_state_projector.subscribe_rag_events()
            if _logger:
                _logger.info("Phase 3.8.4 SessionStateProjector 已订阅 RAG 事件")

        # --------------------------------------------------------
        # 3.7 发布 EVENT_INIT_COMPLETE 事件
        # 通知所有订阅者初始化完成
        # --------------------------------------------------------
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_EVENT_BUS
        from shared.event_types import EVENT_INIT_COMPLETE
        event_bus = ServiceLocator.get(SVC_EVENT_BUS)
        event_bus.publish(EVENT_INIT_COMPLETE, {"timestamp": time.time()})
        if _logger:
            _logger.info("Phase 3.8 EVENT_INIT_COMPLETE 已发布")

        print("=" * 50)
        print("初始化完成！应用已就绪。")
        print("=" * 50)

        if _logger:
            _logger.info("所有初始化阶段完成，应用已就绪")

    except Exception as e:
        if _logger:
            _logger.error(f"Phase 3 延迟初始化失败: {e}")
        else:
            print(f"[Phase 3] 延迟初始化失败: {e}")
        traceback.print_exc()
        # Phase 3 失败不致命，功能降级运行
        print("[WARNING] 部分功能可能不可用，应用将以降级模式运行")



def _init_simulation_job_manager():
    """Compose and register the one simulation stack.

    A missing ngspice library is represented by a real ``SpiceExecutor`` that
    returns diagnostic failure bundles, so it is safe to keep the application
    alive in that case. Composition failure itself is different: without the
    manager the UI and agent tool have no simulation authority. Let that bug
    reach the Phase-3 boundary instead of publishing a false INIT_COMPLETE.
    """

    from domain.services.simulation_job_manager import SimulationJobManager
    from domain.services.simulation_service import SimulationService
    from domain.simulation.executor.spice_executor import SpiceExecutor
    from domain.simulation.service.simulation_result_repository import (
        simulation_result_repository,
    )
    from shared.service_locator import ServiceLocator
    from shared.service_names import SVC_EVENT_BUS, SVC_SIMULATION_JOB_MANAGER

    executor = SpiceExecutor()
    simulation_service = SimulationService(executor=executor)
    manager = SimulationJobManager(
        simulation_service=simulation_service,
        result_repository=simulation_result_repository,
        event_bus=ServiceLocator.get_optional(SVC_EVENT_BUS),
    )
    ServiceLocator.register(SVC_SIMULATION_JOB_MANAGER, manager)

    if _logger:
        _logger.info("Phase 3.5.3 SimulationJobManager 初始化完成")
        if executor.is_available():
            _logger.info("ngspice 共享库可用，SPICE 仿真功能已就绪")
        else:
            _logger.warning("ngspice 共享库不可用，SPICE 仿真请求将明确失败")


def refresh_llm_runtime_services() -> bool:
    global _logger

    try:
        import asyncio

        from shared.service_locator import ServiceLocator
        from shared.service_names import (
            SVC_CONFIG_MANAGER,
            SVC_CREDENTIAL_MANAGER,
            SVC_EVENT_BUS,
            SVC_LLM_CLIENT,
            SVC_LLM_RUNTIME_CONFIG_MANAGER,
            SVC_LLM_EXECUTOR,
        )
        from infrastructure.llm_adapters import LLMClientFactory

        config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
        credential_manager = ServiceLocator.get_optional(SVC_CREDENTIAL_MANAGER)
        llm_runtime_config_manager = ServiceLocator.get_optional(SVC_LLM_RUNTIME_CONFIG_MANAGER)

        if not config_manager or not credential_manager or not llm_runtime_config_manager:
            if _logger:
                _logger.warning("Phase 3.6 LLM 客户端初始化跳过：LLM 运行时配置依赖不可用")
            return False

        old_client = ServiceLocator.get_optional(SVC_LLM_CLIENT)
        if old_client is not None and hasattr(old_client, "close"):
            try:
                from shared.async_runtime import get_event_loop, is_initialized as is_async_runtime_initialized

                if is_async_runtime_initialized():
                    loop = get_event_loop()
                    if loop.is_running():
                        loop.create_task(old_client.close())
                    elif not loop.is_closed():
                        loop.run_until_complete(old_client.close())
                else:
                    asyncio.run(old_client.close())
            except Exception as close_exc:
                if _logger:
                    _logger.debug(f"Failed to close previous LLM client cleanly: {close_exc}")

        ServiceLocator.unregister(SVC_LLM_CLIENT)

        active_config = llm_runtime_config_manager.resolve_active_config()
        provider = active_config.provider
        if not provider:
            if _logger:
                _logger.info("Phase 3.6 LLM 客户端初始化跳过：未配置 LLM 厂商")
            return False

        if provider not in {"zhipu", "deepseek", "qwen"}:
            if _logger:
                _logger.warning(f"Phase 3.6 LLM 客户端初始化跳过：厂商 {provider} 暂未接入统一运行时")
            return False

        if not active_config.api_key:
            if _logger:
                _logger.info(f"Phase 3.6 LLM 客户端初始化跳过：{provider} 的 API Key 未配置")
            return False

        client = LLMClientFactory.create_client(
            provider_id=provider,
            api_key=active_config.api_key,
            base_url=active_config.base_url if active_config.base_url else None,
            model=active_config.model if active_config.model else None,
            timeout=active_config.timeout,
        )
        ServiceLocator.register(SVC_LLM_CLIENT, client)

        llm_executor = ServiceLocator.get_optional(SVC_LLM_EXECUTOR)
        if llm_executor is None:
            from domain.llm.llm_executor import LLMExecutor

            llm_executor = LLMExecutor()
            ServiceLocator.register(SVC_LLM_EXECUTOR, llm_executor)

        if _logger:
            _logger.info(f"Phase 3.6 LLM 客户端初始化完成：{provider}, model={active_config.model or 'default'}")
        return True

    except Exception as e:
        if _logger:
            _logger.warning(f"Phase 3.6 LLM 客户端初始化失败（非致命）: {e}")
        return False


def _init_llm_client():
    """
    初始化 LLM 客户端（可选）
    
    根据配置创建 LLM 客户端并注册到 ServiceLocator。
    如果配置不完整（如 API Key 未设置），则跳过初始化。
    """
    refresh_llm_runtime_services()


def _init_rag_services():
    """
    初始化 RAG 服务（Phase 3.8）

    3.8.1 创建 RAGManager → 注册 SVC_RAG_MANAGER
          → 订阅 EVENT_STATE_PROJECT_OPENED / EVENT_STATE_PROJECT_CLOSED
    3.8.2 创建 DocumentWatcher → 启动监听
    """
    try:
        from domain.rag.rag_manager import RAGManager
        from domain.rag.document_watcher import DocumentWatcher
        from shared.service_locator import ServiceLocator
        from shared.service_names import (
            SVC_EVENT_BUS,
            SVC_FILE_MANAGER,
            SVC_RAG_MANAGER,
        )

        event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)

        # 3.8.1 RAGManager + 订阅生命周期事件
        rag_manager = RAGManager(event_bus=event_bus)
        rag_manager.subscribe_lifecycle_events()
        ServiceLocator.register(SVC_RAG_MANAGER, rag_manager)
        if _logger:
            _logger.info("Phase 3.8.1 RAGManager 创建完成，已订阅项目生命周期事件")

        # 3.8.2 DocumentWatcher
        doc_watcher = DocumentWatcher(
            event_bus=event_bus,
            rag_manager=rag_manager,
            file_manager=ServiceLocator.get_optional(SVC_FILE_MANAGER),
        )
        rag_manager.attach_document_watcher(doc_watcher)
        doc_watcher.start()
        if _logger:
            _logger.info("Phase 3.8.2 DocumentWatcher 启动完成")

    except Exception as e:
        if _logger:
            _logger.warning(f"Phase 3.8 RAG 服务初始化失败（非致命）: {e}")
        else:
            print(f"[Phase 3.8] RAG 服务初始化失败: {e}")


def _show_fatal_error(message: str):
    """
    显示致命错误弹窗
    
    Args:
        message: 错误信息
    """
    try:
        from PyQt6.QtWidgets import QMessageBox, QApplication
        # 确保有 QApplication 实例
        if QApplication.instance() is None:
            app = QApplication(sys.argv)
        QMessageBox.critical(None, "启动错误", message)
    except Exception:
        # 如果 PyQt6 也失败了，回退到控制台输出
        print(f"[FATAL] {message}")


def _install_qt_message_filter():
    """
    安装 Qt 消息过滤器
    
    过滤无害的 Qt 内部警告消息，如字体初始化警告
    """
    from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
    
    # 需要过滤的警告消息模式
    _filtered_warnings = [
        "QFont::setPointSize: Point size <= 0",  # Qt 字体初始化时的无害警告
        "DirectWrite: CreateFontFaceFromHDC() failed",  # DirectWrite 字体加载警告（Fixedsys等旧字体）
        "Fixedsys",  # 过滤 Fixedsys 相关警告
    ]
    
    def qt_message_handler(msg_type: QtMsgType, context, message: str):
        """自定义 Qt 消息处理器"""
        # 检查是否需要过滤
        for pattern in _filtered_warnings:
            if pattern in message:
                return  # 静默忽略
        
        # 其他消息正常输出
        if msg_type == QtMsgType.QtDebugMsg:
            print(f"[Qt Debug] {message}")
        elif msg_type == QtMsgType.QtInfoMsg:
            print(f"[Qt Info] {message}")
        elif msg_type == QtMsgType.QtWarningMsg:
            print(f"[Qt Warning] {message}")
        elif msg_type == QtMsgType.QtCriticalMsg:
            print(f"[Qt Critical] {message}")
        elif msg_type == QtMsgType.QtFatalMsg:
            print(f"[Qt Fatal] {message}")
    
    qInstallMessageHandler(qt_message_handler)
    if _logger:
        _logger.debug("Qt 消息过滤器已安装")


def _setup_exception_hook():
    """
    绑定全局异常钩子
    
    未捕获异常写入日志并弹窗提示，防止程序静默崩溃
    """
    def exception_hook(exc_type, exc_value, exc_tb):
        # 格式化异常信息
        error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))

        # 记录到日志
        if _logger:
            _logger.critical(f"未捕获异常:\n{error_msg}")
        else:
            print(f"[UNCAUGHT EXCEPTION]\n{error_msg}")

        # 显示错误弹窗（仅在有 GUI 时）
        try:
            from PyQt6.QtWidgets import QApplication
            if QApplication.instance() is not None:
                _show_fatal_error(
                    f"发生未处理的错误:\n{exc_value}\n\n详细信息已记录到日志文件。"
                )
        except Exception:
            pass

        # 调用默认处理
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = exception_hook



def run() -> int:
    """
    应用程序主启动函数
    
    执行完整的初始化流程并启动 qasync 融合事件循环。
    
    qasync 融合事件循环架构：
    - 将 asyncio 事件循环挂载到 Qt 事件循环上
    - 所有异步操作在主线程协作式执行
    - 消除跨线程同步风险（死锁、信号丢失、竞态条件）
    
    Returns:
        int: 退出码，0 表示正常退出
    """
    _configure_runtime_paths()

    print("=" * 50)
    print("Circuit Design AI 启动中...")
    print(f"Python 版本: {sys.version}")
    print(f"工作目录: {Path.cwd()}")
    print("=" * 50)

    start_time = time.time()

    # 绑定全局异常钩子
    _setup_exception_hook()

    # ============================================================
    # Phase 0: 基础设施初始化
    # ============================================================
    print("\n[Phase 0] 基础设施初始化...")
    phase_0_success = _init_phase_0()
    if not phase_0_success:
        print("[Phase 0] 失败，尝试继续启动（功能可能受限）...")

    # ============================================================
    # Phase 1: 核心管理器初始化
    # ============================================================
    print("\n[Phase 1] 核心管理器初始化...")
    phase_1_success = _init_phase_1()
    if not phase_1_success:
        print("[Phase 1] 失败，尝试继续启动（功能可能受限）...")

    # 检查 Phase 0-1 耗时（应在 500ms 内完成）
    elapsed = (time.time() - start_time) * 1000
    if elapsed > 500:
        warning_msg = f"Phase 0-1 耗时 {elapsed:.0f}ms，超过 500ms 阈值"
        if _logger:
            _logger.warning(warning_msg)
        else:
            print(f"[WARNING] {warning_msg}")

    # ============================================================
    # Phase 2: GUI 框架初始化
    # ============================================================
    print("\n[Phase 2] GUI 框架初始化...")

    # 2.0 安装 Qt 消息过滤器（过滤无害的 Qt 内部警告）
    _install_qt_message_filter()

    # 2.0.1 预导入 WebEngine（必须在 QApplication 创建之前）
    # PyQt6-WebEngine 要求在 QCoreApplication 实例化之前导入
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from presentation.core.web_resource_host import register_app_web_scheme
        register_app_web_scheme()
        if _logger:
            _logger.info("Phase 2.0.1 WebEngine 预导入成功")
        else:
            print("[Phase 2.0.1] WebEngine 预导入成功")
    except ImportError as e:
        if _logger:
            _logger.warning(f"Phase 2.0.1 WebEngine 预导入失败: {e}")
        else:
            print(f"[Phase 2.0.1] WebEngine 预导入失败: {e}")

    # 2.1 创建 QApplication 实例

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QFont

    app = QApplication(sys.argv)

    try:
        from presentation.core.web_resource_host import install_app_web_resource_handler
        install_app_web_resource_handler()
        if _logger:
            _logger.info("Phase 2.1 WebEngine 资源宿主安装成功")
        else:
            print("[Phase 2.1] WebEngine 资源宿主安装成功")
    except Exception as e:
        if _logger:
            _logger.warning(f"Phase 2.1 WebEngine 资源宿主安装失败: {e}")
        else:
            print(f"[Phase 2.1] WebEngine 资源宿主安装失败: {e}")

    # 设置应用程序信息
    app.setApplicationName("Circuit Design AI")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("Circuit AI")
    
    # 设置应用程序默认字体（使用现代字体）
    # 明确设置字体，避免 Qt 回退到 Fixedsys 等旧字体
    app_font = QFont()
    app_font.setStyleHint(QFont.StyleHint.SansSerif, QFont.StyleStrategy.PreferAntialias)
    
    # 尝试按优先级设置系统字体
    font_found = False
    for font_name in ["Segoe UI", "SF Pro Display", "Roboto", "Microsoft YaHei UI", "Arial"]:
        app_font.setFamily(font_name)
        if app_font.exactMatch():
            font_found = True
            break
    
    if not font_found:
        # 如果所有字体都不可用，使用通用 sans-serif
        app_font.setFamily("sans-serif")
    
    app_font.setPointSize(9)  # 设置合理的默认字体大小
    app.setFont(app_font)
    
    if _logger:
        _logger.info(f"Phase 2.1 应用程序字体设置完成: {app_font.family()}")
    else:
        print(f"[Phase 2.1] 应用程序字体设置完成: {app_font.family()}")

    # ============================================================
    # 2.1.2 初始化 qasync 融合事件循环
    # 必须在 QApplication 创建后、进入事件循环前调用
    # ============================================================
    from shared.async_runtime import init_async_runtime, shutdown as shutdown_async_runtime
    try:
        loop = init_async_runtime(app)
        if _logger:
            _logger.info("Phase 2.1.2 qasync 融合事件循环初始化成功")
        else:
            print("[Phase 2.1.2] qasync 融合事件循环初始化成功")
    except ImportError as e:
        if _logger:
            _logger.critical(f"Phase 2.1.2 qasync 初始化失败: {e}")
        else:
            print(f"[Phase 2.1.2] qasync 初始化失败: {e}")
        _show_fatal_error(f"qasync 库未安装，请运行: pip install qasync>=0.27.1\n\n{e}")
        return 1
    except Exception as e:
        if _logger:
            _logger.critical(f"Phase 2.1.2 qasync 初始化失败: {e}")
        else:
            print(f"[Phase 2.1.2] qasync 初始化失败: {e}")
        _show_fatal_error(f"异步运行时初始化失败: {e}")
        return 1

    # 2.1.1 加载 QSS 样式表
    from resources.resource_loader import load_stylesheet
    if load_stylesheet(app):
        if _logger:
            _logger.info("Phase 2.1.1 QSS 样式表加载完成")
        else:
            print("[Phase 2.1.1] QSS 样式表加载完成")
    else:
        if _logger:
            _logger.warning("Phase 2.1.1 QSS 样式表加载失败，使用默认样式")
        else:
            print("[Phase 2.1.1] QSS 样式表加载失败，使用默认样式")

    # 2.2-2.4 创建并显示主窗口，触发延迟初始化
    main_window = _init_phase_2(app)
    if main_window is None:
        return 1  # 致命错误，退出

    # 检查 Phase 0-2 总耗时
    elapsed = (time.time() - start_time) * 1000
    if elapsed > 500:
        warning_msg = f"Phase 0-2 总耗时 {elapsed:.0f}ms，超过 500ms 阈值"
        if _logger:
            _logger.warning(warning_msg)
        else:
            print(f"[WARNING] {warning_msg}")
    else:
        info_msg = f"Phase 0-2 完成，耗时 {elapsed:.0f}ms"
        if _logger:
            _logger.info(info_msg)
        else:
            print(f"[INFO] {info_msg}")

    # Phase 3 在事件循环中异步执行（已通过 QTimer.singleShot 调度）

    # ============================================================
    # 进入 qasync 融合事件循环
    # 使用 with 上下文管理器确保正确清理
    # ============================================================
    print("\n进入 qasync 融合事件循环...")
    if _logger:
        _logger.info("进入 qasync 融合事件循环 (Qt + asyncio)")

    exit_code = 0
    try:
        with loop:
            try:
                loop.run_forever()
            finally:
                # qasync resources and network clients must be settled while
                # their owning loop is still alive. Closing the loop first
                # used to strand LLM tasks and leave the RAG/simulation pools
                # running during interpreter shutdown.
                if not loop.is_closed():
                    try:
                        loop.run_until_complete(_shutdown_services_async())
                    except Exception as shutdown_exc:
                        if _logger:
                            _logger.warning(
                                f"应用服务关闭时出错: {shutdown_exc}"
                            )
                        else:
                            print(
                                f"[WARNING] 应用服务关闭时出错: "
                                f"{shutdown_exc}"
                            )
    except Exception as e:
        if _logger:
            _logger.error(f"事件循环异常退出: {e}")
        else:
            print(f"[ERROR] 事件循环异常退出: {e}")
        exit_code = 1
    finally:
        # The async shutdown above already settled task owners. This wrapper
        # only resets shared.async_runtime's module state and is idempotent
        # for an already-closed loop.
        shutdown_async_runtime()
    
    if _logger:
        _logger.info(f"应用退出，退出码: {exit_code}")

    return exit_code


async def _shutdown_services_async() -> None:
    """Settle all runtime owners before the qasync loop is closed.

    Every step is best-effort and isolated: one optional service failing to
    close must not prevent the remaining managers from releasing their
    threads, watchers, network clients, or pending asyncio tasks.
    """
    import inspect

    from shared.service_locator import ServiceLocator
    from shared.service_names import (
        SVC_FILE_WATCHER,
        SVC_LLM_CLIENT,
        SVC_LLM_EXECUTOR,
        SVC_PROJECT_SERVICE,
        SVC_RAG_MANAGER,
        SVC_SESSION_STATE_PROJECTOR,
        SVC_SIMULATION_JOB_MANAGER,
    )

    async def _call_async_lifecycle(service, method_name: str, label: str) -> None:
        if service is None:
            return
        method = getattr(service, method_name, None)
        if not callable(method):
            return
        try:
            result = method()
            if inspect.isawaitable(result):
                await result
            if _logger:
                _logger.info(f"{label} 已关闭")
        except Exception as exc:
            if _logger:
                _logger.warning(f"{label} 关闭时出错: {exc}")

    # Stop the task that can still invoke tools before tearing those tools
    # down. LLMExecutor.shutdown() is identity-safe and awaits cancellation.
    await _call_async_lifecycle(
        ServiceLocator.get_optional(SVC_LLM_EXECUTOR),
        "shutdown",
        "LLMExecutor",
    )

    simulation_jobs = ServiceLocator.get_optional(SVC_SIMULATION_JOB_MANAGER)
    if simulation_jobs:
        try:
            settled = simulation_jobs.close(timeout=2.0)
            if _logger:
                if settled:
                    _logger.info("SimulationJobManager 已关闭")
                else:
                    _logger.warning(
                        "SimulationJobManager 已拒绝新任务，但仍有不可中断的 "
                        "executor 正在收尾"
                    )
        except Exception as exc:
            if _logger:
                _logger.warning(f"SimulationJobManager 关闭时出错: {exc}")

    # ProjectService owns the authoritative session-persistence preflight.
    # Run it before independently tearing down the watcher/RAG projection so
    # a failed save leaves project state intact and is reported truthfully.
    project_service = ServiceLocator.get_optional(SVC_PROJECT_SERVICE)
    if project_service and project_service.is_project_open():
        try:
            closed, message = project_service.close_project()
            if closed:
                if _logger:
                    _logger.info("ProjectService 项目已关闭")
            elif _logger:
                _logger.error(
                    "ProjectService 拒绝关闭项目，未清空 dirty 会话状态: %s",
                    message,
                )
        except Exception as exc:
            if _logger:
                _logger.warning(f"ProjectService 关闭项目时出错: {exc}")

    # ProjectService normally stops the watcher itself after its persistence
    # preflight. This fallback is still required when close was rejected or
    # partially initialized; process exit must not leave a watchdog thread.
    file_watcher = ServiceLocator.get_optional(SVC_FILE_WATCHER)
    if file_watcher:
        try:
            file_watcher.stop_watching()
            if _logger:
                _logger.info("FileWatcher 已停止")
        except Exception as exc:
            if _logger:
                _logger.warning(f"FileWatcher 停止时出错: {exc}")

    session_state_projector = ServiceLocator.get_optional(
        SVC_SESSION_STATE_PROJECTOR
    )
    if session_state_projector:
        try:
            session_state_projector.shutdown()
            if _logger:
                _logger.info("SessionStateProjector 已关闭")
        except Exception as exc:
            if _logger:
                _logger.warning(f"SessionStateProjector 关闭时出错: {exc}")

    rag_manager = ServiceLocator.get_optional(SVC_RAG_MANAGER)
    if rag_manager:
        try:
            rag_manager.stop()
            if _logger:
                _logger.info("RAGManager 已关闭")
        except Exception as exc:
            if _logger:
                _logger.warning(f"RAGManager 关闭时出错: {exc}")

    await _call_async_lifecycle(
        ServiceLocator.get_optional(SVC_LLM_CLIENT),
        "close",
        "LLMClient",
    )
    # Last: cancel any task which was not owned by one of the explicit
    # managers above. This still runs on the live qasync loop.
    try:
        from shared.async_runtime import shutdown_async

        await shutdown_async()
    except Exception as exc:
        if _logger:
            _logger.warning(f"异步运行时关闭时出错: {exc}")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "run",
]
