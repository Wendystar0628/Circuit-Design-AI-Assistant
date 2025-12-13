# Circuit Design AI - Application Bootstrap
"""
应用启动引导器，负责整个应用的初始化编排

职责：
- 集中管理所有初始化逻辑
- 协调各组件的启动顺序
- 处理初始化失败和降级策略

初始化顺序（严格按此顺序执行）：
- Phase -1: ngspice 和 AI 模型路径配置（必须在所有其他导入之前）
- Phase 0: 基础设施初始化（同步，阻塞式）
  - 0.1 Logger 初始化
  - 0.2 ServiceLocator 初始化
  - 0.3 EventBus 初始化
- Phase 1: 核心管理器初始化（同步，阻塞式）
  - 1.1 ConfigManager 初始化
  - 1.2 ErrorHandler 初始化
  - 1.3 I18nManager 初始化
  - 1.4 AppState 初始化
- Phase 2: GUI 框架初始化（同步，阻塞式）
  - 2.1 创建 QApplication 实例
  - 2.2 创建 MainWindow 实例
  - 2.3 显示主窗口
  - 2.4 触发延迟初始化
- Phase 3: 延迟初始化（异步，在事件循环中执行）
  - 3.1 WorkerManager 初始化
  - 3.2 FileManager 初始化（阶段二实现）
  - 3.3 发布 EVENT_INIT_COMPLETE 事件

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
    embedding_status = "✓ 本地可用" if is_embedding_available() else "需联网下载"
    reranker_status = "✓ 本地可用" if is_reranker_available() else "需联网下载"
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
    
    0.1 Logger 初始化（最先，其他模块都需要日志）
    0.2 ServiceLocator 初始化（创建空容器）
    0.3 EventBus 初始化（创建事件总线并注册）
    
    Returns:
        bool: 初始化是否成功
    """
    global _logger

    try:
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



def _init_phase_1() -> bool:
    """
    Phase 1: 核心管理器初始化（同步，阻塞式）
    
    1.1 ConfigManager 初始化（依赖 Logger）
    1.2 ErrorHandler 初始化（依赖 Logger、EventBus、ConfigManager）
    1.3 I18nManager 初始化（依赖 ConfigManager）
    1.4 AppState 初始化（依赖 EventBus）
    
    Returns:
        bool: 初始化是否成功
    """
    try:
        # --------------------------------------------------------
        # 1.1 ConfigManager 初始化
        # 依赖：Logger（记录配置加载日志）
        # 职责：加载配置，缺失字段使用默认值，校验失败时记录日志
        # --------------------------------------------------------
        from infrastructure.config.config_manager import ConfigManager
        from shared.service_locator import ServiceLocator
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
        # 1.4 AppState 初始化
        # 依赖：EventBus（状态变更发布事件）
        # 职责：初始化所有状态字段为默认值
        # --------------------------------------------------------
        from shared.app_state import AppState
        from shared.service_names import SVC_APP_STATE
        app_state = AppState()
        ServiceLocator.register(SVC_APP_STATE, app_state)
        if _logger:
            _logger.info("Phase 1.4 AppState 初始化完成")

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
    
    3.1 WorkerManager 初始化（依赖 EventBus）
    3.2 FileManager 初始化（阶段二实现，依赖 Logger、EventBus）
    3.3 发布 EVENT_INIT_COMPLETE 事件
    
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
        # 3.2 FileManager 初始化（阶段二实现，此处预留）
        # 依赖：Logger、EventBus
        # 职责：提供统一文件操作接口
        # --------------------------------------------------------
        # TODO: 阶段二实现后取消注释
        # from infrastructure.persistence.file_manager import FileManager
        # from shared.service_names import SVC_FILE_MANAGER
        # file_manager = FileManager()
        # ServiceLocator.register(SVC_FILE_MANAGER, file_manager)
        # if _logger:
        #     _logger.info("Phase 3.2 FileManager 初始化完成")
        print("[Phase 3.2] FileManager 初始化 - 阶段二实现")

        # --------------------------------------------------------
        # 3.3 发布 EVENT_INIT_COMPLETE 事件
        # 通知所有订阅者初始化完成
        # --------------------------------------------------------
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_EVENT_BUS
        from shared.event_types import EVENT_INIT_COMPLETE
        event_bus = ServiceLocator.get(SVC_EVENT_BUS)
        event_bus.publish(EVENT_INIT_COMPLETE, {"timestamp": time.time()})
        if _logger:
            _logger.info("Phase 3.3 EVENT_INIT_COMPLETE 已发布")

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
    if _logger:
        _logger.info(f"应用退出，退出码: {exit_code}")

    return exit_code


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "run",
    "is_ngspice_available",
    "is_embedding_available",
    "is_reranker_available",
]
