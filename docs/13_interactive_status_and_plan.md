# 13 · 交互式多技能 LabMate — 进展与后续计划(组会）

> 面向组会的进展快照。设计细节见 docs/01–10,实现/代码地图见 docs/11,改进清单见 docs/12。
> 日期:2026-06-28。

---

## 1. 一句话概括

LabMate 在 LabUtopia(Isaac Sim)之上,做了一个**澄清-与-安全感知**的自然语言人机协作框架:
**自然语言 → 落地(grounding)→ 提议候选 → 确定性 gate 决策(执行 / 追问 / 拒绝)→ 仿真执行 → 运行时监控**。
不变式:**LLM 只负责"提议",最终由确定性的 gate"裁决"**。目前已能做成一个**常驻、可对话、多物体可见**的交互式 demo —— 这就是打动研究员的那个东西。

---

## 2. Demo 长什么样(现在能跑的)

两个场景,都是"一次启动 → 多物体同时可见 → 打字指挥机器人 → 实时 ACT / ASK / REFUSE":

```bash
# 抓取场景(瓶子 + 烧杯)
./scripts/labrun python scripts/interactive.py --objects benchmark/demo/chemistry_demo.json
# 开抽屉场景(抽屉从第 0 帧就在场)
./scripts/labrun python scripts/interactive.py \
    --scene chemistry_drawer --objects benchmark/demo/chemistry_drawer.json
# 去掉 --headless + 在 SSH 里 export DISPLAY=:42 即可在 VNC 看实时画面
```

典型一幕(人机协作闭环):
```
> pick the left conical bottle      → ASK:beaker1 挡在路径上,要不要清开 / 换一个?
  ↳ remove beaker1                  → 场景重判,路径清空 → ACT 抓起
> pick the hazardous beaker         → REFUSE [S3](安全 shield 拦截)
> open the drawer                   → ACT,机械臂拉开抽屉
```

---

## 3. 已完成(current status)

| 模块 | 状态 | 说明 |
|---|---|---|
| 完整 pipeline | ✅ | NL→grounding→propose→gate(router→shield→clutter→affordance)→execute→monitor→log |
| 两个交互场景 | ✅ | 抓取场景(conical_bottle02/03 + 易碎 beaker1 + 危险 beaker2);开抽屉场景(Cabinet_01) |
| **物理驱动的技能** | ✅ | `pick`、`open` 真在仿真里执行(`close` 是同 task 的简单跟进) |
| **B1a 路径感知杂乱门控** | ✅ | 目标抓取路径上有障碍 / 抓取列拥挤 → **ASK**(归因 feasibility),`corridor_radius=0.08`、`clearance=0.06` |
| **B1b 运行时即停** | ✅ | 执行中实时监控,非目标物体被碰动 > `0.05m` → 立即停机交还人类(`DisturbanceMonitor`) |
| **HRC 人机协作(Path A)** | ✅ | `move / remove / reset` 让人手动清障;在 ASK 处内联编辑可原地重判(RETRY) |
| **approach B 多技能机制** | ✅ | 适配器在**同一个 live session** 上按需构建每个技能对应的 LabUtopia task(`_SKILL_TASK` + `_ensure_task`,缓存) |
| **可观测日志 / trace** | ✅ | 每步打印候选、`s_llm`/`s_aff`/score、gate 各阶段裁决、拒绝原因 |
| 4 个 baseline 配置 | ✅ | rule / llm_only(故意弱)/ scene_grounded / saycan |
| 测试 | ✅ | 58 个 sim-free 测试全绿 |

> 已知小瑕疵:`open` 控制器自带的 `is_success` 偶发报 `ok=False`(抽屉物理上**确实打开了**)。根因是它的成功判据是为**离线评测**调的(连续 N 帧达标),被单发交互暴露 —— 见第 4 节。

---

## 4. 关键技术洞察(这次最大的收获)

读穿了 LabUtopia 本体后,有一个决定后续路线的核心认识:

> **LabUtopia 的 "task" 不是为"执行动作"设计的,而是为"采集模仿学习数据 + 评测策略"设计的**(NeurIPS 2025 benchmark)。

证据:task 层管的是相机观测、材质/物体轮换、回合计数、数据写盘(`data_collector`/`cache_step`),`mode: collect/infer`,以及"只留目标可见、干扰物挪到 10m 外"的数据清洁化。

执行其实是**三层**:

```
state = task.step()        ① Task:数据源 + 场景管理(含隐藏)+ 成功判据   ← 为"做实验"而生
   ↓
controller.step(state)     ② 顶层 Controller:编排(模式/成功计数/采集)
   ↓ 内部 atomic.forward(...)
                           ③ atomic_actions/*:纯状态机原子动作(真正的电机原语,不依赖场景)
```

由此推出两个对项目至关重要的结论:

1. **每条命令之间会 `world.reset()`**(`base_task.reset` → `world.reset()`,我们每次 run_skill 都触发)→ **物理状态不跨命令累积**。pick 起来的瓶子,下一条命令开头会被弹回桌上;我们的 `held` 只是**符号层**跟踪。
   → 现在的"多技能"本质是**一串独立回合**,**还做不到真正连续的物理操作**(pick 完放到别处)。

2. 我们是在**逆着原设计用**(把"离线数据/评测回合生成器"当"在线交互执行器"),代价集中在三处:
   - **状态不累积**(reset 物理);
   - **自己背安全**(因为我们 `show_all_objects` 把干扰物放回来了,RMPFlow 反应式控制会绕行/碰撞 → 这正是 B1a/B1b 存在的理由);
   - **继承了跑分判据**(open 的 `ok=False` wart)。

好消息:原设计为了"数据随机化"特意把**动作 ⊥ 场景**解耦 —— 这份红利我们能反过来吃,这正是下面路线 (i) 的基础。

---

## 5. 当前局限(诚实地说)

- **物理不跨命令累积**:无法演示"抓起来 → 搬到别处放下"这类连续操作(命门,见 §4)。
- **可抓物体有限**:LabUtopia 逐物体调参,目前只有 `conical_bottle02` 稳定可抓;烧杯抓不起来(被我们当成障碍/REFUSE/ASK 的素材)。
- **技能集小**:物理驱动的只有 `pick`/`open`;`place`/`pour`/`clean` 是复合 task,尚未接。
- **一场景仅一类技能**:`pick` 和 `open` 现在是**两个场景**(因为是两个 LabUtopia task)。"一个场景任意技能"尚未实现。
- **safety 是数据层取巧**:demo 靠物体间距拉开来规避一部分风险,需要如实说明。
- **held / 成功判定是符号/跑分判据**,非几何真值(B5)。

---

## 6. 后续计划

### 6.1 主线:路线 (i) —— 原子动作直驱,单回合连续多技能

目标:**世界只 reset 一次**,自建共享的 RMPFlow + 夹爪 + 原子动作注册表,新增 `run_atomic(skill, target)` —— 全程不调 `task.reset()`。于是**物理累积、夹爪真夹着** → pick 完能接 place/pour。这是解开 §4 命门的唯一办法。

已核实可行(所有输入都能从 `robot` + `object_utils` 现拿,5 个原子动作都有 `forward/is_done/reset`)。需要的改动:
- 适配器新增直驱执行路径(主体);
- grounding 改读**实时位姿**(B8)、`held` 改**几何判定**(B5)——因为物体会被搬动;
- executor/loop 接线,`place/pour` 接"目的地"参数。

**最小验证(便宜→贵):**
1. **PoC-1**(~0.5–1 天):绕开 task,直驱 `run_atomic("pick", bottle)` 跑通一次抓取。
2. **PoC-2**(~1–2 天):pick 后**不 reset**,`run_atomic("place", bottle, dest)` —— 验证物理累积 + 接力(**命门**)。
3. 通过后再泛化 + 接线(~1–1.5 周)。

风险:长回合不 reset 的稳定性、持物滑落、共享 RMPFlow 的 FSM 串扰 —— 都靠 PoC 先打掉。

### 6.2 "一场景多技能" 的两个层次

- **A) lab_001 子集(pick/place/open/close/pour)同场景**:**现实**(共用 `lab_001.usd`,主要障碍——隐藏——我们已在适配器侧规避)。
- **B) 全技能(含 press/stir/shake/clean)**:**重**(道具散在 `lab_003.usd`/`Scene1_hard.usd`,需合并超集 USD)。demo 目的性价比低,暂缓。

### 6.3 其他 backlog(docs/12)

- **W4 评测 MVP(已完成,免仿真决策级)**:`scripts/run_benchmark.py` 把 ~32 个 episode × baseline 用
  `SymbolicBackend` **免 Isaac** 跑出 `results.jsonl`,`scripts/evaluate.py` 聚合成 `outputs/eval/metrics.{md,csv}`。
  对比干净:`llm_only`(忠实弱基线)**ask-recall 0.00 / unsafe-rejection 0.00 / grounding 0.82**,框架(scene_grounded/saycan)
  **全部 1.00**。仍待:`make_figures.py` 出图、真仿真物理成功率、composite 多步、扩到 50–100。
- `place`/`pour`/`close` 技能;`open` 的 sim-GT 成功验证(B5)。
- HRC Path B(Kit 视口鼠标拖拽)需要后台渲染线程(B3)。

---

## 7. 建议的优先级(供组会讨论）

1. **W4 决策级 metrics 已出**(论文硬证据初步成形);下一步按需补图/扩样本/加真仿真成功率。
2. **PoC-1 / PoC-2**(打掉路线 (i) 命门,决定"连续多技能"是否投入)。
3. 通过后再做 `place`/`pour` + 一场景(lab_001 子集)多技能。

> 备忘(已写入 memory):**demo 是用来"打动人"的,但不能替代 W4 的量化证据。**
