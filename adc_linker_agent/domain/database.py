"""
连接子骨架数据库（LinkerDatabase）

统一数据层，替代分散在 linker_designer.py 和 tool_linker.py 中的
CSV 加载逻辑。提供去重、搜索、统计、缓存功能。

新增字段:
  - source: 数据来源 (curated|pubchem|enumerated|literature)
  - source_id: 来源标识 (PubChem CID / 批次 UUID / DOI)

去重策略: 规范 SMILES 作为主键，自动过滤重复骨架。
"""

import csv
import json
import logging
import time
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

SourceType = Literal["curated", "pubchem", "enumerated", "literature"]

# 有效的 source 值集合
_VALID_SOURCES = frozenset({"curated", "pubchem", "enumerated", "literature"})

# 现有 CSV 的列（向后兼容）
_CORE_COLUMNS = [
    "name", "smiles", "mechanism", "trigger_ph", "enzyme",
    "trigger_detail", "description", "drugs_using", "category",
]
# Phase B 新增列
_NEW_COLUMNS = ["source", "source_id"]
# 完整列顺序
_ALL_COLUMNS = _CORE_COLUMNS + _NEW_COLUMNS


def _canonical_smiles(smiles: str) -> str | None:
    """返回规范 SMILES，无效时返回 None。"""
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        return Chem.MolToSmiles(mol)
    except Exception:
        logger.warning("Failed to canonicalize SMILES", exc_info=True)
        return None


class LinkerDatabase:
    """连接子骨架数据库 —— 统一数据层。

    使用方式:
        db = LinkerDatabase()
        print(f"Total: {len(db)} scaffolds")

        # 搜索
        results = db.search(mechanism="pH_sensitive", mw_max=600)

        # 批量添加
        added = db.add_scaffold(
            name="New Linker",
            smiles="CC(=O)OC...",
            mechanism="pH_sensitive",
            source="pubchem",
        )
    """

    def __init__(self, csv_path: str | None = None, data_dir: str | None = None):
        """
        Args:
            csv_path: CSV 文件路径。默认: <data_dir>/linker_scaffolds.csv
            data_dir: 数据目录。默认: Config.data_dir
        """
        if data_dir is None:
            from adc_linker_agent.utils.config import get_config
            data_dir = str(get_config().data_dir)
        if csv_path is None:
            csv_path = str(Path(data_dir) / "linker_scaffolds.csv")

        self.csv_path = Path(csv_path)
        self.data_dir = Path(data_dir)
        self.cache_path = self.data_dir / "linker_properties_cache.json"

        # 主存储: list[dict] 每行一个骨架
        self._scaffolds: list[dict[str, Any]] = []
        # 规范 SMILES 索引: canonical_smiles -> list index
        self._smiles_index: dict[str, int] = {}

        self._load()

    # ─── 加载 / 保存 ───

    def _load(self) -> None:
        """从 CSV 加载，建立 SMILES 索引。"""
        if not self.csv_path.exists():
            self._scaffolds = []
            self._smiles_index = {}
            return

        with open(self.csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("name", "").strip()
                smiles = row.get("smiles", "").strip()
                if not name or not smiles:
                    continue

                # 规范化
                row = self._normalize_row(row)

                # 索引
                canon = _canonical_smiles(smiles)
                if canon:
                    self._smiles_index[canon] = len(self._scaffolds)

                self._scaffolds.append(row)

    def _normalize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """规范化一行数据（类型转换、默认值填充）。"""
        # drugs_using: "a|b|c" → ["a", "b", "c"]
        drugs = row.get("drugs_using", "")
        if isinstance(drugs, str) and drugs.strip():
            row["drugs_using"] = [d.strip() for d in drugs.split("|") if d.strip()]
        elif isinstance(drugs, list):
            row["drugs_using"] = drugs
        else:
            row["drugs_using"] = []

        # trigger_ph: str → float | None
        ph = row.get("trigger_ph")
        if ph is not None and str(ph).strip():
            try:
                row["trigger_ph"] = float(ph)
            except (ValueError, TypeError):
                row["trigger_ph"] = None
        else:
            row["trigger_ph"] = None

        # 新增字段默认值
        row.setdefault("source", "curated")
        row.setdefault("source_id", "")

        # 清理空白
        for k in ("mechanism", "enzyme", "trigger_detail", "description",
                   "category", "source", "source_id"):
            if k in row and row[k] is not None:
                row[k] = str(row[k]).strip()

        return row

    def save(self) -> None:
        """保存到 CSV。"""
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_ALL_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in self._scaffolds:
                # 序列化 drugs_using 回 "a|b|c" 格式
                out = dict(row)
                drugs = out.get("drugs_using", [])
                if isinstance(drugs, list):
                    out["drugs_using"] = "|".join(drugs)
                writer.writerow(out)

    # ─── CRUD ───

    def add_scaffold(
        self,
        name: str,
        smiles: str,
        mechanism: str,
        trigger_ph: float | None = None,
        enzyme: str = "",
        trigger_detail: str = "",
        description: str = "",
        drugs_using: list[str] | None = None,
        category: str = "cleavable_linker",
        source: SourceType = "curated",
        source_id: str = "",
    ) -> bool:
        """
        添加一个骨架。自动去重（按规范 SMILES）。

        Returns:
            True 如果成功添加，False 如果已存在或 SMILES 无效。
        """
        canon = _canonical_smiles(smiles)
        if canon is None:
            return False

        # 去重检查
        if canon in self._smiles_index:
            return False

        # 验证 source
        if source not in _VALID_SOURCES:
            raise ValueError(
                f"Invalid source '{source}'. Must be one of: {sorted(_VALID_SOURCES)}"
            )

        row = {
            "name": str(name).strip(),
            "smiles": smiles.strip(),
            "mechanism": str(mechanism).strip(),
            "trigger_ph": trigger_ph,
            "enzyme": str(enzyme).strip(),
            "trigger_detail": str(trigger_detail).strip(),
            "description": str(description).strip(),
            "drugs_using": drugs_using or [],
            "category": str(category).strip(),
            "source": source,
            "source_id": str(source_id).strip(),
        }

        self._smiles_index[canon] = len(self._scaffolds)
        self._scaffolds.append(row)
        return True

    def get_by_smiles(self, smiles: str) -> dict[str, Any] | None:
        """按 SMILES 查询（接受任意 SMILES，内部规范化）。"""
        canon = _canonical_smiles(smiles)
        if canon is None:
            return None
        idx = self._smiles_index.get(canon)
        if idx is None:
            return None
        return dict(self._scaffolds[idx])

    def remove_by_smiles(self, smiles: str) -> bool:
        """按 SMILES 删除。返回 True 如果成功。"""
        canon = _canonical_smiles(smiles)
        if canon is None or canon not in self._smiles_index:
            return False

        idx = self._smiles_index.pop(canon)
        # 标记删除（不实际移除，避免索引错乱 —— 简单实现）
        self._scaffolds[idx] = {}

        # 重建索引
        self._rebuild_index()
        return True

    # ─── 搜索 ───

    def search(
        self,
        mechanism: str | None = None,
        mw_min: float | None = None,
        mw_max: float | None = None,
        source: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        搜索骨架。

        Args:
            mechanism: 裂解机制筛选
            mw_min: 最小分子量 (Da)
            mw_max: 最大分子量 (Da)
            source: 数据来源筛选
            query: 模糊搜索（匹配 name + description，大小写不敏感）

        Returns:
            匹配的骨架列表（深拷贝）。
        """
        results = []
        for row in self._scaffolds:
            if not row:  # 已删除的行
                continue

            if mechanism and row.get("mechanism") != mechanism:
                continue
            if source and row.get("source") != source:
                continue
            if query:
                q = query.lower()
                name = str(row.get("name", "")).lower()
                desc = str(row.get("description", "")).lower()
                if q not in name and q not in desc:
                    continue

            # MW 筛选需要计算（仅在需要时）
            if mw_min is not None or mw_max is not None:
                mw = self._get_mw(row.get("smiles", ""))
                if mw is None:
                    continue
                if mw_min is not None and mw < mw_min:
                    continue
                if mw_max is not None and mw > mw_max:
                    continue

            results.append(dict(row))

        return results

    def _get_mw(self, smiles: str) -> float | None:
        """快速计算分子量（无缓存版本，用于搜索筛选）。"""
        try:
            from rdkit import Chem
            from rdkit.Chem import Descriptors
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                return None
            return Descriptors.MolWt(mol)
        except Exception:
            logger.warning("Failed to compute molecular weight for scaffold", exc_info=True)
            return None

    # ─── 统计 ───

    def stats(self) -> dict[str, Any]:
        """返回数据库统计信息。"""
        total = len(self)
        by_mechanism: dict[str, int] = {}
        by_source: dict[str, int] = {}

        for row in self._scaffolds:
            if not row:
                continue
            mech = row.get("mechanism", "unknown")
            src = row.get("source", "curated")
            by_mechanism[mech] = by_mechanism.get(mech, 0) + 1
            by_source[src] = by_source.get(src, 0) + 1

        return {
            "total": total,
            "by_mechanism": dict(sorted(by_mechanism.items())),
            "by_source": dict(sorted(by_source.items())),
        }

    # ─── 缓存 ───

    def rebuild_cache(self) -> dict[str, Any]:
        """
        预计算所有骨架的属性 → JSON 缓存。

        Returns:
            缓存 dict（也写入磁盘）。
        """
        from adc_linker_agent.domain.ph_simulator import PhSimulator
        from adc_linker_agent.domain.properties import MolPropertyCalculator, check_toxicity_alerts

        prop_calc = MolPropertyCalculator()
        ph_sim = PhSimulator()

        entries: dict[str, dict] = {}
        start = time.perf_counter()
        total = 0

        for row in self._scaffolds:
            if not row:
                continue
            smiles = row.get("smiles", "")
            try:
                props = prop_calc.calculate_all(smiles)
                ph_results = ph_sim.predict_physiological_phases(smiles)
                tox = check_toxicity_alerts(smiles)

                canon = _canonical_smiles(smiles)
                if canon is None:
                    continue

                entries[canon] = {
                    "logp": round(props.get("logp", 0), 2),
                    "qed": round(props.get("qed", 0), 3),
                    "sas": round(props.get("sas", 0), 2),
                    "tpsa": round(props.get("tpsa", 0), 1),
                    "molecular_weight": round(props.get("molecular_weight", 0), 1),
                    "hbd": props.get("hbd", 0),
                    "hba": props.get("hba", 0),
                    "rotatable_bonds": props.get("rotatable_bonds", 0),
                    "toxicity_alerts": tox.get("alerts", []),
                    "has_toxicity_alerts": tox.get("has_alerts", False),
                    "ph_stability": {
                        phase: {"is_stable": r.is_stable, "labile_groups": r.labile_groups_found}
                        for phase, r in ph_results.items()
                    },
                }
                total += 1
            except Exception:
                logger.warning("Skipping scaffold during cache build", exc_info=True)
                continue

        elapsed = time.perf_counter() - start
        cache = {
            "version": "1.0",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_entries": total,
            "build_time_seconds": round(elapsed, 2),
            "entries": entries,
        }

        # 写入磁盘
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)

        return cache

    def load_cache(self) -> dict[str, Any] | None:
        """加载属性缓存。不存在或版本不匹配返回 None。"""
        if not self.cache_path.exists():
            return None
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("version") != "1.0":
                return None
            return cache
        except (json.JSONDecodeError, KeyError):
            return None

    def get_cached_properties(self, smiles: str) -> dict[str, Any] | None:
        """获取单个 SMILES 的缓存属性。未命中返回 None。"""
        cache = self.load_cache()
        if cache is None:
            return None
        canon = _canonical_smiles(smiles)
        if canon is None:
            return None
        return cache.get("entries", {}).get(canon)

    # ─── 内部工具 ───

    def _rebuild_index(self) -> None:
        """重建 SMILES 索引（删除操作后调用）。"""
        self._smiles_index.clear()
        new_scaffolds = []
        for row in self._scaffolds:
            if not row:
                continue
            smiles = row.get("smiles", "")
            canon = _canonical_smiles(smiles)
            if canon:
                self._smiles_index[canon] = len(new_scaffolds)
            new_scaffolds.append(row)
        self._scaffolds = new_scaffolds

    # ─── 协议方法 ───

    def __len__(self) -> int:
        return sum(1 for r in self._scaffolds if r)

    def __iter__(self):
        return (dict(r) for r in self._scaffolds if r)

    def __contains__(self, smiles: str) -> bool:
        canon = _canonical_smiles(smiles)
        return canon is not None and canon in self._smiles_index

    def __repr__(self) -> str:
        s = self.stats()
        return (
            f"LinkerDatabase(total={s['total']}, "
            f"mechanisms={s['by_mechanism']}, "
            f"sources={s['by_source']})"
        )
