"""Contract tests for :class:`SimulationArtifactReaderBase` (Step 16).

The base concentrates the resolution chain shared by ``read_metrics`` /
``read_output_log`` / ``read_op_result`` / ``read_chart_image``:

    1. Explicit ``result_path`` wins outright.
    2. Explicit ``file_path`` resolves to the most recent bundle of
       that circuit via ``SimulationResultRepository.list_by_circuit``.
    3. Both empty falls back to ``context.current_file`` treated as a
       circuit path; a missing editor-active file is rejected outright.

These tests pin the branch table so that the upcoming four read tools
(and any future addition) cannot each re-implement a subtly different
chain. They also lock in the two hard prohibitions that motivated the
base in the first place:

* Tools must not fall back to "the most recent bundle of any circuit"
  — that was the pre-Step-7 UI drift we refuse to reintroduce.
* ``result_path`` and ``file_path`` cannot be passed together; the
  base returns an is_error ``ToolResult`` instead of picking a winner
  silently.
"""

from pathlib import Path
from typing import Dict, List, Optional

import pytest

from domain.llm.agent.tools.simulation_artifact_reader_base import (
    ResolvedSimulationBundle,
    SimulationArtifactReaderBase,
)
from domain.llm.agent.types import ToolContext, ToolResult
from domain.simulation.models.simulation_result import SimulationResult
from domain.simulation.service.simulation_result_repository import (
    CircuitResultGroup,
    SimulationResultSummary,
)
from shared.models.load_result import LoadResult


# ============================================================
# 测试替身
# ============================================================


class _FakeRepository:
    """Minimal ``SimulationResultRepository`` stand-in.

    Exposes only the three methods the base depends on:

    * :meth:`load` — looked up in ``loaded`` map, falls back to
      ``file_missing`` so "unknown result_path" tests don't silently
      succeed.
    * :meth:`resolve_bundle_dir` — returns the configured mapping, or
      ``None`` when the test needs the "bundle vanished" edge.
    * :meth:`list_by_circuit` — returns the configured groups verbatim;
      the repo's real-file scan is not in scope.

    The tests construct small maps per scenario, which keeps each
    test's fixture in sync with what the test asserts.
    """

    def __init__(
        self,
        loaded: Optional[Dict[str, LoadResult[SimulationResult]]] = None,
        bundle_dirs: Optional[Dict[str, Optional[Path]]] = None,
        groups: Optional[List[CircuitResultGroup]] = None,
    ) -> None:
        self._loaded = dict(loaded or {})
        self._bundle_dirs = dict(bundle_dirs or {})
        self._groups = list(groups or [])

    def load(
        self, project_root: str, result_path: str
    ) -> LoadResult[SimulationResult]:
        if result_path in self._loaded:
            return self._loaded[result_path]
        return LoadResult.file_missing(result_path)

    def resolve_bundle_dir(
        self, project_root: str, result_path: str
    ) -> Optional[Path]:
        # 配置里 None 表示"该 path 对应的 bundle 目录已经消失"，
        # 用来测 base 的 bundle_dir_missing 分支。
        return self._bundle_dirs.get(result_path)

    def list_by_circuit(
        self, project_root: str, per_circuit_limit: int = 5
    ) -> List[CircuitResultGroup]:
        return list(self._groups)


# ============================================================
# 辅助工厂
# ============================================================


def _make_simulation_result(
    *,
    file_path: str = "circuits/amp.cir",
    analysis_type: str = "tran",
    success: bool = True,
) -> SimulationResult:
    """最小可构造的 ``SimulationResult``。

    ``SimulationResult.__post_init__`` 会触发 axis metadata 推断，但
    在 ``data=None`` 的路径下这些分支全部落在默认值上，不会引入外部
    依赖（不碰 numpy 真数据、不碰 matplotlib）。
    """
    return SimulationResult(
        executor="spice",
        file_path=file_path,
        analysis_type=analysis_type,
        success=success,
    )


def _make_context(
    *,
    project_root: str = "/fake/project",
    current_file: Optional[str] = None,
    repository: Optional[_FakeRepository] = None,
) -> ToolContext:
    return ToolContext(
        project_root=project_root,
        current_file=current_file,
        sim_result_repository=repository,
    )


# ============================================================
# 分支: 静态配置错误
# ============================================================


def test_resolve_rejects_missing_repository():
    """``ToolContext.sim_result_repository`` 为 ``None`` → is_error。

    这条路径是 ``LLMExecutor`` 没注入依赖时的保险 —— 绝对不能静默
    退化到模块级 singleton。
    """
    context = _make_context(repository=None)
    result = SimulationArtifactReaderBase.resolve({"result_path": "x"}, context)
    assert isinstance(result, ToolResult)
    assert result.is_error
    assert "SimulationResultRepository" in result.content


def test_resolve_rejects_empty_project_root():
    """``project_root`` 为空 → is_error（仓储 API 全部依赖它）。"""
    context = _make_context(project_root="", repository=_FakeRepository())
    result = SimulationArtifactReaderBase.resolve({"result_path": "x"}, context)
    assert isinstance(result, ToolResult)
    assert result.is_error
    assert "project" in result.content.lower()


def test_resolve_rejects_both_path_params():
    """同时给 ``result_path`` 和 ``file_path`` → is_error。"""
    context = _make_context(repository=_FakeRepository())
    result = SimulationArtifactReaderBase.resolve(
        {"result_path": "a/result.json", "file_path": "a.cir"},
        context,
    )
    assert isinstance(result, ToolResult)
    assert result.is_error
    assert "mutually exclusive" in result.content


def test_resolve_rejects_both_params_empty_without_fallback():
    """两个参数都空、``current_file`` 也是 None → is_error。"""
    context = _make_context(repository=_FakeRepository(), current_file=None)
    result = SimulationArtifactReaderBase.resolve({}, context)
    assert isinstance(result, ToolResult)
    assert result.is_error
    assert "editor" in result.content


# ============================================================
# 分支 A: 显式 result_path
# ============================================================


def test_resolve_with_explicit_result_path_returns_bundle(tmp_path):
    """显式 ``result_path`` → repo.load + resolve_bundle_dir。"""
    sim_result = _make_simulation_result(file_path="circuits/amp.cir")
    bundle_dir = tmp_path / "simulation_results" / "amp" / "2026-01-01"
    bundle_dir.mkdir(parents=True)
    result_path = "simulation_results/amp/2026-01-01/result.json"

    repo = _FakeRepository(
        loaded={result_path: LoadResult.ok(sim_result, result_path)},
        bundle_dirs={result_path: bundle_dir},
    )
    context = _make_context(project_root=str(tmp_path), repository=repo)

    resolved = SimulationArtifactReaderBase.resolve(
        {"result_path": result_path}, context
    )
    assert isinstance(resolved, ResolvedSimulationBundle)
    assert resolved.result_path == result_path
    assert resolved.bundle_dir == bundle_dir
    assert resolved.result is sim_result
    assert resolved.circuit_file == "circuits/amp.cir"
    assert resolved.used_fallback is False


def test_resolve_with_unknown_result_path_surfaces_repo_error():
    """仓储 ``load`` 返回 ``file_missing`` → base 转成 is_error。"""
    repo = _FakeRepository()  # loaded 为空 → 所有 load 报 file_missing
    context = _make_context(repository=repo)

    result = SimulationArtifactReaderBase.resolve(
        {"result_path": "nowhere/result.json"}, context
    )
    assert isinstance(result, ToolResult)
    assert result.is_error
    assert "nowhere/result.json" in result.content


def test_resolve_reports_bundle_dir_missing(tmp_path):
    """``resolve_bundle_dir`` 返回 None → is_error（即使 load 成功）。"""
    sim_result = _make_simulation_result()
    result_path = "simulation_results/amp/2026-01-01/result.json"

    repo = _FakeRepository(
        loaded={result_path: LoadResult.ok(sim_result, result_path)},
        bundle_dirs={result_path: None},
    )
    context = _make_context(project_root=str(tmp_path), repository=repo)

    result = SimulationArtifactReaderBase.resolve(
        {"result_path": result_path}, context
    )
    assert isinstance(result, ToolResult)
    assert result.is_error
    assert "bundle directory" in result.content


def test_resolve_normalizes_absolute_result_path_into_project_relative(tmp_path):
    """LLM 偶尔会传绝对路径；base 归一为项目相对 POSIX 再喂仓储。"""
    sim_result = _make_simulation_result()
    rel_path = "simulation_results/amp/2026-01-01/result.json"
    bundle_dir = tmp_path / "simulation_results" / "amp" / "2026-01-01"
    bundle_dir.mkdir(parents=True)

    repo = _FakeRepository(
        loaded={rel_path: LoadResult.ok(sim_result, rel_path)},
        bundle_dirs={rel_path: bundle_dir},
    )
    context = _make_context(project_root=str(tmp_path), repository=repo)

    # 传入绝对路径（混反斜杠），应当被折成同一个 rel_path 再命中 repo。
    abs_input = str(tmp_path / "simulation_results" / "amp" / "2026-01-01" / "result.json")
    resolved = SimulationArtifactReaderBase.resolve(
        {"result_path": abs_input}, context
    )
    assert isinstance(resolved, ResolvedSimulationBundle)
    assert resolved.result_path == rel_path


# ============================================================
# 分支 B: 显式 file_path → list_by_circuit 聚合
# ============================================================


def _make_group_for(
    *,
    circuit_absolute_path: str,
    result_path: str,
    circuit_file: str = "circuits/amp.cir",
    timestamp: str = "2026-01-01T00:00:00",
) -> CircuitResultGroup:
    summary = SimulationResultSummary(
        id=result_path.rsplit("/", 1)[0],
        result_path=result_path,
        circuit_file=circuit_file,
        analysis_type="tran",
        success=True,
        timestamp=timestamp,
    )
    return CircuitResultGroup(
        circuit_file=circuit_file,
        circuit_absolute_path=circuit_absolute_path,
        results=[summary],
    )


def test_resolve_with_explicit_file_path_picks_latest_bundle(tmp_path):
    """显式 ``file_path`` → list_by_circuit 命中 → 展开成 result_path。"""
    circuit_rel = Path("circuits/amp.cir")
    circuit_abs = tmp_path / circuit_rel
    circuit_abs.parent.mkdir(parents=True)
    circuit_abs.write_text("* empty", encoding="utf-8")

    sim_result = _make_simulation_result(file_path="circuits/amp.cir")
    result_path = "simulation_results/amp/2026-01-01/result.json"
    bundle_dir = tmp_path / "simulation_results" / "amp" / "2026-01-01"
    bundle_dir.mkdir(parents=True)

    repo = _FakeRepository(
        loaded={result_path: LoadResult.ok(sim_result, result_path)},
        bundle_dirs={result_path: bundle_dir},
        groups=[
            _make_group_for(
                circuit_absolute_path=str(circuit_abs),
                result_path=result_path,
            ),
        ],
    )
    context = _make_context(project_root=str(tmp_path), repository=repo)

    resolved = SimulationArtifactReaderBase.resolve(
        {"file_path": "circuits/amp.cir"}, context
    )
    assert isinstance(resolved, ResolvedSimulationBundle)
    assert resolved.result_path == result_path
    assert resolved.used_fallback is False


def test_resolve_with_file_path_no_matching_group_is_error(tmp_path):
    """``file_path`` 合法但仓储里没有该电路的任何 bundle → is_error。

    关键不变量：绝不回落到"任意电路的最新 bundle"。
    """
    circuit_rel = Path("circuits/amp.cir")
    circuit_abs = tmp_path / circuit_rel
    circuit_abs.parent.mkdir(parents=True)
    circuit_abs.write_text("* empty", encoding="utf-8")

    other_abs = tmp_path / "circuits" / "filter.cir"
    other_abs.parent.mkdir(exist_ok=True)
    other_abs.write_text("* other", encoding="utf-8")

    # groups 里只有 filter.cir 的 bundle —— 请求 amp.cir 时必须 is_error，
    # 不能 silently 返回 filter 的 bundle。
    repo = _FakeRepository(
        groups=[
            _make_group_for(
                circuit_absolute_path=str(other_abs),
                result_path="simulation_results/filter/2026-01-01/result.json",
                circuit_file="circuits/filter.cir",
            ),
        ],
    )
    context = _make_context(project_root=str(tmp_path), repository=repo)

    result = SimulationArtifactReaderBase.resolve(
        {"file_path": "circuits/amp.cir"}, context
    )
    assert isinstance(result, ToolResult)
    assert result.is_error
    assert "amp.cir" in result.content
    assert "no simulation bundle" in result.content.lower()


def test_resolve_with_missing_file_path_is_error(tmp_path):
    """``file_path`` 指向不存在的文件 → validate_file_path 直接拒。"""
    repo = _FakeRepository()
    context = _make_context(project_root=str(tmp_path), repository=repo)

    result = SimulationArtifactReaderBase.resolve(
        {"file_path": "does/not/exist.cir"}, context
    )
    assert isinstance(result, ToolResult)
    assert result.is_error
    assert "not found" in result.content.lower()


# ============================================================
# 分支 C: 回落到 context.current_file
# ============================================================


def test_resolve_falls_back_to_current_file_and_flags_it(tmp_path):
    """两参数都空、``current_file`` 有值 → 照样走 list_by_circuit；
    ``ResolvedSimulationBundle.used_fallback`` 应为 True。"""
    circuit_abs = tmp_path / "circuits" / "amp.cir"
    circuit_abs.parent.mkdir(parents=True)
    circuit_abs.write_text("* empty", encoding="utf-8")

    sim_result = _make_simulation_result()
    result_path = "simulation_results/amp/2026-01-01/result.json"
    bundle_dir = tmp_path / "simulation_results" / "amp" / "2026-01-01"
    bundle_dir.mkdir(parents=True)

    repo = _FakeRepository(
        loaded={result_path: LoadResult.ok(sim_result, result_path)},
        bundle_dirs={result_path: bundle_dir},
        groups=[
            _make_group_for(
                circuit_absolute_path=str(circuit_abs),
                result_path=result_path,
            ),
        ],
    )
    context = _make_context(
        project_root=str(tmp_path),
        current_file=str(circuit_abs),
        repository=repo,
    )

    resolved = SimulationArtifactReaderBase.resolve({}, context)
    assert isinstance(resolved, ResolvedSimulationBundle)
    assert resolved.result_path == result_path
    assert resolved.used_fallback is True


# ============================================================
# 参数 schema 装配
# ============================================================


def test_build_parameters_schema_merges_extras_and_keeps_required():
    """``extra_properties`` 被合并；``extra_required`` 作为最终
    ``required``。``result_path`` / ``file_path`` **不** 出现在
    ``required`` 里（它们的必填关系由 resolve 里运行时决定）。"""
    schema = SimulationArtifactReaderBase.build_parameters_schema(
        extra_properties={
            "metric_name": {"type": "string", "description": "which metric"},
        },
        extra_required=["metric_name"],
    )
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"result_path", "file_path", "metric_name"}
    assert schema["required"] == ["metric_name"]


def test_build_parameters_schema_rejects_reserved_key_collision():
    """工具开发者如果误用同名 extras 应当在导入期炸掉，不是运行期。"""
    with pytest.raises(ValueError, match="collide"):
        SimulationArtifactReaderBase.build_parameters_schema(
            extra_properties={"result_path": {"type": "string"}},
        )


# ============================================================
# 回归: 已删除的 get_latest
# ============================================================


def test_repository_no_longer_exposes_get_latest():
    """Step 16 prep 删掉了 ``SimulationResultRepository.get_latest`` ——
    保留会成为"agent 觉得自己可以问最新 bundle 是谁"的陷阱接口，
    与 Step 7 禁用 tip-of-history probe 为"当前结果"直接冲突。"""
    from domain.simulation.service.simulation_result_repository import (
        SimulationResultRepository,
    )

    assert not hasattr(SimulationResultRepository, "get_latest")
