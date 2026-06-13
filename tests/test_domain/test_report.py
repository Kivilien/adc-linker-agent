"""
测试 domain/report.py —— 结构化报告引擎
"""

import pytest

from adc_linker_agent.domain.linker_designer import LinkerDesigner, LinkerDesignRequest
from adc_linker_agent.domain.report import (
    CandidateSummary,
    DesignReport,
    generate_report,
)


@pytest.fixture
def designer():
    return LinkerDesigner()


@pytest.fixture
def design_result(designer):
    """标准设计结果，用于报告生成"""
    request = LinkerDesignRequest(target_ph=5.0, max_results=3)
    return designer.design(request)


class TestGenerateReport:
    """测试报告生成"""

    def test_generates_design_report(self, design_result):
        """应返回 DesignReport 实例"""
        report = generate_report(design_result)
        assert isinstance(report, DesignReport)

    def test_report_has_header_info(self, design_result):
        """报告应包含头部信息"""
        report = generate_report(design_result)
        assert len(report.generated_at) > 0
        assert "目标 pH" in report.request_summary
        assert report.total_evaluated > 0
        assert report.candidate_count > 0

    def test_report_candidate_count_matches_result(self, design_result):
        """报告候选数应与结果一致"""
        report = generate_report(design_result)
        assert report.candidate_count == len(design_result.candidates)
        assert len(report.candidates) == len(design_result.candidates)

    def test_report_candidates_have_all_fields(self, design_result):
        """每个候选摘要应有完整字段"""
        report = generate_report(design_result)
        for cs in report.candidates:
            assert isinstance(cs, CandidateSummary)
            assert cs.rank >= 1
            assert len(cs.name) > 0
            assert len(cs.smiles) > 0
            assert len(cs.mechanism) > 0
            assert 0 <= cs.overall_score <= 1
            assert isinstance(cs.blood_stable, bool)
            assert isinstance(cs.lysosome_labile, bool)
            assert 0 <= cs.qed <= 1
            assert cs.molecular_weight > 0

    def test_detailed_cards_are_top_3(self, design_result):
        """详细卡片最多 3 张"""
        report = generate_report(design_result)
        assert len(report.detailed_cards) <= 3
        if report.detailed_cards:
            card = report.detailed_cards[0]
            assert "name" in card
            assert "smiles" in card
            assert "properties" in card
            assert "scores" in card
            assert "strengths" in card
            assert "weaknesses" in card
            assert "recommendation" in card

    def test_detailed_card_has_property_status(self, design_result):
        """详细卡片中每个性质应有 status"""
        report = generate_report(design_result)
        if report.detailed_cards:
            card = report.detailed_cards[0]
            props = card["properties"]
            for prop_name in ["logp", "qed", "sas", "tpsa"]:
                assert prop_name in props
                assert "status" in props[prop_name]
                assert props[prop_name]["status"] in ("ideal", "ok", "warning")

    def test_report_has_toxicity_summary(self, design_result):
        """报告应包含毒性汇总"""
        report = generate_report(design_result)
        assert isinstance(report.has_any_toxicity, bool)
        assert len(report.toxicity_summary) > 0

    def test_report_has_comparison(self, design_result):
        """报告应包含对比分析"""
        report = generate_report(design_result)
        if report.candidate_count >= 2:
            assert len(report.comparison_dimensions) >= 1
            assert len(report.comparison_text) > 0
        else:
            assert "无法进行对比" in report.comparison_text

    def test_report_warnings_list_exists(self, design_result):
        """警告列表应存在（可为空）"""
        report = generate_report(design_result)
        assert isinstance(report.warnings, list)

    def test_empty_result_handled(self, designer):
        """空结果应安全处理"""
        request = LinkerDesignRequest(
            min_qed=0.99,  # 极高阈值，不太可能有结果
            max_results=1,
        )
        result = designer.design(request)
        report = generate_report(result)
        assert report.candidate_count == len(result.candidates)
        assert isinstance(report.candidates, list)


class TestPropertyStatus:
    """测试性质状态判断"""

    def test_logp_ideal(self):
        from adc_linker_agent.domain.report import _logp_status
        assert _logp_status(1.5) == "ideal"
        assert _logp_status(3.0) == "ideal"

    def test_logp_warning(self):
        from adc_linker_agent.domain.report import _logp_status
        assert _logp_status(6.0) == "warning"

    def test_logp_ok(self):
        from adc_linker_agent.domain.report import _logp_status
        assert _logp_status(4.0) == "ok"

    def test_qed_ideal(self):
        from adc_linker_agent.domain.report import _qed_status
        assert _qed_status(0.6) == "ideal"

    def test_qed_warning(self):
        from adc_linker_agent.domain.report import _qed_status
        assert _qed_status(0.2) == "warning"

    def test_sas_ideal(self):
        from adc_linker_agent.domain.report import _sas_status
        assert _sas_status(3.0) == "ideal"

    def test_sas_warning(self):
        from adc_linker_agent.domain.report import _sas_status
        assert _sas_status(7.0) == "warning"

    def test_tpsa_ideal(self):
        from adc_linker_agent.domain.report import _tpsa_status
        assert _tpsa_status(100.0) == "ideal"


class TestCandidateSummary:
    """测试 CandidateSummary 数据类"""

    def test_construction(self):
        cs = CandidateSummary(
            rank=1,
            name="Test",
            smiles="CCO",
            mechanism="pH_sensitive",
            mechanism_label="🔴 酸敏感",
            overall_score=0.85,
            blood_stable=True,
            lysosome_labile=True,
            qed=0.65,
            logp=1.5,
            sas=3.2,
            tpsa=87.3,
            molecular_weight=450.0,
            has_toxicity_alerts=False,
            toxicity_count=0,
            recommendation="✅ 推荐",
        )
        assert cs.name == "Test"
        assert cs.overall_score == 0.85

    def test_toxicity_fields(self):
        cs = CandidateSummary(
            rank=1, name="Bad", smiles="c1ccccc1",
            mechanism="pH_sensitive", mechanism_label="pH",
            overall_score=0.4, blood_stable=True,
            lysosome_labile=False, qed=0.3, logp=3.0,
            sas=5.0, tpsa=50.0, molecular_weight=300.0,
            has_toxicity_alerts=True, toxicity_count=3,
            recommendation="🚨 不推荐",
            risk_flags=["PAINS 假阳性警报"],
        )
        assert cs.has_toxicity_alerts
        assert cs.toxicity_count == 3
        assert len(cs.risk_flags) == 1
