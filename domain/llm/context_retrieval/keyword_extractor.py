# Keyword Extractor
"""
关键词提取器 - 从用户消息中提取 SPICE 领域相关的关键词

职责：
- 从用户消息中提取 SPICE 领域相关的关键词
- 用于精确匹配检索

关键词提取策略（针对 SPICE 领域优化）：
- 器件名提取：正则匹配 R\d+、C\d+、L\d+、Q\d+、M\d+、D\d+
- 节点名提取：正则匹配 V[a-zA-Z_]+、大写开头的标识符
- 文件名提取：正则匹配 \w+\.(cir|sp|spice)
- 子电路名提取：正则匹配 .subckt 后的标识符
- 指标词提取：预定义词表
- 语义查询生成：去除已提取关键词后的剩余文本

被调用方：context_retriever.py
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Set


# ============================================================
# 常量定义
# ============================================================

# 器件名正则模式
DEVICE_PATTERNS = [
    (r'\b[Rr]\d+\b', "resistor"),      # R1, R2, r1
    (r'\b[Cc]\d+\b', "capacitor"),     # C1, C2, c1
    (r'\b[Ll]\d+\b', "inductor"),      # L1, L2, l1
    (r'\b[Qq]\d+\b', "bjt"),           # Q1, Q2 (BJT)
    (r'\b[Mm]\d+\b', "mosfet"),        # M1, M2 (MOSFET)
    (r'\b[Dd]\d+\b', "diode"),         # D1, D2
    (r'\b[Vv]\d+\b', "voltage_source"),# V1, V2
    (r'\b[Ii]\d+\b', "current_source"),# I1, I2
    (r'\b[Xx]\d+\b', "subcircuit"),    # X1, X2 (子电路实例)
]

# 节点名正则模式
NODE_PATTERNS = [
    r'\bV[a-zA-Z_]\w*\b',      # Vcc, Vdd, Vin, Vout
    r'\bGND\b',                 # 地节点
    r'\b0\b',                   # 地节点（数字0）
    r'\b[A-Z][a-zA-Z_]\w*\b',  # 大写开头的标识符
]

# 文件名正则模式
FILE_PATTERN = r'\b(\w+)\.(cir|sp|spice|lib|inc)\b'

# 子电路名正则模式
SUBCKT_PATTERN = r'\.subckt\s+(\w+)'
SUBCKT_INSTANCE_PATTERN = r'\bX\w*\s+\S+\s+\S+\s+(\w+)\b'


# SPICE 指标词表
SPICE_METRICS = {
    # 增益相关
    "gain", "amplification", "attenuation",
    # 频率相关
    "bandwidth", "frequency", "cutoff", "rolloff", "bode",
    # 相位相关
    "phase", "margin", "stability",
    # 阻抗相关
    "impedance", "resistance", "capacitance", "inductance",
    # 电压电流
    "voltage", "current", "power", "bias",
    # 噪声相关
    "noise", "snr", "distortion", "thd",
    # 时域相关
    "slew", "settling", "overshoot", "undershoot", "rise", "fall", "delay",
    # 运放相关
    "offset", "cmrr", "psrr", "gbw", "unity",
    # 分析类型
    "ac", "dc", "transient", "tran", "op", "sweep",
    # 电路类型
    "amplifier", "filter", "oscillator", "comparator", "regulator",
    "inverting", "noninverting", "differential", "feedback",
}

# 停用词（不作为关键词）
STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "shall",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
    "this", "that", "these", "those", "what", "which", "who", "whom",
    "and", "or", "but", "if", "then", "else", "when", "where", "how",
    "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "no", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "also", "now", "here", "there",
    "please", "help", "want", "need", "can", "make", "design",
}


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
        """获取所有关键词"""
        return (self.devices | self.nodes | self.files | 
                self.subcircuits | self.metrics | self.identifiers)
    
    def to_dict(self) -> Dict[str, Set[str]]:
        """转换为字典"""
        return {
            "devices": self.devices,
            "nodes": self.nodes,
            "files": self.files,
            "subcircuits": self.subcircuits,
            "metrics": self.metrics,
            "identifiers": self.identifiers,
        }



class KeywordExtractor:
    """
    关键词提取器
    
    从用户消息中提取 SPICE 领域相关的关键词。
    """

    def __init__(self):
        self._logger = None

    @property
    def logger(self):
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
        keywords = ExtractedKeywords()
        
        keywords.devices = self.extract_device_names(message)
        keywords.nodes = self.extract_node_names(message)
        keywords.files = self.extract_file_names(message)
        keywords.subcircuits = self.extract_subcircuit_names(message)
        keywords.metrics = self.extract_metric_keywords(message)
        keywords.identifiers = self._extract_identifiers(message)
        
        if self.logger:
            total = len(keywords.all_keywords())
            self.logger.debug(f"Extracted {total} keywords from message")
        
        return keywords

    # ============================================================
    # 提取方法
    # ============================================================

    def extract_device_names(self, message: str) -> Set[str]:
        """
        提取器件名
        
        匹配：R1, C2, L3, Q4, M5, D6, V1, I1, X1 等
        """
        devices = set()
        for pattern, _ in DEVICE_PATTERNS:
            matches = re.findall(pattern, message, re.IGNORECASE)
            devices.update(m.upper() for m in matches)
        return devices

    def extract_node_names(self, message: str) -> Set[str]:
        """
        提取节点名
        
        匹配：Vcc, Vdd, Vin, Vout, GND 等
        """
        nodes = set()
        for pattern in NODE_PATTERNS:
            matches = re.findall(pattern, message)
            # 过滤掉已识别为器件的
            for m in matches:
                if not re.match(r'^[RCLQMDVIX]\d+$', m, re.IGNORECASE):
                    nodes.add(m)
        return nodes

    def extract_file_names(self, message: str) -> Set[str]:
        """
        提取文件名
        
        匹配：xxx.cir, xxx.sp, xxx.spice, xxx.lib, xxx.inc
        """
        files = set()
        matches = re.findall(FILE_PATTERN, message, re.IGNORECASE)
        for name, ext in matches:
            files.add(f"{name}.{ext}")
        return files

    def extract_subcircuit_names(self, message: str) -> Set[str]:
        """
        提取子电路名
        
        匹配：.subckt 后的标识符，以及 X 实例引用的子电路
        """
        subcircuits = set()
        
        # .subckt 定义
        subckt_matches = re.findall(SUBCKT_PATTERN, message, re.IGNORECASE)
        subcircuits.update(subckt_matches)
        
        # X 实例引用（简化匹配）
        instance_matches = re.findall(SUBCKT_INSTANCE_PATTERN, message, re.IGNORECASE)
        subcircuits.update(instance_matches)
        
        return subcircuits


    def extract_metric_keywords(self, message: str) -> Set[str]:
        """
        提取指标词
        
        从预定义词表中匹配
        """
        words = set(re.findall(r'\b\w+\b', message.lower()))
        return words & SPICE_METRICS

    def _extract_identifiers(self, message: str) -> Set[str]:
        """
        提取其他标识符
        
        大写开头的词，排除已识别的关键词
        """
        identifiers = set()
        matches = re.findall(r'\b[A-Z][a-zA-Z0-9_]+\b', message)
        
        for m in matches:
            # 排除器件名
            if re.match(r'^[RCLQMDVIX]\d+$', m, re.IGNORECASE):
                continue
            # 排除常见节点名
            if m.upper() in {"VCC", "VDD", "VSS", "VEE", "GND"}:
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
        
        去除已提取的关键词后的剩余文本，用于向量检索。
        
        Args:
            message: 原始用户消息
            keywords: 已提取的关键词
            
        Returns:
            str: 语义查询文本
        """
        # 获取所有已提取的关键词
        all_kw = keywords.all_keywords()
        
        # 分词
        words = re.findall(r'\b\w+\b', message)
        
        # 过滤
        filtered_words = []
        for word in words:
            word_lower = word.lower()
            word_upper = word.upper()
            
            # 跳过已提取的关键词
            if word in all_kw or word_lower in all_kw or word_upper in all_kw:
                continue
            
            # 跳过停用词
            if word_lower in STOP_WORDS:
                continue
            
            # 跳过纯数字
            if word.isdigit():
                continue
            
            filtered_words.append(word)
        
        # 重建查询
        query = " ".join(filtered_words)
        
        # 如果查询太短，返回原始消息
        if len(query) < 10:
            return message
        
        return query

    def get_search_terms(self, keywords: ExtractedKeywords) -> List[str]:
        """
        获取搜索词列表（按优先级排序）
        
        优先级：器件名 > 子电路名 > 文件名 > 指标词 > 节点名 > 标识符
        """
        terms = []
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
]
