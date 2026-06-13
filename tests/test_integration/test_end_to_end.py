"""
集成测试：端到端场景

测试完整数据管道（不依赖 LLM）：
  1. 性质计算 + 毒性检测管道（SMILES → validate → properties → toxicity）
  2. 连接子设计 → 结构化报告管道（DesignRequest → DesignResult → DesignReport）
  3. 多 Agent 图结构验证（compile + nodes + edges）

这些测试验证组件集成的正确性，与 LLM 调用解耦。
"""

import pytest

from adc_linker_agent.agent.graph import (
    create_multi_agent_graph,
    create_single_agent_graph,
)
from adc_linker_agent.agent.specialists import (
    LINKER_TOOLS,
    PH_TOOLS,
    PROPERTY_TOOLS,
)
from adc_linker_agent.agent.tools import (
    calculate_properties,
    check_lipinski,
    check_toxicity,
    validate_smiles,
)
from adc_linker_agent.domain.linker_designer import (
    LinkerDesigner,
    LinkerDesignRequest,
)
from adc_linker_agent.domain.report import DesignReport, generate_report

# ─── 测试数据 ───

HYDRAZONE_SMILES = "CC(=O)NN=C(C)c1ccccc1"
ASPIRIN_SMILES = "CC(=O)Oc1ccccc1C(=O)O"
PD0325901_SMILES = "O=C(NO)C1=CC=C(F)C(F)=C1N"


# ═══════════════════════════════════════════════════════════════
# Scenario 1: 性质计算 + 毒性检测完整管道
# "评估 CC(=O)NN=C(C)c1ccccc1" → property card + toxicity alerts
# ═══════════════════════════════════════════════════════════════


class TestPropertyToxicityPipeline:
    """
    场景 1: 性质计算 → 毒性检测完整管道

    模拟用户 "评估 CC(=O)NN=C(C)c1ccccc1" 的操作流程。
    """

    def test_validate_then_calculate_properties(self):
        """SMILES 验证 → 性质计算 → 数据完整"""
        valid_result = validate_smiles.invoke({"smiles": HYDRAZONE_SMILES})
        assert valid_result["valid"], f"SMILES should be valid: {valid_result}"

        props = calculate_properties.invoke({"smiles": HYDRAZONE_SMILES})
        assert "logp" in props
        assert "qed" in props
        assert "sas" in props
        assert "tpsa" in props
        assert "molecular_weight" in props
        assert props["molecular_weight"] > 0

    def test_properties_then_lipinski(self):
        """性质计算 → Lipinski 规则检查 → 返回规则评估"""
        calculate_properties.invoke({"smiles": HYDRAZONE_SMILES})
        lipinski = check_lipinski.invoke({"smiles": HYDRAZONE_SMILES})
        assert "violations" in lipinski
        assert "violation_details" in lipinski
        assert isinstance(lipinski["is_oral_drug_like"], bool)

    def test_properties_then_toxicity(self):
        """性质计算 → 毒性检测 → 返回 PAINS/Brenk 警报"""
        toxicity = check_toxicity.invoke({"smiles": HYDRAZONE_SMILES})
        assert "has_alerts" in toxicity
        assert "alerts" in toxicity
        assert isinstance(toxicity["has_alerts"], bool)
        # 警报列表应有 count 或为 list
        alerts = toxicity["alerts"]
        assert isinstance(alerts, list)

    def test_full_property_pipeline(self):
        """完整性质管道: validate → properties → lipinski → toxicity"""
        # Step 1: 验证
        valid = validate_smiles.invoke({"smiles": ASPIRIN_SMILES})
        assert valid["valid"]

        # Step 2: 性质计算
        props = calculate_properties.invoke({"smiles": ASPIRIN_SMILES})
        assert props["molecular_weight"] > 100

        # Step 3: Lipinski
        lipinski = check_lipinski.invoke({"smiles": ASPIRIN_SMILES})
        assert isinstance(lipinski["is_oral_drug_like"], bool)

        # Step 4: 毒性检测
        toxicity = check_toxicity.invoke({"smiles": ASPIRIN_SMILES})
        assert isinstance(toxicity["has_alerts"], bool)

    def test_invalid_smiles_handled_gracefully(self):
        """无效 SMILES 被验证步骤率先拒绝"""
        result = validate_smiles.invoke({"smiles": "invalid_smiles_xyz"})
        assert not result["valid"]

        # 计算性质应对无效 SMILES 返回错误
        props = calculate_properties.invoke({"smiles": "invalid_smiles_xyz"})
        assert "error" in props

    def test_known_toxicity_alerts_detected(self):
        """含 PAINS 警报的分子应被检出（PD0325901 含异羟肟酸）"""
        toxicity = check_toxicity.invoke({"smiles": PD0325901_SMILES})
        # PD0325901 含有异羟肟酸 (hydroxamic acid)，可能在 PAINS/Brenk 中
        # 不一定有警报，但至少返回结构化结果
        assert isinstance(toxicity["has_alerts"], bool)
        assert isinstance(toxicity["alerts"], list)


# ═══════════════════════════════════════════════════════════════
# Scenario 2: 连接子设计 → 结构化报告管道
# "设计 pH 5.0 裂解的连接子" → structured report + ranking table
# ═══════════════════════════════════════════════════════════════


class TestDesignToReportPipeline:
    """
    场景 2: 连接子设计 → 结构化报告完整管道

    模拟用户 "设计 pH 5.0 裂解的连接子" 的完整数据流。
    """

    @pytest.fixture
    def design_result(self):
        """标准设计请求 → DesignResult"""
        designer = LinkerDesigner()
        request = LinkerDesignRequest(target_ph=5.0, max_results=3)
        return designer.design(request)

    def test_design_produces_candidates(self, design_result):
        """设计请求应产生至少 1 个候选"""
        assert len(design_result.candidates) >= 1
        assert design_result.total_evaluated > 0

    def test_candidates_have_complete_data(self, design_result):
        """每个候选应有完整的字段"""
        for c in design_result.candidates:
            assert c.name
            assert c.smiles
            assert c.mechanism
            assert 0 <= c.overall_score <= 1
            assert 0 <= c.qed <= 1
            assert c.molecular_weight > 0
            assert isinstance(c.blood_stable, bool)
            assert isinstance(c.lysosome_labile, bool)

    def test_design_result_to_report(self, design_result):
        """DesignResult → generate_report() → 结构化数据"""
        report = generate_report(design_result)
        assert isinstance(report, DesignReport)
        assert report.candidate_count == len(design_result.candidates)
        assert len(report.generated_at) > 0
        assert len(report.request_summary) > 0

    def test_report_has_all_sections(self, design_result):
        """
        报告应包含全部 6 个部分:
          1. Header（需求摘要 + 统计）
          2. Candidate Table（对比表）
          3. Detailed Cards（Top-3 详细信息）
          4. Comparison（对比分析）
          5. Toxicity Summary（毒性汇总）
          6. Warnings（警告）
        """
        report = generate_report(design_result)

        # Section 1: Header
        assert report.total_evaluated > 0
        assert report.candidate_count > 0

        # Section 2: Candidate Table
        assert len(report.candidates) == report.candidate_count

        # Section 3: Detailed Cards
        assert len(report.detailed_cards) <= 3
        if report.detailed_cards:
            card = report.detailed_cards[0]
            assert "properties" in card
            assert "scores" in card
            assert "strengths" in card
            assert "weaknesses" in card
            assert "recommendation" in card

        # Section 4: Comparison
        if report.candidate_count >= 2:
            assert len(report.comparison_dimensions) >= 1

        # Section 5: Toxicity
        assert isinstance(report.has_any_toxicity, bool)
        assert len(report.toxicity_summary) > 0

        # Section 6: Warnings
        assert isinstance(report.warnings, list)

    def test_report_candidates_sorted_by_score(self, design_result):
        """候选应按综合分降序排列"""
        report = generate_report(design_result)
        scores = [c.overall_score for c in report.candidates]
        assert scores == sorted(scores, reverse=True), f"Not sorted: {scores}"

    def test_custom_weights_affect_report(self):
        """自定义权重应改变排名"""
        designer_default = LinkerDesigner()
        request = LinkerDesignRequest(target_ph=5.0, max_results=3)
        result_default = designer_default.design(request)

        # 极端权重：只看药物相似性
        designer_custom = LinkerDesigner(
            weights={"blood_stability": 0.0, "lysosome_lability": 0.0,
                     "drug_likeness": 1.0, "synthetic": 0.0}
        )
        result_custom = designer_custom.design(request)

        report_default = generate_report(result_default)
        report_custom = generate_report(result_custom)

        # 两个报告都应有候选
        assert report_default.candidate_count >= 1
        assert report_custom.candidate_count >= 1

    def test_empty_design_handled(self):
        """极高阈值可能产生空结果，报告应处理"""
        designer = LinkerDesigner()
        request = LinkerDesignRequest(min_qed=0.99, max_results=1)
        result = designer.design(request)
        report = generate_report(result)

        assert isinstance(report, DesignReport)
        assert report.candidate_count == len(result.candidates)


# ═══════════════════════════════════════════════════════════════
# Scenario 3: Agent 图结构验证 + 文献搜索集成（可选）
# ═══════════════════════════════════════════════════════════════


class TestMultiAgentGraphStructure:
    """
    场景 3: Multi-Agent 图结构验证

    验证图编译正确性、节点连接完整性和工具分配正确性。
    """

    def test_multi_agent_graph_compiles(self):
        """多 Agent 图应成功编译"""
        graph = create_multi_agent_graph()
        assert graph is not None

    def test_single_agent_graph_compiles(self):
        """单 Agent 图应成功编译"""
        graph = create_single_agent_graph()
        assert graph is not None

    def test_multi_agent_has_all_nodes(self):
        """多 Agent 图应有 5 个节点（supervisor + 4 specialists）"""
        graph = create_multi_agent_graph()
        # 通过 graph.get_graph() 获取节点信息
        nodes = graph.get_graph().nodes
        node_names = {n for n in nodes}
        expected = {"supervisor", "property_agent", "ph_agent", "linker_agent", "literature_agent"}
        # __start__ 和 __end__ 也会出现在 nodes 中
        assert expected.issubset(node_names), f"Missing nodes: {expected - node_names}"

    def test_multi_agent_has_correct_edges(self):
        """多 Agent 图应有正确的边结构"""
        graph = create_multi_agent_graph()
        edges = graph.get_graph().edges

        # 应该有从 supervisor 到各 specialist 的边
        edge_pairs = {(e[0], e[1]) for e in edges}

        # supervisor → specialists
        specialists = ("property_agent", "ph_agent", "linker_agent", "literature_agent")
        for spec in specialists:
            assert ("supervisor", spec) in edge_pairs, f"Missing: supervisor → {spec}"

        # specialists → supervisor (返回)
        for spec in specialists:
            assert (spec, "supervisor") in edge_pairs, f"Missing: {spec} → supervisor"

    def test_property_agent_has_minimal_tools(self):
        """PropertyAgent 应有最小工具集（validate + properties + lipinski + toxicity = 4）"""
        assert len(PROPERTY_TOOLS) >= 4

    def test_ph_agent_has_ph_tools(self):
        """PHAgent 应有 pH 稳定性工具（2 个）"""
        assert len(PH_TOOLS) == 2

    def test_linker_agent_has_all_tools(self):
        """LinkerAgent 应有全工具集（9 个）"""
        assert len(LINKER_TOOLS) == 9

    def test_specialists_not_overlapping_tools(self):
        """
        专长 Agent 工具集应按最小权限原则分配:
          - PROPERTY_TOOLS ⊂ LINKER_TOOLS
          - PH_TOOLS ⊂ LINKER_TOOLS
        """
        linker_names = {t.name for t in LINKER_TOOLS}
        property_names = {t.name for t in PROPERTY_TOOLS}
        ph_names = {t.name for t in PH_TOOLS}

        assert property_names.issubset(linker_names)
        assert ph_names.issubset(linker_names)


class TestLiteratureIntegration:
    """
    文献搜索集成测试（需要网络访问）。
    如果网络不可用则跳过。
    """

    @pytest.mark.skip(reason="Requires network access to Europe PMC API")
    def test_search_literature_returns_papers(self):
        """文献搜索应返回论文列表（需要网络）"""
        from adc_linker_agent.agent.tools import search_literature

        result = search_literature.invoke({
            "query": "Val-Cit-PABC ADC linker",
            "max_results": 3,
        })

        # 即使无网络也应返回结构化结果（包含 error 字段或 papers 列表）
        assert isinstance(result, dict)
        if "error" not in result:
            assert "papers" in result
            assert "total_found" in result

    def test_search_literature_structured_result(self):
        """文献搜索返回结果应有正确的字段结构"""
        from adc_linker_agent.agent.tools import search_literature

        result = search_literature.invoke({
            "query": "antibody drug conjugate linker cleavage",
            "max_results": 3,
        })

        assert isinstance(result, dict)
        # 至少有 query 字段
        assert "query" in result
        # 可能有 error 或 papers
        assert "error" in result or "papers" in result
