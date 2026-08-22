<p align="center">
  <img src="docs/img.png" alt="TurnCraft - 多轮任务型 Agent 框架" width="100%">
</p>

# TurnCraft

> 多轮任务型 Agent 框架 · Turn-taking Task-oriented Agent Framework

TurnCraft 是一个面向企业工单、智能客服等多轮任务场景的 **任务型 Agent 框架**。它将 LLM 的语言理解能力与确定性的业务流程解耦：**LLM 只负责"听懂"用户，路由、编排、执行与状态恢复全部由代码与配置决定**。围绕任务路由、状态恢复与执行可靠性三个核心问题，TurnCraft 提供了一整套可插拔、可配置、可观测的工程化方案。

```
┌─────────────────────────────────────────────────────────────┐
│   TurnCraft: Task-oriented Agent Framework                  │
│                                                             │
│   LLM 只做理解 · 代码做决策 · 配置驱动执行 · 状态可恢复       │
└─────────────────────────────────────────────────────────────┘
```

---

## 目录

- [背景与问题](#背景与问题)
- [核心特性](#核心特性)
- [技术栈](#技术栈)
- [架构总览](#架构总览)
- [分层路由](#分层路由)
- [配置化 Workflow](#配置化-workflow)
- [状态管理与断点恢复](#状态管理与断点恢复)
- [执行可靠性](#执行可靠性)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [评测与优化](#评测与优化)
- [如何扩展新任务](#如何扩展新任务)

---

## 背景与问题

在企业工单、客服等真实业务中，多轮任务通常面临三个典型痛点：

| 痛点 | 具体表现 |
|---|---|
| **用户信息不完整** | 用户一次只表达一部分诉求，关键槽位（订单号、退款原因等）分散在多轮对话中，单轮模型难以补齐。 |
| **任务状态易丢失** | 会话中断、任务暂停后无法恢复；用户在中途切换话题后，任务上下文与槽位信息丢失。 |
| **大模型自由执行不可控** | 让 LLM 自由决定"下一步做什么"会导致流程漂移、漏步骤、跳过校验，甚至执行出无效操作。 |

TurnCraft 的核心思路是**把"任务理解"与"流程执行"彻底解耦**：

- **LLM 只做语言理解**：从用户话语中提取意图与参数，输出结构化的 `tool_calls`，不参与路由判决与流程编排；
- **代码做确定性决策**：规则匹配、置信度融合、四态判决、参数校验全部由代码完成；
- **配置驱动业务**：业务流程用 YAML 描述，新增业务无需修改框架代码。

---

## 核心特性

- **多级意图路由**：`规则匹配 → Embedding 召回 → LLM 理解` 三级路由，根据置信度自动进入任务执行、澄清追问或异常兜底流程；
- **分层可插拔管道**：召回、排序、校验、判决每一层都是独立组件，可替换、可组合、可观测；
- **配置化 Workflow**：基于 YAML 定义任务流程、槽位规则与执行动作，动态构建任务 Workflow，业务与 Agent 代码解耦；
- **结构化输出约束**：Pydantic 约束 LLM 输出，工具执行前进行参数与业务规则校验，降低模型异常执行风险；
- **状态持久化与断点恢复**：统一维护用户槽位、对话上下文与任务执行状态并持久化，支持多轮参数补充、任务暂停与断点恢复；
- **低成本高响应**：代码级规则优先 + 路由缓存，在同等模型与环境下显著降低对话响应耗时；
- **快速扩展**：内置 5 类业务任务，新增任务只需追加一份 YAML 配置。

---

## 技术栈

| 分类 | 技术 |
|---|---|
| 语言 | Python 3.13+ |
| Web 框架 | FastAPI + Uvicorn |
| 大模型 | Qwen LLM（通义千问） |
| Embedding | 千问 text-embedding（Qwen Embedding） |
| 配置 | PyYAML、Pydantic（结构化约束与校验） |
| 持久化 | MySQL（SQLAlchemy Async + aiomysql） |
| LLM 编排 | LangChain、LangChain-OpenAI |
| 测试 | pytest |

---

## 架构总览

```
┌─────────────────────────── 接入层 ───────────────────────────┐
│                     FastAPI HTTP API                          │
│              (Chat API · 会话管理 · 状态恢复)                  │
└─────────────────────────────┬────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────┐
│                         DialogueEngine                        │
│                     （对话引擎 · 外观 Facade）                  │
│   ┌──────────────┐    ┌──────────────────┐                   │
│   │  RouterService│──▶│  ToolRouterPlanner│                   │
│   │  分层路由管道   │    │   + TurnPlanAdapter│                   │
│   └──────┬───────┘    └────────┬─────────┘                   │
└──────────┼─────────────────────┼─────────────────────────────┘
           │ RoutingResult       │ TurnPlan
           │                     ▼
┌──────────┼─────────┐  ┌──────────────────────────────────────┐
│  路由层  │  编排层  │  │             执行层                    │
│  (见下节) │         │  │ ┌────────────┐ ┌──────────────────┐ │
│          │         │  │ │ FlowEngine  │ │ CommandProcessor │ │
│          │         │  │ │ (状态机执行) │ │ (取消/暂停/恢复)  │ │
│          │         │  │ └──────┬─────┘ └─────────┬────────┘ │
│          │         │  │        │                 │          │
│          │         │  │ ┌──────▼─────┐  ┌───────▼────────┐ │
│          │         │  │ │ ActionExecutor│  │ Knowledge/     │ │
│          │         │  │ │ (ActionRegistry)│ │ Chitchat/Clarify│ │
│          │         │  │ └──────┬─────┘  │ Handlers        │ │
│          │         │  │        │        └────────────────┘ │
│          │         │  │ ┌──────▼─────┐                      │
│          │         │  │ │ 业务 API    │ (订单/课程/进度/工单) │
│          │         │  │ └────────────┘                      │
│          │         │  └──────────────────────────────────────┘
└──────────┼─────────┘
           │ 持久化
┌──────────▼──────────────────────────────────────────────────┐
│               MySQL (SQLAlchemy Async)                       │
│         槽位 / 对话上下文 / 任务执行状态                       │
└──────────────────────────────────────────────────────────────┘
```

### 核心模块

| 模块 | 职责 |
|---|---|
| `agent/router` | 分层意图路由：缓存、规则捷径、双通道召回、LLM 理解、融合排序、参数校验、四态判决 |
| `agent/engine` | 对话引擎、TurnPlan 规划、任务校验、Workflow 状态机执行与轨迹追踪 |
| `agent/handler/task` | Flow 流程执行、Action 动作注册与执行、命令处理（start/resume/cancel/set_slots） |
| `agent/handler` | 知识问答、闲聊、澄清三种非任务轨道 Handler |
| `agent/domain` | Pydantic 领域模型：对话状态、任务上下文、会话、回合 |
| `agent/infrastructure` | LLM、Embedding、MySQL、业务系统 API 等基础设施适配 |
| `agent/api` | FastAPI 接入层（REST API） |

---

## 分层路由

TurnCraft 的意图路由是一条 **逐级升级、层层兜底** 的管道。低成本的确定性规则优先处理高置信表达，只有当规则无法判定时才升级到更"贵"的模型理解。

```
用户输入
   │
   ▼
① RouteCache（LRU 缓存，key = 文本 + 状态指纹）
   │ 未命中
   ▼
② 代码级规则捷径 (RoutingOrchestrator.shortcut_route)  ★ 无需 LLM
   │  取消当前任务 / 纯闲聊 / 精确知识主题 / GUIDE(怎么操作) / 活跃任务槽位补充
   │ 未命中
   ▼
③ 双通道候选召回 (CandidateSelector)
   │  KeywordRecallStrategy（关键词锚点，快）
   │  + EmbeddingRecallStrategy（千问 text-embedding，覆盖长尾口语）
   ▼
④ LLM 语言理解 (ToolReasoner)
   │  只输出 tool_calls + 参数，注入紧凑候选，不做路由决策
   ▼
⑤ 加权融合排序 (ToolRanker)
   │  embedding .10 / reasoning .55 / 参数覆盖 .20 / 动词 .10 / 模式 .05
   ▼
⑥ 结构化参数校验 (ParameterValidator)
   │  required / type / pattern 校验
   ▼
⑦ 四态判决 (RoutingOrchestrator.decide)
   │  CLEAR → 任务执行
   │  INSUFFICIENT → 进入澄清/槽位追问
   │  AMBIGUOUS → 多意图澄清
   │  LOW → 闲聊兜底 / 异常兜底
   ▼
⑧ TurnPlanAdapter → TurnPlan（start / resume / cancel / set_slots）
   ▼
FlowEngine · KnowledgeHandler · ChitchatHandler
```

### 四态判决

| 决策 | 触发条件 | 处理 |
|---|---|---|
| `CLEAR` | 唯一工具且置信度超过阈值 | 直接进入任务执行 |
| `INSUFFICIENT` | 意图明确但缺少必填槽位 | 进入澄清追问，收集槽位 |
| `AMBIGUOUS` | 多意图命中或 top1/top2 置信度接近 | 澄清候选，让用户确认 |
| `LOW` | 置信度低于阈值 | 闲聊兜底，自然引导回业务 |

### 设计模式

路由层大量运用经典设计模式，保证管道各环节可插拔：

| 模式 | 位置 | 说明 |
|---|---|---|
| 模板方法 | `RouterService.route` | 固定管线：缓存→规则→召回→理解→排序→校验→判决 |
| 工厂 | `agent/engine/builder.py` | 配置驱动装配整个路由服务 |
| 策略 | `CandidateSelector` / `ToolRanker` | 召回通道与评分策略可插拔 |
| 适配器 | `RoutingOrchestrator.TurnPlanAdapter` | `RoutingResult → TurnPlan`，FlowEngine 零改动 |
| 外观 | `RouterService` | 屏蔽底层多通道细节 |
| 组合 | `HybridRecallStrategy` | 多通道并集去重 |
| 缓存 | `RouteCache` | LRU + 状态指纹 |

---

## 配置化 Workflow

业务流程完全由 YAML 描述，框架动态解析并构建任务 Workflow，**实现业务流程与 Agent 代码解耦**。

```
flow_config/*.yml
   │  FlowManager.load_from_dir
   ▼
┌──────────────────────────────────────────────┐
│  YAML → 流程解析 → 状态机建模                  │
│  FlowsList + FlowManager                     │
│                                              │
│  节点类型：                                   │
│   ┌─────────┐  ┌─────────┐  ┌─────────┐      │
│   │  start   │→│ collect  │→│  action  │      │
│   └─────────┘  │ (槽位收集)│  │ (执行动作)│      │
│                └─────────┘  └────┬────┘      │
│                                  │ 条件分支    │
│                             ┌────▼────┐      │
│                             │   end    │      │
│                             └─────────┘      │
└──────────────┬───────────────────────────────┘
               │
               ▼
        ActionExecutor
        ├── 内置动作 action_response / action_listen
        └── 自定义动作 register_custom_actions（业务系统 API 调用）
```

以退款申请流程为例，完整的流程定义如下：

```yaml
# flow_config/user_flows.yml
slots:
  order_number:        # 槽位规则：多轮收集、持久化
    type: text
    label: 订单号
  refund_reason:
    type: text
    label: 退款原因
  refund_type:
    type: text
    label: 退款类型
    # personal_reason / course_unsatisfied / schedule_conflict / duplicate_purchase

flows:
  refund_request:
    name: 退款申请
    description: 收集订单号和退款原因、退款类型，提交退款申请并反馈处理结果。
    steps:
      - id: start
        type: start
        next: ask_order_number

      - id: ask_order_number
        type: collect                    # 槽位收集节点
        slot_name: order_number
        response:
          text: "请告诉我你的订单号。"
        next: ask_refund_reason

      - id: ask_refund_reason
        type: collect
        slot_name: refund_reason
        response:
          text: "请简单说一下退款原因。"
        next: ask_refund_type

      - id: submit_refund
        type: action                     # 执行动作节点
        action: action_submit_refund     # 绑定到自定义 Action
        next: refund_result

      - id: refund_result
        type: action
        action: action_response
        args:
          text: "{{ slots.refund_result }}"
        next: end

      - id: end
        type: end
        next: []
```

内置的 5 类业务任务全部通过 YAML 定义，无需改动一行框架代码：

| 流程 | 说明 | 涉及槽位 |
|---|---|---|
| `course_consultation` | 课程咨询 | 课程名称、课程信息 |
| `order_status_query` | 订单状态查询 | 订单号、订单状态、订单摘要 |
| `learning_progress_query` | 学习进度查询 | 班次名称、进度摘要 |
| `refund_request` | 退款申请 | 订单号、退款原因、退款类型 |
| `ticket_submission` | 工单提交（含投诉） | 工单类型、订单号、问题描述 |

---

## 状态管理与断点恢复

TurnCraft 用统一的 Pydantic 领域模型表达整个对话的"世界状态"，并持久化到 MySQL，保证任务可暂停、可恢复。

```
DialogueState (持久化到 MySQL)
├── active_task      当前活跃任务（flow_id + 当前 step + 已收集槽位）
├── paused_tasks     暂停中的任务栈（支持多任务挂起）
├── focused_object   焦点对象（用户正在谈论的订单/课程/班次）
├── sessions         会话历史（多轮上下文）
└── current_session_id
```

状态机在代码层面提供确定性转换，杜绝"自由执行"：

```
        start_flow              set_slots（多轮补齐）
用户 ─────────────▶ 活跃任务 ──────────────────────────▶ 继续推进
                     │  ▲
      resume_flow    │  │ pause / 用户切走话题
                     ▼  │
                暂停任务栈（paused_tasks）
                     │
     cancel_flow     ▼
                  任务取消 / 完成 ─────────▶ 清空状态
```

关键能力：

- **多轮参数补充**：用户在流程中途提供的缺失槽位会被 `set_slots` 增量补齐，无需重开流程；
- **任务暂停与恢复**：用户切换话题时当前任务进入 `paused_tasks`，回到原话题后按 `flow_id` 恢复现场；
- **焦点对象继承**：用户提到"这个订单""那门课"时，`focused_object` 会把上下文中的对象自动映射为必填槽位；
- **对话历史注入**：路由时注入最近 8 轮会话历史，帮助模型理解指代与省略表达。

---

## 执行可靠性

TurnCraft 通过"约束 + 校验 + 兜底"三道防线，把模型异常执行的风险压到最低：

```
① 结构化输出约束
   ToolReasoner 被 Pydantic 约束，只允许输出
   {"tool_calls": [{"tool": "...", "parameters": {...}}]}，
   禁止模型自由输出自然语言"计划"或路由判决。

② 执行前参数与规则校验
   ParameterValidator 对 LLM 抽取的参数做
   required / type / pattern 结构化校验；
   缺少必填参数 → INSUFFICIENT → 进入澄清，而不是带病执行。

③ 异常兜底降级
   - embedding 服务失败  → 降级为关键词召回通道
   - LLM 解析失败        → LOW → 闲聊兜底，自然引导回业务
   - 单候选无参数工具    → 跳过 LLM，快路径直达（如转人工）
   - TurnPlanValidator   → 执行前校验计划合法性
```

---

## 目录结构

```
TurnCraft/
├── agent/
│   ├── api/                  # FastAPI 接入层
│   │   ├── app.py
│   │   ├── routers/chat_router.py
│   │   └── schemas.py
│   ├── config/config_loader.py    # 配置加载（.env 可覆盖）
│   ├── domain/                    # Pydantic 领域模型
│   │   ├── dialogue_state.py      #   对话状态（槽位/任务/上下文）
│   │   ├── context.py
│   │   └── session.py
│   ├── engine/                    # 对话引擎与状态机
│   │   ├── builder.py             #   工厂：依赖装配
│   │   ├── dialogue_engine.py
│   │   ├── turn_planner.py
│   │   └── workflow_trace.py      #   执行轨迹观测
│   ├── handler/                   # 四类轨道 Handler
│   │   ├── task/                  #   任务轨道
│   │   │   ├── flow/              #     流程状态机执行
│   │   │   ├── action/            #     Action 注册与执行
│   │   │   ├── command/           #     命令处理
│   │   │   └── handler.py
│   │   ├── knowledge/             # 知识问答
│   │   ├── chitchat/              # 闲聊
│   │   └── clarify/               # 澄清
│   ├── infrastructure/            # 基础设施
│   │   ├── llm.py                 #   Qwen LLM 封装
│   │   ├── database.py            #   MySQL 异步连接池
│   │   ├── edu_api.py             #   业务系统 API
│   │   └── http.py
│   ├── router/                    # ★ 分层意图路由
│   │   ├── router_service.py      #   模板方法：路由管道
│   │   ├── orchestrator.py        #   规则捷径 + 四态判决 + TurnPlan 适配
│   │   ├── candidate_selector.py  #   双通道召回
│   │   ├── embedding_retriever.py #   Qwen Embedding 召回
│   │   ├── rule_router.py         #   确定性规则
│   │   ├── tool_reasoner.py       #   LLM 语言理解（tool_calls）
│   │   ├── tool_ranker.py         #   加权融合排序
│   │   ├── parameter_validator.py #   结构化参数校验
│   │   ├── tool_registry.py       #   工具注册表（由 YAML 自动生成）
│   │   └── route_cache.py         #   LRU 路由缓存
│   └── prompts/                   # Prompt 模板
├── flow_config/                   # ★ 业务流程配置
│   ├── user_flows.yml             #   业务任务流程（5 类）
│   └── system_flows.yml           #   系统流程（欢迎引导）
├── tests/
│   ├── eval/
│   │   ├── golden_set.py          #   100 条多轮客服测试集
│   │   └── run_eval.py            #   真实 LLM + Embedding 评测
│   ├── test_router.py
│   ├── test_golden_code_path.py   #   确定性 FakeLLM 代码路径测试
│   └── test_task_chain.py
├── frontend/                      # 演示前端
└── pyproject.toml
```

---

## 快速开始

```bash
# 1. 安装依赖（Python 3.13+）
uv sync    # 或 pip install -e .

# 2. 配置环境变量（.env）
cp .env.example .env
# 填写 Qwen LLM / Embedding 的 api_key、base_url、model，
# 以及 MySQL 连接串 db_url

# 3. 启动服务
./run.sh   # 或 uvicorn agent.api.app:app --reload

# 4. 打开前端 / 调用 API
# POST /api/chat  { "sender_id": "user_1", "text": "我要退款" }
```

### 测试与评测

```bash
# 代码路径测试（无需网络，确定性 FakeLLM）
.venv/bin/python -m pytest tests/test_router.py tests/test_golden_code_path.py

# 真实 LLM + Qwen Embedding 端到端评测（会调用 dashscope）
.venv/bin/python -m tests.eval.run_eval
```

---

## 配置说明

通过 `.env` 或环境变量覆盖（见 `agent/config/config_loader.py`）：

| 配置项 | 说明 |
|---|---|
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | Qwen LLM 服务配置 |
| `EMBEDDING_MODEL` / `EMBEDDING_BASE_URL` / `EMBEDDING_ENABLED` | 千问 Embedding 配置 |
| `ROUTER_TOP_K` | 候选召回数量（默认 8） |
| `ROUTER_CACHE_SIZE` | 路由 LRU 缓存容量 |
| `ROUTER_LOW_THRESHOLD` | 低置信度阈值（默认 0.40） |
| `ROUTER_AMBIGUITY_DELTA` | 模糊判定阈值 top1-top2 差值（默认 0.20） |
| `DB_URL` | MySQL 异步连接串 |
| `COMMERCE_API_BASE_URL` | 业务系统 API 地址 |

---

## 评测与优化

TurnCraft 使用**100 条多轮客服测试集**进行端到端评测，覆盖订单查询、退换货、投诉处理、课程咨询、学习进度查询等任务。

### 任务成功率

| 指标 | 结果 |
|---|---|
| 端到端任务成功率 | **91%** |

### 响应耗时优化

通过**分层路由 + 规则优先**机制（规则捷径与路由缓存大量跳过 LLM 调用），在相同模型与测试环境下：

| 阶段 | 平均对话响应耗时 |
|---|---|
| 改造前（单一 Prompt 意图分类） | 3.5 s |
| 改造后（分层路由 + 规则优先） | **1.2 s** |
| 提升 | **约 66%** |

> 优化手段：① 代码级规则捷径（取消/闲聊/槽位补充等无需 LLM）；② LRU 路由缓存（文本+状态指纹命中直接返回）；③ 单候选无参数工具快路径跳过 LLM。

---

## 如何扩展新任务

新增一类业务任务只需**配置**，无需修改框架代码：

1. 在 `flow_config/user_flows.yml` 中新增 `slots`（槽位）与 `flows.<flow_id>`（流程定义）；
2. 如需新动作，在 `agent/handler/task/action/custom.py` 的 `register_custom_actions` 中注册一个 Action；
3. 如需补充路由关键词/提示，在 `agent/router/tool_annotations.yml` 添加同名条目；
4. 重启服务，工具注册表会自动从 YAML 生成，路由、执行、状态恢复全部自动生效。

---

## License

本项目为个人开源项目，代码仅供学习与参考。
