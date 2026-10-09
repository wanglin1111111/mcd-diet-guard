---
name: mcd-diet-guard
description: 读懂麦当劳 MCP 返回的真实营养与配料数据，按高血压、高血糖、痛风、减脂、增肌、孕期、儿童八类人群画像逐项核算能量/钠/碳水/糖/脂肪风险，并基于 query-meal-detail 的真实配料明细给出可量化的改配削减方案。当用户说「我想吃麦当劳但要控钠」「糖尿病能点巨无霸吗」「减脂期麦当劳怎么点」「痛风能吃麦辣鸡腿堡吗」「帮我把套餐改一下降低钠摄入」「这份套餐热量超了吗」「健身增肌选哪个套餐」，或需要为特定人群点单、控钠控糖控热量、评估某份麦当劳套餐是否适合自己时使用。
license: Apache-2.0
compatibility: "Requires Python 3.9+ (zero third-party deps); needs 麦当劳 MCP Server (https://mcp.mcd.cn) with a valid token."
metadata:
  author: wanglin1111111
  version: "1.0.0"
  mcp-server: "https://mcp.mcd.cn"
  mcp-tools: "list-nutrition-foods, query-meals, query-meal-detail, now-time-info"
---

# 麦当劳膳食守门员

## 这个 Skill 解决什么

麦当劳官方渠道能看到热量，但**看不到「对我意味着什么」**。同样一份巨无霸，
高血压人群看到的是 961mg 钠（占成人每日推荐量 48%），增肌人群看到的是 27g 蛋白。

本 Skill 的唯一职责：把 MCP 返回的**真实营养数值**翻译成**特定人群的阈值判定**，
并给出**基于真实配料明细的改配方案**。

## 核心约束（不可违背）

★ 判据：任何输出数字都必须能追溯到 MCP 返回值或用户显式提供的数值。
  **绝不臆造营养数据、餐品价格、门店信息。** MCP 没返回的字段就说「未获取到」，
  不填 0、不用常识估算。
  反例：不能因为「可乐大概含糖 40g」就写进表格——那是编的。
  触发词：用户问某个餐品多少卡、MCP 返回字段缺失时。

★ 判据：改配方案只能来自 `query-meal-detail` 返回的真实配料与替换项。
  没有配料明细就没有改配建议，只给阈值判定。
  反例：不要为没有返回配料的面包类单品编造「去酱」建议。
  触发词：套餐、替换、改一下、配料。

★ 判据：涉及疾病（高血压、糖尿病、痛风、孕期）的输出一律附「不构成医疗建议」
  与「遵医嘱」。阈值采用中国膳食指南口径并**显式写出出处口径**。
  反例：不要说「这个方案能控制你的血糖」——只能说「按通用阈值判定为超标」。
  触发词：血压、血糖、尿酸、孕期、痛风、糖尿。

## 工作流

### 第 1 步：取真实营养数据

首选 `list-nutrition-foods`——它一次返回常见餐品的营养成分，
是本 Skill 的数据主干。

- 若用户要点的餐品不在返回里 → 用 `query-meals` 查当前门店在售菜单拿到餐品编码
- 拿到编码后用 `query-meal-detail` 取**配料组成与可替换选项**（改配建议的必需来源）
- 用户提到具体日期/活动时，可调 `campaign-calendar` 补充活动信息（不作为营养依据）

判据：`list-nutrition-foods` 未覆盖目标餐品时，**不要跳过**，
     要么 `query-meals` 补齐，要么明确告诉用户该餐品营养数据未获取到。

### 第 2 步：确定人群画像

按用户表述映射到 8 个画像之一；**用户没说就问，不要默认套 `general`**。

| 画像 key | 触发信号 | 主阈值 |
|---|---|---|
| `hypertension` | 血压高、控钠、钠敏感 | 钠 ≤500mg/份 |
| `diabetes` | 血糖、胰岛素、控糖 | 碳水 ≤40g、糖 ≤15g |
| `gout` | 尿酸、痛风 | 肉类类别（估算） |
| `weightloss` | 减脂、瘦身、控热量 | 能量 ≤500kcal |
| `muscle` | 增肌、健身、蛋白 | 蛋白 ≥25g/份 |
| `pregnancy` | 孕期、孕妇 | 钠 ≤600mg、咖啡因 |
| `child` | 儿童、孩子 | 能量 ≤500kcal、钠 ≤700mg |
| `general` | 未指明人群 | 能量/钠粗筛 |

用户自述具体情况（如「我一天只吃 400kcal」）时，
用 `--` 传入 `constraints` 覆盖默认阈值，不要去改脚本源码。

### 第 3 步：跑核算引擎

把 MCP 返回的数值整理成 JSON，交给脚本算。**不要手算**——
跨维度比较（钠密度 vs 蛋白密度）手算容易错。

```bash
# 1) 看可用画像
python scripts/nutrition_guard.py --list-profiles

# 2) 核算（示例）
python scripts/nutrition_guard.py --input payload.json --profile hypertension

# 3) 需要程序化处理时用 JSON 输出
python scripts/nutrition_guard.py --input payload.json --profile diabetes --json

# 4) 临时覆盖阈值
python scripts/nutrition_guard.py --input payload.json --profile weightloss \
  --input <(...)   # 或直接在 JSON 里写 "constraints": {"energy_kcal": 400}
```

payload.json 结构见 [references/data-contract.md](references/data-contract.md)——
**字段名支持多别名**（`energy_kcal` / `energy` / `calorie` / `热量` 均可），
以适配 MCP 字段命名随版本变化。

### 第 4 步：呈现结论

给用户的输出按这个顺序，前置最重要信息：

1. **一句话结论**——能不能吃、风险在哪（不要先铺方法论）
2. **超标表格**——哪一项超了、超多少（给倍数，如「2.1×」）
3. **改配方案**——去掉/替换哪个配料，省下多少钠和热量
4. **更优替代**——若 MCP 返回中有同类低风险餐品，一并列出
5. **免责声明**——疾病相关画像必带

## 关键判据速查

★ 判据：优先用**密度**而非绝对值做跨餐品比较。
  巨无霸 961mg 钠看着吓人，但 513kcal 下钠密度 187mg/100kcal；
  同能量档的猪柳炒双蛋堡 437kcal / 705mg，密度 161mg/100kcal 反而更低——
  单看绝对钠会误判「热量低的更健康」。
  判据：比较两个不同大小的餐品是否高钠，看钠密度；比较同热量则直接看绝对值。
  触发词：哪个更健康、哪个钠更低、对比。

★ 判据：`gout` 画像的嘌呤判定只能做**类别估算**（依据标签命中内脏/红肉/海鲜分级），
  必须标注「估算」，不能伪装成嘌呤含量实测值。
  反例：绝不写「麦辣鸡腿堡嘌呤含量 120mg」——MCP 不提供该数据。
  触发词：痛风、尿酸、嘌呤。

★ 判据：`sodium_density > 150 mg/100kcal` 才提示高钠密度。
  这是实测校准过的界（麦当劳主餐多落在 60~210 区间），不要凭直觉改这个数。
  反例：设成 2.5 会让几乎每样餐品都误报，等于没有筛选力。
  触发词：修改阈值、调参、密度界。

## 参考文档

| 文件 | 何时读 |
|---|---|
| [references/data-contract.md](references/data-contract.md) | 组装 payload.json 前必读：字段别名表、完整示例、components 改配结构 |
| [references/nutrition-facts.md](references/nutrition-facts.md) | 需要引用阈值出处（中国膳食指南口径）、或解释某个指标为何这样设阈值时 |
| [references/mcp-calling.md](references/mcp-calling.md) | 需要完整 MCP 调用链路、字段缺失时的降级策略、限流（600次/分）规避时 |