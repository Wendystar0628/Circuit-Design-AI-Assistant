# Circuit Design AI - Application Bootstrap
"""
应用启动引导器，负责整个应用的初始化编排

职责：
- 集中管理所有初始化逻辑
- 协调各组件的启动顺序
- 处理初始化失败和降级策略

三层状态分离架构：
- Layer 1: UIState (Presentation) - 纯 UI 状态，Phase 2.2 在 MainWindow 中初始化
- Layer 2: SessionState (Application) - GraphState 的只读投影，Phase 3.5.1 初始化
- Layer 3: GraphState (Domain) - LangGraph 工作流的唯一真理来源

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
  - 1.5 TracingStore 初始化（可观测性基础设施）
- Phase 2: GUI 框架初始化（同步，阻塞式）
  - 2.0.1 预导入 WebEngine
  - 2.1 创建 QApplication 实例
  - 2.2 创建 MainWindow 实例（内部初始化 UIState）
  - 2.3 显示主窗口
  - 2.4 触发延迟初始化
- Phase 3: 延迟初始化（异步，在事件循环中执行）
  - 3.1 WorkerManager 初始化
  - 3.2 FileManager 初始化
  - 3.2.1 FileSearchService 初始化（精确搜索引擎）
  - 3.2.2 UnifiedSearchService 初始化（统一搜索门面）
  - 3.3 ProjectService 初始化
  - 3.4 ContextManager 初始化
  - 3.5 SessionStateManager 初始化
  - 3.5.1 SessionState 初始化（GraphState 的只读投影）
  - 3.5.2 GraphStateProjector 初始化（自动投影 GraphState 到 SessionState）
  - 3.5.5 TracingLogger 初始化（可观测性基础设施）
  - 3.6 LLM 客户端初始化
  - 3.7 发布 EVENT_INIT_COMPLETE 事件
- 应用关闭时：
  - TracingLogger 关闭（最后一次刷新）
  - TracingStore 关闭

注意：ngspice 路径配置必须在任何 PySpice 导入之前执行
"""

import sys
import time
import traceback
from pathlib import Path
from typing import Optional

# ============================================================
# Phase -1.1: ngspice 路径配置（必须在所有其他导入之前）
# ============================================================
from infrastructure.utils.ngspice_config import (
    configure_ngspice,
    is_ngspice_available,
    get_configuration_error
)

_ngspice_init_success = configure_ngspice()
if not _ngspice_init_success:
    print(f"[WARNING] ngspice 配置失败: {get_configuration_error()}")
    print("[WARNING] 仿真功能可能不可用")
else:
    print("[Phase -1.1] ngspice 配置成功")


# ============================================================
# Phase -1.2: AI 模型路径配置
# ============================================================
from infrastructure.utils.model_config import (
    configure_models,
    is_embedding_available,
    is_reranker_available,
    get_configuration_errors
)

_models_init_success = configure_models()
if not _models_init_success:
    print("[WARNING] AI 模型配置失败，RAG 功能可能需要联网下载模型")
    for model_type, error in get_configuration_errors().items():
        print(f"  - {error}")
else:
    embedding_status = "[OK] 本地可用" if is_embedding_available() else "需联网下载"
    reranker_status = "[OK] 本地可用" if is_reranker_available() else "需联网下载"
    print("[Phase -1.2] AI 模型配置完成")
    print(f"  - 嵌入模型: {embedding_status}")
    print(f"  - 重排序模型: {reranker_status}")


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
    1.5 TracingStore 初始化（依赖 Logger）
    
    Returns:
        bool: 初始化是否成功
    """
    try:
        # --------------------------------------------------------
        # 1.0 CredentialManager 初始化
        # 依赖：Logger（记录凭证操作日志）
        # 职责：加载凭证，初始化加密密钥
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
        ModelRegistry.initialize()
        if _logger:
            _logger.info("Phase 1.4 ModelRegistry 初始化完成")

        # --------------------------------------------------------
        # 1.5 TracingStore 初始化
        # 依赖：Logger
        # 职责：初始化追踪数据存储（SQLite）
        # --------------------------------------------------------
        _init_tracing_store()

        return True

    except Exception as e:
        if _logger:
            _logger.error(f"Phase 1 初始化失败: {e}")
        else:
            print(f"[Phase 1] 初始化失败: {e}")
        traceback.print_exc()
        return False


def _init_tracing_store():
    """
    初始化追踪存储（Phase 1.5）
    
    同步初始化 TracingStore，因为需要在 Phase 3 之前准备好。
    使用 asyncio.run() 执行异步初始化。
    """
    import asyncio
    
    try:
        from shared.tracing import TracingStore
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_TRACING_STORE
        
        # 创建存储实例
        tracing_store = TracingStore()
        
        # 同步执行异步初始化
        asyncio.run(tracing_store.initialize())
        
        # 清理过期数据（7天）
        asyncio.run(tracing_store.cleanup_old_traces(days=7))
        
        # 注册到 ServiceLocator
        ServiceLocator.register(SVC_TRACING_STORE, tracing_store)
        
        if _logger:
            _logger.info(f"Phase 1.5 TracingStore 初始化完成: {tracing_store.db_path}")
            
    except Exception as e:
        if _logger:
            _logger.warning(f"Phase 1.5 TracingStore 初始化失败（非致命）: {e}")
        else:
            print(f"[Phase 1.5] TracingStore 初始化失败: {e}")



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
    
    3.1 WorkerManager 初始化（依赖 EventBus）
    3.2 FileManager 初始化（依赖 Logger、EventBus）
    3.3 ProjectService 初始化（依赖 FileManager、SessionState、EventBus）
    3.4 ContextManager 初始化（依赖 Logger、EventBus）
    3.5 SessionStateManager 初始化（依赖 Logger、EventBus、ContextManager）
    3.5.1 SessionState 初始化（GraphState 的只读投影）
    3.5.2 GraphStateProjector 初始化（自动投影 GraphState 到 SessionState）
    3.5.5 TracingLogger 初始化（可观测性基础设施）
    3.6 LLM 客户端初始化（可选）
    3.7 发布 EVENT_INIT_COMPLETE 事件
    
    此阶段的耗时操作在事件循环中异步执行，不阻塞 UI 显示
    """
    try:
        # --------------------------------------------------------
        # 3.1 WorkerManager 初始化
        # 依赖：EventBus（Worker 状态事件）
        # 职责：创建 Worker 注册表（此时不创建 Worker 实例）
        # --------------------------------------------------------
        from shared.worker_manager import WorkerManager
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_WORKER_MANAGER
        worker_manager = WorkerManager()
        ServiceLocator.register(SVC_WORKER_MANAGER, worker_manager)
        # 启动健康检查
        worker_manager.start_health_check()
        if _logger:
            _logger.info("Phase 3.1 WorkerManager 初始化完成")

        # --------------------------------------------------------
        # 3.2 FileManager 初始化
        # 依赖：Logger、EventBus
        # 职责：提供统一文件操作接口
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

        # --------------------------------------------------------
        # 3.2.2 UnifiedSearchService 初始化
        # 依赖：FileSearchService、RAGService（延迟获取）
        # 职责：统一搜索门面，协调精确搜索和语义搜索
        # --------------------------------------------------------
        from domain.search import UnifiedSearchService
        from shared.service_names import SVC_UNIFIED_SEARCH_SERVICE
        unified_search_service = UnifiedSearchService()
        ServiceLocator.register(SVC_UNIFIED_SEARCH_SERVICE, unified_search_service)
        if _logger:
            _logger.info("Phase 3.2.2 UnifiedSearchService 初始化完成")

        # --------------------------------------------------------
        # 3.5.1 SessionState 初始化（先于 ProjectService）
        # 依赖：EventBus
        # 职责：GraphState 的只读投影，供 UI 层读取业务状态
        # --------------------------------------------------------
        from application.session_state import SessionState
        from shared.service_names import SVC_SESSION_STATE
        session_state = SessionState()
        ServiceLocator.register(SVC_SESSION_STATE, session_state)
        if _logger:
            _logger.info("Phase 3.5.1 SessionState 初始化完成")

        # --------------------------------------------------------
        # 3.5.2 GraphStateProjector 初始化
        # 依赖：SessionState、EventBus
        # 职责：监听 GraphState 变更，自动投影到 SessionState
        # --------------------------------------------------------
        from application.graph_state_projector import GraphStateProjector
        from shared.service_names import SVC_GRAPH_STATE_PROJECTOR
        graph_state_projector = GraphStateProjector(session_state)
        ServiceLocator.register(SVC_GRAPH_STATE_PROJECTOR, graph_state_projector)
        if _logger:
            _logger.info("Phase 3.5.2 GraphStateProjector 初始化完成")

        # --------------------------------------------------------
        # 3.3 ProjectService 初始化
        # 依赖：FileManager、SessionState、GraphStateProjector、EventBus
        # 职责：管理工作文件夹的初始化和状态
        # --------------------------------------------------------
        from application.project_service import ProjectService
        from shared.service_names import SVC_PROJECT_SERVICE
        project_service = ProjectService()
        ServiceLocator.register(SVC_PROJECT_SERVICE, project_service)
        if _logger:
            _logger.info("Phase 3.3 ProjectService 初始化完成")

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

        # --------------------------------------------------------
        # 3.5.5 TracingLogger 初始化
        # 依赖：EventBus、TracingStore
        # 职责：内存缓冲 + 定时刷新追踪日志
        # --------------------------------------------------------
        _init_tracing_logger()

        # --------------------------------------------------------
        # 3.6 LLM 客户端初始化（可选，依赖配置）
        # 依赖：ConfigManager、CredentialManager
        # 职责：提供 LLM API 调用能力
        # --------------------------------------------------------
        _init_llm_client()

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
            _logger.info("Phase 3.7 EVENT_INIT_COMPLETE 已发布")

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



def _init_tracing_logger():
    """
    初始化追踪日志记录器（Phase 3.5.5）
    
    依赖 EventBus 和 TracingStore，在 Phase 3 延迟初始化中执行。
    """
    try:
        from shared.tracing import TracingLogger
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_TRACING_LOGGER, SVC_TRACING_STORE, SVC_EVENT_BUS
        
        # 获取 TracingStore
        tracing_store = ServiceLocator.get_optional(SVC_TRACING_STORE)
        if not tracing_store:
            if _logger:
                _logger.warning("Phase 3.5.5 TracingLogger 初始化跳过：TracingStore 不可用")
            return
        
        # 创建 TracingLogger（通过 set_store 注入依赖，而非构造函数参数）
        tracing_logger = TracingLogger()
        tracing_logger.set_store(tracing_store)
        
        # 注入 EventBus（可选）
        event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
        if event_bus:
            tracing_logger.set_event_bus(event_bus)
        
        # 启动定时刷新（内部会注册 TracingContext 回调）
        tracing_logger.start()
        
        # 注册到 ServiceLocator
        ServiceLocator.register(SVC_TRACING_LOGGER, tracing_logger)
        
        if _logger:
            _logger.info("Phase 3.5.5 TracingLogger 初始化完成")
            
    except Exception as e:
        if _logger:
            _logger.warning(f"Phase 3.5.5 TracingLogger 初始化失败（非致命）: {e}")
        else:
            print(f"[Phase 3.5.5] TracingLogger 初始化失败: {e}")


def _init_llm_client():
    """
    初始化 LLM 客户端（可选）
    
    根据配置创建 LLM 客户端并注册到 ServiceLocator。
    如果配置不完整（如 API Key 未设置），则跳过初始化。
    """
    global _logger
    
    try:
        from shared.service_locator import ServiceLocator
        from shared.service_names import (
            SVC_CONFIG_MANAGER,
            SVC_CREDENTIAL_MANAGER,
            SVC_LLM_CLIENT,
        )
        from infrastructure.config.settings import LLM_PROVIDER_ZHIPU
        
        config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
        credential_manager = ServiceLocator.get_optional(SVC_CREDENTIAL_MANAGER)
        
        if not config_manager or not credential_manager:
            if _logger:
                _logger.warning("Phase 3.6 LLM 客户端初始化跳过：ConfigManager 或 CredentialManager 不可用")
            return
        
        # 获取当前 LLM 厂商
        provider = config_manager.get("llm_provider", "")
        if not provider:
            if _logger:
                _logger.info("Phase 3.6 LLM 客户端初始化跳过：未配置 LLM 厂商")
            return
        
        # 获取凭证
        credential = credential_manager.get_credential("llm", provider)
        if not credential or not credential.get("api_key"):
            if _logger:
                _logger.info(f"Phase 3.6 LLM 客户端初始化跳过：{provider} 的 API Key 未配置")
            return
        
        api_key = credential.get("api_key")
        base_url = config_manager.get("llm_base_url", "")
        model = config_manager.get("llm_model", "")
        timeout = config_manager.get("llm_timeout", 60)
        
        # 根据厂商创建客户端
        if provider == LLM_PROVIDER_ZHIPU:
            from infrastructure.llm_adapters.zhipu import ZhipuClient
            
            client = ZhipuClient(
                api_key=api_key,
                base_url=base_url if base_url else None,
                model=model if model else None,
                timeout=timeout,
            )
            ServiceLocator.register(SVC_LLM_CLIENT, client)
            
            if _logger:
                _logger.info(f"Phase 3.6 LLM 客户端初始化完成：{provider}, model={model or 'default'}")
        else:
            if _logger:
                _logger.warning(f"Phase 3.6 LLM 客户端初始化跳过：厂商 {provider} 暂未实现")
                
    except Exception as e:
        if _logger:
            _logger.warning(f"Phase 3.6 LLM 客户端初始化失败（非致命）: {e}")
        # LLM 客户端初始化失败不是致命错误，用户可以稍后在设置中配置



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
    
    执行完整的初始化流程并启动事件循环
    
    Returns:
        int: 退出码，0 表示正常退出
    """
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
    app = QApplication(sys.argv)

    # 设置应用程序信息
    app.setApplicationName("Circuit Design AI")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("Circuit AI")

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
    # 进入事件循环
    # ============================================================
    print("\n进入事件循环...")
    if _logger:
        _logger.info("进入 Qt 事件循环")

    exit_code = app.exec()

    # 清理工作
    _shutdown_tracing()
    
    if _logger:
        _logger.info(f"应用退出，退出码: {exit_code}")

    return exit_code


def _shutdown_tracing():
    """
    关闭追踪系统
    
    在应用退出时调用，确保所有追踪数据被刷新到存储。
    """
    import asyncio
    
    try:
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_TRACING_LOGGER, SVC_TRACING_STORE
        
        # 停止 TracingLogger（最后一次刷新）
        tracing_logger = ServiceLocator.get_optional(SVC_TRACING_LOGGER)
        if tracing_logger:
            asyncio.run(tracing_logger.shutdown())
            if _logger:
                _logger.info("TracingLogger 已关闭")
        
        # 关闭 TracingStore
        tracing_store = ServiceLocator.get_optional(SVC_TRACING_STORE)
        if tracing_store:
            asyncio.run(tracing_store.close())
            if _logger:
                _logger.info("TracingStore 已关闭")
                
    except Exception as e:
        if _logger:
            _logger.warning(f"追踪系统关闭时出错: {e}")
        else:
            print(f"[WARNING] 追踪系统关闭时出错: {e}")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "run",
    "is_ngspice_available",
    "is_embedding_available",
    "is_reranker_available",
]
