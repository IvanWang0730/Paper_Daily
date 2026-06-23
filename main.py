import os
import datetime
import urllib.request
import xml.etree.ElementTree as ET
import requests
import time

# PDF 文本提取
try:
    from PyPDF2 import PdfReader
    HAS_PDF = True
except ImportError:
    HAS_PDF = False
    print("⚠️ PyPDF2 未安装。请运行: pip install PyPDF2")

# 从环境变量获取密钥
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
LLM_API_KEY = os.environ.get("LLM_API_KEY")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

# os.environ["http_proxy"] = "http://127.0.0.1:18081"
# os.environ["https_proxy"] = "https://127.0.0.1:18081"

# 2. 计算昨天的日期字符串 (arXiv 的格式通常是 YYYY-MM-DDThh:mm:ssZ)
# 我们只需要匹配 YYYY-MM-DD
yesterday_str = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

save_dir="arxiv_papers/{}".format(yesterday_str)
if not os.path.exists(save_dir):
    os.makedirs(save_dir)
    print(f"📁 已创建保存目录: {save_dir}")

def fetch_arxiv_recsys():
    """从 arXiv 抓取昨天发布的推荐系统、广告算法相关论文"""

    # 1. 扩充关键词 (包含推荐、点击率、广告、匹配等)
    # ti: 标题，abs: 摘要
    keywords = [
        "recommend",
        "recommendation",
        "recommender",
        "click-through",
        "ctr",
        "cvr",
        "advertising",
        "ad-click",
        "matching",
        "ranking",
        "re-ranking",
        "retrieval"
    ]

    # 构建查询语句：(ti:A OR ti:B...) OR (abs:A OR abs:B...)
    ti_queries = "+OR+".join([f"ti:{kw}" for kw in keywords])
    abs_queries = "+OR+".join([f"abs:{kw}" for kw in keywords])
    query = f"cat:cs.IR+AND+({ti_queries}+OR+{abs_queries})"

    # 为了确保能捞到昨天的所有论文，适当放大 max_results（比如取最近的 50 篇再做日期过滤）
    url = f"http://export.arxiv.org/api/query?search_query={query}&max_results=50&sortBy=submittedDate&sortOrder=descending"

    try:
        response = urllib.request.urlopen(url)
        xml_data = response.read()
        root = ET.fromstring(xml_data)

        papers = []
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

        for entry in root.findall("atom:entry", ns):
            # 获取论文发布时间
            published_time = entry.find("atom:published", ns).text.strip()

            # 过滤：只保留昨天发布的论文
            if not published_time.startswith(yesterday_str):
                continue

            title = (entry.find("atom:title", ns).text.strip().replace("\n", " "))
            summary = (entry.find("atom:summary", ns).text.strip().replace("\n", " "))
            link = entry.find("atom:link", ns).attrib["href"]

            # 4. 核心修改：解析作者与机构信息
            authors_list = []
            for author_node in entry.findall("atom:author", ns):
                # 获取作者姓名
                name_node = author_node.find("atom:name", ns)
                author_name = (name_node.text.strip() if name_node is not None else "Unknown")

                # 获取机构名称 (arxiv:affiliation)
                aff_node = author_node.find("arxiv:affiliation", ns)
                affiliation = (aff_node.text.strip() if aff_node is not None else "N/A")

                authors_list.append({"name": author_name, "affiliation": affiliation})

                # --- 核心修改：解析 PDF 专用链接 ---
                pdf_url = None
                for link_node in entry.findall("atom:link", ns):
                    if link_node.attrib.get("title") == "pdf":
                        pdf_url = link_node.attrib["href"]
                        # arXiv API 给的链接有时不带后缀，加上 .pdf 让本地阅读器更好识别
                        if not pdf_url.endswith(".pdf"):
                            pdf_url += ".pdf"
                        break

                # 如果没找到特定的 pdf 标签，尝试把默认网页链接的 /abs/ 替换为 /pdf/
                if not pdf_url:
                    main_link = entry.find("atom:link", ns).attrib["href"]
                    pdf_url = main_link.replace("/abs/", "/pdf/") + ".pdf"

            papers.append(
                {
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "published": published_time,
                    "authors": authors_list,  # 包含姓名和机构的列表
                    "pdf_url": pdf_url
                }
            )

        # --- 核心修改 2：开始执行下载任务 ---
        print(f"🎯 筛选完毕，共找到 {len(papers)} 篇昨天发布的论文。准备下载：")
        print("-" * 50)

        for idx, paper in enumerate(papers, 1):
            title = paper["title"]
            pdf_url = paper["pdf_url"]

            # 清理标题中的特殊字符，防止 Windows/Mac 创建文件失败
            safe_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c == ' ']).rstrip()
            # 限制文件名长度，避免超长报错
            safe_title = safe_title[:100]
            filepath = os.path.join(save_dir, f"{safe_title}.pdf")

            print(f"[{idx}/{len(papers)}] 正在下载: {title[:50]}...")

            try:
                # 请求 PDF 文件流并写入本地
                pdf_req = urllib.request.Request(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(pdf_req) as pdf_response, open(filepath, 'wb') as out_file:
                    out_file.write(pdf_response.read())

                print(f"   ✅ 成功保存至: {filepath}")

            except Exception as e:
                print(f"   ❌ 下载失败: {e}")

            # ⚠️ 防封禁护城河：每下载完一篇强制休息 3 秒
            if idx < len(papers):
                time.sleep(3)

            print("\n🎉 所有任务执行完毕！")

        return papers

    except Exception as e:
        print(f"Fetch arXiv failed: {e}")
        return []


def extract_pdf_text(filepath, max_chars=10000):
    """从 PDF 文件中提取文本内容，用于发送给 LLM"""
    if not HAS_PDF:
        return None
    try:
        reader = PdfReader(filepath)
        text_parts = []
        total = 0
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
                total += len(page_text)
                if total >= max_chars:
                    break
        text = "\n".join(text_parts)
        return text[:max_chars]
    except Exception as e:
        print(f"   ⚠️ 提取 PDF 文本失败 {filepath}: {e}")
        return None


def llm_summarize(papers):
    """调用大模型生成中文日报总结，结合论文 PDF 全文内容"""
    if not papers:
        return "今日无更新或抓取失败。"

    # 拼接 Prompt
    prompt = """
    # Role: 资深 AI 与推荐系统前沿研究员 / 科技媒体主编

    ## Objective:
    仔细阅读我提供的多篇论文文本或核心摘要，洞察这些研究的共同趋势，提炼核心创新点，并**严格**按照给定的 Markdown 模板生成一份高质量的「每日论文日报」。

    ## Rules & Requirements:
    1. **深度洞察 (Section 1)**：不要简单堆砌摘要。你需要对比这些论文，找出底层的技术共性或范式转移（如：机制设计的转变、大模型角色的演进等），提炼出 1-2 个核心趋势，并输出"💡 核心转向"或"🛠️ 工业启示"。
    2. **高度概括 (Section 2)**：提炼每篇论文的一句话核心贡献，保持精炼，突出机构、方法与核心结果。
    3. **结构解析 (Section 3)**：
       - 提取原文链接（如果没有则标注为"待定"）、来源机构类别（学术界/工业界/产学合作）。
       - 给出推荐指数（1-5星）和"一句话推荐"。
       - **重点**：请务必尝试用 **ASCII 字符画 (Text Art)** 或简明的文本流程图（放在代码块 ` ``` ` 中）来直观展示该论文的核心架构、对比关系或因果逻辑。
       - 论文摘要需分点叙述，加粗核心专有名词与核心数据指标，忌大段平铺直叙。
    4. **语气与排版**：客观、专业、极具极客感。严格保留模板中的所有 Emoji、分级标题（`##`, `###`）、加粗（`**`）以及引用块（`>`）。

    ---

    ## 📥 输入文本（含论文 PDF 全文与元数据）：

    """

    # 拼接每篇论文的摘要 + PDF 全文
    for i, p in enumerate(papers):
        prompt += f"\n{'='*60}\n"
        prompt += f"### 论文 [{i + 1}/{len(papers)}]\n"
        prompt += f"**标题**: {p['title']}\n"
        prompt += f"**链接**: {p['link']}\n"
        prompt += f"**摘要**: {p['summary']}\n"

        # 尝试读取已下载的 PDF 文件并提取文本
        safe_title = "".join([c for c in p['title'] if c.isalpha() or c.isdigit() or c == ' ']).rstrip()[:100]
        filepath = os.path.join(save_dir, f"{safe_title}.pdf")

        if os.path.exists(filepath):
            pdf_text = extract_pdf_text(filepath)
            if pdf_text:
                print(f"   📄 已提取 PDF 文本: {safe_title[:50]}... ({len(pdf_text)} 字符)")
                prompt += f"\n**📄 PDF 全文内容** (前 {len(pdf_text)} 字符):\n{pdf_text}\n"
            else:
                print(f"   ⚠️ 无法提取 PDF 文本: {safe_title[:50]}...，将仅使用摘要")
        else:
            print(f"   ⚠️ PDF 文件不存在: {filepath}")

        prompt += "\n"

    prompt += f"\n{'='*60}\n"
    prompt += """

    ---

    ## 📤 严格遵循的输出模板：

    ## 📊 Section 1: Trend Analysis | 趋势分析

    ### [🔥 趋势主题的精炼概括，例如：LLM 语义先验深度赋能推荐]

    [一段关于该趋势的背景引入说明。]

    - **[论文A简称]** [说明其如何体现该趋势]。
    - **[论文B简称]** [说明其如何体现该趋势]。

    > **💡 [核心转向/工业启示/宏观洞察]**：[一段具有高度总结性和启发性的结论]。

    （如果有第二个趋势，可继续添加 `### [趋势主题]`，否则跳过）

    ---

    ## 📋 Section 2: 今日速览 | Overview

    - **[[机构名称] 等] [论文简称]**
    [一句话提炼核心方法、发现与收益，保持在 80 字以内]。
    - **[[机构名称] 等] [论文简称]**
    [一句话提炼核心方法、发现与收益，保持在 80 字以内]。

    ---

    ## 📰 Section 3: Daily Digest | 论文精读

    ### 1. [论文全名]

    - **🔗 原文链接**: [arXiv链接或DOI]
    - **🏷️ 来源机构**: [🎓 学术界 / 🏭 工业界 / 🤝 产学合作] | [主要机构名称] 等
    - **⭐ 推荐指数**: [如：⭐⭐⭐⭐ (4/5)]
    - **🎯 一句话推荐**: [精炼提炼卖点]
    """

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system",
             "content": "你是一个严谨的 AI 论文助手，直接输出总结内容，不要带'好的，这是为您生成的日报'等客套话。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3
    }

    print(f"\n🤖 正在调用 LLM ({LLM_MODEL}) 生成日报...")
    print(f"   Prompt 总长度: {len(prompt)} 字符")

    try:
        res = requests.post(f"{LLM_BASE_URL}/chat/completions", json=payload, headers=headers)
        if res.status_code == 200:
            content = res.json()['choices'][0]['message']['content']
            print(f"   ✅ LLM 返回内容长度: {len(content)} 字符")
            return content
        else:
            print(f"   ❌ LLM API 返回错误状态码 {res.status_code}: {res.text}")
            return f"AI 总结生成失败 (HTTP {res.status_code})。"
    except Exception as e:
        print(f"   ❌ LLM API 调用异常: {e}")
        return "AI 总结生成失败。"


def write_to_notion(content):
    """将结果写入 NotionNext 兼容的 Database"""
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2026-03-11",
        "Content-Type": "application/json"
    }

    today_str = datetime.date.today().isoformat()
    title_text = f"RecSys Daily Digest | 推荐系统前沿论文速递{datetime.date.today().strftime('%Y%m%d')}"
    slug_text = f"recsys{datetime.date.today().strftime('%Y%m%d')}"

    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "title": {"title": [{"text": {"content": title_text}}]},
            "slug": {"rich_text": [{"text": {"content": slug_text}}]},
            "order": {"rich_text": [{"text": {"content": slug_text}}]},
            "type": {"select": {"name": "Post"}},
            "status": {"select": {"name": "Published"}},
            "category": {"select": {"name": "推荐日报"}},
            "date": {"date": {"start": today_str}},
            "summary": {"rich_text": [{"text": {"content": content[:100] + "..."}}]},  # 列表页摘要
            "tags": {"multi_select": [{"name": "推荐"}, {"name": "日报"}]}
        },
        "markdown": content  
    }

    res = requests.post(url, json=payload, headers=headers)
    if res.status_code == 200:
        print("Successfully written to NotionNext!")
    else:
        print(f"Failed to write to Notion: {res.text}")


if __name__ == "__main__":
    print("Starting Daily ArXiv Workflow...")
    paper_list = fetch_arxiv_recsys()
    print(f"Fetched {len(paper_list)} papers.")
    print(paper_list)
    if paper_list:
        summary_result = llm_summarize(paper_list)

        # 保存日报到 daily_report/ 目录，以日期命名
        report_dir = "daily_reports"
        if not os.path.exists(report_dir):
            os.makedirs(report_dir)
            print(f"📁 已创建日报目录: {report_dir}")

        today_str = datetime.date.today().isoformat()
        report_path = os.path.join(report_dir, f"{today_str}.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(summary_result)
        print(f"📝 日报已保存至: {report_path}")

        write_to_notion(summary_result)
