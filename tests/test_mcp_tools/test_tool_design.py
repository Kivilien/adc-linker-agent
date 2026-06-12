"""
测试 MCP 设计工具：design_linker
"""

import pytest

from adc_linker_agent.mcp_tools.tool_design import design_linker


class TestDesignLinkerTool:
    """测试 design_linker MCP 工具"""

    def test_returns_dict_with_expected_keys(self):
        """返回 dict 包含所有必要字段"""
        result = design_linker(max_results=2)
        assert isinstance(result, dict)
        assert "candidates" in result
        assert "total_evaluated" in result
        assert "total_filtered" in result
        assert "design_summary" in result
        assert "request" in result

    def test_respects_max_results(self):
        """遵守 max_results 限制"""
        for n in [1, 2, 3]:
            result = design_linker(max_results=n)
            assert len(result["candidates"]) <= n

    def test_filter_by_mechanism(self):
        """机制筛选正确"""
        result = design_linker(
            preferred_mechanism="pH_sensitive",
            max_results=5,
        )
        for c in result["candidates"]:
            assert c["mechanism"] == "pH_sensitive"

    def test_each_candidate_has_properties(self):
        """每个候选有完整性质"""
        result = design_linker(max_results=2)
        for c in result["candidates"]:
            props = c["properties"]
            assert "logp" in props
            assert "qed" in props
            assert "sas" in props
            assert "molecular_weight" in props

    def test_each_candidate_has_scores(self):
        """每个候选有四维评分"""
        result = design_linker(max_results=2)
        for c in result["candidates"]:
            scores = c["scores"]
            assert "blood_stability" in scores
            assert "lysosome_lability" in scores
            assert "drug_likeness" in scores
            assert "synthetic_accessibility" in scores
            assert "overall" in scores

    def test_each_candidate_has_strengths_weaknesses(self):
        """每个候选有优缺点分析"""
        result = design_linker(max_results=2)
        for c in result["candidates"]:
            assert isinstance(c["strengths"], list)
            assert isinstance(c["weaknesses"], list)
            assert len(c["recommendation"]) > 10

    def test_each_candidate_has_ph_stability(self):
        """每个候选有 pH 稳定性信息"""
        result = design_linker(max_results=2)
        for c in result["candidates"]:
            ph = c["ph_stability"]
            assert "blood_stable" in ph
            assert "lysosome_labile" in ph
            assert "summary" in ph

    def test_candidates_have_rank(self):
        """候选有序号"""
        result = design_linker(max_results=2)
        for i, c in enumerate(result["candidates"]):
            assert c["rank"] == i + 1

    def test_request_info_included(self):
        """请求参数包含在结果中"""
        result = design_linker(
            target_ph=5.5,
            preferred_mechanism="enzymatic",
        )
        assert result["request"]["target_ph"] == 5.5
        assert result["request"]["preferred_mechanism"] == "enzymatic"

    def test_blood_stable_filter_works(self):
        """血液稳定性筛选有效"""
        result = design_linker(
            require_blood_stable=True,
            max_results=5,
        )
        for c in result["candidates"]:
            assert c["ph_stability"]["blood_stable"] is True

    def test_quality_filters_work(self):
        """质量筛选有效"""
        result = design_linker(
            min_qed=0.3,
            max_sas=6.0,
            max_results=5,
        )
        for c in result["candidates"]:
            assert c["properties"]["qed"] >= 0.3
            assert c["properties"]["sas"] <= 6.0

    def test_low_target_ph_returns_pH_sensitive(self):
        """低 pH 目标应该优先返回 pH 敏感连接子"""
        result = design_linker(
            target_ph=5.0,
            preferred_mechanism="pH_sensitive",
            max_results=5,
        )
        # pH 敏感连接子应该在特定 pH 附近裂解
        for c in result["candidates"]:
            assert c["mechanism"] == "pH_sensitive"
