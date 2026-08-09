# 分层工具路由（agent/router）

把原来的「单 Prompt 意图分类」（`agent/engine/turn_planner.py` + `turn_plan.jinja2`）
升级为**分层工具路由**：LLM 只做语言理解，路由/编排决策由代码完成；执行层（FlowEngine）完全复用。

## 架构

```
用户输入
  → RouteCache（LRU，key=文本+状态指纹）
  → RoutingOrchestrator.shortcut_route（代码级确定性规则，跳过 LLM）
      取消 / 纯闲聊 / 精确知识主题 / GUIDE（怎么操作） / 活跃任务槽位补充
  → CandidateSelector（双通道召回）
      KeywordRecallStrategy（关键词，快） + EmbeddingRecallStrategy（千问 text-embedding-v4）
  → ToolReasoner（LLM：只输出 tool_calls + 参数，紧凑候选注入）
  → ToolRanker（加权融合：embedding .10 / reasoning .55 / 参数覆盖 .20 / 动词 .10 / 模式 .05）
  → ParameterValidator（required/type/pattern 结构化校验）
  → RoutingOrchestrator.decide（四态判决：clear / ambiguous / insufficient / low）
  → TurnPlanAdapter（RoutingResult → 旧 TurnPlan，覆盖 start/resume/cancel/set_slots/焦点对象）
  → FlowEngine / KnowledgeHandler / ChitchatHandler（不变）
```

## 设计模式

| 模式 | 位置 | 说明 |
|---|---|---|
| 工厂 Factory | `agent/engine/builder.py: build_router_service` | 装配路由组件，配置驱动 |
| 策略 Strategy | `candidate_selector.py`（召回）、`tool_ranker.py`（排序） | 通道/评分可插拔 |
| 模板方法 Template Method | `router_service.py: RouterService.route` | 固定管线：缓存→规则→召回→理解→排序→校验→判决 |
| 适配器 Adapter | `orchestrator.py: TurnPlanAdapter` | RoutingResult → TurnPlan，FlowEngine 零改动 |
| 外观 Facade | `RouterService` / `CandidateSelector` | 屏蔽底层多通道细节 |
| 组合 Composite | `HybridRecallStrategy` | 多通道并集去重 |
| 缓存 | `route_cache.py` | LRU + 状态指纹 |

## 关键决策（对应文章阶段）

- **LLM 只做理解**：`ToolReasoner` 输出 `{"tool_calls": [{"tool", "parameters"}]}`，
  不输出路由/置信度/编排；四态判决在代码里（`RoutingOrchestrator.decide`）。
- **工具替代意图**（阶段七）：`ToolEntry` 统一了流程/知识/闲聊，带参数 schema；
  注册表从 `flow_config/user_flows.yml` 自动生成，注解在 `tool_annotations.yml` 补充。
- **规则优先 + 负向排除**（阶段二/三）：`rule_router.py` 只处理高确定性表达；
  「怎么做」命中 GUIDE 但「怎么做才能」负向排除。
- **双通道召回**（阶段四/五）：关键词负责锚点、embedding 负责长尾口语。
- **兜底降级**：embedding 失败 → 关键词通道；LLM 解析失败 → LOW → 闲聊兜底。

## 如何新增能力

1. **新业务流程**：改 `flow_config/user_flows.yml`（加 flow + slots），工具自动出现；
   如需补充关键词/区分提示，在 `agent/router/tool_annotations.yml` 加同名条目。
2. **新知识主题**：在 `agent/handler/knowledge/__init__.py` 的 `MOCK_KNOWLEDGE` 增加，
   并在 `tool_registry.py` 的 `KNOWLEDGE_SLUGS / KNOWLEDGE_DESCRIPTIONS` 注册。
3. **无需改核心代码**。

## 配置（agent/config/config_loader.py，可用 .env 覆盖）

- `EMBEDDING_MODEL` / `EMBEDDING_BASE_URL` / `EMBEDDING_ENABLED`（千问 embedding）
- `ROUTER_TOP_K` / `ROUTER_CACHE_SIZE` / `ROUTER_LOW_THRESHOLD` / `ROUTER_AMBIGUITY_DELTA`

## 评估

```bash
# 代码路径（无需网络，确定性 FakeLLM）
.venv/bin/python -m pytest tests/test_router.py tests/test_golden_code_path.py

# 真实 LLM + 千问 embedding（会调用 dashscope）
.venv/bin/python -m tests.eval.run_eval
```

## 预热（可选）

首次请求会懒构建 embedding 索引（一次性几秒）。部署时可在应用启动后显式预热：

```python
engine = build_dialogue_engine()
await engine._planner.warmup()
```
