"""
测试导出功能 (HTML/PPTX)。
"""

import pytest

from adc_linker_agent.domain.linker_designer import LinkerDesigner, LinkerDesignRequest
from adc_linker_agent.domain.report import generate_report


@pytest.fixture(scope="module")
def sample_report():
    """生成一个测试用的 DesignReport"""
    designer = LinkerDesigner()
    request = LinkerDesignRequest(target_ph=5.0, max_results=3)
    result = designer.design(request)
    return generate_report(result)


class TestGenerateHTMLSlides:
    """HTML 幻灯片导出"""

    def test_generates_valid_html(self, sample_report):
        """有效报告生成非空 HTML bytes"""
        from adc_linker_agent.ui.export import generate_html_slides

        html = generate_html_slides(sample_report)
        assert html is not None, "HTML slides should generate successfully"
        assert len(html) > 1000
        content = html.decode("utf-8")
        assert "<!DOCTYPE html>" in content
        assert "ADC" in content
        assert "Nord" in content or "--nord0" in content or "nord" in content.lower()

    def test_contains_candidates(self, sample_report):
        """HTML 包含候选信息"""
        from adc_linker_agent.ui.export import generate_html_slides

        html = generate_html_slides(sample_report)
        content = html.decode("utf-8")
        for c in sample_report.candidates[:3]:
            assert c.name in content, f"Candidate {c.name} should appear in HTML"

    def test_empty_candidates(self):
        """空候选列表仍生成合法 HTML"""
        from adc_linker_agent.domain.report import DesignReport
        from adc_linker_agent.ui.export import generate_html_slides

        empty = DesignReport(
            generated_at="2026-01-01T00:00:00",
            request_summary="test empty",
            total_evaluated=0,
            total_filtered=0,
            candidate_count=0,
            candidates=[],
            detailed_cards=[],
            comparison_text="No comparison available",
            comparison_dimensions=[],
            has_any_toxicity=False,
            toxicity_summary="No issues",
            warnings=[],
            failed_scaffolds=[],
        )
        html = generate_html_slides(empty)
        assert html is not None
        assert len(html) > 500


class TestGeneratePPTX:
    """PPTX 导出"""

    def test_generates_valid_pptx(self, sample_report):
        """有效报告生成非空 PPTX bytes"""
        from adc_linker_agent.ui.export import generate_pptx

        pptx = generate_pptx(sample_report)
        if pptx is None:
            pytest.skip("python-pptx not available")
        assert len(pptx) > 1000
        # PPTX 是 ZIP 格式
        assert pptx[:2] == b"PK"

    def test_empty_candidates_pptx(self):
        """空候选列表仍生成合法 PPTX"""
        from adc_linker_agent.domain.report import DesignReport
        from adc_linker_agent.ui.export import generate_pptx

        empty = DesignReport(
            generated_at="2026-01-01T00:00:00",
            request_summary="test",
            total_evaluated=0,
            total_filtered=0,
            candidate_count=0,
            candidates=[],
            detailed_cards=[],
            comparison_text="N/A",
            comparison_dimensions=[],
            has_any_toxicity=False,
            toxicity_summary="OK",
            warnings=[],
            failed_scaffolds=[],
        )
        pptx = generate_pptx(empty)
        if pptx is None:
            pytest.skip("python-pptx not available")
        assert pptx[:2] == b"PK"


class TestExportDegradation:
    """优雅降级测试"""

    def test_pptx_none_for_none_report(self):
        """None report 返回 None"""
        from adc_linker_agent.ui.export import generate_pptx

        assert generate_pptx(None) is None

    def test_html_none_for_none_report(self):
        """None report 返回 None"""
        from adc_linker_agent.ui.export import generate_html_slides

        assert generate_html_slides(None) is None
