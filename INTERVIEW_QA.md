# 澶?Agent 鏃呰瑙勫垝绯荤粺 鈥斺€?闈㈣瘯 Q&A

> 姣忔潯闂鍖哄垎 **Demo 绾у洖绛?*锛堥潰璇曞畼绉掕繃锛夊拰 **钀藉湴绾у洖绛?*锛堥潰璇曞畼杩介棶锛夈€?> 鎶€鏈粏鑺傚搴斾唬鐮佷綅缃紝闈㈣瘯鏃跺彲瀹氫綅鍒板叿浣撴枃浠跺拰鏂规硶銆?
---

## 涓€銆丄gent 鏋舵瀯涓庣姸鎬佺鐞?
### Q1: 涓轰粈涔堥€?LangGraph 鑰屼笉鏄?CrewAI/AutoGen锛?
**Demo 绾?*锛歀angGraph 鏀寔澶?Agent锛屾瘮 CrewAI 鐏垫椿銆?
**钀藉湴绾?*锛氫笁涓伐绋嬬悊鐢憋紝涓嶆"瀹冩敮鎸佸 Agent"锛?
1. **鎵嬪啓 StateGraph 鑰岄潪鍐呯疆 Supervisor**銆侰rewAI 鐨?Supervisor 鏄粦鐩掞紝鏃犳硶鍦ㄦ媶瑙ｅ悗娉ㄥ叆涓氬姟閫昏緫銆傛垜鐨?Coordinator 瀹屽叏鎵嬪啓锛坄langgraph_agents.py:815`锛夛紝LLM 鍔ㄦ€佺敓鎴?`subtasks` 瀛楀吀鍚庣敤 `_coordinator_router` 鍋氫袱姝ユ潯浠跺垎鍙戔€斺€斿瓙 Agent 鍐呴儴杩樻湁鐙珛 `call_llm 鈬?tool_call` 寰幆锛坄:165` 鐨?`_run_analysis_agent_with_private_context`锛夛紝杩欑矑搴︾殑鎺у埗鍦?CrewAI 涓仛涓嶅埌銆?
2. **Checkpointer 妗嗘灦鍐呯疆**銆俙workflow.compile(checkpointer=SqliteSaver)` 涓€琛屾寔涔呭寲瀹屾暣鍥剧姸鎬侊紙`:813`锛夈€備笉鐢ㄨ嚜宸卞簭鍒楀寲 TypedDict銆?
3. **LangSmith/SSE/Send API** 鍏ㄩ摼璺敓鎬佲€斺€擠emo 椤圭洰閫氬父鍙敤 `graph.invoke()`锛屾垜鐨勫叏鐢ㄤ簡銆?
### Q2: 澶氫釜 Agent 涔嬮棿鎬庝箞鍏变韩涓婁笅鏂囷紵鎬庝箞閬垮厤骞跺彂鍐茬獊锛?
**Demo 绾?*锛氬畾涔変簡涓€涓?TypedDict 鍏变韩鐘舵€併€?
**钀藉湴绾?*锛歚TravelPlanState` 涓変釜鍏抽敭璁捐锛?
1. **瀛楁闅旂**銆傛瘡瀛楁鐢辩壒瀹?Agent 鐙崰鍐欏叆锛歚agent_outputs` 鈫?鍒嗘瀽 Agent锛堟寜 agent_name 鍋?key 闅旂锛夈€乣final_plan` 鈫?Summarizer 鐙崰銆傚苟鍙戜笉鍔犻攣涔熶笉鍐茬獊銆?2. **澧為噺鍚堝苟**銆俙Annotated[List, add_messages]`锛圠angGraph 鏈哄埗锛夆€斺€旇拷鍔犱笉瑕嗙洊銆傛櫘閫?`list` 浼氭暣浣撴浛鎹㈠巻鍙层€?3. **涓夌骇瀛樺偍**锛歋QLite锛堝浘蹇収锛岄噸鍚仮澶嶏級鈫?Redis锛堢儹鐘舵€侊紝SSE 鎺ㄩ€侊級鈫?PostgreSQL锛堟柟妗堝綊妗ｏ級銆?
杩介棶"涓轰粈涔堜笉鍏ㄦ斁 Redis锛?锛欰gent 鐘舵€佸嚑鍗?KB 娑堟伅鍘嗗彶锛孯edis 鍐呭瓨鎴愭湰楂橈紝SQLite 纾佺洏鏇撮€傚悎銆?
### Q3: Coordinator 鎷嗚В vs 纭紪鐮?Pipeline锛?
**Demo 绾?*锛歅ipeline 绠€鍗曞彲闈犮€?
**钀藉湴绾?*锛歅ipeline 鍋氫笉鍒板姩鎬佸姣斺€斺€旂敤鎴疯"姣旇緝鏉窞鍜岃嫃宸?锛孭ipeline 闇€璺戜袱閬嶃€侰oordinator LLM 涓€娆＄敓鎴?6 涓瓙浠诲姟骞跺彂銆傚叧閿笉鏄媶瑙ｆ湰韬紝鏄媶瑙ｅ悗鐨?*瀹归敊**锛氬崟 Agent 澶辫触鏍囪 `failed`锛孲ummarizer 鏍囨敞"鏆傛湭鑾峰彇"锛涘叏澶辫触闄嶇骇涓轰覆琛岄噸寤猴紙`_build_analysis_fallback_output:423`锛夈€?
---

## 浜屻€佸伐鍏疯皟鐢ㄤ笌 API 闆嗘垚

### Q4: 15 涓?Tool 鎬庝箞璁?LLM 鍑嗙‘璋冪敤锛?
**Demo 绾?*锛氱敤浜?@tool 瑁呴グ鍣紝GPT 鑷繁鍒ゆ柇銆?
**钀藉湴绾?*锛氫笁涓敓浜х骇鑰冭檻锛?
1. **Schema description 鍐冲畾鍑嗙‘鐜?*銆俙Field(description="鍑哄彂鍩庡競锛屼緥濡傦細鍖椾含銆佷笂娴?)` 鑰屼笉鍐?"鍑哄彂鍩庡競"鈥斺€擫LM 闇€瑕佺煡閬撲紶鍩庡競鍚嶈€岄潪 IATA 浠ｇ爜銆?2. **姣?Agent 鐙珛 LLM 瀹炰緥**锛坄_new_llm():117`锛夈€俙ChatOpenAI` 澶氱嚎绋嬪鐢ㄤ細杩炴帴姹犳薄鏌撯€斺€擠emo 鍗曞疄渚嬬敤鍒板簳锛岀敓浜у苟鍙戝繀鍑洪棶棰樸€?3. **宸ュ叿缁撴灉鍙娴?*銆俙tool_artifacts` 璁板綍姣忔璋冪敤鐨勫弬鏁?杩斿洖鍊?success 鏍囪+鏃堕棿鎴炽€侺LM 鍚庣画杞璇诲け璐ヨ褰曞喅瀹氶噸璇曟垨璺宠繃銆?
### Q5: 涓轰粈涔堝寘涓€灞?Provider 鎶借薄锛?
**Demo 绾?*锛氭柟渚垮垏鎹㈡暟鎹簮銆?
**钀藉湴绾?*锛歚BaseProvider` ABC 瑙ｅ喅 Agent 浠ｇ爜涓嶅簲鎰熺煡 HTTP/閲嶈瘯/缂撳瓨銆傛瘡涓?Provider 鐨?`search()` 鍐呴儴娉ㄥ叆 `retry_api_call` + `cache_api_call`銆侫gent 璋?tool 涓嶆劅鐭ヨ繖浜涙í鍒囧眰銆傝拷闂?API Key 鎬庝箞绠★紵"锛歅ydantic Settings 鍚姩鏍￠獙锛孠ey 涓虹┖鏃?tool 杩斿洖闄嶇骇鎻愮ず鑰岄潪鎶涘紓甯搞€?
### Q6: 楂樺痉涓嶈繑閰掑簵浠锋牸鎬庝箞澶勭悊锛?
鍒嗗眰闄嶇骇锛氶珮寰锋彁渚涚湡瀹炲悕绉?璇勫垎/鍦板潃 + Mock 鍩庡競鍩哄噯浠?脳 鏄熺骇绯绘暟銆傝緭鍑烘爣娉?鍙傝€冧环锛堝疄闄呬互鎼虹▼/椋炵尓涓哄噯锛?銆侻ockPriceProvider 鍜?AmapHotelProvider 瀹炵幇鍚屼竴鎺ュ彛鈥斺€旀崲鐪熷疄 API 涓嶆敼 Agent 浠ｇ爜銆?


## 三、记忆与持久化

### Q7: 记忆系统为什么是"双轨"？

**Demo 级**：MemorySaver 记对话历史。

**落地级**：MemorySaver 进程内存，重启即丢。我的方案：

| 存储 | 技术 | 存什么 | 检索方式 |
|------|------|--------|---------|
| 图状态 | SqliteSaver | 消息历史+Agent输出+子任务进度 | thread_id 精确读 |
| 语义记忆 | Chroma | 历史行程摘要 | 向量相似度 |
| 用户画像 | Chroma profile | 偏好/出行方式/星级 | user_id 精确读 |

设计决策：图状态不用 Redis（消息历史几十 KB，SQLite 磁盘更合适）；语义记忆用向量而非 SQL（"上次那种类型的酒店"需要语义相似度）；三者分工：热状态（Redis TTL 24h）→ 图快照（SQLite 永久）→ 归档（PostgreSQL）。

---

## 四、成本控制

### Q8: 5 个 Agent 都调 LLM，Token 怎么控？

**Demo 级**：GPT-4o-mini 不贵。

**落地级**：三层控制：
1. **模型分级**：Coordinator（GPT-4o 复杂推理）+ 4 分析 Agent（GPT-4o-mini 单一工具调用）。单次规划约 $0.02-0.05，全用 GPT-4o 要 $0.15-0.30。
2. **缓存削减**：航班 24h/天气 1h 分级 TTL，命中即零 Token。
3. **调用上限**：每 Agent 最多 5 次 tool 调用，防幻觉无限循环。

---

## 五、可靠性

### Q9: 外部 API 不可用怎么处理？

**Demo 级**：try/except 打印日志。

**落地级**：四层独立容错：
1. **Provider**：Tenacity 指数退避（3 次，2s→4s→8s）
2. **Tool**：异常返回降级文本而非抛异常——LLM 看到后建议替代方案
3. **Agent**：单 tool 失败不阻塞同 Agent 其他调用（`add_tool_artifact(..., success=False)`）
4. **图**：单 Agent 失败不阻塞整体（`as_completed` 中 try/except 隔离）

---

## 六、可观测性

### Q10: Agent 出问题怎么排查？

**Demo 级**：看 print 日志。

**落地级**：两套分层：
- **日常**：Loguru JSON（`core/logging.py`）——10MB 轮转，7 天过期，`jq` 可搜索
- **深度**：LangSmith Trace——每个 LLM 调用的 tokens+延迟+Tool 输入输出。可回溯"为什么 Supervisor 没调 Hotel Agent？"

---

## 七、Demo vs 落地对照总表

| 技术点 | Demo 做法 | 生产做法 | 代码位置 |
|--------|----------|---------|---------|
| Agent 图 | 复制 tutorial | 手写 StateGraph+自定义路由 | `langgraph_agents.py:822` |
| 工具 | requests 包 try/except | BaseProvider ABC + retry/cache | `apis/base.py` `core/retry.py` |
| 并发 | 注释写"4 Agent 并发" | ThreadPoolExecutor+as_completed+错误隔离 | `:1558` |
| 记忆 | MemorySaver | SqliteSaver+Chroma+Redis+PG 三级 | `:813` |
| 日志 | print() | Loguru JSON + LangSmith | `core/logging.py` |
| 配置 | os.getenv | Pydantic Settings 启动校验 | `core/config.py` |
| 错误 | except: pass | 四层容错(重试→降级→标记→汇总) | `core/retry.py` + tool 层 |
| 成本 | 全用 GPT-4o | 模型分级 + 分级 TTL 缓存 | `langgraph_config.py` + `core/cache.py` |

---

## 八、面试回答框架

面试官问任何技术点，用这个模板回答：

```
Demo 的做法是 [简单方案]
但在生产环境，会遇到 [具体问题]
所以我做了 [改进措施]
具体实现是 [代码位置]
这样做的结果是 [可感知改进]
```