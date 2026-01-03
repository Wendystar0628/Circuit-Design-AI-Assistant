# Keyword Extractor
r"""
关键词提取器 - 从用户消息中提取 SPICE 领域相关的关键词

职责：
- 从用户消息中提取 SPICE 领域相关的关键词
- 用于精确匹配检索

关键词提取策略（针对 SPICE 领域优化）：
- 器件名提取：R\d+、C\d+、L\d+、Q\d+、M\d+、D\d+、V\d+、I\d+、X\d+
- 节点名提取：V[a-zA-Z_]\w*、GND、net_\w+、n_\w+、大写开头的标识符
- 文件名提取：\w+\.(cir|sp|spice|lib|inc)
- 子电路名提取：.subckt 定义和 X 实例引用
- 指标词提取：预定义词表
- 语义查询生成：去除已提取关键词后的剩余文本

被调用方：context_retriever.py
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ============================================================
# 常量定义
# ============================================================

# 器件名正则模式：(pattern, device_type)
DEVICE_PATTERNS: List[Tuple[str, str]] = [
    (r"\b[Rr]\d+\b", "resistor"),        # R1, R2, r1
    (r"\b[Cc]\d+\b", "capacitor"),       # C1, C2, c1
    (r"\b[Ll]\d+\b", "inductor"),        # L1, L2, l1
    (r"\b[Qq]\d+\b", "bjt"),             # Q1, Q2 (BJT)
    (r"\b[Mm]\d+\b", "mosfet"),          # M1, M2 (MOSFET)
    (r"\b[Dd]\d+\b", "diode"),           # D1, D2
    (r"\b[Vv]\d+\b", "voltage_source"),  # V1, V2
    (r"\b[Ii]\d+\b", "current_source"),  # I1, I2
    (r"\b[Xx]\d+\b", "subcircuit"),      # X1, X2 (子电路实例)
    (r"\b[Ee]\d+\b", "vcvs"),            # E1, E2 (电压控制电压源)
    (r"\b[Ff]\d+\b", "cccs"),            # F1, F2 (电流控制电流源)
    (r"\b[Gg]\d+\b", "vccs"),            # G1, G2 (电压控制电流源)
    (r"\b[Hh]\d+\b", "ccvs"),            # H1, H2 (电流控制电压源)
]

# 器件名正则（用于过滤，匹配所有器件类型）
DEVICE_NAME_PATTERN = r"^[RCLQMDVIXEFGHrclqmdvixefgh]\d+$"

# 节点名正则模式
NODE_PATTERNS: List[str] = [
    r"\bV[a-zA-Z_]\w*\b",       # Vcc, Vdd, Vin, Vout
    r"\bGND\b",                  # 地节点
    r"\bVSS\b",                  # 负电源
    r"\bVDD\b",                  # 正电源
    r"\bVEE\b",                  # 负电源
    r"\bVCC\b",                  # 正电源
    r"\bnet_\w+\b",              # net_1, net_out
    r"\bn_\w+\b",                # n_1, n_out
    r"\bnode_\w+\b",             # node_1, node_out
]

# 文件名正则模式
FILE_PATTERN = r"\b(\w+)\.(cir|sp|spice|lib|inc|sub|mod)\b"

# 子电路定义正则模式
SUBCKT_DEF_PATTERN = r"\.subckt\s+(\w+)"

# 子电路实例正则模式（X<name> <nodes...> <subckt_name>）
# 匹配最后一个非数字、非节点的标识符作为子电路名
SUBCKT_INSTANCE_PATTERN = r"\bX\w*\s+(?:\S+\s+)+(\w+)\s*$"

# SPICE 指标词表（扩展版）
SPICE_METRICS: Set[str] = {
    # 增益相关
    "gain", "amplification", "attenuation", "av", "ai",
    # 频率相关
    "bandwidth", "frequency", "cutoff", "rolloff", "bode",
    "f3db", "fh", "fl", "fc", "bw",
    # 相位相关
    "phase", "margin", "stability", "pm", "gm",
    # 阻抗相关
    "impedance", "resistance", "capacitance", "inductance",
    "zin", "zout", "rin", "rout",
    # 电压电流
    "voltage", "current", "power", "bias",
    # 噪声相关
    "noise", "snr", "distortion", "thd", "nf",
    # 时域相关
    "slew", "settling", "overshoot", "undershoot",
    "rise", "fall", "delay", "propagation",
    "risetime", "falltime", "slewrate",
    # 运放相关
    "offset", "cmrr", "psrr", "gbw", "gbp", "unity",
    "vos", "ios", "ib",
    # 分析类型
    "ac", "dc", "transient", "tran", "op", "sweep",
    "monte", "corner", "sensitivity", "pz",
    # 电路类型
    "amplifier", "filter", "oscillator", "comparator", "regulator",
    "inverting", "noninverting", "differential", "feedback",
    "lowpass", "highpass", "bandpass", "notch",
    # 仿真参数
    "temperature", "temp", "vdd", "vss", "supply",
}

# 停用词（不作为关键词）
STOP_WORDS: Set[str] = {
    # 冠词和代词
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "shall",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
    "this", "that", "these", "those", "what", "which", "who", "whom",
    # 连词和介词
    "and", "or", "but", "if", "then", "else", "when", "where", "how",
    "for", "to", "from", "with", "without", "in", "on", "at", "by",
    "of", "about", "into", "through", "during", "before", "after",
    # 限定词
    "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "no", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "also", "now", "here", "there",
    # 常见动词
    "please", "help", "want", "need", "can", "make", "design",
    "show", "tell", "explain", "analyze", "check", "fix", "modify",
    "create", "add", "remove", "change", "update", "set", "get",
}

# 常见英文单词（用于过滤标识符，不应作为 SPICE 关键词）
COMMON_WORDS: Set[str] = {
    # 句首常见词（大写开头）
    "the", "please", "check", "analyze", "show", "tell", "explain",
    "help", "want", "need", "make", "design", "create", "add",
    "remove", "change", "update", "set", "get", "find", "look",
    "see", "use", "using", "used", "try", "test", "run", "start",
    "stop", "open", "close", "save", "load", "read", "write",
    # 其他常见词
    "circuit", "file", "value", "values", "model", "node", "nodes",
    "output", "input", "result", "results", "error", "warning",
    "simulation", "analysis", "parameter", "parameters",
}


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class ExtractedKeywords:
    """提取的关键词集合"""

    devices: Set[str] = field(default_factory=set)
    nodes: Set[str] = field(default_factory=set)
    files: Set[str] = field(default_factory=set)
    subcircuits: Set[str] = field(default_factory=set)
    metrics: Set[str] = field(default_factory=set)
    identifiers: Set[str] = field(default_factory=set)

    def all_keywords(self) -> Set[str]:
        """获取所有关键词的并集"""
        return (
            self.devices
            | self.nodes
            | self.files
            | self.subcircuits
            | self.metrics
            | self.identifiers
        )

    def to_dict(self) -> Dict[str, List[str]]:
        """转换为字典格式（集合转列表，便于序列化）"""
        return {
            "devices": sorted(self.devices),
            "nodes": sorted(self.nodes),
            "files": sorted(self.files),
            "subcircuits": sorted(self.subcircuits),
            "metrics": sorted(self.metrics),
            "identifiers": sorted(self.identifiers),
        }

    def is_empty(self) -> bool:
        """检查是否为空"""
        return len(self.all_keywords()) == 0

    def __len__(self) -> int:
        """返回关键词总数"""
        return len(self.all_keywords())


# ============================================================
# 关键词提取器
# ============================================================

class KeywordExtractor:
    """
    关键词提取器

    从用户消息中提取 SPICE 领域相关的关键词，用于精确匹配检索。
    """

    def __init__(self) -> None:
        self._logger: Optional[object] = None
        # 预编译正则表达式以提高性能
        self._device_patterns = [
            (re.compile(pattern, re.IGNORECASE), device_type)
            for pattern, device_type in DEVICE_PATTERNS
        ]
        self._device_filter = re.compile(DEVICE_NAME_PATTERN, re.IGNORECASE)
        self._node_patterns = [re.compile(p) for p in NODE_PATTERNS]
        self._file_pattern = re.compile(FILE_PATTERN, re.IGNORECASE)
        self._subckt_def_pattern = re.compile(SUBCKT_DEF_PATTERN, re.IGNORECASE)
        self._word_pattern = re.compile(r"\b\w+\b")

    @property
    def logger(self) -> Optional[object]:
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("keyword_extractor")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 主入口
    # ============================================================

    def extract(self, message: str) -> ExtractedKeywords:
        """
        提取所有类型的关键词

        Args:
            message: 用户消息

        Returns:
            ExtractedKeywords: 提取的关键词集合
        """
        if not message or not message.strip():
            return ExtractedKeywords()

        keywords = ExtractedKeywords()

        # 按顺序提取各类关键词
        keywords.devices = self.extract_device_names(message)
        keywords.nodes = self.extract_node_names(message)
        keywords.files = self.extract_file_names(message)
        keywords.subcircuits = self.extract_subcircuit_names(message)
        keywords.metrics = self.extract_metric_keywords(message)
        keywords.identifiers = self._extract_identifiers(message, keywords)

        if self.logger:
            total = len(keywords)
            self.logger.debug(f"Extracted {total} keywords from message")

        return keywords

    # ============================================================
    # 器件名提取
    # ============================================================

    def extract_device_names(self, message: str) -> Set[str]:
        """
        提取器件名

        匹配：R1, C2, L3, Q4, M5, D6, V1, I1, X1, E1, F1, G1, H1 等

        Args:
            message: 用户消息

        Returns:
            Set[str]: 器件名集合（统一转为大写）
        """
        devices: Set[str] = set()

        for pattern, _ in self._device_patterns:
            matches = pattern.findall(message)
            devices.update(m.upper() for m in matches)

        return devices

    # ============================================================
    # 节点名提取
    # ============================================================

    def extract_node_names(self, message: str) -> Set[str]:
        """
        提取节点名

        匹配：Vcc, Vdd, Vin, Vout, GND, net_1, n_out 等

        Args:
            message: 用户消息

        Returns:
            Set[str]: 节点名集合
        """
        nodes: Set[str] = set()

        for pattern in self._node_patterns:
            matches = pattern.findall(message)
            for m in matches:
                # 过滤掉已识别为器件的（如 V1, V2）
                if not self._device_filter.match(m):
                    nodes.add(m)

        # 特殊处理：数字 0 作为地节点
        if re.search(r"\b0\b", message):
            nodes.add("0")

        return nodes

    # ============================================================
    # 文件名提取
    # ============================================================

    def extract_file_names(self, message: str) -> Set[str]:
        """
        提取文件名

        匹配：xxx.cir, xxx.sp, xxx.spice, xxx.lib, xxx.inc, xxx.sub, xxx.mod

        Args:
            message: 用户消息

        Returns:
            Set[str]: 文件名集合
        """
        files: Set[str] = set()

        matches = self._file_pattern.findall(message)
        for name, ext in matches:
            files.add(f"{name}.{ext.lower()}")

        return files

    # ============================================================
    # 子电路名提取
    # ============================================================

    def extract_subcircuit_names(self, message: str) -> Set[str]:
        """
        提取子电路名

        匹配：
        - .subckt <name> 定义中的名称
        - X<instance> <nodes...> <subckt_name> 实例引用中的子电路名

        Args:
            message: 用户消息

        Returns:
            Set[str]: 子电路名集合
        """
        subcircuits: Set[str] = set()

        # 1. 提取 .subckt 定义中的名称
        subckt_matches = self._subckt_def_pattern.findall(message)
        subcircuits.update(subckt_matches)

        # 2. 提取 X 实例引用中的子电路名
        # 按行处理，因为 X 实例通常在单独一行
        for line in message.split("\n"):
            line = line.strip()
            if not line:
                continue

            # 检查是否以 X 开头（子电路实例）
            if re.match(r"^[Xx]\w*\s+", line):
                # 提取最后一个标识符作为子电路名
                parts = line.split()
                if len(parts) >= 3:
                    # 最后一个非注释部分
                    last_part = parts[-1]
                    # 排除数字和常见节点名
                    if (
                        not last_part.isdigit()
                        and not self._device_filter.match(last_part)
                        and last_part.upper() not in {"GND", "VCC", "VDD", "VSS", "VEE", "0"}
                    ):
                        subcircuits.add(last_part)

        return subcircuits

    # ============================================================
    # 指标词提取
    # ============================================================

    def extract_metric_keywords(self, message: str) -> Set[str]:
        """
        提取指标词

        从预定义词表中匹配 SPICE 领域相关的指标词

        Args:
            message: 用户消息

        Returns:
            Set[str]: 指标词集合（小写）
        """
        words = set(self._word_pattern.findall(message.lower()))
        return words & SPICE_METRICS

    # ============================================================
    # 标识符提取
    # ============================================================

    def _extract_identifiers(
        self,
        message: str,
        existing_keywords: ExtractedKeywords,
    ) -> Set[str]:
        """
        提取其他标识符

        大写开头的词，排除已识别的关键词和常见英文单词

        Args:
            message: 用户消息
            existing_keywords: 已提取的关键词

        Returns:
            Set[str]: 标识符集合
        """
        identifiers: Set[str] = set()

        # 匹配大写开头的标识符
        matches = re.findall(r"\b[A-Z][a-zA-Z0-9_]+\b", message)

        # 已识别的关键词集合
        existing = existing_keywords.all_keywords()
        existing_upper = {k.upper() for k in existing}

        for m in matches:
            m_upper = m.upper()
            m_lower = m.lower()

            # 排除已识别的关键词
            if m in existing or m_upper in existing_upper:
                continue

            # 排除器件名模式
            if self._device_filter.match(m):
                continue

            # 排除常见节点名
            if m_upper in {"VCC", "VDD", "VSS", "VEE", "GND"}:
                continue

            # 排除常见英文单词
            if m_lower in COMMON_WORDS or m_lower in STOP_WORDS:
                continue

            identifiers.add(m)

        return identifiers

    # ============================================================
    # 语义查询生成
    # ============================================================

    def generate_semantic_query(
        self,
        message: str,
        keywords: ExtractedKeywords,
    ) -> str:
        """
        生成语义查询

        去除已提取的关键词和停用词后的剩余文本，用于向量检索。

        Args:
            message: 原始用户消息
            keywords: 已提取的关键词

        Returns:
            str: 语义查询文本
        """
        # 获取所有已提取的关键词（包括大小写变体）
        all_kw = keywords.all_keywords()
        all_kw_lower = {k.lower() for k in all_kw}
        all_kw_upper = {k.upper() for k in all_kw}

        def is_keyword(word: str) -> bool:
            """检查单词是否为已提取的关键词"""
            return (
                word in all_kw
                or word.lower() in all_kw_lower
                or word.upper() in all_kw_upper
            )

        # 分词
        words = self._word_pattern.findall(message)

        # 过滤
        filtered_words: List[str] = []
        for word in words:
            word_lower = word.lower()

            # 跳过已提取的关键词
            if is_keyword(word):
                continue

            # 跳过停用词
            if word_lower in STOP_WORDS:
                continue

            # 跳过纯数字
            if word.isdigit():
                continue

            # 跳过单字符
            if len(word) <= 1:
                continue

            filtered_words.append(word)

        # 重建查询
        query = " ".join(filtered_words)

        # 如果查询太短，返回原始消息（去除停用词和关键词）
        if len(query) < 10:
            fallback_words = [
                w for w in words
                if w.lower() not in STOP_WORDS
                and len(w) > 1
                and not is_keyword(w)
            ]
            return " ".join(fallback_words) if fallback_words else message

        return query

    # ============================================================
    # 搜索词列表
    # ============================================================

    def get_search_terms(self, keywords: ExtractedKeywords) -> List[str]:
        """
        获取搜索词列表（按优先级排序）

        优先级顺序：
        1. 器件名（最高优先级，直接定位元件）
        2. 子电路名（定位模块）
        3. 文件名（定位文件）
        4. 指标词（定位分析类型）
        5. 节点名（定位连接点）
        6. 其他标识符（最低优先级）

        Args:
            keywords: 提取的关键词

        Returns:
            List[str]: 按优先级排序的搜索词列表
        """
        terms: List[str] = []
        terms.extend(sorted(keywords.devices))
        terms.extend(sorted(keywords.subcircuits))
        terms.extend(sorted(keywords.files))
        terms.extend(sorted(keywords.metrics))
        terms.extend(sorted(keywords.nodes))
        terms.extend(sorted(keywords.identifiers))
        return terms


__all__ = [
    "KeywordExtractor",
    "ExtractedKeywords",
    "SPICE_METRICS",
    "DEVICE_PATTERNS",
    "STOP_WORDS",
    "COMMON_WORDS",
]
