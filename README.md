# Multi-Agent Incident Response System

## Current Implementation Status

当前版本已经完成第一版可运行 MVP，并继续补充了以下能力：

- Multi-Agent workflow：基于 FastAPI + LangGraph，包含 Log Analyst、Metric Analyst、Knowledge Agent、Root Cause Agent、Fix Planner、Reviewer、Eval Adapter。
- LLM 接入：支持 OpenAI-compatible API，可接正规厂商模型，也可接 API 中转站；严格隐私模式下默认不向外部 LLM 发送原始日志和完整知识库内容。
- 真实向量 RAG：已选择 Chroma，使用本地持久化向量库 `backend/data/chroma/`，并配套 deterministic local embedding；Chroma 不可用时自动回退关键词检索。
- 外部工具接入 mock：已实现 Prometheus 指标查询 mock、Loki/Elasticsearch 风格日志搜索 mock、Git 部署历史 mock；Slack / 飞书通知 mock 暂不实现。
- 可观测性：trace events、agent execution metadata、LLM token/latency/fallback 信息、RAG retrieval mode、tool result counts 都会进入 eval report。
- Human-in-the-loop：高风险修复计划支持人工 approve/reject API 和前端操作。
- 前端控制台：React + Vite + TypeScript，支持 incident 输入、报告、工具结果、trace、eval、LLM 状态、历史记录、人工审批。
- 本地持久化：SQLite 保存运行历史和 trace，Chroma 保存本地知识库索引；这些生成数据不会提交到 Git。

暂缓内容：

- Slack / 飞书通知 mock 暂不做。
- 认证和权限暂不做。
- 云部署、CI/CD、GitHub Actions 暂不做。

多 Agent 智能故障排查系统。

这是一个面向真实工程场景的多 agent 项目。它模拟企业线上服务发生故障后的排查流程：系统读取告警、日志、指标和历史故障知识库，组织多个专业 agent 协作分析，最终生成结构化 Incident Report，帮助工程师快速定位问题、评估风险并制定修复方案。

这个项目的目标不是做一个简单聊天机器人，而是做一个面向真实工程场景、能体现 agent 工程能力的完整系统。

## 1. 项目背景

在真实企业生产环境中，线上服务故障通常会涉及多类信息：

```text
错误日志
服务指标（系统运行时持续采集的数据，用来描述服务健康状况，比如错误率、延迟、内存使用率等，能告诉你系统哪里不健康）
告警内容（监控系统发出来的警报信息，告诉你“出事了”）
历史 incident（一次完整的线上故障时间，包含时间、范围、修复过程、方案、复盘等）
runbook 排查手册（遇到某问题的排查步骤说明）
代码变更记录（如果是最近发生了代码或者配置的变化，就可以看变更记录进行排查）
部署记录
```

工程师排查故障时，往往需要同时完成这些事情：

```text
从大量日志中提取关键错误
从指标中判断异常时间点和影响范围
查询历史故障和排查手册
推断可能根因
制定修复和回滚方案
验证修复是否有效
把整个过程记录成 incident report
```

这些步骤天然适合多 agent 协作。每个 agent 负责一个专业方向，最后由 reviewer 检查证据链和最终结论。

## 2. 项目目标

用户输入一次故障相关信息，例如：

```text
告警描述
错误日志
指标数据
服务名称
时间范围
可选的历史 incident / runbook
```

系统自动执行多 agent 故障分析流程，输出：

```text
故障摘要
异常时间线
关键证据
可能根因
排查步骤
修复建议
回滚方案
验证步骤
风险等级
置信度
reviewer 检查意见
trace / eval 报告
```

最终效果是：工程师可以快速了解“发生了什么、为什么可能发生、下一步该怎么做、这些结论有什么证据支撑”。

## 3. 项目定位

这个项目定位为：

```text
AI + SRE(Site Reliability Engineering) / 后端工程 / 平台工程方向的多 agent 实战项目
```

它重点展示这些能力：

```text
多 agent 工作流设计
LangGraph 状态图编排
日志和指标分析
RAG 历史故障检索
工具调用
结构化输出
错误处理
日志追踪
human-in-the-loop
agent trace 采集和评估
前后端完整展示
```


## 4. 核心功能

### 4.1 Incident 输入

系统第一版支持三类输入：

```text
告警描述：用户手动输入，描述故障现象
日志文件：上传或选择 sample log
指标文件：上传或选择 sample metrics JSON
```

示例：

```text
Service checkout-api error rate increased from 0.5% to 12% after deployment.
Users report timeout when creating orders.
```

日志示例：

```text
2026-06-18T10:21:03Z ERROR checkout-api DatabaseConnectionTimeout
2026-06-18T10:21:04Z ERROR checkout-api failed to acquire connection from pool
2026-06-18T10:21:05Z WARN checkout-api retrying payment transaction
```

指标示例：

```json
{
  "service": "checkout-api",
  "error_rate": {
    "before": 0.005,
    "after": 0.12
  },
  "p95_latency_ms": {
    "before": 230,
    "after": 2400
  },
  "db_connection_pool_usage": {
    "before": 0.45,
    "after": 0.98
  }
}
```

### 4.2 多 Agent 分析

系统会组织多个 agent 协作：

```text
Log Analyst Agent
Metric Analyst Agent
Knowledge Agent
Root Cause Agent
Fix Planner Agent
Reviewer Agent
```

每个 agent 都有明确职责、输入、输出和结构化 schema。

### 4.3 历史故障知识库

系统包含本地 incident knowledge base。

第一版知识库可以使用：

```text
JSON incident cases
Markdown runbook
故障排查手册
服务依赖说明
```

后续可以升级为：

```text
Chroma / FAISS 向量库
OpenAI embeddings
混合检索
rerank
来源引用
权限过滤
```

### 4.4 结构化报告

最终输出不是一段自然语言，而是结构化 Incident Report。

核心字段：

```text
incident_id
service
severity
summary
timeline
signals
possible_root_causes
recommended_actions
rollback_plan
verification_steps
confidence
review_notes
human_approval_required
```

同时生成 Markdown 报告，方便阅读和展示。

### 4.5 Eval Adapter

项目会加入一个 Eval / Observability Adapter。

它不参与业务推理，不负责判断根因，也不直接影响 agent 的结论。

它的职责是旁路采集每个 agent 的执行过程，方便评估和调试。

采集内容包括：

```text
trace_id
step_id
agent_name
node_name
input_state
output
tool_calls
tool_results
errors
retry_count
duration_ms
state_diff
structured_output_valid
```

流程结束后，Eval Adapter 生成评估报告：

```text
每个 agent 是否成功执行
输出 schema 是否通过校验
工具调用是否成功
RAG 检索是否命中相关资料
根因是否有证据支撑
修复建议是否有风险
reviewer 是否发现证据不足
整条流程耗时
失败和重试情况
```

这是本项目的重要工程亮点。

## 5. Agent 设计

### 5.1 Log Analyst Agent

职责：

```text
读取错误日志
提取关键错误类型
识别异常模块
提取异常时间点
统计错误频率
找出重复出现的错误模式
```

输入：

```text
raw_logs
alert_description
service_name
time_window
```

输出：

```text
error_patterns
important_log_lines
suspected_components
log_timeline
log_confidence
```

示例输出：

```json
{
  "error_patterns": ["DatabaseConnectionTimeout", "connection pool exhausted"],
  "suspected_components": ["database", "connection_pool"],
  "important_log_lines": [
    "ERROR checkout-api failed to acquire connection from pool"
  ],
  "log_confidence": 0.86
}
```

### 5.2 Metric Analyst Agent

职责：

```text
分析服务指标
识别异常变化
判断影响范围
发现日志和指标之间的关联
```

输入：

```text
metrics_json
alert_description
service_name
```

输出：

```text
metric_anomalies
impact_summary
timeline
suspected_bottlenecks
metric_confidence
```

典型指标：

```text
error_rate
p95_latency
p99_latency
throughput
cpu_usage
memory_usage
db_connection_pool_usage
queue_lag
```

### 5.3 Knowledge Agent

职责：

```text
检索历史 incident
检索 runbook
查找相似故障案例
返回相关资料和引用来源
```

输入：

```text
log_findings
metric_findings
alert_description
```

输出：

```text
retrieved_cases
related_runbooks
known_failure_modes
source_references
retrieval_confidence
```

第一版可以先用关键词检索。后续升级为向量检索。

### 5.4 Root Cause Agent

职责：

```text
综合日志、指标和知识库结果
提出可能根因
给每个根因标注证据
给出置信度
区分 confirmed / likely / possible
```

输入：

```text
log_analysis
metric_analysis
knowledge_results
```

输出：

```text
root_cause_hypotheses
evidence_map
confidence
missing_information
```

它不能只“猜原因”，必须说明证据来自哪里。

### 5.5 Fix Planner Agent

职责：

```text
生成排查步骤
生成修复建议
生成回滚方案
生成修复后验证步骤
标记高风险操作
```

输入：

```text
root_cause_hypotheses
evidence_map
service_context
```

输出：

```text
diagnostic_steps
recommended_actions
rollback_plan
verification_steps
risk_level
requires_human_approval
```

高风险操作必须触发 human-in-the-loop。

例如：

```text
重启核心服务
回滚生产部署
修改数据库连接池配置
执行数据修复脚本
```

### 5.6 Reviewer Agent

职责：

```text
检查最终报告是否完整
检查根因是否有证据支撑
检查修复建议是否过于冒险
检查是否需要人工审批
输出最终 review notes
```

输入：

```text
incident_report_draft
trace_summary
agent_outputs
```

输出：

```text
approved
review_notes
quality_score
evidence_score
safety_score
required_revisions
```

Reviewer 不负责重新分析所有问题，而是负责质量控制。

## 6. Eval Adapter 设计

### 6.1 为什么需要 Eval Adapter

Agent 系统很难像普通函数一样测试。

普通函数通常是：

```text
input -> output
```

多 agent 系统是：

```text
input -> state -> agent -> tool -> state -> agent -> RAG -> state -> reviewer -> output
```

中间有很多不确定性：

```text
模型输出不稳定
工具可能失败
RAG 检索可能不相关
多个 agent 的结论可能冲突
状态可能被错误更新
最终结果可能看起来合理但没有证据
```

所以项目需要一个专门的旁路组件来采集 trace、state、tool output 和 agent output。

### 6.2 Eval Adapter 不是什么

它不是业务 agent。

它不应该：

```text
参与根因判断
直接修改业务 state
直接决定修复方案
和其他 agent 对话争论
```

它应该：

```text
记录过程
保存证据
生成评估数据
帮助调试和离线分析
```

### 6.3 Eval Adapter 采集点

在每个 agent 节点执行前：

```text
record_node_start(trace_id, node_name, input_state)
```

在工具调用时：

```text
record_tool_call(trace_id, node_name, tool_name, args, result, error)
```

在每个 agent 节点执行后：

```text
record_node_end(trace_id, node_name, output, state_diff, duration_ms)
```

在流程结束后：

```text
generate_eval_report(trace_id)
```

### 6.4 Eval Report 示例

```json
{
  "trace_id": "inc_20260618_001",
  "workflow_status": "completed",
  "total_duration_ms": 4280,
  "agent_scores": {
    "log_analyst": {
      "success": true,
      "schema_valid": true,
      "evidence_count": 4
    },
    "knowledge_agent": {
      "success": true,
      "retrieval_hit_count": 3,
      "top_source_score": 0.82
    },
    "root_cause_agent": {
      "success": true,
      "hypothesis_count": 2,
      "evidence_coverage": 0.75
    }
  },
  "risks": [
    "Fix plan includes production rollback and requires human approval."
  ],
  "recommendations": [
    "Add more database metrics to improve root cause confidence."
  ]
}
```

### 6.5 后续可扩展评估方式

第一版做规则评估：

```text
schema 是否通过
字段是否完整
是否有证据
是否调用了必要工具
是否命中知识库
是否产生高风险建议
是否触发人工审批
```

第二版可以加人工评分：

```text
工程师对根因质量打分
工程师对修复建议打分
工程师标记最终根因是否正确
```

第三版可以加 LLM-as-judge：

```text
让 judge model 根据 rubric 评价报告质量
检查 evidence 是否支持 root cause
检查 fix plan 是否安全
```

## 7. 工作流设计

第一版工作流：

```text
ingest_incident
  -> log_analysis
  -> metric_analysis
  -> knowledge_retrieval
  -> root_cause_analysis
  -> fix_planning
  -> review
  -> human_approval_if_needed
  -> final_report
```

更完整的条件流程：

```text
START
  -> ingest_incident
  -> log_analysis
  -> metric_analysis
  -> knowledge_retrieval
  -> root_cause_analysis
  -> fix_planning
  -> review

review approved
  -> final_report

review needs_revision
  -> root_cause_analysis

fix plan high risk
  -> human_approval

human approved
  -> final_report

human rejected
  -> manual_escalation

tool failure
  -> retry
  -> fallback
  -> reviewer
```

## 8. 技术栈

### 8.1 后端

```text
Python
FastAPI
Pydantic
Uvicorn
```

选择原因：

```text
Python 适合 AI agent 和数据处理
FastAPI 适合快速构建 API
Pydantic 适合定义结构化输出和校验 schema
Uvicorn 作为 ASGI 服务运行后端
```

### 8.2 Agent 编排

```text
LangGraph
```

选择原因：

```text
项目有明确状态流转
需要条件分支
需要 reviewer 打回
需要 human-in-the-loop
需要 checkpoint
需要可追踪 workflow
```

LangGraph 对应关系：

```text
GraphState -> 全局 incident state
node -> 每个 agent 节点
conditional edge -> 根据状态决定下一步
checkpoint -> 保存流程状态
interrupt -> 人工审批
```

### 8.3 LLM

```text
OpenAI API
```

用途：

```text
日志摘要
根因分析
修复建议生成
报告生成
reviewer 质量检查
```

第一版可以保留 mock LLM 层，确保没有 API key 也能跑 demo。后续再接真实模型。

### 8.4 RAG / Knowledge

当前版本：

```text
本地 JSON / Markdown
Chroma 向量检索
本地 deterministic embedding
关键词检索 fallback
```

后续增强：

```text
OpenAI embeddings 或 sentence-transformers
Hybrid search
Rerank
```

当前版本已经接入 Chroma，优先保证本地可运行、可测试、可持久化，后续可以替换为更强的 embedding 或 hybrid search。

### 8.5 数据存储

```text
SQLite
SQLModel 或 SQLAlchemy
```

保存内容：

```text
incident runs
agent outputs
trace events
tool calls
eval reports
final reports
human approvals
```

SQLite 适合项目第一版，因为部署简单、可复制、可演示。

### 8.6 前端

```text
React
TypeScript
Vite
Tailwind CSS 或普通 CSS
```

页面功能：

```text
创建 incident
上传日志和指标
查看 agent 执行进度
查看 trace
查看最终 incident report
查看 eval report
人工审批高风险操作
```

如果第一阶段想降低复杂度，可以先做 CLI + FastAPI，后面补 Web UI。

### 8.7 测试

```text
pytest
Pydantic schema tests
workflow tests
sample incident fixtures
tool tests
eval adapter tests
```

测试重点：

```text
每个 agent 输出是否符合 schema
sample incident 是否能完整跑通
高风险修复是否触发人工审批
工具失败是否能重试
reviewer 打回是否能回到正确节点
eval adapter 是否能记录完整 trace
```

### 8.8 日志和追踪

第一版：

```text
自定义 trace_id / span_id
Python logging
Eval Adapter trace events
```

后续可选：

```text
LangSmith
OpenTelemetry
```

## 9. 核心数据结构

### 9.1 IncidentState

全局状态，用于 LangGraph 流转。

核心字段：

```text
incident_id
service_name
alert_description
raw_logs
metrics
log_analysis
metric_analysis
knowledge_results
root_cause_analysis
fix_plan
review_result
human_approval
final_report
trace_id
status
errors
retry_count
```

### 9.2 IncidentReport

最终报告。

核心字段：

```text
incident_id
service_name
severity
summary
timeline
signals
root_causes
recommended_actions
rollback_plan
verification_steps
confidence
review_notes
sources
```

### 9.3 TraceEvent

Eval Adapter 采集的事件。

核心字段：

```text
trace_id
span_id
node_name
agent_name
event_type
input_snapshot
output_snapshot
state_diff
tool_calls
error
duration_ms
timestamp
```

## 10. MVP 边界

第一版必须完成：

```text
FastAPI 后端
LangGraph 工作流
6 个 agent 节点
本地 sample logs / metrics
本地 JSON knowledge base
Chroma 向量检索版 Knowledge Agent
Prometheus / 日志搜索 / Git 部署历史 mock tools
Pydantic 结构化输出
Eval Adapter trace 采集
结构化 Incident Report
Markdown Report
pytest 测试
```

第一版暂不做：

```text
真实 Prometheus 接入
真实 Elasticsearch 接入
Slack / 飞书通知
用户登录权限
生产级部署
复杂前端大屏
自动执行真实修复命令
```

原因：

```text
第一版重点是展示多 agent workflow 和工程设计，而不是堆外部系统集成。
```

## 11. 后续扩展

第二版可扩展：

```text
React Web UI
真实 OpenAI 模型调用
LangGraph checkpoint
human-in-the-loop interrupt
LLM-as-judge 评估
真实 Prometheus / Elasticsearch / Loki API
trace 可视化页面
incident replay
```

第三版可扩展：

```text
接真实监控系统
接 Git deployment history
接 Slack / 飞书通知
自动生成 postmortem
自动创建 Jira / GitHub issue
多服务依赖图分析
```

## 12. 推荐目录结构

```text
Multi-Agent Incident Response System/
  README.md
  backend/
    app/
      main.py
      api/
      agents/
      graph/
      schemas/
      tools/
      knowledge/
      eval/
      storage/
      reports/
    tests/
    data/
      sample_logs/
      sample_metrics/
      knowledge_base/
    pyproject.toml
  frontend/
    src/
    package.json
  docs/
    architecture.md
    incident_report_example.md
```

## 13. 项目展示方式

最终演示可以这样展示：

```text
1. 输入一次 checkout-api 故障
2. 系统运行多 agent workflow
3. 页面显示每个 agent 的执行状态
4. 展示日志分析、指标分析、知识库检索结果
5. 展示 Root Cause Agent 的证据链
6. 展示 Fix Planner 的修复建议
7. 高风险操作触发人工审批
8. 展示 Reviewer 的质量检查
9. 输出最终 Incident Report
10. 展示 Eval Adapter 生成的 trace / eval 报告
```

## 14. 后续可选调整

下面这些方向暂不纳入第一版 MVP，但可以作为后续实现时的增强项。

### 14.1 真实 LLM 调用与 Mock fallback

第一版可以先保留 mock LLM，保证没有 API key 也能跑通完整 demo。

后续可以增加真实模型调用，并通过配置切换：

```text
LLM_MODE=mock
LLM_MODE=openai
```

建议保留 mock fallback，避免因为外部模型不可用、额度不足或网络异常导致 demo 完全不可运行。

### 14.2 Docker / CI / 部署说明

后续可以补充最小可复现运行环境：

```text
Dockerfile
docker-compose.yml
.env.example
GitHub Actions / CI
pytest 自动化测试
一键启动命令
```

目标是让项目可以被快速拉起、测试和演示。

### 14.3 更可量化的 Eval Adapter

现阶段 Eval Adapter 重点记录 trace、state diff、tool call 和结构化输出校验。

后续可以增加更明确的评估指标：

```text
schema_pass_rate
evidence_coverage
retrieval_hit_rate
hallucination_risk_flag
high_risk_action_approval_rate
average_workflow_latency
failed_tool_call_count
```

这样可以让 agent workflow 的质量更容易被观察、比较和持续改进。

### 14.4 安全与 Guardrails

故障响应系统会涉及高风险操作，因此后续需要补充安全边界：

```text
禁止自动执行真实生产修复命令
高风险动作只生成建议，不直接执行
敏感日志脱敏
API key 不入库
prompt injection 防护
tool allowlist
```

human-in-the-loop 是第一层安全控制，guardrails 是更完整的工程边界。

### 14.5 MCP 或 Tool Server 扩展点

后续可以增加 MCP 或独立 tool server，用于统一接入外部系统和工具。

可选工具包括：

```text
Prometheus mock tool
Git deployment history tool
runbook search tool
incident knowledge search tool
notification tool
```

这样可以把 agent 推理流程和外部工具访问解耦。

### 14.6 README 项目主页化

当项目开始有实际代码和 demo 后，可以把 README 从设计文档调整成项目主页。

建议保留在 README 前半部分的内容：

```text
项目简介
架构图
Quick Start
API 示例
示例输入输出
demo 截图或 GIF
测试方式
当前完成度
```

更详细的设计内容可以移动到：

```text
docs/architecture.md
docs/eval_adapter.md
docs/workflow.md
```

## 15. 项目核心价值

这个项目的核心价值不是“调用一次大模型生成报告”。

它真正展示的是：

```text
如何把真实工程排障流程拆成多个专业 agent
如何用 LangGraph 控制复杂状态流转
如何用 RAG 引入历史知识
如何用结构化输出保证结果可被程序消费
如何用 human-in-the-loop 控制高风险操作
如何用 Eval Adapter 评估和调试 agent 系统
如何把 AI agent 做成一个可维护、可测试、可展示的工程项目
```

这也是它适合作为 AI agent 工程项目持续迭代的原因。

## 16. 当前 MVP 运行方式

当前第一版 MVP 已实现后端核心流程：

```text
FastAPI 后端
LangGraph 工作流
6 个 agent 节点
本地 sample logs / metrics
本地 JSON / Markdown knowledge base
Chroma 向量检索版 Knowledge Agent
Prometheus / 日志搜索 / Git 部署历史 mock tools
Pydantic 结构化输出
Eval Adapter trace 采集
结构化 Incident Report
Markdown Report
pytest 测试
```

### 16.1 LLM 配置

项目支持 OpenAI-compatible API provider。可以接正规云厂商，也可以接兼容 OpenAI Chat Completions 协议的 API provider。

本地配置放在：

```text
backend/.env
```

示例：

```env
LLM_BASE_URL=https://example.com
LLM_API_KEY=your_api_key
LLM_MODEL=your_model_name
LLM_TIMEOUT_SECONDS=30
LLM_PRIVACY_MODE=strict
```

如果配置了 `LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`，系统会自动使用：

```text
LLM_MODE=openai_compatible
```

如果没有配置真实模型，系统会回退到：

```text
LLM_MODE=mock
```

当前接入大模型的 agent：

```text
Root Cause Agent
Fix Planner Agent
Reviewer Agent
```

这些 agent 会优先调用真实 LLM，并在模型不可用、返回格式不符合 schema、请求超时等情况下自动回退到规则版逻辑。

LLM 可观测性会记录：

```text
llm_provider
llm_model
prompt_tokens
completion_tokens
total_tokens
llm_latency_ms
llm_error_type
prompt_version
privacy_mode
```

`LLM_PRIVACY_MODE=strict` 时，发送给外部 LLM 的内容会裁剪为结构化信号：

```text
不发送 raw log 原文
不发送 knowledge base 正文
只发送 error pattern / suspected component / metric anomaly / source_id / known failure mode
```

验证 LLM 连通性：

```powershell
cd backend
..\.venv\Scripts\python.exe check_llm.py
```

安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

运行测试：

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

启动 API 服务：

```powershell
cd backend
..\.venv\Scripts\python.exe run_server.py
```

服务地址：

```text
http://127.0.0.1:8000
```

健康检查：

```text
GET /health
```

运行一次 incident 分析：

```text
POST /incidents/run
```

历史记录与人工审批：

```text
GET /incidents
GET /incidents/{incident_id}
GET /incidents/{incident_id}/trace
POST /incidents/{incident_id}/approve
POST /incidents/{incident_id}/reject
```

启动前端：

```powershell
cd frontend
npm install
npm run dev
```

前端地址：

```text
http://127.0.0.1:5173
```

前端当前包含：

```text
Incident 输入表单
Incident Report 展示
Trace 节点执行视图
Eval Report 展示
LLM provider 状态展示
每个 LLM agent 的 execution_mode / fallback_reason 展示
Incident Run History
Human Approval approve / reject
LLM token / latency / privacy mode 展示
```

Docker Compose 启动：

```powershell
docker compose up --build
```

如果本机 Docker 使用旧版 Compose 命令：

```powershell
docker-compose up --build
```

Docker 启动后：

```text
Backend: http://127.0.0.1:8000
Frontend: http://127.0.0.1:5173
```
