# mcd-diet-guard · 麦当劳膳食守门员

> **同等热量，钠含量能差 5.2 倍。**
>
> 下表 17 项餐品，热量都在 400–550 kcal 之间——热量档几乎一样，
> 钠却从 258mg 到 1343mg。麦当劳官方页面给你热量数字，
> 不告诉你**这份热量里的钠，对你意味着什么**。

| 餐品（实测） | 能量 | 蛋白 | 钠 | **钠密度** |
|---|---:|---:|---:|---:|
| 浓浓黑巧雪冰大杯 | 444 | 11 | **258** mg | 58 mg/100kcal |
| 猪柳炒双蛋堡 | 437 | 25 | 705 mg | 161 |
| 牛气满满 | 495 | 26 | 764 mg | 154 |
| 巨无霸 | 513 | 27 | 961 mg | 187 |
| 双层吉士汉堡 | 429 | 27 | 1017 mg | 237 |
| 麦辣鸡腿汉堡 | 485 | 24 | **1208** mg | 249 |
| 果然多肉 | 478 | **36** | **1343** mg | 281 |

<sub>数据来源：麦当劳 MCP Server `list-nutrition-foods` 实测返回（156 项餐品），
经 `scripts/mcp_fetch.py` 取回，非手工整理。</sub>

**mcd-diet-guard** 把 MCP 返回的真实营养数据，翻译成特定人群的阈值判定，
并给出基于真实配料明细的可执行改配方案。

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/dependencies-zero-green" alt="零依赖">
  <img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License">
  <img src="https://img.shields.io/badge/MCP-mcd.mcd.cn-orange" alt="MCP">
</p>

---

## 它解决什么问题

你打开点单页，看到的是：

```
巨无霸    513 kcal    961mg 钠    42g 碳水
```

这些数字本身不构成决策。你真正要问的是：

| 你的情况 | 你真正想知道 |
|---|---|
| 在管血压 | 961mg 是不是超过我一天该吃的量？去掉哪个配料最有效？ |
| 在控血糖 | 42g 碳水会不会顶掉一顿的额度？ |
| 在减脂 | 513kcal 是单餐上限的几倍？ |
| 在增肌 | 27g 蛋白够不够？ |
| 想要更优解 | **同样 500kcal，有没有钠低一半的选项？** |

答案就在上表里：**猪柳炒双蛋堡，437kcal / 705mg 钠**——
比巨无霸少 43kcal、少 256mg 钠，蛋白还接近（25g vs 27g）。

## 核心能力

### 1. 八类人群画像，各自的阈值口径

| 画像 | 主阈值 | 适用 |
|---|---|---|
| `hypertension` | 钠 ≤500mg/份 | 高血压、高钠敏感 |
| `diabetes` | 碳水 ≤40g、糖 ≤15g | 血糖管理 |
| `gout` | 肉类类别风险估算 | 痛风、高尿酸 |
| `weightloss` | 能量 ≤500kcal、脂肪 ≤22g | 减脂期 |
| `muscle` | 蛋白 ≥25g/份、能量 ≤900kcal | 增肌期 |
| `pregnancy` | 钠 ≤600mg、控咖啡因 | 孕期 |
| `child` | 能量 ≤500kcal、钠 ≤700mg | 儿童 6-12 岁 |
| `general` | 能量/钠粗筛 | 无特殊限制 |

阈值采用中国居民膳食营养素参考摄入量口径，可在 payload 里按个人情况覆盖。

### 2. 真实数据实测输出

以高血压画像跑同一批 MCP 真实餐品：

```
| 餐品| 能量 | 蛋白 | 钠      | 主要风险      |
| 圆筒冰淇淋   |93   |2   | 36mg    | 🟢 无超标项  |
| 大杯玉米杯   |  87  |  4  | 2mg     | 🟢 无超标项     |
| 麦乐鸡5块    |  213 |  12 | 422mg   | 🟡 接近上限   |
| 巨无霸       |  513 |  27 | 961mg   | 🔴 超标 1.9× |
| 麦辣鸡腿汉堡 |  485 |  24 | 1208mg  | 🔴 超标 2.4× |
```

麦辣鸡腿堡单项钠就达 1208mg —— 相当于成人每日推荐量（2000mg）的 **60%**，
而它并不比巨无霸更"重"（485 vs 513 kcal）。
**热量看不出钠风险，只有阈值判定能。**

### 3. 密度视角：避免被数字误导

绝对值跨餐品不可比。按每 100kcal 归一化，结论常常反转：

| 餐品 | 能量 | 钠绝对值 | **钠密度** |
|---|---:|---:|---:|
| 巨无霸 | 513kcal | 961mg | 187 mg/100kcal |
| 猪柳炒双蛋堡 | 437kcal | 705mg | 161 |
| 果然多肉 | 478kcal | 1343mg | **281** |

单看绝对值会以为"低热量 = 低风险"。密度视角才看得出
**同等热量下谁才是真正的高钠选项**。

### 4. 不只给「超标」，给可量化改配

拿到 `query-meal-detail` 的真实配料明细后，输出**能量化的改配建议**：

```
可执行的改配（数据来自套餐配料明细，非臆造）：
- 去掉酱料（钠-620mg, 能量-140kcal, 脂肪-14g）
- 芝士片 → 替换选项（钠-180mg, 能量-80kcal）
```

「去掉酱料省 620mg 钠」是配料数值相减的**确定结论**，
而非「建议少放酱料」这类模糊表述。

### 5. 三条硬约束：不编数据

项目最重要的设计原则——**输出里每个数字都可追溯**：

- ❌ 绝不臆造营养数据。MCP 没返回的字段就说「未获取到」，不填 0、不凭常识估算
- ❌ 改配建议只能来自真实配料明细。没有配料就没有建议
- ❌ 痛风判定只做**类别估算**并明确标注，绝不编造嘌呤毫克数

## 安装

### 前置条件

- Python 3.9+（**零第三方依赖**，只用标准库）
- 麦当劳 MCP Token（[申请方式](https://github.com/M-China/mcd-mcp-server#1-%E7%94%B3%E8%AF%B7-mcp-token)）

### 安装 Skill

```bash
# WorkBuddy
cp -r skill/mcd-diet-guard ~/.workbuddy/skills/
```

### 配置 MCP

复制 `mcp-config.example.json` 并填入你的 Token。
真实 Token 请只存于本地 `~/.workbuddy/mcp.json`，**不要提交进仓库**。

## 使用示例

### 拉取真实数据

```bash
export MCD_MCP_TOKEN=你的token

# 列出全部 MCP 工具（35 个）
python scripts/mcp_fetch.py --tools

# 拉取全部营养数据（实测 156 项）
python scripts/mcp_fetch.py --list-nutrition --out payload.json

# 按关键词过滤
python scripts/mcp_fetch.py --list-nutrition --keyword 巨无霸 --out bigmac.json
```

`mcp_fetch.py` 是「真实 MCP 调用」的可复现证据——
README 里的每个数字都能由它从 MCP Server 重新取回。

### 核算

```bash
# 列出所有人群画像
python scripts/nutrition_guard.py --list-profiles

# 按高血压口径核算
python scripts/nutrition_guard.py --input payload.json --profile hypertension

# 输出 JSON 供程序处理
python scripts/nutrition_guard.py -i payload.json -p diabetes --json

# 管道输入
cat payload.json | python scripts/nutrition_guard.py -p weightloss
```

### 跑回归测试

```bash
python scripts/test_guard.py
```

42 项断言，覆盖 MCP 字符串字段解析、中文别名、缺失值处理、
密度换算、改配求解、阈值边界、免责声明完整性。
测试数据固定使用 **MCP 实测原始格式**（字符串数值、扁平表头）——
用自己写的"干净"示例数据会让真实 bug 藏起来。

### 在 Skill 中对话

```
> 我血压偏高，想吃个麦当劳，帮我看看怎么点比较安全

> 减脂期，晚餐想吃麦当劳，500 大卡以内有什么选择？

> 同样 500 大卡，巨无霸和猪柳炒双蛋堡哪个更适合我？

> 这份巨无霸套餐帮我改一下，想把钠降下来
```

Skill 会自动取 MCP 真实数据 → 匹配画像 → 跑核算引擎 → 输出阈值判定与改配方案。

### payload.json 结构

```json
{
  "profile": "hypertension",
  "foods": [
    {
      "name": "巨无霸",
      "energy_kcal": 513,
      "protein_g": 27,
      "fat_g": 26,
      "carbs_g": 42,
      "sodium_mg": 961,
      "calcium_mg": 171
    }
  ]
}
```

（上例为 MCP 实测值。字段支持多别名，适配 MCP 字段随版本变化；
完整契约见 [references/data-contract.md](skill/mcd-diet-guard/references/data-contract.md)。）

## 目标用户

| 用户 | 场景 |
|---|---|
| 慢病管理人群 | 高血压、糖尿病、高尿酸，需要在快餐里做安全选择 |
| 健身与减脂人群 | 需要蛋白/热量口径的定量对比 |
| 家庭决策者 | 给儿童点餐时控制能量与钠 |
| 营养师 / 健康顾问 | 快速生成带数据依据的膳食建议初稿 |
| 对餐饮数据感兴趣的开发者 | 学习如何把 MCP 真实数据转成决策支持 |

## 项目结构

```
mcd-diet-guard/
├── README.md                      # 本文件
├── CONTEST_DECLARATION.md         # 参赛声明（官方原文，勿改）
├── MCP_INTEGRATION.md             # MCP 集成说明
├── mcp-config.example.json        # 脱敏 MCP 配置
├── workbuddy.md                   # WorkBuddy 开发上下文
├── scripts/
│   ├── mcp_fetch.py               # MCP 客户端：取数 + 格式适配
│   ├── nutrition_guard.py         # 核算引擎：阈值判定 + 改配求解
│   └── test_guard.py              # 回归测试（42 项，零依赖）
├── skill/
│   └── mcd-diet-guard/
│       ├── SKILL.md
│       └── references/
│           ├── data-contract.md
│           ├── nutrition-facts.md
│           └── mcp-calling.md
└── data/
    ├── mcd_nutrition.json         # MCP 实测全量数据（156 项）
    └── real_case.json             # README 示例对应的真实数据
```

## 设计取舍

| 决策 | 理由 |
|---|---|
| 零第三方依赖 | 任何环境可直接运行，不会有依赖地狱 |
| 数值交给脚本而非模型手算 | 跨维度密度比较手算易错，算法要可复现、可测试 |
| MCP 数据适配独立成层 | MCP 返回扁平表格式，与核算逻辑解耦，上游改格式不影响引擎 |
| 阈值口径显式输出 | 让用户知道判定依据，且知道自己可以改 |
| 改配只认真实配料 | 宁可少给建议，不给无依据的改动 |
| 字段多别名容错 | MCP 字段改名不应导致 Skill 整体失效 |

## 免责声明

本项目为**麦当劳程序员创意开发大赛参赛作品**，由参赛者独立开发，
**非麦当劳官方产品**。

项目输出仅供参考，**不构成医疗、营养或其他专业建议**；
餐品信息、营养成分、价格及供应状态以麦当劳官方渠道的实时结果为准。
如有代谢疾病请遵医嘱。

## License

Apache-2.0