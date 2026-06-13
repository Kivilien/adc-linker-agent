"""
测试 LiteratureSearchEngine 查询预处理

验证 ADC 化学缩写展开逻辑，确保 Europe PMC 兼容性。
不调用真实 API（无需网络）。
"""

import pytest

from adc_linker_agent.domain.literature import LiteratureSearchEngine


class TestQueryExpansion:
    """查询预处理测试：化学缩写 → Europe PMC 同义词展开"""

    def test_val_cit_pabc_expansion(self):
        """Val-Cit-PABC → Val-Cit-PAB + 同义词变体 OR"""
        result = LiteratureSearchEngine._expand_query("Val-Cit-PABC ADC linker")
        assert "Val-Cit-PAB" in result
        assert "valine-citrulline PAB" in result
        assert "Val-Cit dipeptide" in result
        assert "cathepsin B cleavable" in result
        assert "ADC linker" in result
        # 不应有双括号
        assert not result.startswith("((")
        # 不应含字面量 PABC（防止叠加替换）
        assert "PABC" not in result

    def test_vc_pabc_expansion(self):
        """vc-PABC 小写变体展开"""
        result = LiteratureSearchEngine._expand_query("vc-PABC cleavable linker")
        assert "vc-PAB" in result
        assert "valine-citrulline" in result
        assert "PABC" not in result

    def test_mc_vc_pabc_expansion(self):
        """MC-VC-PABC 长模式优先匹配（避免被 PABC 短模式抢先）"""
        result = LiteratureSearchEngine._expand_query("MC-VC-PABC cathepsin")
        assert "MC-VC-PAB" in result
        assert "maleimidocaproyl-valine-citrulline" in result
        assert "PABC" not in result

    def test_standalone_pabc_expansion(self):
        """独立 PABC（无 Val-Cit 前缀）展开为 PAB + 描述"""
        result = LiteratureSearchEngine._expand_query("PABC self-immolative linker")
        assert "PAB" in result
        assert "p-aminobenzyl" in result
        assert "self-immolative linker" in result

    def test_smcc_expansion(self):
        """SMCC 展开为全称"""
        result = LiteratureSearchEngine._expand_query("SMCC crosslinker ADC")
        assert "SMCC" in result
        assert "succinimidyl 4-(N-maleimidomethyl)cyclohexane" in result

    def test_no_double_expansion(self):
        """确保 PABC 不会在 Val-Cit-PABC 展开后二次替换"""
        result = LiteratureSearchEngine._expand_query("Val-Cit-PABC ADC linker")
        # PABC 已被替换，展开文本中不再有 PABC 字面量
        assert result.count("PABC") == 0

    def test_unchanged_query(self):
        """不包含已知缩写的查询原样返回"""
        result = LiteratureSearchEngine._expand_query("ADC linker pH-sensitive")
        assert result == "ADC linker pH-sensitive"

    def test_multiple_expansions(self):
        """同一个查询中的多个缩写都展开"""
        result = LiteratureSearchEngine._expand_query("Val-Cit-PABC vs SMCC linker")
        assert "Val-Cit-PAB" in result
        assert "SMCC" in result
        assert "succinimidyl" in result
        assert "valine-citrulline" in result


@pytest.mark.slow
class TestLiteratureSearchEngineIntegration:
    """集成测试：真实 Europe PMC API 调用（需网络）"""

    def test_expanded_query_returns_results(self):
        """展开后的 Val-Cit-PABC 查询应返回文献"""
        engine = LiteratureSearchEngine()
        engine._min_interval = 1.0
        papers = engine.search("Val-Cit-PABC ADC linker", max_results=3)
        # Europe PMC 应返回 >0 结果（360+ hits）
        assert len(papers) > 0, (
            f"Expanded query returned 0 results. "
            f"Query: {engine._expand_query('Val-Cit-PABC ADC linker')}"
        )

    def test_unexpanded_query_still_works(self):
        """未展开的普通查询不受影响"""
        engine = LiteratureSearchEngine()
        engine._min_interval = 1.0
        papers = engine.search("antibody drug conjugate linker", max_results=3)
        assert len(papers) > 0, "Basic ADC query should return results"
