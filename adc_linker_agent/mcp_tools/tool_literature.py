"""
MCP 工具：科学文献搜索

包装 LiteratureSearchEngine 为 MCP 兼容的工具函数。
通过 Europe PMC REST API 搜索 PubMed/Europe PMC 论文。

工具列表:
  - search_literature: 搜索科学文献并返回真实论文元数据
"""

from adc_linker_agent.domain.literature import LiteratureSearchEngine

_engine = LiteratureSearchEngine()


def search_literature(query: str, max_results: int = 5) -> dict:
    """
    Search scientific literature (PubMed/Europe PMC) for ADC-related papers.

    Returns REAL papers with verified titles, authors, journals, DOIs, and abstracts.
    Use this to verify chemical/biological claims against published research,
    find evidence for linker design decisions, or get up-to-date references.

    Args:
        query: Search query in English (PubMed/Europe PMC index English literature).
               Use specific terms like "carbamate linker pH stability ADC".
        max_results: Max papers to return (default 5, max 10).

    Returns:
        dict with 'papers' list (title, authors, year, journal, doi, abstract, url)
        and 'total_found' count. Each paper includes a clickable DOI link.
    """
    try:
        papers = _engine.search(query, max_results=min(max_results, 10))

        return {
            "query": query,
            "total_found": len(papers),
            "papers": [
                {
                    "title": p.title,
                    "authors": p.authors,
                    "year": p.year,
                    "journal": p.journal,
                    "doi": p.doi,
                    "url": p.url,
                    "abstract": p.abstract[:300] if p.abstract else "",
                    "citation_count": p.citation_count,
                    "citation": p.format_citation("brief"),
                }
                for p in papers
            ],
        }
    except Exception as e:
        return {"error": str(e), "query": query, "papers": []}
