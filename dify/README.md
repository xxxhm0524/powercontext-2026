# 梗王对线 —— Dify × seekdb 智能辩论擂台

> 赛题：2026 OceanBase 大赛 · Dify 赛道《Just for Fun——用 Dify 做一个好玩的智能应用》
> 一句话：**用户给一个辩题，正反双方 AI 轮流开杠，主持人负责点评毒舌收尾。**

---

## 一、先看效果

| 截图 | 说明 |
|---|---|
| `evidence/1_全绿画布.png` | Dify 工作流 7 个节点全部运行成功 |
| `evidence/2_检索命中.png` | HTTP Request 节点返回的 seekdb 检索结果（带 `move` 类别与相似度） |
| `evidence/3_辩论效果.png` | 正方 / 反方 / 主持人点评的实际发言输出 |
| `evidence/4_服务日志.png` | 后端 `[ammo]` 日志，可见每次请求的 query 与命中 id |
| `evidence/5_对比.png` | **换辩题后命中 id 完全不同** —— 语义检索真的在工作 |

第 5 张是最关键的证据：**不同辩题命中不同弹药**，说明 seekdb 不是在糊弄。

---

## 二、架构

```
用户辩题
   │
   ▼
Dify 工作流 ──HTTP──► seekdb 弹药库服务 (FastAPI + pyseekdb)
   │                        │
   │                        ├─ debate_ammo   语义检索辩论话术（素材匹配）
   │                        └─ debate_memory 金句写入 / 跨轮复用（记忆）
   │
   ├─ 正方发言（用「辩题」检索弹药）
   ├─ 反方发言（用「辩题 + 正方原话」检索 → 针锋相对）
   └─ 主持人点评（综合双方发言）
```

## 三、seekdb 在作品里干什么

这是整个作品的**技术核心**，不是摆设：

| seekdb 集合 | 职责 | 对应的赛题要求 |
|---|---|---|
| `debate_ammo` | 45 条辩论话术/梗，按辩题做**语义检索 + 招式类别过滤** | 为应用提供数据存储、查询与检索能力（素材匹配） |
| `debate_memory` | 辩论中产生的金句与战绩，**写入后可在后续轮次被检索复用** | 保存并复用应用中的记忆或上下文 |

去掉 seekdb，AI 发言就退化成普通聊天机器人的自由发挥——没有章法、不可复现、也不体现任何数据库能力。

**工作流节点与 seekdb 的对应关系：**

| # | 节点 | 作用 | 是否调用 seekdb |
|---|---|---|---|
| 1 | 开始 | 接收用户输入的辩题 | — |
| 2 | 请求 | HTTP POST `/ammo`，用**辩题**检索弹药 | ✅ 第 1 次 |
| 3 | 正方 | LLM 依据弹药生成正方立论 | — |
| 4 | 检索反方弹药 | HTTP POST `/ammo`，用**辩题 + 正方原话**检索 | ✅ 第 2 次 |
| 5 | 反方 | LLM 依据弹药针对性反驳 | — |
| 6 | 主持人点评 | LLM 综合双方发言做点评 | — |
| 7 | 直接回复 | 把点评输出到聊天框 | — |

第 4 步的设计是亮点：**把对手的原话作为检索 query**，检索到的天然就是能反驳这句话的弹药，从而实现真正的"杠"而不是自说自话。

---

## 四、快速开始

### 环境

- Python **3.11+**
- 磁盘约 500MB（含首次自动下载的 ~86MB embedding 模型）
- 首次运行需联网

### 启动

```bash
pip install -r requirements.txt
python seekdb_service.py --host 0.0.0.0
```

看到 `[ready] seekdb 弹药库服务已就绪` 即成功。浏览器打开 <http://127.0.0.1:8000/health> 应显示 `ammo_count: 45`。

> **Windows 注意**
> 1. `--host 0.0.0.0` 必须加，否则 Dify 的 Docker 容器访问不到（会得到 503）
> 2. 控制台中文乱码：先 `set PYTHONIOENCODING=utf-8`
> 3. pip 慢用清华源：`-i https://pypi.tuna.tsinghua.edu.cn/simple`
> 4. 模型下载卡住：`set HF_ENDPOINT=https://hf-mirror.com`
> 5. pylibseekdb 可能不被自动安装，报错时手动 `pip install pylibseekdb`

### 不用 Dify 也能先验一遍

```bash
python seekdb_service.py --selftest
```

直接打印三个不同辩题的检索结果——**不同辩题返回不同弹药 = seekdb 真在工作**，这段输出本身就是截图素材。

---

## 五、在 Dify 里复现

1. Dify 工作室 → **导入 DSL** → 选择 `dsl/梗王对线.yml`
2. 给工作流里的 LLM 节点配上模型（任意可用模型均可）
3. 检查两个 HTTP Request 节点的地址，本机 Docker 部署时必须是：

```
http://host.docker.internal:8000/ammo
```

> 不能写 `127.0.0.1` —— 容器内的 localhost 是容器自己。

4. Body 选 `json`，正方的：( 反方的把 `正方/text` 一起拼进 query )

```json
{ "query": "{{#开始/topic#}}", "top_k": 3 }
```

5. 预览框输入辩题开跑。

---

## 六、接口说明

### `POST /ammo` —— 检索弹药（主接口）

```json
{ "query": "大学生要不要每天打卡学习", "top_k": 3, "move": "幽默反击" }
```

- `query`：辩题，或上一轮对方的最新原话
- `top_k`：取几条，建议 2–3
- `move`：（可选）限定招式类别
- `exclude`：（可选）已用过的素材 id，避免重复引用

返回每条含 `id` / `text` / `move` / `distance` / `similarity`（`similarity = 1/(1+distance)`，越大越相似）。

### 其他接口

| 接口 | 作用 |
|---|---|
| `GET /health` | 健康检查，返回两个库的条数 |
| `POST /memory` | 写入一条记忆（金句/战绩） |
| `POST /recall` | 检索记忆，可限定 `side` |
| `POST /reload` | 改完 `data/ammunition.json` 后重新装载 |
| `GET /ammo/simple?query=&top_k=` | GET 版检索，方便直接浏览器验证 |

### 招式类别（`move` 可选值）

`偷换概念` `类比攻击` `诉诸情感` `数据轰炸` `归谬反击` `釜底抽薪` `未来想象` `以退为进` `生活观察` `权威引用` `幽默反击`

想加素材：往 `data/ammunition.json` 里按同格式加条目，再调 `POST /reload`。

---

## 七、目录结构

```
dify-app/
├── seekdb_service.py      # 后端服务（seekdb 封装 + FastAPI 接口）
├── requirements.txt
├── data/ammunition.json   # 45 条辩论弹药原始数据
├── dsl/梗王对线.yml        # Dify 工作流 DSL，可直接导入复现
├── evidence/              # 运行截图证据
└── README.md
```

> `seekdb_data/` 是 seekdb 的本地数据目录，属运行产物，**不要提交入库**。

---

## 八、已知限制

- seekdb 以嵌入式模式运行，同一时刻只支持一个进程读写数据目录，**不要同时开两个服务实例**。
- 首次启动需下载 embedding 模型，慢属正常。
- 数据存于本地 `seekdb_data/`，删除即可重置。
