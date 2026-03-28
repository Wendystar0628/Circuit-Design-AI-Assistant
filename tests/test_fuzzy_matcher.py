# Test Fuzzy Matcher - Business-Oriented Test Cases
"""
模糊匹配器测试

测试场景基于实际业务：
1. 文件名搜索 - 用户输入部分文件名查找电路文件
2. SPICE 代码修改定位 - LLM patch_file 时模糊匹配代码块
3. 符号搜索 - 查找子电路、参数定义
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.file_intelligence.search.fuzzy import (
    FuzzyMatcher,
    MatchOptions,
    SimilarityAlgorithms,
    TextNormalizer,
    NormalizeOptions,
)


def test_file_name_search():
    """
    场景1：文件名搜索
    
    用户在文件浏览器中输入部分名称，查找电路文件。
    """
    print("=" * 60)
    print("场景1：文件名搜索")
    print("=" * 60)
    
    # 模拟项目中的文件列表
    project_files = [
        "amplifier.cir",
        "inverting_amplifier.cir",
        "non_inverting_amp.cir",
        "opamp_741.cir",
        "opamp_lm358.cir",
        "sallen_key_lowpass.cir",
        "butterworth_filter.cir",
        "power_supply.cir",
        "voltage_regulator.cir",
        "parameters/resistors.param",
        "parameters/capacitors.param",
        "subcircuits/opamp_model.sub",
        "subcircuits/transistor_model.sub",
    ]
    
    matcher = FuzzyMatcher(MatchOptions(
        threshold=0.4,
        algorithm='jaro_winkler'  # 文件名匹配用 jaro_winkler
    ))
    
    # 测试用例
    test_queries = [
        ("amp", "查找所有放大器相关文件"),
        ("opamp", "查找运放文件"),
        ("filter", "查找滤波器"),
        ("inv", "查找反相放大器"),
        ("param", "查找参数文件"),
        ("741", "查找特定型号"),
    ]
    
    for query, desc in test_queries:
        print(f"\n查询: '{query}' ({desc})")
        results = matcher.find_best_matches(query, project_files, top_k=5)
        for r in results:
            print(f"  {r.score:.2f} | {r.target} | 类型: {r.match_type}")


def test_spice_code_patch_location():
    """
    场景2：SPICE 代码修改定位
    
    LLM 使用 patch_file 修改电路参数时，需要模糊匹配定位代码块。
    处理空白字符差异、注释变化等情况。
    """
    print("\n" + "=" * 60)
    print("场景2：SPICE 代码修改定位")
    print("=" * 60)
    
    # 模拟文件中的实际内容（可能有格式差异）
    file_content = """.title Inverting Amplifier
* 反相放大器电路

.param Rf = 10k
.param Rin = 1k
.param Vcc = 15

* 输入信号
Vin input 0 AC 1 SIN(0 1 1k)

* 运放电路
Xopamp input inv_in output Vcc 0 opamp_741
Rf inv_in output {Rf}
Rin input inv_in {Rin}

* 电源
Vpos Vcc 0 DC {Vcc}
Vneg 0 Vee DC {Vcc}

.ac dec 100 1 1Meg
.end"""

    # LLM 生成的搜索内容（可能有轻微格式差异）
    search_content = """.param Rf = 10k
.param Rin = 1k
.param Vcc = 15"""

    # 要替换成的新内容
    replace_content = """.param Rf = 20k
.param Rin = 2k
.param Vcc = 12"""

    matcher = FuzzyMatcher()
    
    # 查找相似内容块
    matches = matcher.find_similar_content(
        search_content,
        file_content,
        threshold=0.8
    )
    
    print(f"\n搜索内容:\n{search_content}")
    print(f"\n找到 {len(matches)} 处匹配:")
    
    for m in matches:
        print(f"\n  行 {m['start_line']}-{m['end_line']} (相似度: {m['score']:.2f})")
        print(f"  匹配内容:\n{m['matched_content']}")


def test_symbol_search():
    """
    场景3：符号搜索
    
    用户搜索子电路名称、参数名称，支持模糊匹配。
    """
    print("\n" + "=" * 60)
    print("场景3：符号搜索")
    print("=" * 60)
    
    # 模拟项目中的符号列表
    symbols = [
        # 子电路
        "opamp_741",
        "opamp_lm358",
        "opamp_tl072",
        "npn_2n2222",
        "pnp_2n2907",
        "mosfet_2n7000",
        # 参数
        "Rf_feedback",
        "Rin_input",
        "Cf_compensation",
        "Vcc_supply",
        "Vee_negative",
        # 节点
        "input_signal",
        "output_buffer",
        "feedback_node",
    ]
    
    matcher = FuzzyMatcher(MatchOptions(
        threshold=0.5,
        algorithm='levenshtein'  # 符号匹配用 levenshtein
    ))
    
    test_queries = [
        ("opamp", "查找运放子电路"),
        ("741", "查找特定型号"),
        ("Rf", "查找反馈电阻参数"),
        ("input", "查找输入相关符号"),
        ("2n", "查找晶体管型号"),
        ("fb", "缩写搜索 feedback"),
    ]
    
    for query, desc in test_queries:
        print(f"\n查询: '{query}' ({desc})")
        results = matcher.find_best_matches(query, symbols, top_k=5)
        for r in results:
            print(f"  {r.score:.2f} | {r.target}")


def test_text_normalizer():
    """
    场景4：文本规范化
    
    处理 SPICE 文件中的格式差异。
    """
    print("\n" + "=" * 60)
    print("场景4：文本规范化")
    print("=" * 60)
    
    # 原始代码（有注释、不规范空格）
    original = """
.param   Rf = 10k   ; 反馈电阻
.param Rin=1k  ; 输入电阻
* 这是注释行
.param  Vcc  =  15
"""
    
    # 规范化后
    normalized = TextNormalizer.normalize_for_matching(
        original,
        NormalizeOptions(
            ignore_whitespace=True,
            ignore_case=True,
            ignore_empty_lines=True,
            strip_comments=True
        )
    )
    
    print(f"原始内容:\n{original}")
    print(f"规范化后:\n{normalized}")
    
    # 词元提取
    text = "FileSearchService"
    tokens = TextNormalizer.extract_tokens(text)
    print(f"\n词元提取: '{text}' -> {tokens}")
    
    text2 = "opamp_741_model"
    tokens2 = TextNormalizer.extract_tokens(text2)
    print(f"词元提取: '{text2}' -> {tokens2}")


def test_similarity_algorithms():
    """
    场景5：相似度算法对比
    
    展示不同算法在不同场景下的表现。
    """
    print("\n" + "=" * 60)
    print("场景5：相似度算法对比")
    print("=" * 60)
    
    test_pairs = [
        ("opamp", "opamp_741", "精确前缀"),
        ("amp", "amplifier", "缩写匹配"),
        ("741", "opamp_741", "型号搜索"),
        ("Rf feedback", "feedback Rf", "词序变化"),
        (".param Rf = 10k", ".param  Rf=10k", "空格差异"),
    ]
    
    print(f"\n{'查询':<20} {'目标':<20} {'场景':<12} {'Lev':<6} {'JW':<6} {'Part':<6} {'TokSort':<8}")
    print("-" * 90)
    
    for query, target, scenario in test_pairs:
        lev = SimilarityAlgorithms.levenshtein_ratio(query, target)
        jw = SimilarityAlgorithms.jaro_winkler_ratio(query, target)
        part = SimilarityAlgorithms.partial_ratio(query, target)
        tok = SimilarityAlgorithms.token_sort_ratio(query, target)
        
        print(f"{query:<20} {target:<20} {scenario:<12} {lev:.2f}   {jw:.2f}   {part:.2f}   {tok:.2f}")


def test_quick_filter_performance():
    """
    场景6：大列表快速过滤
    
    模拟大型项目中的文件搜索预过滤。
    """
    print("\n" + "=" * 60)
    print("场景6：大列表快速过滤")
    print("=" * 60)
    
    import time
    
    # 生成模拟的大文件列表
    base_names = ["amplifier", "filter", "oscillator", "regulator", "converter", "driver"]
    suffixes = ["_v1", "_v2", "_test", "_final", "_backup", ""]
    extensions = [".cir", ".sp", ".sub", ".param"]
    
    large_file_list = []
    for base in base_names:
        for suffix in suffixes:
            for ext in extensions:
                large_file_list.append(f"{base}{suffix}{ext}")
    
    # 复制扩大列表
    large_file_list = large_file_list * 100  # 约 14400 个文件
    
    matcher = FuzzyMatcher()
    query = "amp"
    
    # 测试快速过滤
    start = time.perf_counter()
    filtered = matcher.quick_filter(query, large_file_list, threshold=0.3)
    filter_time = time.perf_counter() - start
    
    # 测试完整匹配
    start = time.perf_counter()
    results = matcher.find_best_matches(query, filtered, top_k=10)
    match_time = time.perf_counter() - start
    
    print(f"文件总数: {len(large_file_list)}")
    print(f"快速过滤后: {len(filtered)} 个候选")
    print(f"过滤耗时: {filter_time*1000:.2f}ms")
    print(f"精确匹配耗时: {match_time*1000:.2f}ms")
    print(f"\n前5个结果:")
    for r in results[:5]:
        print(f"  {r.score:.2f} | {r.target}")


if __name__ == "__main__":
    test_file_name_search()
    test_spice_code_patch_location()
    test_symbol_search()
    test_text_normalizer()
    test_similarity_algorithms()
    test_quick_filter_performance()
    
    print("\n" + "=" * 60)
    print("所有测试完成!")
    print("=" * 60)
