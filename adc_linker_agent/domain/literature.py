"""
科学文献搜索引擎（LiteratureSearchEngine）

通过 Europe PMC REST API 搜索 PubMed/Europe PMC 生物医学文献。
无需 API Key，零配置，直接 HTTP 请求。

使用方式:
    engine = LiteratureSearchEngine()
    papers = engine.search("ADC linker pH-sensitive cleavable", max_results=5)
    for p in papers:
        print(p.format_citation())

数据来源:
    Europe PMC (https://europepmc.org/) — 4000万+ 摘要，800万+ 全文 OA
    包含 PubMed、PubMed Central、预印本、专利等
"""

import contextlib
import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Europe PMC REST API base URL
EUROPE_PMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"


@dataclass
class PaperResult:
    """单篇科学论文的元数据"""

    title: str
    authors: str  # "LastName FirstInitial, ..." 格式
    year: int | None = None
    journal: str = ""
    abstract: str = ""
    doi: str = ""
    pmid: str = ""
    pmcid: str = ""
    citation_count: int = 0
    source: str = "MED"  # MED = PubMed, PMC = PubMed Central, etc.

    @property
    def url(self) -> str:
        """论文的公开访问 URL"""
        if self.doi:
            return f"https://doi.org/{self.doi}"
        if self.pmcid:
            return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{self.pmcid}/"
        if self.pmid:
            return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"
        return ""

    @property
    def europepmc_url(self) -> str:
        """Europe PMC 上的论文页面"""
        if self.pmid:
            return f"https://europepmc.org/article/MED/{self.pmid}"
        if self.pmcid:
            return f"https://europepmc.org/article/PMC/{self.pmcid}"
        return ""

    def format_citation(self, style: str = "ama") -> str:
        """
        生成带链接的引用字符串。

        Args:
            style: 引用格式 ("ama" | "brief")

        Returns:
            格式化的引用字符串
        """
        if style == "brief":
            # 简短格式：标题 + DOI 链接
            doi_link = f"https://doi.org/{self.doi}" if self.doi else self.url
            return f"{self.title} → {doi_link}"

        # AMA 格式: Authors. Title. Journal. Year. DOI
        parts = []
        if self.authors:
            parts.append(f"{self.authors}.")
        parts.append(f"*{self.title}*")
        if self.journal and self.year:
            parts.append(f"{self.journal}. {self.year}.")
        elif self.year:
            parts.append(f"({self.year})")
        if self.doi:
            parts.append(f"https://doi.org/{self.doi}")
        elif self.pmid:
            parts.append(f"PMID: {self.pmid}")

        return " ".join(parts)


class LiteratureSearchEngine:
    """
    科学文献搜索引擎。

    使用 Europe PMC REST API 搜索生物医学文献。
    无需 API Key，速率限制约 30-60 请求/分钟。

    使用方式:
        engine = LiteratureSearchEngine()
        papers = engine.search("antibody-drug conjugate linker design")
        for p in papers:
            print(p.title, p.doi)
    """

    # ADC 连接子化学术语 → 文献常用同义词（Europe PMC 索引兼容）
    # PABC 在论文中多用 PAB，连字符术语需展开为空格分隔 + 同义词 OR
    # 重要：为防止叠加替换（如 Val-Cit-PABC 展开后又被 PABC 二次替换），
    # 所有展开文本中避免使用 "PABC" 字面量，改用 "PAB"。
    # 按长度降序替换，确保先匹配更具体的模式。
    _ADC_SYNONYMS: dict[str, str] = {
        "MC-VC-PABC": (
            '(MC-VC-PAB OR "maleimidocaproyl-valine-citrulline"'
            ' OR "Val-Cit PAB" OR "cathepsin B cleavable")'
        ),
        "mc-vc-PABC": (
            '(mc-vc-PAB OR "maleimidocaproyl-valine-citrulline"'
            ' OR "Val-Cit PAB" OR "cathepsin B cleavable")'
        ),
        "Val-Cit-PABC": (
            '(Val-Cit-PAB OR "valine-citrulline PAB"'
            ' OR "Val-Cit dipeptide" OR "cathepsin B cleavable")'
        ),
        "vc-PABC": (
            '(vc-PAB OR "Val-Cit PAB" OR "valine-citrulline"'
            ' OR "cathepsin B cleavable")'
        ),
        "VC-PABC": (
            '(VC-PAB OR "Val-Cit PAB" OR "valine-citrulline"'
            ' OR "cathepsin B cleavable")'
        ),
        # Standalone PABC — only fires when no specific prefix matched above
        "PABC": (
            '(PAB OR "p-aminobenzyl" OR "p-aminobenzyloxycarbonyl"'
            ' OR "self-immolative linker")'
        ),
        "SMCC": '(SMCC OR "succinimidyl 4-(N-maleimidomethyl)cyclohexane")',
    }

    def __init__(self, timeout: int = 15):
        """
        Args:
            timeout: HTTP 请求超时秒数
        """
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "ADC-Linker-Agent/1.0 "
                "(Academic Research Tool; mailto:student@example.com)"
            ),
        })
        self._last_request_time = 0.0
        self._min_interval = 0.5  # 每秒最多 2 请求，避免触发限流

    @classmethod
    def _expand_query(cls, query: str) -> str:
        """
        预处理查询：展开 ADC 化学缩写，使 Europe PMC 能匹配到文献。

        Europe PMC 对连字符化学术语（如 Val-Cit-PABC）索引不佳，
        需要替换为论文中实际使用的同义词变体（OR 逻辑）。

        按模式长度降序替换，确保 MC-VC-PABC 等长模式优先匹配，
        避免短模式（如 PABC）在长模式展开后造成二次替换。

        展开文本已自带括号，无需额外包裹。

        示例:
            "Val-Cit-PABC ADC linker" →
            '(Val-Cit-PAB OR "valine-citrulline PAB" OR ...) ADC linker'

        Args:
            query: 原始查询字符串

        Returns:
            展开后的查询字符串（如无匹配则返回原串）
        """
        expanded = query
        sorted_items = sorted(
            cls._ADC_SYNONYMS.items(), key=lambda x: -len(x[0])
        )
        for pattern, replacement in sorted_items:
            if pattern in expanded:
                expanded = expanded.replace(pattern, replacement)
        return expanded

    def search(
        self,
        query: str,
        max_results: int = 10,
        page_size: int | None = None,
        sort: str = "RELEVANCE",
    ) -> list[PaperResult]:
        """
        搜索科学文献。

        查询自动预处理：ADC 化学缩写（如 Val-Cit-PABC）会被展开为
        Europe PMC 兼容的同义词变体（OR 逻辑）。

        Args:
            query: 搜索关键词（支持 Europe PMC 查询语法，如字段前缀 TITLE:, ABSTRACT:）
            max_results: 最大返回论文数 (1-100)
            page_size: 每页结果数（默认与 max_results 一致，上限 1000）
            sort: 排序方式 RELEVANCE（默认）/ CITED desc / DATE desc

        Returns:
            PaperResult 列表，按相关性排序。API 失败返回空列表。

        Example:
            >>> engine = LiteratureSearchEngine()
            >>> papers = engine.search("ADC linker pH-sensitive")
            >>> for p in papers:
            ...     print(p.title)
        """
        # ─── 查询预处理：展开化学缩写 ───
        query = self._expand_query(query)

        if page_size is None:
            page_size = min(max_results, 100)

        params: dict[str, Any] = {
            "query": query,
            "resultType": "core",  # 完整元数据含摘要
            "format": "json",
            "pageSize": min(page_size, 1000),
            "sort": sort,
        }

        papers: list[PaperResult] = []

        url = f"{EUROPE_PMC_BASE}/search"
        max_retries = 2

        for attempt in range(max_retries + 1):
            try:
                # 速率限制（重试时额外等待）
                self._rate_limit()
                if attempt > 0:
                    time.sleep(2 * attempt)  # 指数退避

                logger.debug("Europe PMC search (attempt %d): %s", attempt + 1, query[:100])

                response = self._session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()

                # 检测限流响应（只有 version 字段，无 resultList）
                if "resultList" not in data and "hitCount" not in data:
                    if attempt < max_retries:
                        delay = 3 * (attempt + 1)
                        logger.warning(
                            "Europe PMC rate limited, retrying in %ds...", delay
                        )
                        time.sleep(delay)
                        continue
                    logger.warning(
                        "Europe PMC empty response after %d retries", max_retries
                    )
                    return papers

                results = data.get("resultList", {}).get("result", [])
                total_hits = data.get("hitCount", 0)
                logger.info(
                    "Europe PMC: %d total hits, %d returned for query: %s",
                    total_hits, len(results), query[:80],
                )

                for item in results:
                    paper = self._parse_result(item)
                    if paper:
                        papers.append(paper)
                        if len(papers) >= max_results:
                            break

                # 成功获取结果后跳出重试循环
                break

            except requests.exceptions.Timeout:
                logger.warning("Europe PMC 请求超时 (%ds)", self.timeout)
                if attempt < max_retries:
                    continue
            except requests.exceptions.ConnectionError as e:
                logger.warning("Europe PMC 连接失败: %s", e)
                if attempt < max_retries:
                    continue
            except requests.exceptions.RequestException as e:
                logger.warning("Europe PMC 请求错误: %s", e)
                if attempt < max_retries:
                    continue
            except Exception:
                logger.exception("Europe PMC 解析异常")
                if attempt < max_retries:
                    continue
            break  # 异常且无更多重试 → 跳出

        return papers

    def search_verified(
        self,
        claim: str,
        context: str = "ADC linker",
        max_results: int = 5,
    ) -> list[PaperResult]:
        """
        搜索与某个声明相关的验证文献。

        这是一个便捷方法，自动构建包含声明关键词的搜索查询。

        Args:
            claim: 需要验证的科学声明（英文）
            context: 背景关键词（如 "ADC linker" "antibody-drug conjugate"）
            max_results: 最大返回数

        Returns:
            相关论文列表

        Example:
            >>> papers = engine.search_verified(
            ...     "carbamate linker stable at pH 7.4",
            ...     context="ADC linker",
            ... )
        """
        # 构建查询：取 claim 和 context 的关键词组合
        # 避免查询过长导致零结果
        keywords = claim.strip().rstrip(".")
        query = f'({context}) AND ({keywords})'
        return self.search(query, max_results=max_results)

    def get_by_doi(self, doi: str) -> PaperResult | None:
        """
        通过 DOI 获取单篇论文元数据。

        Args:
            doi: 论文 DOI

        Returns:
            PaperResult 或 None（如未找到）
        """
        try:
            self._rate_limit()
            url = f"{EUROPE_PMC_BASE}/search"
            params = {
                "query": f'DOI:"{doi}"',
                "resultType": "core",
                "format": "json",
                "pageSize": 1,
            }
            response = self._session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            results = data.get("resultList", {}).get("result", [])
            if results:
                return self._parse_result(results[0])
        except Exception:
            logger.warning("Failed to fetch DOI: %s", doi)

        return None

    @staticmethod
    def search_query_builder(
        keywords: list[str] | None = None,
        title_terms: list[str] | None = None,
        abstract_terms: list[str] | None = None,
        author: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        open_access: bool = False,
    ) -> str:
        """
        构建结构化 Europe PMC 查询。

        支持 Europe PMC 字段前缀语法:
          - TITLE: 标题搜索
          - ABSTRACT: 摘要搜索
          - AUTH: 作者搜索
          - FIRST_PDATE: 首次发布日期范围
          - (OPEN_ACCESS:y) 仅开放获取

        Args:
            keywords: 全字段关键词
            title_terms: 标题限定词
            abstract_terms: 摘要限定词
            author: 作者名
            year_from: 起始年份
            year_to: 截止年份
            open_access: 仅返回 OA 论文

        Returns:
            Europe PMC 查询字符串

        Example:
            >>> q = LiteratureSearchEngine.search_query_builder(
            ...     title_terms=["ADC", "linker"],
            ...     abstract_terms=["pH", "cleavable"],
            ...     open_access=True,
            ... )
            >>> # → 'TITLE:ADC AND TITLE:linker AND ABSTRACT:pH ...'
        """
        parts: list[str] = []

        if title_terms:
            parts.extend(f'TITLE:"{t}"' for t in title_terms)
        if abstract_terms:
            parts.extend(f'ABSTRACT:"{t}"' for t in abstract_terms)
        if author:
            parts.append(f'AUTH:"{author}"')
        if keywords:
            parts.extend(keywords)

        if not parts:
            return ""

        query = " AND ".join(parts)

        if year_from and year_to:
            query += f" AND FIRST_PDATE:[{year_from}-01-01 TO {year_to}-12-31]"
        elif year_from:
            query += f" AND FIRST_PDATE:[{year_from}-01-01 TO 3000-12-31]"
        elif year_to:
            query += f" AND FIRST_PDATE:[0000-01-01 TO {year_to}-12-31]"

        if open_access:
            query += " AND (OPEN_ACCESS:y)"

        return query

    # ─── Private ───

    def _rate_limit(self) -> None:
        """简单的速率限制，避免过度请求"""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()

    @staticmethod
    def _parse_result(item: dict) -> PaperResult | None:
        """解析 Europe PMC API 返回的单条结果为 PaperResult"""
        try:
            # 提取摘要（可能分段）
            abstract = ""
            if "abstractText" in item:
                abstract = str(item["abstractText"])[:1000]

            # 提取期刊信息
            journal_info = item.get("journalInfo", {}) or {}
            journal_title = item.get("journalTitle", "")
            if not journal_title and journal_info:
                journal_title = journal_info.get("journal", {}).get("title", "")

            year = None
            if journal_info:
                year = journal_info.get("yearOfPublication")
            if not year:
                year_str = item.get("pubYear")
                if year_str:
                    with contextlib.suppress(ValueError, TypeError):
                        year = int(year_str)

            return PaperResult(
                title=str(item.get("title", "Unknown Title")),
                authors=str(item.get("authorString", "")),
                year=year,
                journal=str(journal_title),
                abstract=abstract,
                doi=str(item.get("doi", "")),
                pmid=str(item.get("pmid", "")),
                pmcid=str(item.get("pmcid", "")),
                citation_count=int(item.get("citedByCount", 0)),
                source=str(item.get("source", "MED")),
            )
        except Exception:
            logger.exception("Failed to parse Europe PMC result")
            return None


# ─── 便捷函数 ───


def quick_search(query: str, max_results: int = 5) -> list[PaperResult]:
    """快速搜索：一行代码搜文献"""
    engine = LiteratureSearchEngine()
    return engine.search(query, max_results=max_results)


def quick_citation(doi: str) -> str | None:
    """快速获取单篇论文的引用格式"""
    engine = LiteratureSearchEngine()
    paper = engine.get_by_doi(doi)
    if paper:
        return paper.format_citation()
    return None
