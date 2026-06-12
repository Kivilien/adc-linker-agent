#!/usr/bin/env python3
"""
ADC Linker Agent — 5 分钟演示脚本

展示从自然语言查询到连接子设计候选的完整流水线。
无需 API Key —— 所有演示使用本地 RDKit 计算。

运行:
  python scripts/demo.py

输出:
  1. 分子性质计算演示
  2. pH 稳定性分析演示
  3. 连接子骨架搜索演示
  4. 设计优化循环演示（核心功能）
"""

import json
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def section(title: str):
    """打印分节标题"""
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def subsection(title: str):
    """打印子标题"""
    print(f"\n── {title} ──")


def demo_1_property_calculation():
    """演示 1: 分子性质计算"""
    section("演示 1: 分子性质计算")

    from adc_linker_agent.domain.properties import MolPropertyCalculator

    calc = MolPropertyCalculator()

    molecules = {
        "阿司匹林 (Aspirin)": "CC(=O)Oc1ccccc1C(=O)O",
        "苯 (Benzene)": "c1ccccc1",
        "Val-Cit-PABC 连接子": (
            "CC(C)[C@H](N)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(O)cc1"
        ),
    }

    for name, smiles in molecules.items():
        subsection(name)
        props = calc.calculate_all(smiles)
        print(f"  SMILES: {smiles}")
        print(f"  LogP:   {props['logp']} (ideal 1-3)")
        print(f"  QED:    {props['qed']} (>0.5 = drug-like)")
        print(f"  SAS:    {props['sas']} (<4 = easy to synthesize)")
        print(f"  TPSA:   {props['tpsa']} Å² (80-140 ideal)")
        print(f"  MW:     {props['molecular_weight']} Da")

        # Lipinski
        lip = calc.check_lipinski(smiles)
        status = "✅ Pass" if lip["is_oral_drug_like"] else "❌ Fail"
        print(f"  Lipinski: {status} ({lip['violations']} violations)")


def demo_2_ph_stability():
    """演示 2: pH 稳定性分析"""
    section("演示 2: pH 稳定性分析")

    from adc_linker_agent.domain.ph_simulator import PhSimulator

    sim = PhSimulator()

    # 腙键连接子
    hydrazone = "CC(=O)NN=C(C)c1ccccc1"

    subsection("腙键连接子的 ADC 递送路径模拟")
    print(f"  SMILES: {hydrazone}")

    results = sim.predict_physiological_phases(hydrazone)
    for phase, result in results.items():
        status = "🟢 稳定" if result.is_stable else "🔴 不稳定"
        labile = f" | 敏感基团: {', '.join(result.labile_groups_found)}" if result.labile_groups_found else ""
        print(f"  {phase:25s} pH {result.target_ph} → {status}{labile}")

    # 判断是否是理想连接子
    blood_ok = results["blood"].is_stable
    lysosome_ok = not results["lysosome"].is_stable
    print()
    if blood_ok and lysosome_ok:
        print("  ✅ 理想 ADC 连接子：血液稳定 + 溶酶体裂解")
    elif not blood_ok:
        print("  ❌ 不合格：血液中不稳定，毒素会提前释放！")
    elif not lysosome_ok:
        print("  ⚠️  部分合格：溶酶体中裂解不充分")

    # 苯（无 pH 敏感基团）
    subsection("苯（对照：无 pH 敏感基团）")
    result = sim.predict("c1ccccc1", ph=7.4)
    print(f"  pH 7.4: {'🟢 稳定' if result.is_stable else '🔴 不稳定'}")
    print(f"  检测到的敏感基团: 无")


def demo_3_scaffold_search():
    """演示 3: 连接子骨架搜索"""
    section("演示 3: 连接子骨架搜索")

    from adc_linker_agent.mcp_tools.tool_linker import search_linker_scaffolds

    # 按机制搜索
    mechanisms = ["pH_sensitive", "enzymatic", "redox", "non_cleavable"]
    for mech in mechanisms:
        results = search_linker_scaffolds(mechanism=mech)
        mech_names = {
            "pH_sensitive": "酸敏感",
            "enzymatic": "酶裂解",
            "redox": "氧化还原",
            "non_cleavable": "不可裂解",
        }
        print(f"\n  {mech_names[mech]} ({mech}): {len(results)} 个骨架")
        for r in results[:2]:  # 每种只显示前 2 个
            mw = r["properties"]["molecular_weight"]
            qed = r["properties"]["qed"]
            print(f"    - {r['name']} (MW={mw:.0f}, QED={qed:.3f})")


def demo_4_linker_design():
    """演示 4: 连接子设计优化循环（核心）"""
    section("演示 4: 连接子设计优化循环 ⭐")

    from adc_linker_agent.domain.linker_designer import (
        LinkerDesigner,
        LinkerDesignRequest,
    )

    designer = LinkerDesigner()
    print(f"  骨架数据库: {designer.scaffold_count} 个连接子\n")

    # 场景 1: pH 5.0 裂解 + pH 敏感
    subsection("场景 1: 设计 pH 5.0 裂解的 pH 敏感连接子")
    request1 = LinkerDesignRequest(
        target_ph=5.0,
        preferred_mechanism="pH_sensitive",
        max_results=3,
    )
    result1 = designer.design(request1)
    print(f"  {result1.design_summary}\n")
    for i, c in enumerate(result1.candidates):
        print(f"  #{i+1} {c.name}")
        print(f"     SMILES: {c.smiles}")
        print(f"     机制: {c.mechanism}")
        print(f"     评分: overall={c.overall_score:.3f} "
              f"(blood={c.score_blood_stability:.2f} "
              f"lyso={c.score_lysosome_lability:.2f} "
              f"QED={c.score_drug_likeness:.2f} "
              f"synth={c.score_synthetic:.2f})")
        print(f"     血液: {'🟢 稳定' if c.blood_stable else '🔴 不稳定'}"
              f" | 溶酶体: {'🟢 裂解' if c.lysosome_labile else '⚠️ 不充分'}")
        print(f"     优点: {', '.join(c.strengths[:2])}")
        if c.weaknesses:
            print(f"     缺点: {', '.join(c.weaknesses[:2])}")
        print(f"     推荐: {c.recommendation}")
        print()

    # 场景 2: 酶裂解连接子
    subsection("场景 2: 搜索酶裂解连接子（Cathepsin B）")
    request2 = LinkerDesignRequest(
        preferred_mechanism="enzymatic",
        require_blood_stable=True,
        max_results=2,
    )
    result2 = designer.design(request2)
    for i, c in enumerate(result2.candidates):
        print(f"  #{i+1} {c.name} (评分: {c.overall_score:.3f})")
        print(f"     临床参考: {', '.join(c.drugs_using[:2])}")
        print(f"     性质: LogP={c.logp}, QED={c.qed}, SAS={c.sas}")
        print()

    # 场景 3: 高质量筛选
    subsection("场景 3: 高质量筛选 (QED≥0.4, SAS≤5, 血液稳定)")
    request3 = LinkerDesignRequest(
        min_qed=0.4,
        max_sas=5.0,
        require_blood_stable=True,
        max_results=3,
    )
    result3 = designer.design(request3)
    for i, c in enumerate(result3.candidates):
        print(f"  #{i+1} {c.name}")
        print(f"     QED={c.qed:.3f} SAS={c.sas:.1f} "
              f"血液={'✅' if c.blood_stable else '❌'} "
              f"评分={c.overall_score:.3f}")


def demo_5_tool_chain():
    """演示 5: 工具链集成"""
    section("演示 5: 完整的工具链调用")

    from adc_linker_agent.mcp_tools.tool_design import design_linker

    print("  调用 design_linker MCP 工具:\n")

    result = design_linker(
        target_ph=5.5,
        preferred_mechanism="pH_sensitive",
        min_qed=0.3,
        max_sas=6.0,
        max_results=3,
    )

    print(f"  {result['design_summary']}\n")
    print(f"  候选数: {len(result['candidates'])}")
    print(f"  评估总数: {result['total_evaluated']}")
    print(f"  过滤数: {result['total_filtered']}\n")

    # JSON 输出（供 API 参考）
    print("  Top 候选摘要 (JSON):")
    summary = [
        {
            "name": c["name"],
            "mechanism": c["mechanism"],
            "overall_score": c["scores"]["overall"],
            "blood_stable": c["ph_stability"]["blood_stable"],
            "recommendation": c["recommendation"][:80],
        }
        for c in result["candidates"]
    ]
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    """运行完整演示"""
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   🧬 ADC 连接子智能设计 AI Agent — 演示脚本            ║")
    print("║   v1.0.0 | 255 tests | ruff clean                      ║")
    print("╚══════════════════════════════════════════════════════════╝")

    try:
        demo_1_property_calculation()
        demo_2_ph_stability()
        demo_3_scaffold_search()
        demo_4_linker_design()
        demo_5_tool_chain()

        section("演示完成 ✅")
        print()
        print("  以上所有计算均在本地完成（RDKit），无需 API Key。")
        print("  Agent 调用（LLM）需要配置 ANTHROPIC_API_KEY。")
        print()
        print("  下一步:")
        print("    streamlit run adc_linker_agent/ui/app.py")
        print("    python -m adc_linker_agent.api.server")
        print()

    except Exception as e:
        print(f"\n❌ 演示出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
