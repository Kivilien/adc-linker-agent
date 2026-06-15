"""
连接子骨架枚举器（LinkerEnumerator）

通过"LEGO 积木"方式组装 ADC 连接子变体。

ADC 连接子 = 抗体偶联端 + 间隔基 + 裂解触发器 + 自毁间隔基 + 载荷连接端

策略:
  1. 定义 5 类构建块（block）：Cap / Spacer / Trigger / Self-immolative / Payload-end
  2. 按 ADC 连接子逻辑组合（必须含 Cap + Trigger，其余可选）
  3. 验证: RDKit 可解析 + 无 PAINS/Brenk + 合理性质范围
  4. BRICS 分解重组（对能分解的骨架补充）

来源: ADC 化学文献 + 已上市药物连接子结构
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class EnumerateResult:
    """枚举结果。"""
    smiles: str
    parent_scaffold: str
    operation: str  # "assembly" | "substitution" | "recombination"


def _canonical_smiles(smiles: str) -> str | None:
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        return Chem.MolToSmiles(mol)
    except Exception:
        logger.warning("Failed to canonicalize SMILES", exc_info=True)
        return None


class LinkerEnumerator:
    """ADC 连接子枚举器 —— LEGO 积木组装。

    使用方式:
        enumerator = LinkerEnumerator(database=db)
        results = enumerator.batch_enumerate(max_total=200)
    """

    # ─── 构建块定义 ───

    # 抗体偶联端 (Cap) — 与抗体 Cys/Lys 残基反应
    CAPS = {
        "maleimide": "O=C1C=CC(=O)N1",
        "maleimide_hexanoic": "O=C1C=CC(=O)N1CCCCCC(=O)",
        "bromoacetamide": "BrCC(=O)N",
        "succinimidyl_ester": "O=C1CCC(=O)N1OC(=O)",
    }

    # 间隔基 (Spacer) — 调节水溶性/柔韧性
    SPACERS = {
        "PEG2": "OCCOCCO",
        "PEG3": "OCCOCCOCCO",
        "PEG4": "OCCOCCOCCOCCO",
        "C6_alkyl": "CCCCCC",
        "beta_alanine": "NCCC(=O)",
    }

    # 裂解触发器 (Trigger)
    TRIGGERS = {
        # 酶切
        "Val-Cit": "CC(C)[C@H](N)C(=O)N[C@@H](CCCNC(N)=O)C(=O)",
        "Val-Ala": "CC(C)[C@H](N)C(=O)N[C@H](C)C(=O)",
        "Phe-Lys": "N[C@@H](Cc1ccccc1)C(=O)N[C@@H](CCCCN)C(=O)",
        "Glu-Val-Cit": "N[C@@H](CCC(=O)O)C(=O)N[C@@H](C(C)C)C(=O)N[C@@H](CCCNC(N)=O)C(=O)",
        # pH 敏感
        "hydrazone": "CC(=O)NN=C",
        "acetal": "CCOC(C)OCC",
        "ketal": "CC(C)OC(C)(C)OC(C)C",
        "imine": "CC(C)=NC",
        "silyl_ether": "C[Si](C)(C)OC",
        "carbonate": "CC(C)OC(=O)O",
        "ester": "CC(=O)OC",
        "TMALIN_dual": "CC(C)(C)OC(=O)NCCNC(=O)OC",
        # 氧化还原
        "disulfide": "CCSSC",
        "hindered_disulfide": "CC(C)(C)SSC(C)(C)C",
        "GSH_disulfide": "CCSSCCO",
        # 非可裂解
        "non_cleavable_alkyl": "CCCCCCCC",
    }

    # 自毁间隔基 (Self-immolative)
    SELF_IMMOLATIVE = {
        "PABC": "NCc1ccc(O)cc1",
        "PABC_carbamate": "NC(=O)OCc1ccc(O)cc1",
        "PABC_NMe": "CNCc1ccc(O)cc1",
        "bis_PABC": "NCc1ccc(OC(=O)Nc2ccc(CO)cc2)cc1",
    }

    # 载荷连接端 (Payload-end)
    PAYLOAD_ENDS = {
        "hydroxyl": "O",       # 与含-OH 载荷成酯/醚
        "amine": "N",           # 与含-NH2 载荷成酰胺
        "carbonyl": "C(=O)",   # 与含-NH2 载荷成酰胺
    }

    def __init__(self, database=None):
        self._db = database

    # ─── SMARTS 缩合反应 ───

    @staticmethod
    def _amidate(amine_smi: str, acid_smi: str) -> str | None:
        """胺 + 酸 → 酰胺。"""
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem
            amine = Chem.MolFromSmiles(amine_smi)
            acid = Chem.MolFromSmiles(acid_smi)
            if amine is None or acid is None:
                return None
            rxn = AllChem.ReactionFromSmarts(
                "[N:1].[C:2](=[O:3])[O:4]>>[N:1][C:2](=[O:3])"
            )
            products = rxn.RunReactants((amine, acid))
            if products:
                for prod_set in products:
                    for prod in prod_set:
                        Chem.SanitizeMol(prod)
                        return Chem.MolToSmiles(prod)
        except Exception:
            logger.warning("Amidation reaction failed", exc_info=True)
        return None

    @staticmethod
    def _esterify(alcohol_smi: str, acid_smi: str) -> str | None:
        """醇 + 酸 → 酯。"""
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem
            alcohol = Chem.MolFromSmiles(alcohol_smi)
            acid = Chem.MolFromSmiles(acid_smi)
            if alcohol is None or acid is None:
                return None
            rxn = AllChem.ReactionFromSmarts(
                "[O:1].[C:2](=[O:3])[O:4]>>[O:1][C:2](=[O:3])"
            )
            products = rxn.RunReactants((alcohol, acid))
            if products:
                for prod_set in products:
                    for prod in prod_set:
                        Chem.SanitizeMol(prod)
                        return Chem.MolToSmiles(prod)
        except Exception:
            logger.warning("Esterification reaction failed", exc_info=True)
        return None

    # ─── R-group 替换 ───

    _RGROUP_SWAPS = [
        ("[CH3]", "CC"),
        ("[CH3]", "C(C)C"),
        ("[OH1]", "OC"),
        ("[OH1]", "F"),
        ("[CX4H2][CX4H2][CX4H3]", "CCCC"),
    ]

    def _rgroup_swap(self, smiles: str, max_results: int = 10) -> list[str]:
        """R-group 替换生成小变体。"""
        try:
            from rdkit import Chem
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                return []
            results: list[str] = []
            seen: set[str] = {_canonical_smiles(smiles)}
            for pattern_sma, repl_smi in self._RGROUP_SWAPS:
                if len(results) >= max_results:
                    break
                pat = Chem.MolFromSmarts(pattern_sma)
                repl = Chem.MolFromSmiles(repl_smi)
                if pat is None or repl is None:
                    continue
                matches = mol.GetSubstructMatches(pat)
                for _match in matches[:3]:
                    if len(results) >= max_results:
                        break
                    try:
                        new_mol = Chem.ReplaceSubstructs(
                            mol, pat, repl, replaceAll=False
                        )[0]
                        s = Chem.MolToSmiles(new_mol)
                        canon = _canonical_smiles(s)
                        if canon and canon not in seen:
                            seen.add(canon)
                            results.append(canon)
                    except Exception:
                        logger.debug("R-group swap variant failed, skipping", exc_info=True)
                        continue
            return results
        except Exception:
            logger.warning("R-group swap enumeration failed", exc_info=True)
            return []

    # ─── 精选连接子库（文献 + 专利 + 已上市 ADC）───

    # 已知 ADC 连接子变体（完整 SMILES），来自文献和已上市药物
    # noqa: E501 — SMILES strings cannot be wrapped
    CURATED_LIBRARY = [  # noqa: E501
        # === Val-Cit 变体 ===
        ("Val-Cit-PABC-MMAE", "CC(C)[C@H](N)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(O)cc1"),
        ("Val-Ala-PABC", "CC(C)[C@H](N)C(=O)N[C@H](C)C(=O)NCc1ccc(O)cc1"),
        ("Phe-Lys-PABC", "N[C@@H](Cc1ccccc1)C(=O)N[C@@H](CCCCN)C(=O)NCc1ccc(O)cc1"),
        ("Val-Cit-PABC-NMe", "CC(C)[C@H](N)C(=O)N[C@@H](CCCNC(N)=O)C(=O)N(C)Cc1ccc(O)cc1"),
        ("Glu-Val-Cit-PABC", "N[C@@H](CCC(=O)O)C(=O)N[C@@H](C(C)C)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(O)cc1"),
        ("Val-Lys-PABC", "CC(C)[C@H](N)C(=O)N[C@@H](CCCCN)C(=O)NCc1ccc(O)cc1"),
        # === 马来酰亚胺-二肽变体 ===
        ("Mc-Val-Cit-PABC-OH", "O=C1C=CC(=O)N1CCCCCC(=O)N[C@@H](C(C)C)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(O)cc1"),
        ("Mc-Val-Ala-PABC", "O=C1C=CC(=O)N1CCCCCC(=O)N[C@@H](C(C)C)C(=O)N[C@H](C)C(=O)NCc1ccc(O)cc1"),
        ("Mc-Phe-Lys-PABC", "O=C1C=CC(=O)N1CCCCCC(=O)N[C@@H](Cc1ccccc1)C(=O)N[C@@H](CCCCN)C(=O)NCc1ccc(O)cc1"),
        ("Mc-Gly-Gly-Phe-Gly-PABC", "O=C1C=CC(=O)N1CCCCCC(=O)NCC(=O)NCC(=O)N[C@@H](Cc1ccccc1)C(=O)NCC(=O)NCc1ccc(O)cc1"),
        # === β-葡萄糖醛酸酶可裂解 ===
        ("Glucuronide-PABC", "O[C@@H]1[C@@H](O)[C@H](O)[C@@H](O[C@@H]2O[C@H](C(=O)O)[C@@H](O)[C@H](O)[C@H]2O)O[C@@H]1OCc1ccc(NC(=O)O)cc1"),
        ("Mc-Glucuronide-PABC", "O=C1C=CC(=O)N1CCCCCC(=O)Nc1ccc(CO[C@@H]2O[C@H](C(=O)O)[C@@H](O)[C@H](O)[C@H]2O)cc1"),
        # === PEG 连接子 ===
        ("Mc-PEG4-Val-Cit-PABC", "O=C1C=CC(=O)N1CCCCCC(=O)NCCOCCOCCOCCOCC(=O)N[C@@H](C(C)C)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(O)cc1"),
        ("Mc-PEG8-Val-Cit-PABC", "O=C1C=CC(=O)N1CCCCCC(=O)NCCOCCOCCOCCOCCOCCOCCOCCOCC(=O)N[C@@H](C(C)C)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(O)cc1"),
        ("Mc-PEG2-Val-Cit-PABC", "O=C1C=CC(=O)N1CCCCCC(=O)NCCOCCOCC(=O)N[C@@H](C(C)C)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(O)cc1"),
        # === 二硫键连接子 ===
        ("SPDP-PEG4-SPDP", "O=C(ON1C(=O)CCC1=O)CCSSCCOCCOCCOCCOCCSSCCC(=O)ON1C(=O)CCC1=O"),
        ("Mal-PEG2-SS-PEG2-Mal", "O=C1C=CC(=O)N1CCOCCOCCSSCCNC(=O)CCOCCN1C(=O)C=CC1=O"),
        ("SPDP-PEG2", "O=C(ON1C(=O)CCC1=O)CCSSCCOCCO"),
        # === PY-DT 前药连接子 ===
        ("Mc-Val-Cit-PABC-DMAE", "O=C1C=CC(=O)N1CCCCCC(=O)N[C@@H](C(C)C)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(OC(=O)N(C)CCO)cc1"),
        # === 磷酸酶可裂解 ===
        ("Phosphate-PABC", "O=P(O)(O)OCc1ccc(NC(=O)O)cc1"),
        ("Mc-Phosphate-PABC", "O=C1C=CC(=O)N1CCCCCC(=O)Nc1ccc(COP(=O)(O)O)cc1"),
        # === 硝基还原酶可裂解 ===
        ("Nitro-PABC", "O=[N+]([O-])c1ccc(COC(=O)Nc2ccc(CO)cc2)cc1"),
        # === 酯可裂解 ===
        ("Mc-Caproyl-SN38", "O=C1C=CC(=O)N1CCCCCC(=O)O[C@@]1(CC)C(=O)OCc2c1cc1ccc(O)c3c1c2Cc1c-3[nH]c(=O)c2c(C)cccc12"),
        # === 非可裂解 + PEG ===
        ("SMCC-PEG4", "O=C1C=CC(=O)N1CCCCCC(=O)NCCOCCOCCOCCOCC(=O)O"),
        ("SMCC-PEG2", "O=C1C=CC(=O)N1CCCCCC(=O)NCCOCCOCC(=O)O"),
        # === 双马来酰亚胺交联 ===
        ("BisMal-PEG3", "O=C1C=CC(=O)N1CCOCCOCCN1C(=O)C=CC1=O"),
        ("BisMal-PEG2", "O=C1C=CC(=O)N1CCOCCN1C(=O)C=CC1=O"),
        # === 点击化学连接子 ===
        ("Azide-PEG3-amine", "[N-]=[N+]=NCCCOCCOCCOCCCN"),
        ("DBCO-PEG4-amine", "O=C1CC(c2ccccc2)c2ccccc2N1C(=O)CCOCCOCCOCCOCCN"),
        # === 磺酸增强溶解性 ===
        ("Mc-Val-Cit-PABC-SO3H", "O=C1C=CC(=O)N1CCCCCC(=O)N[C@@H](C(C)C)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(OS(=O)(=O)O)cc1"),
        ("Mc-sulfonyl-Val-Cit-PABC", "O=C1C=CC(=O)N1CCCCS(=O)(=O)N[C@@H](C(C)C)C(=O)N[C@@H](CCCNC(N)=O)C(=O)NCc1ccc(O)cc1"),
        # === 焦磷酸酶可裂解 ===
        ("Pyrophosphate-PABC", "O=P(O)(O)OP(=O)(O)OCc1ccc(NC(=O)O)cc1"),
    ]

    # ─── LEGO 组装 ───

    def _assemble_adc_linker(
        self,
        cap: str,
        trigger: str,
        spacer: str | None = None,
        si: str | None = None,
        payload_end: str = "O",
    ) -> str | None:
        """
        按 ADC 连接子逻辑组装:

        顺序: Cap — Spacer — Trigger — Self-immolative — Payload-end

        组装通过酰胺键或酯键连接各模块。
        """
        current = cap

        # 1. Cap + Spacer（如有）
        if spacer:
            # 马来酰亚胺-酸 + spacer 胺 → 酰胺
            result = self._amidate(spacer, current)
            if result:
                current = result

        # 2. + Trigger（酸-胺缩合）
        result = self._amidate(trigger, current)
        if result:
            current = result
        elif current != cap:
            # 回退: ester 连接
            result = self._esterify(trigger, current)
            if result:
                current = result

        # 3. + Self-immolative spacer（如有）
        if si and si not in current:
            result = self._amidate(si, current)
            if result:
                current = result
            else:
                result = self._esterify(si, current)
                if result:
                    current = result

        if current == cap:
            return None
        return current

    def _assemble_all(
        self, max_per_category: int = 10
    ) -> list[tuple[str, str]]:
        """
        遍历所有构建块组合，生成连接子。

        Returns:
            [(smiles, description), ...]
        """
        results: list[tuple[str, str]] = []
        seen: set[str] = set()

        caps = list(self.CAPS.items())
        triggers = list(self.TRIGGERS.items())
        spacers = [(None, "")] + list(self.SPACERS.items())
        sis = [(None, "")] + list(self.SELF_IMMOLATIVE.items())

        count = 0
        for cap_name, cap_smi in caps:
            for trig_name, trig_smi in triggers:
                for sp_name, sp_smi in spacers:
                    for si_name, si_smi in sis:
                        if count >= max_per_category * 4:
                            break
                        # 限制: 不能全是可选组件
                        if sp_name is None and si_name is None:
                            continue

                        linker_smi = self._assemble_adc_linker(
                            cap_smi, trig_smi,
                            spacer=sp_smi,
                            si=si_smi,
                        )
                        if linker_smi is None:
                            continue

                        canon = _canonical_smiles(linker_smi)
                        if not canon or canon in seen:
                            continue
                        seen.add(canon)

                        desc_parts = [cap_name, trig_name]
                        if sp_name:
                            desc_parts.insert(1, sp_name)
                        if si_name:
                            desc_parts.append(si_name)

                        results.append((canon, "|".join(desc_parts)))
                        count += 1

        return results

    # ─── 验证 ───

    def validate(
        self,
        smiles_list: list[str],
        min_atoms: int = 10,
        max_atoms: int = 200,
        min_mw: float = 100,
        max_mw: float = 1500,
    ) -> list[str]:
        """验证和过滤 SMILES。"""
        try:
            from rdkit import Chem
            from rdkit.Chem import Descriptors

            from adc_linker_agent.domain.properties import check_toxicity_alerts
        except ImportError:
            return []

        valid: list[str] = []
        seen: set[str] = set()

        for smi in smiles_list:
            mol = Chem.MolFromSmiles(smi)
            if mol is None:
                continue
            n = mol.GetNumAtoms()
            if n < min_atoms or n > max_atoms:
                continue
            mw = Descriptors.MolWt(mol)
            if mw < min_mw or mw > max_mw:
                continue
            tox = check_toxicity_alerts(smi)
            if tox.get("has_alerts"):
                continue
            canon = Chem.MolToSmiles(mol)
            if canon in seen:
                continue
            seen.add(canon)
            if self._db is not None and canon in self._db:
                continue
            valid.append(canon)

        return valid

    # ─── BRICS 补充 ───

    def _brics_recombine(self, smiles: str, max_results: int = 10) -> list[str]:
        """尝试 BRICS 分解重组（对部分骨架有效）。"""
        try:
            from rdkit import Chem
            from rdkit.Chem import BRICS
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                return []
            frags = list(BRICS.BRICSDecompose(mol))
            if len(frags) < 2:
                return []
            frag_mols = [Chem.MolFromSmiles(f) for f in frags]
            frag_mols = [m for m in frag_mols if m is not None]
            unique_mols = []
            seen_smi = set()
            for m in frag_mols:
                s = Chem.MolToSmiles(m)
                if s not in seen_smi:
                    seen_smi.add(s)
                    unique_mols.append(m)
            if len(unique_mols) < 2:
                return []
            built = list(BRICS.BRICSBuild(unique_mols))
            results = []
            for m in built:
                if len(results) >= max_results:
                    break
                try:
                    Chem.SanitizeMol(m)
                    s = Chem.MolToSmiles(m)
                    # 排除含 dummy atom [*] 的产物
                    if "[*]" not in s:
                        results.append(s)
                except Exception:
                    logger.debug("BRICS molecule sanitization failed, skipping", exc_info=True)
                    continue
            return results
        except Exception:
            logger.warning("BRICS recombination failed", exc_info=True)
            return []

    # ─── 批量枚举 ───

    def batch_enumerate(
        self,
        scaffolds: list[dict] | None = None,
        max_per_scaffold: int = 15,
        max_total: int = 200,
    ) -> list[EnumerateResult]:
        """
        批量生成连接子变体。

        流程:
          1. LEGO 积木组装（主策略）
          2. R-group 替换（现有骨架微调）
          3. BRICS 重组（补充）
          4. 验证 + 去重
        """
        results: list[EnumerateResult] = []
        seen: set[str] = set()

        # ─── 策略 1: 精选文献库 ───
        curated_smiles = [smi for _, smi in self.CURATED_LIBRARY]
        valid_curated = self.validate(curated_smiles)
        for i, smi in enumerate(valid_curated):
            if len(results) >= max_total:
                break
            if smi in seen:
                continue
            seen.add(smi)
            name = self.CURATED_LIBRARY[i][0] if i < len(self.CURATED_LIBRARY) else "curated"
            results.append(EnumerateResult(
                smiles=smi,
                parent_scaffold=name,
                operation="assembly",
            ))

        # ─── 策略 2: R-group 替换 ───
        if scaffolds is None:
            scaffolds = [] if self._db is None else list(self._db)

        for scaffold in scaffolds:
            if len(results) >= max_total:
                break
            name = scaffold.get("name", "unknown")
            smi = scaffold.get("smiles", "")
            if not smi:
                continue

            swapped = self._rgroup_swap(smi, max_results=max_per_scaffold // 4)
            valid_swapped = self.validate(swapped)
            for vs in valid_swapped:
                if vs in seen or len(results) >= max_total:
                    break
                seen.add(vs)
                results.append(EnumerateResult(
                    smiles=vs, parent_scaffold=name, operation="substitution",
                ))

        # ─── 策略 3: BRICS 重组 ───
        for scaffold in scaffolds:
            if len(results) >= max_total:
                break
            name = scaffold.get("name", "unknown")
            smi = scaffold.get("smiles", "")
            if not smi:
                continue

            recombined = self._brics_recombine(smi, max_results=5)
            # BRICS 产物需要单独验证（可能含 dummy atoms）
            valid_recomb = []
            for s in recombined:
                mol = None
                try:
                    from rdkit import Chem
                    mol = Chem.MolFromSmiles(s)
                except Exception:
                    logger.debug("MolFromSmiles failed during BRICS validation", exc_info=True)
                if mol and "[*]" not in s:
                    valid_recomb.append(s)
            valid_recomb = self.validate(valid_recomb)
            for vr in valid_recomb:
                if vr in seen or len(results) >= max_total:
                    break
                seen.add(vr)
                results.append(EnumerateResult(
                    smiles=vr, parent_scaffold=name, operation="recombination",
                ))

        return results

    def quick_enumerate(self, smiles: str, max_results: int = 10) -> list[str]:
        """快速枚举单分子变体。"""
        all_smiles = self._rgroup_swap(smiles, max_results)
        all_smiles += self._brics_recombine(smiles, max_results // 2)
        return self.validate(all_smiles)[:max_results]
