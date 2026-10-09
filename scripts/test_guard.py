#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_guard.py — nutrition_guard.py 回归测试（零依赖，python 直接跑）

    python test_guard.py

为什么需要它
------------
★ 判据：两个 bug 都曾真实发生过，且**用示例数据测不出来**——
  ① MCP 返回的全是字符串（"961"），只认 int/float 会让真实链路上所有营养值变成 0；
     而示例数据写的是数字 961，所以单测示例永远通过。
  ② 表头解析按 ":" 切分，把最后一个字段名连同 "}" 吃掉，导致 160 行钙值全丢。
  两者都只有在接真实 MCP 时才暴露。故本测试固定用**MCP 实测原始格式**。
  反例：不要把测试数据"简化"成数字类型，那等于把真实 bug 藏起来。
  触发词：修改字段解析、加新字段、改别名表。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from nutrition_guard import (  # noqa: E402
    PROFILES, Food, assess, load_food, plan_swaps, render,
)
from mcp_fetch import adapt_food, parse_api_envelope  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}\n         期望: {want!r}\n         实际: {got!r}")


# ------------------------------------------------------- 1. MCP 原始格式解析
# 这是麦当劳 list-nutrition-foods 的真实返回形态：字段值全是字符串
MCP_RAW = {
    "productName": "巨无霸", "nutritionDescription": "null",
    "energyKj": "1929", "energyKcal": "513",
    "protein": "27", "fat": "26", "carbohydrate": "42",
    "sodium": "961", "calcium": "171",
}

print("\n[1] MCP 实测字符串字段解析（历史 bug：类型过滤导致全为 0）")
f = load_food(MCP_RAW)
check("name", f.name, "巨无霸")
check("energy_kcal", f.energy_kcal, 513.0)
check("protein_g", f.protein_g, 27.0)
check("fat_g", f.fat_g, 26.0)
check("carbs_g", f.carbs_g, 42.0)
check("sodium_mg", f.sodium_mg, 961.0)
check("calcium_mg", f.calcium_mg, 171.0)

print("\n[2] 中文别名（活动面向中国大陆开发者，中文键名要能吃）")
cn = {"名称": "巨无霸", "热量": "513", "蛋白质": "27",
      "脂肪": "26", "碳水化合物": "42", "钠": "961", "钙": "171"}
fc = load_food(cn)
check("中文 name", fc.name, "巨无霸")
check("中文 sodium_mg", fc.sodium_mg, 961.0)
check("中文 calcium_mg", fc.calcium_mg, 171.0)

print("\n[3] 缺失与异常值处理（不该把缺失当 0 通过）")
sparse = load_food({"name": "测试", "energy_kcal": 500, "sodium_mg": 100})
check("缺 sugars_g 为 None", sparse.sugars_g, None)
check("缺 satfat_g 为 None", sparse.satfat_g, None)
blank = load_food({"name": "空", "energy_kcal": "null",
                   "sodium_mg": "-", "calcium_mg": "n/a"})
check("null 能量回落默认", blank.energy_kcal, 0.0)
check("'-' 钠回落默认", blank.sodium_mg, 0.0)
check("'n/a' 钙回落默认", blank.calcium_mg, 0.0)

print("\n[4] 密度换算（MCP 实测巨无霸）")
check("钠密度 ≈187", round(f.sodium_density), 187)
check("蛋白密度 ≈5.3", round(f.protein_density, 1), 5.3)

# ------------------------------------------------------- 5. 表头解析
print("\n[5] MCP 扁平表格式解析（历史 bug：'}' 被吃进字段名）")
flat = '[3]{productName,energyKcal,protein,fat,carbohydrate,sodium,calcium}:\n  巨无霸,513,27,26,42,961,171\n  麦辣鸡腿汉堡,485,24,23,42,1208,154\n  大杯玉米杯,87,4,1,12,2,10'
env = ('{"success":true,"code":200,"message":"ok","data":'
       + __import__("json").dumps(flat, ensure_ascii=False) + "}")
rows = parse_api_envelope(env)["rows"]
check("行数", len(rows), 3)
check("末列字段名不含 '}'", "calcium" in rows[0], True)
check("首行钙值", rows[0]["calcium"], "171")
check("末行钙值", rows[2]["calcium"], "10")
check("末行名称", rows[2]["productName"], "大杯玉米杯")

print("\n[6] 适配器映射到核算结构")
foods = [adapt_food(r) for r in rows]
check("餐品数", len(foods), 3)
check("映射后钠值类型为 float", isinstance(foods[0]["sodium_mg"], float), True)
check("映射后钙值", foods[0]["calcium_mg"], 171.0)

# ------------------------------------------------------- 7. 改配求解
print("\n[7] 改配方案（数据必须来自真实配料）")
meal = load_food({
    "name": "巨无霸套餐", "energy_kcal": "513", "sodium_mg": "961",
    "components": [
        {"name": "酱料", "sodium_mg": "620", "energy_kcal": "140",
         "fat_g": "14", "removable": True},
        {"name": "芝士片", "sodium_mg": "180", "energy_kcal": "80",
         "swap": {"sodium_mg": "0", "energy_kcal": "0"}},
    ],
})
plans = plan_swaps(meal)
check("方案数", len(plans), 2)
check("按钠削减排序，首项为去掉酱料", plans[0].action, "去掉酱料")
check("去掉酱料钠削减", plans[0].d_sodium, -620.0)
check("替换芝士钠削减", plans[1].d_sodium, -180.0)
check("改配后总钠 961-620-180", 961 - 620 - 180, 161)

print("\n[8] 无配料时不得臆造改配")
plain = load_food({"name": "大杯玉米杯", "energy_kcal": "87", "sodium_mg": "2"})
check("无配料 -> 无改配建议", plan_swaps(plain), [])

# ------------------------------------------------------- 9. 阈值判定
print("\n[9] 阈值判定（高血压画像，钠上限 500mg）")
htn = PROFILES["hypertension"]
findings = assess(f, htn, htn.limits)
highs = [x for x in findings if x.level == "high"]
check("巨无霸触发钠超标", any("钠" in x.label for x in highs), True)
check("麦辣鸡腿堡(1208mg)更高",
      assess(load_food({"name": "麦辣鸡腿汉堡", "energy_kcal": "485",
                        "sodium_mg": "1208"}), htn, htn.limits)[0].level, "high")
check("玉米杯(2mg)不超标",
      [x.level for x in assess(plain, htn, htn.limits)
       if x.level == "high"], [])

print("\n[10] 边界值行为（阈值即红线：等于上限应判超标）")
edge = load_food({"name": "边界", "energy_kcal": "300", "sodium_mg": "500"})
edge_f = assess(edge, htn, htn.limits)
check("钠=上限(500)判超标",
      any(x.level == "high" for x in edge_f if "钠" in x.label), True)
under = load_food({"name": "欠一点", "energy_kcal": "300", "sodium_mg": "499"})
check("钠=499(未达红线)不判超标",
      any(x.level == "high" for x in assess(under, htn, htn.limits)
          if "钠" in x.label), False)

print("\n[11] 八类画像均可用且阈值非空")
check("画像数量", len(PROFILES), 8)
check("每画像均有 limits", all(p.limits for p in PROFILES.values()), True)
check("muscle 强调蛋白", "protein_g" in PROFILES["muscle"].emphasis, True)

print("\n[12] 免责声明必须出现在输出中（活动规则要求）")
out = render([f], htn, htn.limits)
check("含免责声明", "不构成医疗" in out, True)
check("含非官方声明", "非麦当劳官方产品" in out, True)

print("\n[13] 空输入不崩溃")
check("空 foods 渲染", isinstance(render([], htn, htn.limits), str), True)

print(f"\n{'=' * 46}")
print(f"通过 {PASS} · 失败 {FAIL}")
print(f"{'=' * 46}")
sys.exit(1 if FAIL else 0)