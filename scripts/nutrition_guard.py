#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nutrition_guard.py — 麦当劳膳食风险核算与改配求解引擎

设计原则
--------
1. 零第三方依赖：只用 Python 标准库，任何环境可直接跑。
2. 数据由 MCP 提供：营养数值来自 list-nutrition-foods / query-meals /
   query-meal-detail，本引擎不硬编码任何菜单数据。
3. 宽松字段解析：MCP 字段命名可能随版本变化，故对多别名做归一化。
4. 显式标注估算：凡是基于密度/类别而非直接给出的判断，一律标 estimated。

用法
----
    python nutrition_guard.py --input foods.json
    python nutrition_guard.py --input foods.json --profile gout
    cat foods.json | python nutrition_guard.py --profile hypertension
    python nutrition_guard.py --input foods.json --json      # 机器可读输出

输入 JSON 结构（字段名可用别名，见 ALIASES）
------------------------------------------------
{
  "profile": "hypertension",              # 可选，默认 general
  "constraints": {"sodium_mg": 1500},      # 可选，覆盖画像默认阈值
  "foods": [
    {
      "name": "巨无霸汉堡",
      "energy_kcal": 523, "protein_g": 25, "fat_g": 30,
      "carbs_g": 44, "sodium_mg": 1060, "calcium_mg": 156,
      "tags": ["beef", "fried", "sauce"],
      "components": [                       # 可选，来自 query-meal-detail
        {"name": "酱料", "sodium_mg": 620, "energy_kcal": 140,
         "removable": true, "swap": {"energy_kcal": 20, "sodium_mg": 30}}
      ]
    }
  ]
}
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------- 字段归一化

ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "foodName", "food_name", "productName", "title",
             "itemName", "名称"),
    "energy_kcal": ("energy_kcal", "energy", "calorie", "calories", "kcal",
                    "energyKcal", "热量", "能量"),
    "protein_g": ("protein_g", "protein", "蛋白质"),
    "fat_g": ("fat_g", "fat", "脂肪"),
    "carbs_g": ("carbs_g", "carbs", "carbohydrate", "carbohydrates",
                "carb", "碳水化合物"),
    "sodium_mg": ("sodium_mg", "sodium", "na", "钠"),
    "calcium_mg": ("calcium_mg", "calcium", "钙"),
    "sugars_g": ("sugars_g", "sugar", "sugars", "糖"),
    "fiber_g": ("fiber_g", "fiber", "膳食纤维"),
    "satfat_g": ("satfat_g", "saturatedFat", "saturated_fat", "satfat", "饱和脂肪"),
    "transfat_g": ("transfat_g", "transFat", "trans_fat", "transfat", "反式脂肪"),
    "tags": ("tags", "tag", "labels", "categories", "category", "标签"),
}

_NUM = (int, float)


def to_float(value: Any) -> float | None:
    """
    把 MCP 返回值转为 float，失败返回 None。

    ★ 必须接受字符串：麦当劳 MCP 的 list-nutrition-foods 把所有营养值
      以字符串返回（如 "961"），只认 int/float 会让全部字段匹配失败，
      导致真实链路上营养值全为 0。这是实测踩过的坑，不要退回类型严格判断。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, _NUM):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in ("null", "none", "-", "n/a"):
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def pick(food: dict, key: str, default: float | None = 0.0) -> float | None:
    """按别名列表取值，返回 float 或 default。接受字符串数值（MCP 实测格式）。"""
    for alias in ALIASES[key]:
        if alias in food:
            number = to_float(food[alias])
            if number is not None:
                return number
    return default


def pick_str(food: dict, key: str, default: str = "") -> str:
    for alias in ALIASES[key]:
        val = food.get(alias)
        if isinstance(val, str) and val.strip() and val.strip().lower() != "null":
            return val.strip()
    return default


def pick_tags(food: dict) -> list[str]:
    for alias in ALIASES["tags"]:
        val = food.get(alias)
        if isinstance(val, str):
            return [val.strip()]
        if isinstance(val, (list, tuple, set)):
            return [str(x).strip().lower() for x in val if str(x).strip()]
    return []


# ---------------------------------------------------------------- 人群画像

@dataclass(frozen=True)
class Profile:
    """一个膳食约束画像。阈值单位统一为 mg / g / kcal。"""
    key: str
    label: str
    limits: dict[str, float]          # 硬上限：单品不得超
    emphasis: tuple[str, ...] = ()    # 重点关注项（用于排序与提示）
    note: str = ""
    # 该画像下优先推荐的低风险标签（命中则加分）
    good_tags: tuple[str, ...] = ("salad", "water", "tea", "coffee", "fruit")


PROFILES: dict[str, Profile] = {
    "general": Profile(
        key="general", label="通用",
        limits={"energy_kcal": 800, "sodium_mg": 2300, "satfat_g": 12},
        note="无特殊限制，仅做能量与钠的粗筛。",
    ),
    "hypertension": Profile(
        key="hypertension", label="高血压 / 高钠敏感",
        limits={"sodium_mg": 500, "satfat_g": 8},
        emphasis=("sodium_mg",),
        note="中国膳食指南建议钠 <2000mg/天；高血压人群建议更低。"
             "套餐层面建议不超过 500mg/份。",
    ),
    "diabetes": Profile(
        key="diabetes", label="血糖管理",
        limits={"carbs_g": 40, "sugars_g": 15, "energy_kcal": 600},
        emphasis=("carbs_g", "sugars_g"),
        note="关注可吸收碳水与添加糖；优先选无糖饮品。"
             "本品非医疗建议，糖代谢异常请遵医嘱。",
    ),
    "gout": Profile(
        key="gout", label="痛风 / 高尿酸",
        limits={"energy_kcal": 700},
        emphasis=("protein_g",),
        note="按肉类密度分级给出估算：红肉与内脏类汤汁嘌呤风险更高，"
             "本项为类别估算而非嘌呤含量测定值，不可替代医嘱。",
    ),
    "weightloss": Profile(
        key="weightloss", label="减脂期",
        limits={"energy_kcal": 500, "fat_g": 22, "satfat_g": 6},
        emphasis=("energy_kcal", "fat_g"),
        note="以单餐 500kcal 为上限，可拆为早中餐两段。",
    ),
    "muscle": Profile(
        key="muscle", label="增肌期",
        limits={"energy_kcal": 900, "sodium_mg": 2500},
        emphasis=("protein_g", "energy_kcal"),
        note="蛋白密度优先；单餐蛋白 ≥25g 视为达标。",
    ),
    "pregnancy": Profile(
        key="pregnancy", label="孕期",
        limits={"sodium_mg": 600, "energy_kcal": 700},
        emphasis=("sodium_mg", "caffeine"),
        note="高钠与咖啡因需控制；具体饮食请遵产科医嘱。",
    ),
    "child": Profile(
        key="child", label="儿童（6-12 岁）",
        limits={"energy_kcal": 500, "sodium_mg": 700, "satfat_g": 8},
        emphasis=("energy_kcal", "sodium_mg"),
        note="按半份估算；饮品优先无糖或低糖。",
    ),
}

# 嘌呤类别估算：标签命中越多风险越高（est = 估算，非实测嘌呤值）
PURINE_RISK: list[tuple[tuple[str, ...], int]] = [
    (("organ", "liver", "gizzard", "blood"), 3),      # 内脏类
    (("beef", "pork", "chicken", "meat", "bacon"), 2), # 红肉类
    (("seafood", "shrimp", "fish", "sauce-gravy"), 1), # 海鲜/肉汁
]

# 高钠加工类标签（用于给出具体可执行改配建议）
SODIUM_HINT_TAGS = ("sauce", "gravy", "fried", "bacon", "cheese", "pickle")
SUGAR_HINT_TAGS = ("soda", "coke", "sweet", "dessert", "milkshake", "syrup")


def purine_score(tags: list[str]) -> tuple[int, bool]:
    """返回 (0-3 风险分, 是否为估算)。"""
    for keys, level in PURINE_RISK:
        if any(k in t for t in tags for k in keys):
            return level, True
    return 0, True


# ---------------------------------------------------------------- 数据模型

@dataclass
class Component:
    name: str
    energy_kcal: float = 0.0
    protein_g: float = 0.0
    fat_g: float = 0.0
    carbs_g: float = 0.0
    sodium_mg: float = 0.0
    removable: bool = False
    swap: dict[str, float] = field(default_factory=dict)   # 替换后的营养值


@dataclass
class Food:
    name: str
    energy_kcal: float = 0.0
    protein_g: float = 0.0
    fat_g: float = 0.0
    carbs_g: float = 0.0
    sodium_mg: float = 0.0
    calcium_mg: float = 0.0
    sugars_g: float | None = None
    satfat_g: float | None = None
    transfat_g: float | None = None
    tags: list[str] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)

    @property
    def protein_density(self) -> float:
        """每 100kcal 的蛋白克数——比单看绝对值更能跨餐比较。"""
        return (self.protein_g / self.energy_kcal * 100) if self.energy_kcal > 0 else 0.0

    @property
    def sodium_density(self) -> float:
        """每 100kcal 的钠毫克数。"""
        return (self.sodium_mg / self.energy_kcal * 100) if self.energy_kcal > 0 else 0.0

    @property
    def added_sugar_est(self) -> float | None:
        """
        添加糖估算：MCP 给出 sugars_g 时用实测值；否则返回 None 而非猜测——
        碳水里有多少是添加糖无法从总量反推，宁缺勿臆。
        """
        return self.sugars_g


def load_food(raw: dict) -> Food:
    food = Food(
        name=pick_str(raw, "name", "未命名餐品"),
        energy_kcal=pick(raw, "energy_kcal", 0.0) or 0.0,
        protein_g=pick(raw, "protein_g", 0.0) or 0.0,
        fat_g=pick(raw, "fat_g", 0.0) or 0.0,
        carbs_g=pick(raw, "carbs_g", 0.0) or 0.0,
        sodium_mg=pick(raw, "sodium_mg", 0.0) or 0.0,
        calcium_mg=pick(raw, "calcium_mg", 0.0) or 0.0,
        sugars_g=pick(raw, "sugars_g", None),
        satfat_g=pick(raw, "satfat_g", None),
        transfat_g=pick(raw, "transfat_g", None),
        tags=pick_tags(raw),
    )
    for c in raw.get("components") or []:
        if not isinstance(c, dict):
            continue
        swap = c.get("swap") if isinstance(c.get("swap"), dict) else {}
        food.components.append(Component(
            name=pick_str(c, "name", "配料"),
            energy_kcal=pick(c, "energy_kcal", 0.0) or 0.0,
            protein_g=pick(c, "protein_g", 0.0) or 0.0,
            fat_g=pick(c, "fat_g", 0.0) or 0.0,
            carbs_g=pick(c, "carbs_g", 0.0) or 0.0,
            sodium_mg=pick(c, "sodium_mg", 0.0) or 0.0,
            removable=bool(c.get("removable", False)),
            swap={k: n for k, v in swap.items()
                  for n in [to_float(v)] if n is not None},
        ))
    return food


# ---------------------------------------------------------------- 核算逻辑

@dataclass
class Finding:
    level: str          # "high" | "medium" | "ok"
    label: str          # 中文短标签
    detail: str         # 数值依据
    action: str = ""    # 可执行动作


def assess(food: Food, profile: Profile,
           limits: dict[str, float]) -> list[Finding]:
    """对单个餐品按画像阈值做风险核算，返回按严重度排序的发现项。"""
    out: list[Finding] = []

    def check(value: float, limit: float, label: str,
              unit: str, higher_is_worse: bool = True,
              action: str = "") -> None:
        if limit <= 0 or value <= 0:
            return
        ratio = value / limit
        if not higher_is_worse:
            ratio = 1.0 / ratio if ratio > 0 else 0.0
        if ratio >= 1.0:
            out.append(Finding("high", f"{label}超标",
                               f"{value:g}{unit} / 上限 {limit:g}{unit}（{ratio:.1f}×）",
                               action))
        elif ratio >= 0.75:
            out.append(Finding("medium", f"{label}接近上限",
                               f"{value:g}{unit} / 上限 {limit:g}{unit}（{ratio:.0%}）",
                               action))

    check(food.energy_kcal, limits.get("energy_kcal", 0), "能量",
          "kcal", action="拆成两餐，或去掉可替换的高脂配料")
    check(food.sodium_mg, limits.get("sodium_mg", 0), "钠",
          "mg", action="优先去掉酱料/肉汁类配料，并核对当日饮品")
    check(food.carbs_g, limits.get("carbs_g", 0), "碳水",
          "g", action="主食减半，或换成无糖饮品")
    if food.sugars_g is not None:
        check(food.sugars_g, limits.get("sugars_g", 0), "糖",
              "g", action="把含糖饮料换成无糖或纯水")
    if food.satfat_g is not None:
        check(food.satfat_g, limits.get("satfat_g", 0), "饱和脂肪",
              "g", action="去酱、去芝士可显著降低")
    check(food.fat_g, limits.get("fat_g", 0), "脂肪", "g",
          action="去裹粉油炸类配料是最大单点削减")

    # 嘌呤类别估算
    if profile.key == "gout":
        score, est = purine_score(food.tags)
        if score >= 2:
            lvl = "high" if score == 3 else "medium"
            out.append(Finding(
                lvl, "高嘌呤类别（估算）",
                f"标签命中肉类/内脏类风险级 {score}/3" + ("，按类别推断" if est else ""),
                "改选鸡肉沙拉类或不含肉汤汁的组合"))

    # 达标型正向提示
    if profile.key == "muscle" and food.protein_g >= 25:
        out.append(Finding("ok", "蛋白达标",
                           f"{food.protein_g:g}g 蛋白 / {food.energy_kcal:g}kcal"
                           f"（密度 {food.protein_density:.1f}g/100kcal）"))
    if food.calcium_mg >= 100:
        out.append(Finding("ok", "钙含量较好", f"{food.calcium_mg:g}mg"))

    order = {"high": 0, "medium": 1, "ok": 2}
    return sorted(out, key=lambda f: order[f.level])


@dataclass
class SwapPlan:
    """一条可执行的改配方案及其削减量。"""
    action: str
    d_energy: float = 0.0
    d_sodium: float = 0.0
    d_carbs: float = 0.0
    d_fat: float = 0.0


def plan_swaps(food: Food) -> list[SwapPlan]:
    """
    基于 query-meal-detail 返回的可替换配料生成改配方案。
    无配料明细时返回空列表——不臆造改动项。
    """
    plans: list[SwapPlan] = []
    for c in food.components:
        if not c.removable and not c.swap:
            continue
        if c.swap:
            plans.append(SwapPlan(
                action=f"{c.name} → 替换选项",
                d_energy=c.swap.get("energy_kcal", c.energy_kcal) - c.energy_kcal,
                d_sodium=c.swap.get("sodium_mg", c.sodium_mg) - c.sodium_mg,
                d_carbs=c.swap.get("carbs_g", c.carbs_g) - c.carbs_g,
                d_fat=c.swap.get("fat_g", c.fat_g) - c.fat_g,
            ))
        elif c.removable:
            plans.append(SwapPlan(
                action=f"去掉{c.name}",
                d_energy=-c.energy_kcal, d_sodium=-c.sodium_mg,
                d_carbs=-c.carbs_g, d_fat=-c.fat_g,
            ))
    # 按钠削减量排序——钠是最容易一改就见效的维度
    return sorted(plans, key=lambda p: p.d_sodium)


def tag_suggestions(food: Food) -> list[str]:
    """基于标签给出粗粒度提示；不臆造具体餐品名。"""
    hints: list[str] = []
    tags = food.tags
    if any(k in t for t in tags for k in SODIUM_HINT_TAGS):
        hints.append("含酱料/加工类配料，钠的主要来源")
    if any(k in t for t in tags for k in SUGAR_HINT_TAGS):
        hints.append("搭配的饮料或甜品可能含糖，注意看单品糖数据")
    # 量级说明：麦当劳主餐钠密度实测多在 60~210 mg/100kcal 区间
    #（快餐普遍高钠，密度差异才是可比维度，而非绝对高低）。
    # 150 为「同能量下明显偏高」的界，低于此不提示。
    if food.sodium_density > 150:
        hints.append(f"钠密度偏高（{food.sodium_density:.0f}mg/100kcal），"
                     "同等热量下属于高钠选项")
    if food.protein_density >= 10:
        hints.append(f"蛋白密度高（{food.protein_density:.1f}g/100kcal）")
    return hints


# ---------------------------------------------------------------- 输出

LEVEL_MARK = {"high": "🔴 超标", "medium": "🟡 接近上限", "ok": "🟢 达标"}


def render(foods: list[Food], profile: Profile,
           limits: dict[str, float]) -> str:
    lines: list[str] = []
    lines.append(f"# 麦当劳膳食风险核算 — 画像：{profile.label}")
    lines.append("")
    lines.append(f"> 阈值口径：{profile.note}")
    lines.append("")
    lines.append("| 餐品 | 能量 | 蛋白 | 钠 | 碳水 | 主要风险 |")
    lines.append("|---|---:|---:|---:|---:|---|")

    for food in foods:
        findings = assess(food, profile, limits)
        top = next((f for f in findings if f.level != "ok"), None)
        mark = LEVEL_MARK[top.level] if top else "🟢 无超标项"
        sug = food.sugars_g
        carbs = f"{food.carbs_g:g}{f' (糖{sug:g})' if sug is not None else ''}"
        lines.append(
            f"| {food.name} | {food.energy_kcal:g} | {food.protein_g:g} | "
            f"{food.sodium_mg:g}mg | {carbs} | {mark} |")

    for food in foods:
        findings = assess(food, profile, limits)
        alerts = [f for f in findings if f.level != "ok"]
        positives = [f for f in findings if f.level == "ok"]
        plans = plan_swaps(food)
        hints = tag_suggestions(food)

        lines.append("")
        lines.append(f"## {food.name}")
        if not alerts and not positives:
            lines.append("- 在当前画像阈值下未触发任何阈值项。")
        for f in alerts:
            suffix = f"  \n  → {f.action}" if f.action else ""
            lines.append(f"- {LEVEL_MARK[f.level]} **{f.label}**：{f.detail}{suffix}")
        for f in positives:
            lines.append(f"- {LEVEL_MARK[f.level]} {f.label}：{f.detail}")
        for h in hints:
            lines.append(f"- ℹ️ {h}")

        if plans:
            lines.append("")
            lines.append("可执行的改配（数据来自套餐配料明细，非臆造）：")
            for p in plans[:5]:
                deltas = []
                if p.d_sodium:
                    deltas.append(f"钠{p.d_sodium:+g}mg")
                if p.d_energy:
                    deltas.append(f"能量{p.d_energy:+g}kcal")
                if p.d_carbs:
                    deltas.append(f"碳水{p.d_carbs:+g}g")
                if p.d_fat:
                    deltas.append(f"脂肪{p.d_fat:+g}g")
                lines.append(f"- {p.action}（{', '.join(deltas) or '变化可忽略'}）")
        elif food.components:
            lines.append("")
            lines.append("该餐品无可替换配料明细。")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**免责声明**：本工具为麦当劳程序员创意开发大赛参赛作品输出，"
                 "非麦当劳官方产品，不构成医疗、营养或其他专业建议。")
    lines.append("营养数值来自麦当劳 MCP 实时返回，餐品成分与供应状态以官方渠道为准。")
    lines.append("如有代谢疾病请遵医嘱。")
    return "\n".join(lines)


def render_json(foods: list[Food], profile: Profile,
                limits: dict[str, float]) -> str:
    payload = {
        "profile": {"key": profile.key, "label": profile.label,
                    "limits": limits, "note": profile.note},
        "results": [
            {
                "name": f.name,
                "nutrition": {
                    "energy_kcal": f.energy_kcal, "protein_g": f.protein_g,
                    "fat_g": f.fat_g, "carbs_g": f.carbs_g,
                    "sodium_mg": f.sodium_mg, "calcium_mg": f.calcium_mg,
                    "sugars_g": f.sugars_g, "satfat_g": f.satfat_g,
                },
                "density": {"protein_per_100kcal": round(f.protein_density, 2),
                            "sodium_per_100kcal": round(f.sodium_density, 2)},
                "tags": f.tags,
                "findings": [vars(x) for x in assess(f, profile, limits)],
                "swaps": [vars(p) for p in plan_swaps(f)],
                "hints": tag_suggestions(f),
            }
            for f in foods
        ],
        "disclaimer": "参赛作品输出，不构成医疗或营养专业建议。",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def list_profiles() -> str:
    lines = ["可用画像：", ""]
    for key, p in PROFILES.items():
        limits = "，".join(f"{k} ≤ {v:g}" for k, v in p.limits.items())
        lines.append(f"  {key:<14} {p.label}  ——  {limits}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="麦当劳膳食风险核算与改配求解引擎（零依赖）")
    ap.add_argument("--input", "-i", help="输入 JSON 文件路径；缺省则读 stdin")
    ap.add_argument("--profile", "-p", default="general",
                    help="人群画像，默认 general")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非 Markdown")
    ap.add_argument("--list-profiles", action="store_true", help="列出所有画像后退出")
    args = ap.parse_args(argv)

    if args.list_profiles:
        print(list_profiles())
        return 0

    if args.profile not in PROFILES:
        print(f"未知画像：{args.profile}\n", file=sys.stderr)
        print(list_profiles(), file=sys.stderr)
        return 2

    try:
        raw_text = (sys.stdin.read() if not args.input
                    else open(args.input, encoding="utf-8").read())
        data = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"输入解析失败：{exc}", file=sys.stderr)
        return 1

    profile = PROFILES[args.profile]
    limits = dict(profile.limits)
    limits.update(data.get("constraints") or {})   # 用户覆盖优先

    foods = [load_food(f) for f in (data.get("foods") or []) if isinstance(f, dict)]
    if not foods:
        print("输入中没有任何 foods 条目。", file=sys.stderr)
        return 1

    print(render_json(foods, profile, limits) if args.json
          else render(foods, profile, limits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())