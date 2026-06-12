"""
分子性质计算器（MolPropertyCalculator）

这是 ADC Agent 的"数字引擎"——输入 SMILES 字符串，输出一组数值描述符。
每个计算函数背后都是一个 RDKit 内置算法或公开论文的实现。

对程序员的类比:
    这个类就像 sklearn 的 Transformer —— fit() 不需要（分子结构即参数），
    直接 transform(smiles) → 特征向量。

核心设计原则:
    - 每个静态方法都是纯函数: SMILES in → float out
    - 错误处理在调用层（MCP tool），不在计算层
    - 零外部依赖（只依赖 RDKit），可独立测试
"""

from typing import Optional
from functools import lru_cache

from rdkit import Chem
from rdkit.Chem import Descriptors, QED
from rdkit.Contrib.SA_Score import sascorer


class MolPropertyCalculator:
    """
    计算单个分子的所有关键性质。

    使用方式:
        calc = MolPropertyCalculator()
        props = calc.calculate_all("CC(=O)Oc1ccccc1C(=O)O")
        # → {"logp": 1.43, "qed": 0.78, "sas": 1.82, ...}
    """

    @staticmethod
    def calculate_logp(smiles: str) -> float:
        """
        LogP —— 辛醇/水分配系数

        衡量分子"更喜欢油还是水"。
        - LogP > 0: 亲油（容易卡在细胞膜里）
        - LogP < 0: 亲水（容易溶于血液中）
        - ADC 连接子理想范围: 1-3

        用 Wildman-Crippen 方法计算（RDKit 内置），
        基于每个原子的贡献值累加。
        """
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Invalid SMILES: {smiles}")
        return float(Descriptors.MolLogP(mol))

    @staticmethod
    def calculate_qed(smiles: str) -> float:
        """
        QED —— Quantitative Estimate of Drug-likeness

        药物相似性的综合打分（0-1），加权组合了 8 个性质:
        1. 分子量
        2. LogP
        3. 氢键供体数
        4. 氢键受体数
        5. 极性表面积 (TPSA)
        6. 可旋转键数
        7. 芳香环数
        8. 警报结构数（有毒/不稳定的子结构）

        每个性质用 desirability function 映射到 [0,1]，
        然后几何平均。> 0.5 算"看起来像药"。

        类比: 信用评分 = 多维度加权合成一个数
        """
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Invalid SMILES: {smiles}")
        return float(QED.qed(mol))

    @staticmethod
    def calculate_sas(smiles: str) -> float:
        """
        SAS —— Synthetic Accessibility Score

        合成难度（1=easy, 10=difficult）。
        基于 Ertl & Schuffenhauer (2009) 的方法:
        - 把分子按 BRICS 规则切成片段
        - 每个片段在 PubChem 中出现的频率越高 → 越容易合成
        - 加上环复杂度惩罚

        为什么 ADC 连接子需要低 SAS？
        连接子需要大规模 GMP 生产，合成步骤多 = 成本爆炸。
        """
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Invalid SMILES: {smiles}")
        return float(sascorer.calculateScore(mol))

    @staticmethod
    def calculate_tpsa(smiles: str) -> float:
        """
        TPSA —— Topological Polar Surface Area

        所有极性原子（O, N, 以及它们连接的 H）的表面积之和 (Å²)。
        - 低 TPSA (< 140 Å²): 容易穿过细胞膜
        - 高 TPSA (> 140 Å²): 难以穿过细胞膜，但水溶性好

        ADC 连接子的 TPSA 考虑：
        - 太低 → 连接子-payload 太疏水，会聚集
        - 太高 → 难以进入细胞
        理想范围: 80-140 Å²
        """
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Invalid SMILES: {smiles}")
        return float(Descriptors.TPSA(mol))

    @staticmethod
    def calculate_molecular_weight(smiles: str) -> float:
        """分子量 (Da) —— Lipinski 规则要求 < 500"""
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Invalid SMILES: {smiles}")
        return float(Descriptors.MolWt(mol))

    @staticmethod
    def calculate_hbd(smiles: str) -> int:
        """氢键供体数 (HBD) —— Lipinski 规则要求 < 5"""
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Invalid SMILES: {smiles}")
        return int(Descriptors.NumHDonors(mol))

    @staticmethod
    def calculate_hba(smiles: str) -> int:
        """氢键受体数 (HBA) —— Lipinski 规则要求 < 10"""
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Invalid SMILES: {smiles}")
        return int(Descriptors.NumHAcceptors(mol))

    @staticmethod
    def calculate_rotatable_bonds(smiles: str) -> int:
        """可旋转键数 —— 影响分子柔性和口服吸收"""
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Invalid SMILES: {smiles}")
        return int(Descriptors.NumRotatableBonds(mol))

    @staticmethod
    def check_lipinski(smiles: str) -> dict:
        """
        Lipinski 五规则检查（口服药物的经验法则）

        返回每条规则的通过/失败状态。
        违反 ≤ 1 条 → 可能适合口服。
        """
        try:
            mw = MolPropertyCalculator.calculate_molecular_weight(smiles)
            logp = MolPropertyCalculator.calculate_logp(smiles)
            hbd = MolPropertyCalculator.calculate_hbd(smiles)
            hba = MolPropertyCalculator.calculate_hba(smiles)

            violations = []
            if mw > 500:
                violations.append(f"MW={mw:.0f} > 500")
            if logp > 5:
                violations.append(f"LogP={logp:.1f} > 5")
            if hbd > 5:
                violations.append(f"HBD={hbd} > 5")
            if hba > 10:
                violations.append(f"HBA={hba} > 10")

            return {
                "molecular_weight": round(mw, 1),
                "logp": round(logp, 2),
                "hbd": hbd,
                "hba": hba,
                "violations": len(violations),
                "violation_details": violations,
                "is_oral_drug_like": len(violations) <= 1,
            }
        except ValueError as e:
            return {"error": str(e)}

    # ─── 批量计算（本周 MCP 工具的核心接口） ───

    def calculate_all(self, smiles: str) -> dict[str, float]:
        """
        一次性计算所有关键性质。

        这是 MCP 工具 `calculate_properties` 调用的底层函数。
        返回一个字典，方便序列化为 JSON。
        """
        return {
            "smiles": smiles,
            "logp": round(self.calculate_logp(smiles), 2),
            "qed": round(self.calculate_qed(smiles), 3),
            "sas": round(self.calculate_sas(smiles), 2),
            "tpsa": round(self.calculate_tpsa(smiles), 1),
            "molecular_weight": round(self.calculate_molecular_weight(smiles), 1),
            "hbd": self.calculate_hbd(smiles),
            "hba": self.calculate_hba(smiles),
            "rotatable_bonds": self.calculate_rotatable_bonds(smiles),
        }


# ─── 缓存版本（Week 8 性能优化时用） ───

class CachedMolPropertyCalculator(MolPropertyCalculator):
    """
    带 LRU 缓存的性质计算器。
    同一个 SMILES 只计算一次，适合高频调用场景。
    """

    @staticmethod
    @lru_cache(maxsize=1024)
    def calculate_logp_cached(smiles: str) -> float:
        return MolPropertyCalculator.calculate_logp(smiles)

    @staticmethod
    @lru_cache(maxsize=1024)
    def calculate_qed_cached(smiles: str) -> float:
        return MolPropertyCalculator.calculate_qed(smiles)

    def calculate_all_cached(self, smiles: str) -> dict[str, float]:
        """缓存版本的全量计算"""
        return {
            "smiles": smiles,
            "logp": round(self.calculate_logp_cached(smiles), 2),
            "qed": round(self.calculate_qed_cached(smiles), 3),
            "sas": round(self.calculate_sas(smiles), 2),
            "tpsa": round(self.calculate_tpsa(smiles), 1),
            "molecular_weight": round(self.calculate_molecular_weight(smiles), 1),
            "hbd": self.calculate_hbd(smiles),
            "hba": self.calculate_hba(smiles),
            "rotatable_bonds": self.calculate_rotatable_bonds(smiles),
        }
