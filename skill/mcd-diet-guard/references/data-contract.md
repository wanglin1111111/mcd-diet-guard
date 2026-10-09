# 数据契约：MCP 返回 → payload.json

## 为什么要做字段别名

麦当劳 MCP Server 的返回字段命名可能随版本调整（当前 v1.0.9）。
脚本对每个营养字段都接受多个别名，任一命中即可，避免因上游改字段名而整体失效。

## 字段别名表

| 逻辑字段 | 可接受的 JSON 键名 |
|---|---|
| `name` | `name` `foodName` `food_name` `title` `itemName` `名称` |
| `energy_kcal` | `energy_kcal` `energy` `calorie` `calories` `kcal` `energyKcal` `热量` `能量` |
| `protein_g` | `protein_g` `protein` `蛋白质` |
| `fat_g` | `fat_g` `fat` `脂肪` |
| `carbs_g` | `carbs_g` `carbs` `carbohydrate` `carbohydrates` `carb` `碳水化合物` |
| `sodium_mg` | `sodium_mg` `sodium` `na` `钠` |
| `calcium_mg` | `calcium_mg` `calcium` `钙` |
| `sugars_g` | `sugars_g` `sugar` `sugars` `糖` |
| `satfat_g` | `satfat_g` `saturatedFat` `saturated_fat` `satfat` `饱和脂肪` |
| `transfat_g` | `transfat_g` `transFat` `trans_fat` `transfat` `反式脂肪` |
| `tags` | `tags` `tag` `labels` `categories` `category` `标签`（字符串或数组均可） |

★ 缺字段不等于 0：`sugars_g`、`satfat_g`、`transfat_g` 缺省为 `null`，
脚本会**跳过该项阈值检查**，而不是当作 0 通过。
`energy_kcal` 等主要营养项缺省为 0，此时密度类计算会返回 0 并跳过提示。

## 最小示例（够跑起来）

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

注意：上面这些数值来自项目内的示例文件，**实际使用时必须换成 MCP 本次返回的值**。

## 完整示例：带配料改配

配料明细来自 `query-meal-detail`。**只有拿到配料，才能给改配方案。**

```json
{
  "profile": "hypertension",
  "constraints": { "sodium_mg": 400 },
  "foods": [
    {
      "name": "巨无霸",
      "energy_kcal": 513,
      "protein_g": 27,
      "fat_g": 26,
      "carbs_g": 42,
      "sodium_mg": 961,
      "calcium_mg": 171,
      "satfat_g": 12,
      "tags": ["beef", "sauce", "cheese", "bun"],
      "components": [
        {
          "name": "酱料",
          "sodium_mg": 620,
          "energy_kcal": 140,
          "fat_g": 14,
          "removable": true
        },
        {
          "name": "芝士片",
          "sodium_mg": 180,
          "energy_kcal": 80,
          "swap": { "sodium_mg": 0, "energy_kcal": 0, "fat_g": 0 }
        }
      ]
    }
  ]
}
```

### components 的两种形态

| 形态 | 字段 | 脚本行为 |
|---|---|---|
| **可去掉** | `"removable": true` | 生成「去掉X」，削减量 = 该配料的全部营养值 |
| **可替换** | `"swap": { ... }` | 生成「X → 替换选项」，削减量 = swap 值 − 原值 |

★ `removable` 与 `swap` 都为 false/缺省时，该配料被忽略——
  不要把「可能能去掉」写成 `removable: true`，那是替用户做了没依据的决定。

`swap` 里只写变化了的字段即可；缺省字段按原值处理，
即削减量以原配料为基准逐项计算。

## constraints 覆盖阈值

用户自述的具体限制优先于画像默认值：

```json
{
  "profile": "weightloss",
  "constraints": { "energy_kcal": 400, "sodium_mg": 300 },
  "foods": [ ... ]
}
```

只有 `constraints` 里出现的键会被覆盖，其余沿用画像默认。

## 从 MCP 响应到 JSON 的步骤

1. `list-nutrition-foods` → 取出目标餐品的营养项，按别名表映射键名
2. `query-meal-detail` → 取出 `components`，标注 `removable` / `swap`
3. 组装成上面的结构，`profile` 按用户情况填
4. 存成临时 JSON（放系统临时目录，**不要提交进仓库**），跑脚本

★ 别名表是接口层的容错，不是让你随意造字段。
  映射前先看一眼 MCP 实际返回的键名，照着填。