# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Circuit Design AI — Lean Windows Executable

Excludes vendor/models/ (651 MB local AI models — unused).
The app uses Zhipu REST API for embeddings, not local models.
torch/transformers/sentence-transformers are auto-excluded (never imported).
"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path.cwd()

# ── Hidden imports (dynamic/lazy imports PyInstaller can't detect) ──
_hidden = [
    # PyQt6
    'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets',
    'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore',
    'PyQt6.QtWebChannel', 'PyQt6.sip',
    # qasync
    'qasync',
    # ChromaDB
    'chromadb', 'chromadb.db', 'chromadb.api',
    'chromadb.utils.embedding_functions',
    'pypika', 'overrides', 'typing_extensions',
    # HTTP
    'httpx', 'httpcore', 'h11', 'h2', 'certifi',
    # Token / text
    'tiktoken', 'tiktoken_ext', 'tiktoken_ext.openai_public',
    'markdown', 'rapidfuzz',
    # Visualization
    'pyqtgraph', 'matplotlib', 'matplotlib.backends.backend_qtagg',
    # Documents
    'fitz', 'docx',
    # Filesystem / async
    'watchdog',
    # Numeric
    'numpy',
    # LangChain message types
    'langchain_core',
    # Project internals (dynamic imports via ServiceLocator)
    'application', 'application.bootstrap',
    'application.session_state', 'application.session_state_projector',
    'application.project_service', 'application.tasks',
    'application.pending_workspace_edit_service',
    'application.metric_target_service',
    'domain', 'domain.llm', 'domain.llm.agent', 'domain.llm.context_manager',
    'domain.llm.session_state_manager', 'domain.llm.llm_executor',
    'domain.llm.conversation_rollback_service',
    'domain.llm.context_compression_service',
    'domain.simulation', 'domain.simulation.executor',
    'domain.simulation.service',
    'domain.rag', 'domain.rag.rag_manager', 'domain.rag.embedder',
    'domain.rag.vector_store', 'domain.rag.chunker',
    'domain.rag.file_extractor', 'domain.rag.rag_worker',
    'domain.rag.document_watcher',
    'domain.services', 'domain.knowledge',
    'infrastructure', 'infrastructure.config', 'infrastructure.config.settings',
    'infrastructure.config.config_manager', 'infrastructure.config.credential_manager',
    'infrastructure.config.llm_runtime_config_manager',
    'infrastructure.utils', 'infrastructure.utils.logger',
    'infrastructure.utils.ngspice_config', 'infrastructure.utils.model_config',
    'infrastructure.utils.web_search_tool',
    'infrastructure.llm_adapters', 'infrastructure.llm_adapters.base_client',
    'infrastructure.llm_adapters.openai_compatible_client',
    'infrastructure.llm_adapters.client_factory',
    'infrastructure.llm_adapters.deepseek', 'infrastructure.llm_adapters.deepseek.deepseek_client',
    'infrastructure.llm_adapters.model_configs',
    'infrastructure.llm_adapters.model_configs.deepseek_models',
    'infrastructure.llm_adapters.model_configs.zhipu_models',
    'infrastructure.llm_adapters.model_configs.qwen_models',
    'infrastructure.persistence', 'infrastructure.persistence.file_manager',
    'infrastructure.file_intelligence',
    'infrastructure.file_intelligence.search',
    'infrastructure.file_intelligence.search.file_search_service',
    'presentation', 'presentation.main_window', 'presentation.core',
    'presentation.core.web_resource_host',
    'presentation.model_config',
    'presentation.model_config.model_config_controller',
    'shared', 'shared.service_locator', 'shared.service_names',
    'shared.event_bus', 'shared.event_types', 'shared.error_handler',
    'shared.async_runtime', 'shared.i18n_manager',
    'shared.model_registry', 'shared.model_types',
    'shared.embedding_model_registry',
    'resources', 'resources.resource_loader', 'resources.theme',
]

# ── Data files (non-Python assets) ──
_datas = []

def _collect_dir(src_rel):
    """Recursively collect all files from a directory.
    Skips __pycache__ and .pyc (already compiled into the exe)."""
    src = ROOT / src_rel
    if not src.is_dir():
        return
    for f in src.rglob('*'):
        if not f.is_file():
            continue
        if '__pycache__' in f.parts or f.suffix == '.pyc':
            continue
        rel = f.relative_to(ROOT)
        dest = str(rel.parent)
        _datas.append((str(rel), dest))

# vendor/ngspice/ — SPICE simulation engine (13 MB, required)
_collect_dir('vendor/ngspice')

# resources/ — React builds, styles, icons, prompts, i18n, KaTeX, Monaco… (35 MB)
_collect_dir('resources')

# ═══════════════════════════════════════════════════════════════
# NOTE:  vendor/models/ is deliberately EXCLUDED.
# The local AI embedding/reranker models (651 MB) are NOT bundled.
# The app uses Zhipu REST API for embeddings, not local models.
# torch/transformers/sentence-transformers are never imported.
# ═══════════════════════════════════════════════════════════════

# ── Analysis ───────────────────────────────────────────────────
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'unittest', 'test', 'pdb',
        'IPython', 'jupyter', 'notebook',
        'torch', 'torchvision', 'torchaudio',
        'transformers', 'sentence_transformers',
        'tensorflow', 'keras',
    ],
    noarchive=False,
    optimize=0,
)

# ── Collect chromadb package data (metadata + internal assets) ──
# chromadb uses importlib.metadata.version() and needs its dist-info.
# collect_data_files handles directory sources correctly.
try:
    _chroma_hidden = collect_submodules('chromadb')
    for _mod in _chroma_hidden:
        if _mod not in _hidden:
            _hidden.append(_mod)
    _chroma_data = collect_data_files('chromadb')
    for _src, _dst in _chroma_data:
        _datas.append((_src, _dst))
except Exception:
    pass

# ── PYZ ────────────────────────────────────────────────────────
pyz = PYZ(a.pure)

# ── EXE (single-file, no console window) ───────────────────────
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CircuitDesignAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
