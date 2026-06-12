"""
测试 MCP 工具: search_linker_scaffolds
"""

import pytest

from adc_linker_agent.mcp_tools.tool_linker import search_linker_scaffolds


class TestSearchLinkerScaffolds:
    """测试连接子骨架搜索 MCP 工具"""

    def test_returns_all_linkers_when_no_filter(self):
        """无筛选条件时返回所有连接子"""
        results = search_linker_scaffolds()
        assert len(results) >= 5  # 至少有 5 个已知骨架
        # 每个结果应该有基本字段
        for linker in results:
            assert "name" in linker
            assert "smiles" in linker
            assert "mechanism" in linker

    def test_filter_by_ph_sensitive_mechanism(self):
        """按 pH_sensitive 机制筛选"""
        results = search_linker_scaffolds(mechanism="pH_sensitive")
        assert len(results) >= 3
        for linker in results:
            assert linker["mechanism"] == "pH_sensitive"

    def test_filter_by_enzymatic_mechanism(self):
        """按 enzymatic 机制筛选"""
        results = search_linker_scaffolds(mechanism="enzymatic")
        assert len(results) >= 1
        for linker in results:
            assert linker["mechanism"] == "enzymatic"

    def test_filter_by_non_cleavable_mechanism(self):
        """按 non_cleavable 机制筛选"""
        results = search_linker_scaffolds(mechanism="non_cleavable")
        assert len(results) >= 1
        for linker in results:
            assert linker["mechanism"] == "non_cleavable"

    def test_filter_by_unknown_mechanism_returns_empty(self):
        """未知机制返回空列表而不抛异常"""
        results = search_linker_scaffolds(mechanism="quantum_tunneling")
        assert results == []

    def test_filter_by_min_molecular_weight(self):
        """最小分子量筛选"""
        results = search_linker_scaffolds(min_molecular_weight=300)
        for linker in results:
            mw = linker["properties"]["molecular_weight"]
            assert mw >= 300, f"{linker['name']}: MW={mw} < 300"

    def test_filter_by_max_molecular_weight(self):
        """最大分子量筛选"""
        results = search_linker_scaffolds(max_molecular_weight=200)
        for linker in results:
            mw = linker["properties"]["molecular_weight"]
            assert mw <= 200, f"{linker['name']}: MW={mw} > 200"

    def test_each_result_has_properties(self):
        """每个结果应该附带完整的性质数据"""
        results = search_linker_scaffolds()
        for linker in results:
            props = linker["properties"]
            expected = {"smiles", "logp", "qed", "sas", "tpsa",
                        "molecular_weight", "hbd", "hba", "rotatable_bonds"}
            assert set(props.keys()) == expected, f"Missing keys in {linker['name']}"

    def test_each_result_has_description(self):
        """每个结果应该有描述和临床参考"""
        results = search_linker_scaffolds()
        for linker in results:
            assert len(linker["description"]) > 10
            assert "drugs_using" in linker

    def test_val_cit_in_results(self):
        """Val-Cit-PABC 连接子应该在结果中"""
        results = search_linker_scaffolds()
        names = [r["name"] for r in results]
        assert any("Val-Cit" in name for name in names)

    def test_search_returns_list(self):
        """返回类型应该是 list"""
        results = search_linker_scaffolds()
        assert isinstance(results, list)
