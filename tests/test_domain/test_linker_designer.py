"""
测试连接子设计引擎（Week 7）
"""

import pytest
from pydantic import ValidationError

from adc_linker_agent.domain.linker_designer import (
    DesignResult,
    LinkerDesigner,
    LinkerDesignRequest,
    quick_design,
)


class TestLinkerDesignRequest:
    """测试设计需求模型"""

    def test_default_request(self):
        req = LinkerDesignRequest()
        assert req.target_ph == 5.0
        assert req.preferred_mechanism is None
        assert req.max_results == 5

    def test_custom_request(self):
        req = LinkerDesignRequest(
            target_ph=5.5,
            preferred_mechanism="pH_sensitive",
            min_qed=0.4,
            max_sas=5.0,
            max_results=3,
        )
        assert req.target_ph == 5.5
        assert req.min_qed == 0.4
        assert req.max_results == 3

    def test_invalid_target_ph_rejected(self):
        with pytest.raises(ValidationError):
            LinkerDesignRequest(target_ph=15)

    def test_invalid_qed_rejected(self):
        with pytest.raises(ValidationError):
            LinkerDesignRequest(min_qed=1.5)

    def test_invalid_max_results_rejected(self):
        with pytest.raises(ValidationError):
            LinkerDesignRequest(max_results=0)


class TestLinkerDesigner:
    """测试设计引擎核心功能"""

    @pytest.fixture
    def designer(self):
        """创建设计引擎实例（使用项目 CSV）"""
        return LinkerDesigner()

    def test_initialization(self, designer):
        """引擎应该成功初始化并加载骨架"""
        assert designer.scaffold_count >= 15

    def test_design_all_mechanisms(self, designer):
        """无筛选条件时返回所有机制的候选"""
        request = LinkerDesignRequest(max_results=10)
        result = designer.design(request)
        assert result.total_evaluated > 0
        assert len(result.candidates) > 0

    def test_design_ph_sensitive(self, designer):
        """按 pH 敏感机制筛选"""
        request = LinkerDesignRequest(
            target_ph=5.0,
            preferred_mechanism="pH_sensitive",
            max_results=5,
        )
        result = designer.design(request)
        for c in result.candidates:
            assert c.mechanism == "pH_sensitive"

    def test_design_enzymatic(self, designer):
        """按酶裂解机制筛选"""
        request = LinkerDesignRequest(
            preferred_mechanism="enzymatic",
            max_results=5,
        )
        result = designer.design(request)
        for c in result.candidates:
            assert c.mechanism == "enzymatic"

    def test_design_with_quality_filters(self, designer):
        """质量筛选（QED + SAS）"""
        request = LinkerDesignRequest(
            min_qed=0.3,
            max_sas=6.0,
            require_blood_stable=True,
            max_results=10,
        )
        result = designer.design(request)
        for c in result.candidates:
            assert c.qed >= 0.3, f"{c.name}: QED={c.qed} < 0.3"
            assert c.sas <= 6.0, f"{c.name}: SAS={c.sas} > 6.0"
            assert c.blood_stable, f"{c.name}: not blood stable"

    def test_design_returns_top_n(self, designer):
        """返回候选数不应超过 max_results"""
        for n in [1, 3, 5]:
            request = LinkerDesignRequest(max_results=n)
            result = designer.design(request)
            assert len(result.candidates) <= n

    def test_design_blood_stable_filter(self, designer):
        """血液稳定性筛选"""
        request = LinkerDesignRequest(
            require_blood_stable=True,
            max_results=10,
        )
        result = designer.design(request)
        for c in result.candidates:
            assert c.blood_stable, f"{c.name} not blood stable"


class TestLinkerCandidate:
    """测试候选结果模型"""

    @pytest.fixture
    def designer(self):
        return LinkerDesigner()

    def test_candidate_has_properties(self, designer):
        """每个候选应该有完整的分子性质"""
        result = designer.design(LinkerDesignRequest(max_results=3))
        for c in result.candidates:
            assert c.logp != 0 or c.qed != 0  # at least some properties calculated
            assert c.molecular_weight > 0

    def test_candidate_has_ph_stability(self, designer):
        """每个候选应该有 pH 稳定性评估"""
        result = designer.design(LinkerDesignRequest(max_results=3))
        for c in result.candidates:
            assert isinstance(c.blood_stable, bool)
            assert isinstance(c.lysosome_labile, bool)
            assert len(c.ph_stability_summary) > 0

    def test_candidate_has_scores(self, designer):
        """每个候选应该有四维度评分"""
        result = designer.design(LinkerDesignRequest(max_results=3))
        for c in result.candidates:
            assert 0 <= c.score_blood_stability <= 1
            assert 0 <= c.score_lysosome_lability <= 1
            assert 0 <= c.score_drug_likeness <= 1
            assert 0 <= c.score_synthetic <= 1
            assert 0 <= c.overall_score <= 1

    def test_candidate_has_strengths_weaknesses(self, designer):
        """每个候选应该有优缺点分析"""
        result = designer.design(LinkerDesignRequest(max_results=3))
        for c in result.candidates:
            assert len(c.strengths) + len(c.weaknesses) > 0
            assert len(c.recommendation) > 10

    def test_candidates_ranked_by_score(self, designer):
        """候选应该按总分降序排列"""
        result = designer.design(LinkerDesignRequest(max_results=5))
        scores = [c.overall_score for c in result.candidates]
        assert scores == sorted(scores, reverse=True), f"Not sorted: {scores}"


class TestDesignResult:
    """测试设计结果"""

    @pytest.fixture
    def designer(self):
        return LinkerDesigner()

    def test_result_has_summary(self, designer):
        result = designer.design(LinkerDesignRequest())
        assert len(result.design_summary) > 20

    def test_result_has_counts(self, designer):
        result = designer.design(LinkerDesignRequest())
        assert result.total_evaluated > 0
        assert result.total_filtered >= 0

    def test_top_candidate_property(self, designer):
        result = designer.design(LinkerDesignRequest(max_results=3))
        if result.candidates:
            assert result.top_candidate is result.candidates[0]
        else:
            assert result.top_candidate is None

    def test_no_duplicate_candidates(self, designer):
        """不应返回重复候选"""
        result = designer.design(LinkerDesignRequest(max_results=5))
        names = [c.name for c in result.candidates]
        assert len(names) == len(set(names))


class TestQuickDesign:
    """测试便捷函数"""

    def test_quick_design_returns_result(self):
        result = quick_design(target_ph=5.0, max_results=3)
        assert isinstance(result, DesignResult)
        assert len(result.candidates) > 0

    def test_quick_design_ph_sensitive(self):
        result = quick_design(
            target_ph=5.5,
            preferred_mechanism="pH_sensitive",
            max_results=3,
        )
        for c in result.candidates:
            assert c.mechanism == "pH_sensitive"


class TestScoringWeights:
    """测试评分权重总和 + 自定义权重"""

    def test_default_weights_sum_to_one(self):
        """默认权重总和应为 1.0"""
        total = sum(LinkerDesigner.DEFAULT_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01, f"Default weights sum to {total}, not 1.0"

    def test_instance_weights_match_default(self):
        """默认构造的实例权重应匹配 DEFAULT_WEIGHTS"""
        designer = LinkerDesigner()
        for key in LinkerDesigner.DEFAULT_WEIGHTS:
            assert designer.weights[key] == LinkerDesigner.DEFAULT_WEIGHTS[key]

    def test_custom_weights_are_normalized(self):
        """自定义权重应被归一化到总和 1.0"""
        designer = LinkerDesigner(weights={
            "blood_stability": 0.5,
            "lysosome_lability": 0.5,
            "drug_likeness": 0.0,
            "synthetic": 0.0,
        })
        total = sum(designer.weights.values())
        assert abs(total - 1.0) < 0.01, f"Custom weights sum to {total}, not 1.0"

    def test_custom_weights_affect_scoring(self):
        """使用自定义权重后设计结果应不同"""
        default_designer = LinkerDesigner()
        custom_designer = LinkerDesigner(weights={
            "blood_stability": 0.0,
            "lysosome_lability": 0.0,
            "drug_likeness": 1.0,
            "synthetic": 0.0,
        })

        request = LinkerDesignRequest(max_results=5)
        default_result = default_designer.design(request)
        custom_result = custom_designer.design(request)

        # 两种权重下评分应不同（至少有一个候选的排名不同）
        if default_result.candidates and custom_result.candidates:
            default_names = [c.name for c in default_result.candidates]
            custom_names = [c.name for c in custom_result.candidates]
            # 药物相似性优先 vs 血液稳定性优先 → 排序不同
            assert default_names != custom_names, (
                "Custom weights should produce different ranking"
            )

    def test_partial_weights_fill_defaults(self):
        """只提供部分权重时缺失键用默认值补齐"""
        designer = LinkerDesigner(weights={"blood_stability": 0.5})
        # blood_stability 被覆盖，其余保持默认
        assert designer.weights["lysosome_lability"] > 0
        assert designer.weights["drug_likeness"] > 0
        assert designer.weights["synthetic"] > 0
