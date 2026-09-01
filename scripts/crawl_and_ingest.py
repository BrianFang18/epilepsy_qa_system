"""
癫痫知识库构建脚本
====================
爬取三大权威来源的内容，并自动入库到本项目知识库：
  1. PubMed   — 通过 NCBI Entrez API 抓取癫痫相关论著摘要（≥300篇）
  2. Cochrane — 抓取癫痫系统评价全文（≥50篇）
  3. Epilepsy Foundation — 抓取临床指南/患者教育内容（≥200篇）

依赖安装：
  pip install requests beautifulsoup4 biopython tqdm

用法：
  # ① 爬取 + 入库（一次性）
  python scripts/crawl_and_ingest.py --mode all

  # ② 仅爬取，保存到本地 JSON（不调用 API）
  python scripts/crawl_and_ingest.py --mode crawl --output data/crawled_epilepsy.json

  # ③ 仅入库（已有 crawled JSON）
  python scripts/crawl_and_ingest.py --mode ingest --input data/crawled_epilepsy.json

  # ④ 只爬 PubMed
  python scripts/crawl_and_ingest.py --mode crawl --sources pubmed --output data/pubmed_epilepsy.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# NCBI Entrez 必填邮箱（换成你的真实邮箱）
EMAIL = os.environ.get("NCBI_EMAIL", "brianfang0118@gmail.com")

# 爬虫速率限制（秒），避免触发反爬
DELAY_PUBMED   = 0.4   # Entrez 限制 ≤ 10 req/s，建议 ≥ 0.34
DELAY_COHARANE = 1.0
DELAY_EPILEPSY = 0.5

# 目标数量（实际受接口返回量限制，可能略少）
TARGET_PUBMED   = 300
TARGET_COHARANE = 50
TARGET_EPILEPSY = 200

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✓ 已保存 → {path}  ({len(data) if isinstance(data, list) else 'object'})")


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="癫痫知识库爬取 + 入库脚本")
    parser.add_argument("--mode",   choices=["crawl", "ingest", "all"], default="all")
    parser.add_argument("--sources", nargs="+",
                        choices=["pubmed", "cochrane", "epilepsy_foundation"],
                        default=["pubmed", "cochrane", "epilepsy_foundation"])
    parser.add_argument("--input",  type=Path, default=None,
                        help="ingest 模式时读取的 crawled JSON 路径")
    parser.add_argument("--output", type=Path, default=None,
                        help="crawl 模式时保存的 JSON 路径")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# ① PubMed 爬虫（NCBI Entrez API）
# ---------------------------------------------------------------------------

def _entrez_search(query: str, db: str = "pubmed", max_results: int = 300,
                   retstart: int = 0) -> list[str]:
    """调用 NCBI Entrez search，返回 PMIDs 列表。"""
    try:
        from Bio import Entrez
        Entrez.email = EMAIL
    except ImportError:
        print("  ✗ 需要安装 biopython: pip install biopython")
        raise

    handle = Entrez.esearch(
        db=db,
        term=query,
        retmax=min(max_results, 10000),
        retstart=retstart,
        sort="relevance",
    )
    result = Entrez.read(handle)
    handle.close()
    return list(result.get("IdList", []))


def _entrez_fetch(pmids: list[str]) -> list[dict[str, Any]]:
    """批量获取 PubMed 文章详情（标题/摘要/作者/期刊/年份/类型）。"""
    if not pmids:
        return []

    from Bio import Entrez
    Entrez.email = EMAIL

    results: list[dict[str, Any]] = []
    # Entrez EPost 每次最多 10k ID，分批获取
    batch_size = 200
    for i in range(0, len(pmids), batch_size):
        batch = pmids[i:i + batch_size]
        handle = Entrez.efetch(db="pubmed", id=batch, rettype="medline", retmode="text")
        from Bio import Medline
        records = Medline.parse(handle)
        for rec in records:
            abstract = rec.get("AB", "")
            title    = rec.get("TI", "")
            if not title:
                continue
            # 过滤太短的摘要（可能是纯标题记录）
            if len(abstract) < 50:
                abstract = ""
            results.append({
                "source":    "PubMed",
                "pmid":      rec.get("PMID", ""),
                "title":     title,
                "abstract":  abstract,
                "authors":   rec.get("FAU", rec.get("AU", []))[:10],
                "journal":   rec.get("JT", rec.get("TA", "")),
                "year":      rec.get("DP", "")[:4],
                "doi":       rec.get("AID", [""])[0].replace(" [doi]", ""),
                "keywords":  rec.get("OT", []),
                "pub_type":  rec.get("PT", []),
            })
        handle.close()
        time.sleep(DELAY_PUBMED)
    return results


def crawl_pubmed(max_results: int = TARGET_PUBMED) -> list[dict[str, Any]]:
    """
    爬取 PubMed 癫痫相关论文摘要。
    使用多个检索词覆盖不同子领域：
      - 临床指南、药物治疗、外科手术、EEG/影像、儿童癫痫、妊娠管理等
    """
    print("\n[1/3] 正在爬取 PubMed（NCBI Entrez API）...")

    queries = {
        "epilepsy_drugs":         "epilepsy anti-seizure medication treatment",
        "epilepsy_surgery":       "epilepsy surgery resection outcome",
        "epilepsy_eeg":           "epilepsy EEG diagnosis classification",
        "epilepsy_status":        "status epilepticus management treatment",
        "epilepsy_pregnancy":     "epilepsy pregnancy teratogenicity anti-seizure",
        "epilepsy_children":      "pediatric epilepsy children treatment",
        "epilepsy_psychiatric":   "epilepsy psychiatric comorbidity depression anxiety",
        "epilepsy_emergency":     "epilepsy emergency seizure first-aid",
        "epilepsy_prognosis":     "epilepsy prognosis seizure recurrence",
        "epilepsy_guidelines":    "ILAE epilepsy guideline recommendation",
    }

    all_pmis: set[str] = set()
    for label, q in queries.items():
        count_before = len(all_pmis)
        try:
            pmids = _entrez_search(q, max_results=max_results)
            all_pmis.update(pmids)
            added = len(all_pmis) - count_before
            print(f"  [{label}] 检索 \"{q}\" → 新增 {added} 篇（累计 {len(all_pmis)} 篇）")
        except Exception as e:
            print(f"  ✗ [{label}] 失败: {e}")
        time.sleep(DELAY_PUBMED)

    if not all_pmis:
        print("  ✗ 未获取到任何 PubMed ID")
        return []

    # 按相关性排序（已按检索顺序），取目标数量
    pmi_list = list(all_pmis)[:max_results]
    print(f"\n  正在获取 {len(pmi_list)} 篇文献详情...")
    articles = _entrez_fetch(pmi_list)
    print(f"  ✓ 成功获取 {len(articles)} 篇 PubMed 文献")
    return articles


# ---------------------------------------------------------------------------
# ② Cochrane 系统评价爬虫
# ---------------------------------------------------------------------------

def _cochrane_search_url(query: str, page: int = 1) -> str:
    """生成 Cochrane 搜索结果页 URL。"""
    q_encoded = query.replace(" ", "+")
    return (
        f"https://www.cochranelibrary.com/search?searchBy=6"
        f"&searchText={q_encoded}"
        f"&page={page}"
        f"&displayCount=50"
    )


def crawl_cochrane(max_results: int = TARGET_COHARANE) -> list[dict[str, Any]]:
    """
    爬取 Cochrane Library 癫痫相关系统评价全文摘要。
    Cochrane 页面为动态渲染，我们通过搜索结果列表页抓取标题/摘要/CD号。
    """
    import requests
    from bs4 import BeautifulSoup

    print("\n[2/3] 正在爬取 Cochrane 系统评价...")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    results: list[dict[str, Any]] = []
    queries = [
        "epilepsy",
        "anti-epileptic drugs",
        "status epilepticus",
        "seizure",
    ]

    seen_ids: set[str] = set()

    for query in queries:
        if len(results) >= max_results:
            break
        for page in range(1, 5):  # 最多翻4页
            if len(results) >= max_results:
                break
            try:
                url = _cochrane_search_url(query, page)
                resp = requests.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
            except Exception as e:
                print(f"  ✗ Cochrane [{query}] page {page} 失败: {e}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("article.search-result, .search-results .result-item")

            if not cards:
                # 备选：尝试结构更宽泛的选择器
                cards = soup.select(".article-meta, [data-testid='search-result']")

            if not cards:
                # 最后一页或无结果，退出
                break

            for card in cards:
                if len(results) >= max_results:
                    break
                title_el = (
                    card.select_one("h2 a, h3 a, .result-title a, a.result-title")
                    or card.select_one("h2, h3, .title")
                )
                abstract_el = card.select_one(
                    "p.abstract, .abstract, .result-excerpt, [class*='abstract']"
                )
                link_el = (
                    card.select_one("a[href*='/cd/'], a[href*='doi']")
                    or card.select_one("h2 a, h3 a")
                )
                date_el = card.select_one(
                    "time, .date, [class*='date'], .published-date"
                )

                title = title_el.get_text(strip=True) if title_el else ""
                if not title or len(title) < 10:
                    continue

                link = ""
                if link_el and link_el.get("href"):
                    href = link_el["href"]
                    link = href if href.startswith("http") else f"https://www.cochranelibrary.com{href}"

                abstract = abstract_el.get_text(strip=True) if abstract_el else ""

                # 用链接或标题去重
                doc_id = link.split("/")[-1][:60] if link else title[:60]
                if doc_id in seen_ids:
                    continue
                seen_ids.add(doc_id)

                results.append({
                    "source":   "Cochrane",
                    "doc_id":   doc_id,
                    "title":    title,
                    "abstract": abstract,
                    "url":      link,
                    "year":     (date_el.get_text(strip=True)[-4:] if date_el else ""),
                })

            print(f"  [{query}] page {page}: +{len(cards)} 条（累计 {len(results)} 条）")
            time.sleep(DELAY_COHARANE)

    print(f"  ✓ 成功获取 {len(results)} 篇 Cochrane 系统评价")
    return results


# ---------------------------------------------------------------------------
# ③ Epilepsy Foundation（epilepsy.com）爬虫
# ---------------------------------------------------------------------------

def _build_epilepsy_com_search_url(query: str, page: int = 1) -> str:
    """epilepsy.com 搜索 URL。"""
    q_encoded = query.replace(" ", "+")
    return (
        f"https://www.epilepsy.com/search?keys={q_encoded}"
        f"&page={page}"
    )


def crawl_epilepsy_foundation(max_results: int = TARGET_EPILEPSY) -> list[dict[str, Any]]:
    """
    爬取 epilepsy.com 的临床指南/患者教育内容。
    按主题分类爬取，覆盖：诊断、药物、手术、急诊、生活方式等。
    """
    import requests
    from bs4 import BeautifulSoup

    print("\n[3/3] 正在爬取 Epilepsy Foundation (epilepsy.com)...")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    # 覆盖不同主题的 URL（epilepsy.com 分类页）
    topic_urls = [
        ("diagnosis",        "https://www.epilepsy.com/diagnosis"),
        ("treatment",        "https://www.epilepsy.com/treatment"),
        ("medication",       "https://www.epilepsy.com/medication"),
        ("surgery",          "https://www.epilepsy.com/surgery"),
        ("emergencies",      "https://www.epilepsy.com/living-epilepsy/seizure-first-aid-and-safety"),
        ("children",         "https://www.epilepsy.com/learn/living-epilepsy-and-seizures"),
        ("women",            "https://www.epilepsy.com/learn/women-and-epilepsy"),
        ("triggers",         "https://www.epilepsy.com/triggers"),
        ("prognosis",        "https://www.epilepsy.com/prognosis"),
        ("safety",           "https://www.epilepsy.com/living-epilepsy/safety"),
        ("sudep",            "https://www.epilepsy.com/learn/sudep"),
        ("genetics",         "https://www.epilepsy.com/genetic-epilepsy"),
    ]

    for topic, base_url in topic_urls:
        if len(results) >= max_results:
            break
        topic_results: list[dict[str, Any]] = []
        for page_num in range(1, 6):  # 每主题最多5页
            if len(results) + len(topic_results) >= max_results:
                break
            url = f"{base_url}?page={page_num}" if page_num > 1 else base_url
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
            except Exception as e:
                print(f"  ✗ [{topic}] page {page_num} 失败: {e}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")

            # 提取正文段落（主要内容区）
            article_containers = soup.select(
                "article, .node-article, [class*='article'], main, .content-area"
            )
            if not article_containers:
                continue

            for container in article_containers:
                if len(results) + len(topic_results) >= max_results:
                    break

                # 标题
                title_el = (
                    container.select_one("h1, h2.page-title, [class*='title']")
                    or soup.select_one("h1")
                )
                title = title_el.get_text(strip=True) if title_el else ""

                # 正文（合并所有 <p>）
                para_els = container.select("p")
                paragraphs = [p.get_text(strip=True) for p in para_els if p.get_text(strip=True)]
                body = "\n".join(paragraphs)

                # 过滤掉太短或太像导航菜单的内容
                if len(body) < 150 or title in body[:100]:
                    # 尝试直接从 soup 取
                    title_el = soup.select_one("h1")
                    title = title_el.get_text(strip=True) if title_el else ""
                    body = "\n".join(paragraphs)

                if len(body) < 100 or not title:
                    continue

                doc_id = f"ef_{topic}_{len(results) + len(topic_results)}"
                if doc_id in seen_ids:
                    continue
                seen_ids.add(doc_id)

                topic_results.append({
                    "source":   "Epilepsy Foundation",
                    "doc_id":   doc_id,
                    "topic":    topic,
                    "title":    title,
                    "body":     body[:8000],  # 截断超长内容
                    "url":      url,
                })

            print(
                f"  [{topic}] page {page_num}: "
                f"+{len(topic_results)} 条（累计 {len(results) + len(topic_results)} 条）"
            )
            time.sleep(DELAY_EPILEPSY)

        results.extend(topic_results)

    print(f"  ✓ 成功获取 {len(results)} 篇 Epilepsy Foundation 内容")
    return results


# ---------------------------------------------------------------------------
# ④ 内容处理：转换为项目所需格式
# ---------------------------------------------------------------------------

def convert_pubmed_to_ingest(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将 PubMed 文献转换为 IngestTextRequest 格式。"""
    items: list[dict[str, Any]] = []
    for art in articles:
        title    = art.get("title", "").strip()
        abstract = art.get("abstract", "").strip()
        if not title:
            continue

        # 构建文本内容（优先用摘要，否则只用标题）
        if abstract:
            text = f"{title}\n\n摘要：{abstract}"
        else:
            text = title

        # 判断文献类型：review/guideline → literature，其余 → clinical
        pub_types = art.get("pub_type", [])
        is_review = any(
            t.lower() in {"review", "systematic review", "meta-analysis",
                          "practice guideline", "guideline", "consensus development conference"}
            for t in pub_types
        )
        doc_type = "literature" if is_review else "clinical"

        year = art.get("year", "")
        journal = art.get("journal", "")
        pmid    = art.get("pmid", "")
        doi     = art.get("doi", "")

        items.append({
            "doc_id":   f"pubmed_{pmid}" if pmid else f"pubmed_{len(items)}",
            "title":    title,
            "doc_type": doc_type,
            "text":     text,
            "source":   "pubmed",
            "metadata": {
                "pmid":     pmid,
                "doi":      doi,
                "year":     year,
                "journal":  journal,
                "authors":  art.get("authors", []),
                "keywords": art.get("keywords", []),
                "pub_type": pub_types,
            },
        })
    return items


def convert_cochrane_to_ingest(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将 Cochrane 文献转换为 IngestTextRequest 格式。"""
    items: list[dict[str, Any]] = []
    for art in articles:
        title    = art.get("title", "").strip()
        abstract = art.get("abstract", "").strip()
        if not title:
            continue

        text = f"{title}\n\n{abstract}" if abstract else title

        items.append({
            "doc_id":   art.get("doc_id", f"cochrane_{len(items)}"),
            "title":    title,
            "doc_type": "literature",   # Cochrane 全是系统评价
            "text":     text,
            "source":   "cochrane",
            "metadata": {
                "url": art.get("url", ""),
                "year": art.get("year", ""),
            },
        })
    return items


def convert_epilepsy_foundation_to_ingest(
    articles: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """将 Epilepsy Foundation 内容转换为 IngestTextRequest 格式。"""
    items: list[dict[str, Any]] = []
    for art in articles:
        title = art.get("title", "").strip()
        body  = art.get("body", "").strip()
        if not title:
            continue

        # 短内容拼标题，长内容直接用 body
        text = f"{title}\n\n{body}" if len(body) > 100 else (body or title)

        items.append({
            "doc_id":   art.get("doc_id", f"ef_{len(items)}"),
            "title":    title,
            "doc_type": "clinical",    # 临床指南为主
            "text":     text,
            "source":   "epilepsy_foundation",
            "metadata": {
                "topic": art.get("topic", ""),
                "url":   art.get("url", ""),
            },
        })
    return items


# ---------------------------------------------------------------------------
# ⑤ 入库到项目知识库
# ---------------------------------------------------------------------------

def ingest_into_kb(items: list[dict[str, Any]], batch_report: int = 50) -> int:
    """通过 HTTP API 将内容批量入库到 run_server.py 进程。"""
    import requests

    from app.schemas import IngestTextRequest

    base_url = os.environ.get("API_BASE_URL", "http://127.0.0.1:8010")

    # ── 入库前先清库，保证幂等 ────────────────────────────────
    try:
        resp = requests.post(f"{base_url}/v1/ingest/clear", timeout=10)
        resp.raise_for_status()
        print(f"  ✓ 旧数据已清空")
    except Exception as e:
        print(f"  ⚠️  清库失败: {e}")
    # ── ──────────────────────────────────────────────────────

    ingested = 0
    failed = 0

    for i, item in enumerate(items, 1):
        req = IngestTextRequest(
            doc_id=item["doc_id"],
            title=item["title"],
            text=item["text"],
            doc_type=item.get("doc_type", "clinical"),
            source=item.get("source", "crawler"),
            metadata=item.get("metadata", {}),
        )
        try:
            resp = requests.post(
                f"{base_url}/v1/ingest/text",
                json=req.model_dump(mode="json"),
                timeout=30,
            )
            resp.raise_for_status()
            ingested += 1
        except requests.exceptions.ConnectionError:
            print(f"\n!!! 无法连接到 run_server.py (尝试访问 {base_url})")
            print("  → 请先启动 server：python run_server.py")
            print("  → 然后重新运行：python scripts/crawl_and_ingest.py --mode ingest --input data/crawled_epilepsy.json")
            return ingested
        except Exception as e:
            print(f"  ✗ 入库失败 [{item['doc_id']}]: {e}")
            failed += 1

        if i % batch_report == 0:
            print(f"  ... 已入库 {i}/{len(items)}")

    if failed:
        print(f"  注意：有 {failed} 条入库失败")
    return ingested


def merge_and_save(
    pubmed_items: list[dict[str, Any]],
    cochrane_items: list[dict[str, Any]],
    ef_items: list[dict[str, Any]],
    output_path: Path,
) -> list[dict[str, Any]]:
    """合并所有来源，保存到 JSON 并返回。"""
    all_items = pubmed_items + cochrane_items + ef_items
    save_json(all_items, output_path)

    literature_count = sum(1 for i in all_items if i.get("doc_type") == "literature")
    clinical_count   = sum(1 for i in all_items if i.get("doc_type") == "clinical")

    print(f"\n  知识库统计：")
    print(f"    总文档数 : {len(all_items)}")
    print(f"    文献类   : {literature_count} (literature)")
    print(f"    临床类   : {clinical_count} (clinical)")
    print(f"    PubMed   : {len(pubmed_items)}")
    print(f"    Cochrane : {len(cochrane_items)}")
    print(f"    Epilepsy Foundation: {len(ef_items)}")
    return all_items


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    output_path = args.output or ROOT / "data" / "crawled_epilepsy.json"

    all_items: list[dict[str, Any]] = []
    pubmed_items: list[dict[str, Any]] = []
    cochrane_items: list[dict[str, Any]] = []
    ef_items: list[dict[str, Any]] = []

    # ── 爬取阶段 ──
    if args.mode in ("crawl", "all"):
        if "pubmed" in args.sources:
            articles = crawl_pubmed()
            pubmed_items = convert_pubmed_to_ingest(articles)

        if "cochrane" in args.sources:
            articles = crawl_cochrane()
            cochrane_items = convert_cochrane_to_ingest(articles)

        if "epilepsy_foundation" in args.sources:
            articles = crawl_epilepsy_foundation()
            ef_items = convert_epilepsy_foundation_to_ingest(articles)

        all_items = merge_and_save(pubmed_items, cochrane_items, ef_items, output_path)

    # ── 入库阶段 ──
    if args.mode in ("ingest", "all"):
        if args.mode == "ingest" and args.input:
            all_items = load_json(args.input)
            print(f"\n[入库] 从 {args.input} 加载了 {len(all_items)} 条文档")

        if not all_items and args.input:
            all_items = load_json(args.input)

        if all_items:
            print(f"\n[入库] 开始将 {len(all_items)} 条文档写入知识库...")
            print("  注意：确保 run_server.py 已在运行！")
            ingested = ingest_into_kb(all_items)
            print(f"\n  ✓ 成功入库 {ingested} 条文档")
        else:
            print("\n  ✗ 没有可入库的文档（先运行 --mode crawl 或指定 --input）")

    print("\n" + "=" * 60)
    print("完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
