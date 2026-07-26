# 每日阅读 \- 设计文档

**日期**：7月23日，2026年

## 总览

每日阅读是一个本地运行程序。它每日定时从用户提供的一系列网站中，收集文章。通过对比和处理，最终每日推送给用户一个阅读名单。

## 结构，任务细分

### 总体工作流

使用 **LangGraph**，每个步骤是一个 `node`。  
\`\`\`  
Collect  
\-\> exact\_deduplicate  
\-\> extract  
\-\> content\_deduplicate  
\-\> filter  
\-\> classify  
\-\> cluster  
\-\> personalize  
\-\> compare  
\-\> select  
\-\> save  
\`\`\`

### 文章预处理

1. 使用cron 定时开启搜索  
2. 使用RSS feed获取新闻网站上的更新内容，得到（标题，总结，全文链接）。保存为articles  
   1. 可能无法获取有些网站的文章全文，需要其他工具辅助 (Trafilatura/ Newspaper 4K /Jina Reader API)  
3. 在db中创建articles row, 包含 `(url, title, RSS summary, source, publication time, run ID, status=discovered)`  
4. 在获得完整文章后，在articles中加入 `(content, author, word count, content hash, language, embedding, status=extracted)`  
5. 标记重复文章，并关联原始文章  
6. 分类，根据喜好 （来自长期记忆）由 llm 选出最终reading list。（新闻：检查是否证据充足）。

### 存储，搜索

1. 使用Postgre SQL \+ pgvector  
   1. Story cluster：用于分类被多个来源报道的同一个主题  
   2. Pgvector用于查找相似内容的文章，主题分类  
2. 太长的文章切分成几部分,完整文章和chunk都保存 (exceed 1500 words)  
   1. `articles.content_text`  
   2. `articles_chunks.chunk_text`  
3. 把文章/chunk转化为vector embedding   
4. 通过搜索vector similarity 找出需要的内容  
5. 给文章/chunk打分  
6. 搜索到的chunk由 LLM 来对比，返回选中文章和原因

### 记忆

1. 事件记录 (feedback events) 存储在Postgre sql   
   1. History record:   
      1. Like / dislike / skip/open /complete  
      2. Star  
   2. And their reason:  
      1. too\_long / too repetitive/ strong evidence / good writing / not interested / too technical   
2. Derived preference features:  
   1. Compute using feedback:  
      1. feature\_type  
      2. feature\_value  
      3. score  
      4. confidence  
      5. positive\_count  
      6. negative\_count  
3. User config:   
   1. Daily reading list: number of articles  
   2. Like topic / block topic  
   3. Content type  
   4. Source list

### Agent

#### Loop

开始 \-\> 读取偏好 \-\> 抓取文章，articles \-\> 分类，转换embedding \-\> 对比，评分 \-\> 得出阅读名单 \-\> 是否足够文章？ \-\> 是，结束  
\-\> 否，查看未使用articles / 抓取更多文章

expansion round:  
round 0: only use config RSS source

round 1: use RSS candidates not processed yet

round 2: use related coverage search

round 3: adjust soft preference and diversity preference, make it less strict

**终止条件**：  
文章数量达到目标  
或，达到循环最大次数，articles用完

**返回内容**：  
使用Pydantic model 或json规定格式

### Evidence Comparison

同一个 story cluster  
→ 每篇文章提取 atomic claims  
→ 保存 claim 对应的原文 excerpt  
→ 对齐相似 claim  
→ 判断 support / contradict / missing  
→ 识别是否引用同一个原始来源  
→ 给每篇文章评分  
→ 选择 representative article

Claims needs:

article\_claims  
\- id  
\- article\_id  
\- cluster\_id  
\- claim\_text  
\- claim\_type  
\- supporting\_excerpt  
\- attribution  
\- primary\_source\_url  
\- confidence

LLM should return structured output in json:  
{  
  "representative\_article\_id": "...",  
  "shared\_claims": \[\],  
  "disputed\_claims": \[\],  
  "unsupported\_claims": \[\],  
  "article\_scores": \[\],  
  "selection\_reason": "...",  
  "confidence": 0.82  
}

article\_chunks  
\- id  
\- article\_id  
\- chunk\_index  
\- heading  
\- chunk\_text  
\- token\_count  
\- character\_start  
\- character\_end  
\- embedding

### 推送完成后

1. starred article are stored permanently, unless user delete it  
2. invalid or fail candidate are removed in 1 day  
3. articles selected for comparison but not next step are removed in 2 days  
4. articles not added to daily list are removed in 7 days  
5. feedback event are stored long-term  
6. URL, hash, title: lightweight data can be stored long-term

### Tools

1. Web search MCP  
   1. `search_web(query, date_range, domains)`  
   2. `search_news(query)`  
   3. `find_related_coverage(title, entities)`  
2. Web fetch MCP  
   1. `fetch_url(url)`  
   2. `extract_main_content(url)`  
   3. `crawl_page(url)`  
3. Podcast mcp  
4. Social media mcp  
5. Government document mcp  
6. python service (no need for llm)  
   1. fetch\_rss  
   2. extract\_with\_trafilatura  
   3. calculate\_hash  
   4. store\_article  
   5. delete\_expired\_articles

### DB schema

articles  
\- id  
\- source\_id  
\- run\_id  
\- canonical\_url  
\- rss\_guid  
\- title  
\- rss\_summary  
\- content\_text  
\- author  
\- published\_at  
\- fetched\_at  
\- word\_count  
\- language  
\- content\_type  
\- content\_hash  
\- embedding  
\- status  
\- duplicate\_of\_article\_id  
\- expires\_at

The **status** of article can be:   
discovered  
extracting  
extracted  
rejected  
duplicate  
clustered  
selected  
expired

story\_clusters  
\- id  
\- representative\_title  
\- event\_summary  
\- event\_date  
\- cluster\_embedding  
\- comparison\_status

story\_cluster\_members  
\- cluster\_id  
\- article\_id  
\- similarity\_score  
\- relationship

## article retrieval strategy
1. SQL filters
   date, language, source, length, status

2. Keyword/full-text search
   names, events, exact claims

3. pgvector similarity
   related stories, liked-content similarity

4. Reranking
   combine evidence quality, freshness, relevance

5. LLM
   compare retrieved claims or explain selection

## Phases and stages

### Phase 1

Goal: reliably collect and store articles.

Build:

* FastAPI project  
* PostgreSQL  
* `sources` table  
* `articles` table  
* Cron or APScheduler  
* RSS fetching  
* URL/GUID deduplication  
* Full-text extraction with Trafilatura  
* Newspaper4k/Jina fallback  
* Basic API to view fetched articles

Workflow:

schedule  
→ fetch RSS  
→ check URL duplicate  
→ extract content  
→ store article

Article statuses:

discovered  
extracting  
extracted  
failed  
duplicate  
**Done when:** you can add several RSS feeds and reliably see clean articles in the database. 

### Phase 2

Goal: produce a basic daily list without advanced AI.

Add:

* Word-count limits  
* Publication-date limits  
* Language filtering  
* Blocked sources  
* Basic content types  
* Daily article target  
* Reading-time limit  
* Simple scoring rules  
* `daily_reading_lists`  
* `daily_reading_items`

Workflow:

fetched articles  
→ hard filter  
→ basic classify  
→ score  
→ select top N  
→ save daily list

Use deterministic scoring first:

freshness  
topic match  
source preference  
length fit

**Done when:** the system automatically creates a reasonable daily list every day.

### Phase 3

Goal: personalize recommendations based on user behavior.

Add:

* Like  
* Dislike  
* Skip  
* Star  
* Read/complete  
* Feedback reasons  
* Explicit preferences  
* Derived preference scores  
* Article embeddings with pgvector

Tables:

feedback\_events  
user\_preferences  
preference\_features  
saved\_articles

Personalization:

candidate article  
→ explicit preferences  
→ learned topic/source/type scores  
→ similarity to liked articles  
→ similarity to disliked articles  
→ personalization score

Do not use Mem0. Keep PostgreSQL as the source of truth.

Deferred source-blocking requirement:

* While discovery is limited to user-managed RSS feeds, users can remove or disable
  a source directly instead of maintaining an explicit blocked-source preference.
* Before MCP/web-search expansion is enabled, add user-scoped blocked domains and
  blocked sources so related-coverage discovery cannot reintroduce sources the user
  does not want.
* Keep feedback, saved articles, preferences, and daily lists scoped by user so the
  same backend can later support authenticated deployment for multiple people.

**Done when:** repeated likes and dislikes visibly change later recommendations.

### Phase 4

Goal: convert the pipeline into a stateful agent workflow.

Your current document already identifies the intended node sequence and termination idea.

Add:

* `DailyRunState`  
* LangGraph nodes  
* Conditional edges  
* Checkpointer  
* Retry handling  
* Expansion rounds  
* Run status and failure logs

Suggested graph:

load\_settings  
→ collect  
→ exact\_deduplicate  
→ extract  
→ content\_deduplicate  
→ filter  
→ classify  
→ personalize  
→ select  
→ enough\_articles?  
    ├── yes → finalize  
    └── no  → expand\_sources → select

Expansion rounds:

Round 0: configured RSS  
Round 1: unused candidates  
Round 2: related web search  
Round 3: relax soft preferences

**Done when:** a failed run can resume, and the workflow terminates predictably.

### Phase 5

Goal: add the strongest, most distinctive feature.

Add:

* Story/event clustering  
* `story_clusters`  
* `story_cluster_members`  
* Claim extraction  
* Evidence matrix  
* Representative article selection  
* Structured comparison output

Workflow for news:

news candidates  
→ cluster same event  
→ extract claims  
→ align related claims  
→ detect support / contradiction / missing  
→ identify shared original sources  
→ score reports  
→ choose representative article

Use pgvector for:

* Semantic clustering  
* Similar claim retrieval  
* Relevant chunk retrieval

Use chunks only when articles or clusters are too large.

**Done when:** the system can explain why one report was selected and where sources disagree.

### Phase 6

## **Phase 6 — MCP, deployment, and polish**

Goal: make it resume-ready and accessible.

Add only after the core system works:

* Web search MCP  
* Optional Reddit MCP  
* Optional YouTube/podcast transcript MCP  
* Government-document connector  
* Responsive frontend  
* iPhone web access  
* Supabase or hosted PostgreSQL  
* Cloud scheduler  
* Docker  
* Logging and tracing  
* Evaluation dataset  
* README and architecture diagram

Keep RSS and normal extraction as Python services. MCP should support external discovery, not replace your whole ingestion system.

**Done when:** the project is deployed, documented, measurable, and easy for another person to clone.

## 文档结构

reading\_everyday/  
├── app/  
│   ├── main.py                 \# FastAPI entry point  
│   ├── config.py               \# Environment variables and settings  
│   │  
│   ├── api/                    \# HTTP endpoints  
│   │   ├── articles.py  
│   │   ├── daily\_reading.py  
│   │   ├── feedback.py  
│   │   ├── preferences.py  
│   │   └── sources.py  
│   │  
│   ├── agent/                  \# LangGraph agent runtime  
│   │   ├── graph.py            \# Nodes, edges and compilation  
│   │   ├── state.py            \# DailyRunState  
│   │   ├── routing.py          \# Conditional edge decisions  
│   │   └── prompts.py  
│   │  
│   ├── nodes/                  \# Individual workflow steps  
│   │   ├── collect.py  
│   │   ├── extract.py  
│   │   ├── filter.py  
│   │   ├── classify.py  
│   │   ├── deduplicate.py  
│   │   ├── cluster.py  
│   │   ├── retrieve\_memory.py  
│   │   ├── rank.py  
│   │   ├── compare\_evidence.py  
│   │   ├── select.py  
│   │   └── finalize.py  
│   │  
│   ├── tools/                  \# External actions callable by nodes/agent  
│   │   ├── search\_web.py  
│   │   ├── fetch\_url.py  
│   │   ├── parse\_article.py  
│   │   ├── query\_memory.py  
│   │   └── save\_daily\_list.py  
│   │  
│   ├── sources/                \# Website-specific integrations  
│   │   ├── base.py  
│   │   ├── rss.py  
│   │   ├── news\_api.py  
│   │   └── custom\_web.py  
│   │  
│   ├── memory/  
│   │   ├── preferences.py      \# Explicit preferences  
│   │   ├── behavior.py         \# Likes, skips, opens, stars  
│   │   ├── embeddings.py       \# Semantic memory  
│   │   └── retrieval.py  
│   │  
│   ├── services/               \# Normal application business logic  
│   │   ├── article\_service.py  
│   │   ├── cleanup\_service.py  
│   │   ├── scheduler\_service.py  
│   │   └── notification\_service.py  
│   │  
│   ├── db/  
│   │   ├── models/  
│   │   ├── repositories/  
│   │   ├── session.py  
│   │   └── migrations/  
│   │  
│   ├── schemas/                \# Pydantic request/response models  
│   └── evaluation/  
│       ├── datasets/  
│       ├── relevance.py  
│       └── evidence.py  
│  
├── frontend/  
├── tests/  
├── scripts/  
├── docker-compose.yml  
├── pyproject.toml  
└── README.md
