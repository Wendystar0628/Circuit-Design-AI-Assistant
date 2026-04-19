# Simulation Artifact Reader Base - 仿真工件 read 工具共享基座
"""Step 16 agent read-tool 基座。

四个后续落地的 read 工具——``read_metrics`` / ``read_output_log`` /
``read_op_result`` / ``read_chart_image``——拥有**完全一致**的
"怎样从 LLM 传入的参数找到一个仿真工件 bundle"的解析链。本模块
把这条链抽成单一权威实现，供四个具体工具复用；它们只需要各自
添加"拿到 bundle 之后做什么"的小块（metric 名筛选、日志切片、
op 展开、chart 图像编码）即可。

解析链（优先级，严格顺序）::

    1. 显式 result_path（优先级最高）
       ``run_simulation`` 在本轮 turn 里刚返回的 result_path
       应当被原样透传——这是 agent 对最新结果做后续 read 的
       首选路径，不会有歧义。

    2. 显式 file_path（按电路文件）
       没有 result_path 时，agent 可以传入项目内的电路文件路径，
       基座走 ``SimulationResultRepository.list_by_circuit`` 按电路
       分组检索，取该电路**最近一次**仿真的 result_path。

    3. ``context.current_file`` 回落
       两个参数都省略时，回落到编辑器当前活动电路文件，再走
       (2) 的同样聚合逻辑。缺失活动电路则直接报 is_error——read
       工具**不允许**"最近一次任意电路"的野回落，那是 pre-Step-7
       UI 早已禁用过的陷阱。

    *result_path 和 file_path 不能同时给*——它们语义上指向不同的
    bundle 选择策略，同时给会产生"你到底指哪一个？"的歧义，基座
    直接 is_error 拒绝。

与 ``ToolContext`` 的契约：
- ``sim_result_repository`` 必须由 ``LLMExecutor`` 注入，解析链的
  每一步都走它。基座绝不 ``import`` 模块级 singleton，也绝不回落
  到 ``ServiceLocator`` —— ``run_simulation`` 取 ``sim_job_manager``
  是同一姿态。
- ``project_root`` 必须非空，否则仓储的所有 API 都失效。

与具体工具的分工：
- 基座只负责"怎么把参数解析成一个存在且可加载的 bundle"，
  返回 ``ResolvedSimulationBundle``（含 ``result_path`` / ``bundle_dir``
  / ``SimulationResult`` / ``circuit_file``）。
- 上层工具拿到 bundle 后：
    * ``read_metrics``: 从 ``result.measurements`` 里按名字筛
    * ``read_output_log``: 读 ``bundle_dir / "output.log"`` + offset/limit
    * ``read_op_result``: 展开 ``result.data`` 的 op node 表
    * ``read_chart_image``: 定位 ``bundle_dir / "charts" / ...png`` + base64

共享 prompt 片段：
- ``READ_TOOL_SHARED_GUIDELINES`` 列出四条跨 read 工具的行为边界
  （透传 result_path / 不要组合两种路径 / 不要野回落 / 失败不重试
  重推路径），concrete 工具在自己的 ``prompt_guidelines`` 里直接拼
  接这一段即可保持措辞一致。

共享 target 达标判定：
- ``evaluate_metric_target(raw_value, target_text)`` 是"该指标是否
  达到用户目标"的**唯一**权威入口。``read_metrics`` 用它；后续任何
  需要展示"达标/未达标"的 read 工具都必须共用同一函数，禁止在
  tool 内部手写 ``raw_value > target`` 这类比较。
- 不规范化 ``MetricTargetService`` 的原文：这里现场解析用户自由
  文本（``"≥ 20 dB"`` / ``"< 1.5k"`` 等）。字段目的是"判断通过
  与否"，不涉及单位代数——详见 ``evaluate_metric_target`` 文档。
"""

from __future__ import annotations

import enum
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from domain.llm.agent.types import ToolContext, ToolResult
from domain.llm.agent.utils.path_utils import validate_file_path
from domain.simulation.data.op_result_payload import (
    sort_op_result_branch_rows,
    sort_op_result_device_rows,
    sort_op_result_node_rows,
)
from domain.simulation.models.simulation_result import SimulationResult


# ============================================================
# 解析结果数据类
# ============================================================


@dataclass(frozen=True)
class ResolvedSimulationBundle:
    """被 ``SimulationArtifactReaderBase.resolve`` 解析出的 bundle 句柄。

    四个 read 工具通过这个对象**唯一地**访问底层工件——不存在
    "另外 open 一次 result.json 再自行 parse"或"自己拼 bundle_dir"
    的并行通道，所有读路径都汇流到这里。

    Attributes:
        result_path: 项目相对的 POSIX 路径（如
            ``simulation_results/amp/2026-04-06_00-10-00/result.json``）。
            下一步 tool 调用可以原样透传。
        bundle_dir: bundle 的绝对目录路径。工件子文件
            （``output.log`` / ``charts/*.png`` / ``metrics/*.csv``）
            的根。
        result: 已加载好的 ``SimulationResult`` 对象。read 工具不要
            再自己读 ``result.json``。
        circuit_file: ``result.json`` header 里写入的电路文件标识
            （通常是项目相对 POSIX 路径，偶尔为绝对路径）；用于
            LLM 反馈文案里 "which circuit" 的 echo。
        used_fallback: 本次 resolve 是否走了 ``context.current_file``
            回落。concrete 工具若需要在返回文案里提示 "使用了编辑器
            活动电路，请确认"可以据此判断。
    """

    result_path: str
    bundle_dir: Path
    result: SimulationResult
    circuit_file: str
    used_fallback: bool


# ============================================================
# 共享 prompt 片段
# ============================================================


READ_TOOL_SHARED_GUIDELINES: List[str] = [
    "If run_simulation returned a result_path earlier in this turn, pass "
    "that result_path verbatim to this tool — do not re-derive the path "
    "from the editor's active circuit; the explicit handle is always the "
    "safer choice.",
    "Do NOT pass both result_path and file_path in the same call — they "
    "identify different bundle-selection strategies and supplying both is "
    "rejected as ambiguous.",
    "When you pass file_path alone, this tool uses the most recent "
    "simulation bundle of that circuit; leaving both parameters empty "
    "falls back to the editor's active circuit and is allowed only when "
    "that circuit is the implicit subject of the user's question.",
    "If this tool reports the result bundle or a specific artifact is "
    "missing, do not retry with a re-inferred path — surface the error to "
    "the user exactly as reported so they can decide how to proceed.",
]


# ============================================================
# 基座
# ============================================================


class SimulationArtifactReaderBase:
    """Step 16 read-tool 基座（非 ``BaseTool`` 子类）。

    ``read_metrics`` / ``read_output_log`` / ``read_op_result`` /
    ``read_chart_image`` 各自继承自 ``BaseTool`` 并在内部持有一个
    本类实例（或直接调用 ``@staticmethod``）来完成参数解析部分。
    本类不是 ``BaseTool`` 本身——一个 base 里承载"解析链 + 工件
    读取格式化"会让两头职责都变模糊；只做解析，工具自己做格式化。

    典型用法::

        class ReadMetricsTool(BaseTool):
            @property
            def parameters(self):
                return SimulationArtifactReaderBase.build_parameters_schema(
                    extra_properties={
                        "metric_name": {"type": "string", ...},
                    },
                )

            async def execute(self, tool_call_id, params, context):
                resolved = SimulationArtifactReaderBase.resolve(params, context)
                if isinstance(resolved, ToolResult):
                    return resolved
                # resolved 是 ResolvedSimulationBundle
                return self._format_metrics(resolved, params)
    """

    # ------------------------------------------------------------------
    # 参数 schema 装配
    # ------------------------------------------------------------------

    #: 公共参数名 —— 子工具禁止覆盖这两项
    COMMON_PROPERTIES: Dict[str, Dict[str, Any]] = {
        "result_path": {
            "type": "string",
            "description": (
                "Project-relative POSIX path to a simulation bundle's "
                "result.json (as returned by run_simulation). Wins over "
                "file_path when both are somehow present. Omit this when "
                "you do not have a concrete result_path handle."
            ),
        },
        "file_path": {
            "type": "string",
            "description": (
                "Project-relative or absolute path to a circuit file. "
                "When result_path is omitted, the tool resolves this to "
                "the most recent simulation bundle of that circuit. "
                "Omit both parameters to fall back to the editor's "
                "currently active circuit file."
            ),
        },
    }

    @classmethod
    def build_parameters_schema(
        cls,
        extra_properties: Optional[Dict[str, Dict[str, Any]]] = None,
        extra_required: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """合并共享参数 + 子工具自身参数，产出 OpenAI function-calling
        兼容的 JSON schema。

        子工具想新增参数（例如 ``metric_name`` / ``offset`` / ``scope``）
        时通过 ``extra_properties`` 注入；子工具禁止重名覆盖
        ``result_path`` / ``file_path``——若侦测到重名立即 ``ValueError``
        让开发者在导入阶段就失败，避免运行时含糊行为。

        Args:
            extra_properties: 子工具独有参数字典，key 为参数名。
            extra_required: 子工具独有参数里强制要求的字段名列表。

        Returns:
            JSON schema 字典，形如::

                {
                    "type": "object",
                    "properties": {
                        "result_path": {...},
                        "file_path": {...},
                        # extra_properties 展开
                    },
                    "required": [...extra_required],
                }

            ``required`` 里**不包含** ``result_path`` / ``file_path``
            —— 两个都是可选的，基座会自行校验 "至少一个或回落"。
        """
        extras = dict(extra_properties or {})
        overlap = set(extras).intersection(cls.COMMON_PROPERTIES)
        if overlap:
            raise ValueError(
                "SimulationArtifactReaderBase.build_parameters_schema: "
                f"extra_properties collide with reserved keys {overlap}; "
                "rename your tool-specific parameters."
            )

        merged_properties: Dict[str, Any] = {}
        # 先 common 再 extras 保证字段顺序在 schema 里更稳定。
        merged_properties.update(cls.COMMON_PROPERTIES)
        merged_properties.update(extras)

        schema: Dict[str, Any] = {
            "type": "object",
            "properties": merged_properties,
            "required": list(extra_required or []),
        }
        return schema

    # ------------------------------------------------------------------
    # 解析链
    # ------------------------------------------------------------------

    @staticmethod
    def resolve(
        params: Dict[str, Any],
        context: ToolContext,
    ) -> Union[ResolvedSimulationBundle, ToolResult]:
        """把 ``params`` + ``context`` 解析成 ``ResolvedSimulationBundle``。

        返回值二选一：
        - ``ResolvedSimulationBundle``：解析成功，concrete 工具可直接
          读取 ``result`` / ``bundle_dir``。
        - ``ToolResult(is_error=True)``：任何一环失败都返回一个已经
          成文的错误结果，concrete 工具直接 ``return`` 即可，不需要
          自己写模板化 error。

        故意返回 Union 而不是 ``(bundle, error)`` tuple：让调用侧的分
        支只有一个 ``isinstance`` 即可，避免出现 "bundle 有但 error 也
        有"的表达式污染。
        """
        repository = context.sim_result_repository
        if repository is None:
            return ToolResult(
                content=(
                    "Error: SimulationResultRepository is not provided by "
                    "the caller via ToolContext; simulation-artifact read "
                    "tools cannot locate any bundle without it."
                ),
                is_error=True,
            )

        project_root = context.project_root
        if not project_root:
            return ToolResult(
                content=(
                    "Error: no project is open; simulation-artifact read "
                    "tools require a project root to resolve bundle paths."
                ),
                is_error=True,
            )

        raw_result_path = str(params.get("result_path") or "").strip()
        raw_file_path = str(params.get("file_path") or "").strip()

        if raw_result_path and raw_file_path:
            return ToolResult(
                content=(
                    "Error: result_path and file_path are mutually "
                    "exclusive — result_path targets a specific bundle, "
                    "file_path targets the most recent bundle of a "
                    "circuit. Supply only one of them."
                ),
                is_error=True,
            )

        used_fallback = False

        # ---- 分支 A: 显式 result_path ----
        if raw_result_path:
            result_path = _normalize_result_path(project_root, raw_result_path)
            return SimulationArtifactReaderBase._load_by_result_path(
                repository=repository,
                project_root=project_root,
                result_path=result_path,
                used_fallback=used_fallback,
            )

        # ---- 分支 B: 显式 file_path ----
        if raw_file_path:
            abs_circuit_path, err = validate_file_path(
                raw_file_path, project_root, must_exist=True
            )
            if err:
                return ToolResult(content=f"Error: {err}", is_error=True)
            assert abs_circuit_path is not None
            return SimulationArtifactReaderBase._load_by_circuit_file(
                repository=repository,
                project_root=project_root,
                abs_circuit_path=abs_circuit_path,
                display_path=raw_file_path,
                used_fallback=used_fallback,
            )

        # ---- 分支 C: 回落到 context.current_file ----
        fallback = context.current_file or ""
        if not fallback:
            return ToolResult(
                content=(
                    "Error: neither result_path nor file_path was provided "
                    "and no circuit file is currently active in the "
                    "editor. Supply at least one of the two parameters."
                ),
                is_error=True,
            )
        used_fallback = True
        abs_circuit_path, err = validate_file_path(
            fallback, project_root, must_exist=True
        )
        if err:
            # 活动电路存在但出了安全/存在错误——概率极低，但仍
            # 返回 is_error 让 agent 停下重新决定。
            return ToolResult(
                content=(
                    f"Error: editor's active circuit file '{fallback}' "
                    f"could not be resolved for read: {err}"
                ),
                is_error=True,
            )
        assert abs_circuit_path is not None
        return SimulationArtifactReaderBase._load_by_circuit_file(
            repository=repository,
            project_root=project_root,
            abs_circuit_path=abs_circuit_path,
            display_path=fallback,
            used_fallback=used_fallback,
        )

    # ------------------------------------------------------------------
    # 分支 A 实现：按 result_path 直接 load
    # ------------------------------------------------------------------

    @staticmethod
    def _load_by_result_path(
        repository,
        project_root: str,
        result_path: str,
        used_fallback: bool,
    ) -> Union[ResolvedSimulationBundle, ToolResult]:
        load = repository.load(project_root, result_path)
        if not load.success or load.data is None:
            err_msg = load.error_message or "unknown error"
            return ToolResult(
                content=(
                    f"Error: failed to load simulation result at "
                    f"'{result_path}': {err_msg}. If this path came from "
                    "an earlier run_simulation call, re-run that tool; "
                    "otherwise verify the path exists under the project."
                ),
                is_error=True,
            )

        bundle_dir = repository.resolve_bundle_dir(project_root, result_path)
        if bundle_dir is None:
            return ToolResult(
                content=(
                    f"Error: simulation bundle directory for "
                    f"'{result_path}' is missing or unreadable. The "
                    "result.json loaded but its sibling artifacts are "
                    "not accessible on disk."
                ),
                is_error=True,
            )

        sim_result: SimulationResult = load.data
        return ResolvedSimulationBundle(
            result_path=result_path,
            bundle_dir=bundle_dir,
            result=sim_result,
            circuit_file=sim_result.file_path or "",
            used_fallback=used_fallback,
        )

    # ------------------------------------------------------------------
    # 分支 B/C 实现：按电路文件查最近 bundle 后再 load
    # ------------------------------------------------------------------

    @staticmethod
    def _load_by_circuit_file(
        repository,
        project_root: str,
        abs_circuit_path: str,
        display_path: str,
        used_fallback: bool,
    ) -> Union[ResolvedSimulationBundle, ToolResult]:
        """按电路文件聚合检索。

        ``list_by_circuit(per_circuit_limit=1)`` 返回每个电路的最新
        一个 bundle。比较时用 ``os.path.normcase + os.path.normpath``
        的 Windows 不敏感姿态，和 ``run_simulation`` 的并发守护比较
        规则保持一致（见 ``_same_circuit_path``）。
        """
        target = os.path.normcase(os.path.normpath(abs_circuit_path))
        groups = repository.list_by_circuit(project_root, per_circuit_limit=1)
        for group in groups:
            candidate_abs = group.circuit_absolute_path or ""
            if not candidate_abs:
                continue
            if os.path.normcase(os.path.normpath(candidate_abs)) != target:
                continue
            if not group.results:
                continue
            return SimulationArtifactReaderBase._load_by_result_path(
                repository=repository,
                project_root=project_root,
                result_path=group.results[0].result_path,
                used_fallback=used_fallback,
            )

        hint = (
            " (editor's active circuit)" if used_fallback else ""
        )
        # 只陈述事实，不点名下一步该调哪个工具——该电路可能确实
        # 从未被仿真过，也可能 bundle 已被清理；用户/LLM 如何处理
        # 由它们结合上下文自行决定。措辞里"pass a result_path from
        # an earlier run"是**本工具**的参数卫生提示（B 类），不是
        # 跨工具的 workflow 编排。
        return ToolResult(
            content=(
                f"Error: no simulation bundle was found for circuit "
                f"'{display_path}'{hint}. Either this circuit has not "
                "been simulated in this project, or its bundles are no "
                "longer accessible. If you know an earlier simulation "
                "produced a bundle, call this tool with its result_path "
                "directly instead of relying on circuit-path lookup."
            ),
            is_error=True,
        )


# ============================================================
# 内部工具
# ============================================================


def _normalize_result_path(project_root: str, raw_result_path: str) -> str:
    """把 LLM 传入的 ``result_path`` 归一化为仓储期望的"项目相对 POSIX"。

    ``run_simulation`` 返回给 LLM 的 result_path 已经是项目相对
    POSIX 的；但 LLM 有时会加上项目绝对前缀（"E:\\...\\simulation_results/..."
    反斜杠混杂）。仓储 ``load`` 内部用 ``Path(project_root) / result_path``
    拼绝对路径——如果传入本来就是绝对路径，``/`` 运算符**会**保留它
    的绝对性（Path 的语义如此），所以绝对路径本身不会挂。但为了
    ``list_by_circuit`` / ``load`` 的 id 一致性，这里仍统一折成
    项目相对 POSIX：
    - 先把反斜杠折成正斜杠；
    - 若是绝对路径且落在 project_root 内，裁成相对；
    - 否则原样返回（让仓储那边报 file_missing 即可）。
    """
    cleaned = raw_result_path.replace("\\", "/")
    candidate = Path(cleaned)
    if candidate.is_absolute():
        try:
            relative = candidate.resolve().relative_to(
                Path(project_root).resolve()
            )
            return relative.as_posix()
        except (ValueError, OSError):
            # 绝对但不在项目里——仓储 load 会给 file_missing；保留
            # 原样让上层错误文案里直接出现这条 bogus 路径。
            return cleaned
    return cleaned


# ============================================================
# Target 达标判定 —— 所有 read 工具共用的只读 util
# ============================================================


class TargetStatus(enum.Enum):
    """指标是否达到用户设定目标的判定结果。

    四个值覆盖**全部**可能态，不给 tool 留"自己再判断一遍"的空
    间——``NO_TARGET`` 和 ``UNPARSEABLE`` 也是显式状态：

    - ``PASS``: 解析成功且数值满足比较式。
    - ``FAIL``: 解析成功但数值不满足。
    - ``NO_TARGET``: 原文为空字符串——用户没设置目标，这不是错误，
      应当在展示时归入"无目标"段而不是"未达标"段。
    - ``UNPARSEABLE``: 原文非空但语法无法识别——展示时标注"目标
      格式无法解析"，让用户去修 target 文案，而不是让 tool 瞎猜。
    """
    PASS = "pass"
    FAIL = "fail"
    NO_TARGET = "no_target"
    UNPARSEABLE = "unparseable"


# ``evaluate_metric_target`` 的词法：一个可选比较操作符、一个
# 带可选正负号与科学计数法的十进制数、以及剩余文本。剩余文本的
# 第一个非空白字符若为公认的 SI 前缀字符，则乘以对应数量级。
#
# 特意**不**引入完整单位代数（如 ``0.005 Ω`` vs ``5 mΩ`` 的维度
# 转换）——那属于 ``MetricTargetService`` 规范化层的职责，目前用
# 户给的是自由文本，我们只做"数值量级 × 比较方向"这两件 LLM 判达
# 标必须用到的事。
_TARGET_PATTERN = re.compile(
    r"""^\s*
    (?P<op>>=|<=|==|!=|>|<|=|≥|≤|≠)?
    \s*
    (?P<num>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
    \s*
    (?P<rest>.*)$""",
    re.VERBOSE,
)

# SI 前缀字符到量级的映射。大小写分开：``M`` 是 mega（1e6），
# ``m`` 是 milli（1e-3）。``K`` 虽非标准 SI 但用户常写，收录。
# ``μ`` 与 ASCII 回退 ``u`` 都映射 1e-6。
_SI_PREFIXES: Dict[str, float] = {
    "T": 1e12,
    "G": 1e9,
    "M": 1e6,
    "k": 1e3,
    "K": 1e3,
    "m": 1e-3,
    "u": 1e-6,
    "μ": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
}


def evaluate_metric_target(
    raw_value: Optional[float],
    target_text: Optional[str],
) -> TargetStatus:
    """判定某一指标是否达到用户目标——**全局唯一**入口。

    支持的 target 语法::

        [op] <number>[si_prefix][unit_suffix]

    - ``op``: 可省略，省略时默认 ``=``；支持 ASCII ``>=`` / ``<=`` /
      ``>`` / ``<`` / ``=`` / ``==`` / ``!=``，以及 Unicode ``≥`` /
      ``≤`` / ``≠``。
    - ``number``: 普通十进制或科学计数法。
    - ``si_prefix``: 紧跟在数字后的单个 SI 前缀字符（``k``/``M``/
      ``G`` 等），用于把用户写的 ``"5mA"`` 解析为 0.005（与
      ``DisplayMetric.raw_value`` 的 SI-base 量级对齐）。
    - ``unit_suffix``: 随意单位文本（``"dB"`` / ``"Hz"`` /
      ``"Ω"``），**被忽略**——我们不做维度校验，单位一致性是用户
      责任。

    ``=`` 用相对容差 1% 比较（绝对零时退化为 1e-9 绝对容差），
    因为浮点严格相等对仿真输出几乎总会 ``FAIL``。

    Args:
        raw_value: 指标的 SI-base 原值；``None`` 时视为无法判定。
        target_text: 用户原文；``None`` / 空串返回 ``NO_TARGET``。

    Returns:
        :class:`TargetStatus` 的一个实例。**绝不**抛异常——解析失
        败返回 ``UNPARSEABLE``，让上层一律走展示分支。
    """
    if target_text is None:
        return TargetStatus.NO_TARGET
    cleaned = str(target_text).strip()
    if not cleaned:
        return TargetStatus.NO_TARGET

    match = _TARGET_PATTERN.match(cleaned)
    if not match:
        return TargetStatus.UNPARSEABLE

    try:
        numeric = float(match.group("num"))
    except (TypeError, ValueError):
        return TargetStatus.UNPARSEABLE

    rest = (match.group("rest") or "").lstrip()
    if rest:
        prefix_char = rest[0]
        multiplier = _SI_PREFIXES.get(prefix_char)
        if multiplier is not None:
            numeric *= multiplier

    # raw_value 为 None 时严格来说"无法判定"，但既然 target 文本
    # 合法，将其视为 FAIL（展示成"未达标"）比静默降级为 UNPARSEABLE
    # 更诚实——LLM 看到 FAIL 会追问 read_output_log，看到
    # UNPARSEABLE 可能去改目标语法，这两条决策分支不能混。
    if raw_value is None:
        return TargetStatus.FAIL

    op = match.group("op") or "="
    if op == "==":
        op = "="
    if op == "≥":
        op = ">="
    if op == "≤":
        op = "<="
    if op == "≠":
        op = "!="

    if op == ">=":
        return TargetStatus.PASS if raw_value >= numeric else TargetStatus.FAIL
    if op == "<=":
        return TargetStatus.PASS if raw_value <= numeric else TargetStatus.FAIL
    if op == ">":
        return TargetStatus.PASS if raw_value > numeric else TargetStatus.FAIL
    if op == "<":
        return TargetStatus.PASS if raw_value < numeric else TargetStatus.FAIL
    if op == "!=":
        return TargetStatus.PASS if raw_value != numeric else TargetStatus.FAIL
    # op == "="
    tolerance = max(abs(numeric) * 0.01, 1e-9)
    return (
        TargetStatus.PASS
        if abs(raw_value - numeric) <= tolerance
        else TargetStatus.FAIL
    )


# ============================================================
# 模块导出
# ============================================================


__all__ = [
    "SimulationArtifactReaderBase",
    "ResolvedSimulationBundle",
    "READ_TOOL_SHARED_GUIDELINES",
    "TargetStatus",
    "evaluate_metric_target",
    "sort_op_result_node_rows",
    "sort_op_result_branch_rows",
    "sort_op_result_device_rows",
]
