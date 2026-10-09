#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_fetch.py — 麦当劳 MCP 数据获取与适配（零依赖）

作用
----
1. 直连麦当劳 MCP Server（Streamable HTTP），完成 initialize 握手。
2. 调用 list-nutrition-foods 等只读工具。
3. 把 MCP 的扁平表格式返回适配为 nutrition_guard.py 所需的 payload 结构。

★ 本脚本是「真实 MCP 调用」的可复现证据：仓库内所有营养数值
  均可由本脚本从 MCP Server 重新取回，而非手工编造。

用法
----
    export MCD_MCP_TOKEN=xxxx
    python mcp_fetch.py --list-nutrition --out payload.json
    python mcp_fetch.py --keyword 巨无霸 --profile hypertension
    python mcp_fetch.py --tools                # 列出全部工具
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "mcd-diet-guard"


# ------------------------------------------------------------------ MCP 客户端

class McpClient:
    """极简MCP Streamable HTTP 客户端，仅覆盖本项目所需能力。"""

    def __init__(self, token: str, url: str = DEFAULT_URL, timeout: int = 90):
        self.url = url
        self.timeout = timeout
        self._id = 0
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
        }
        self.session_id: str | None = None

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _raw_call(self, payload: dict) -> tuple[int, str]:
        headers = dict(self.headers)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    @staticmethod
    def _parse(body: str) -> dict:
        """兼容纯JSON 与 SSE (text/event-stream) 两种响应形态。"""
        body = body.strip()
        if body.startswith(("event:", "data:")):
            for line in body.splitlines():
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload:
                        return json.loads(payload)
            raise ValueError("SSE 响应中未找到 data 行")
        return json.loads(body)

    def initialize(self) -> dict:
        payload = {
            "jsonrpc": "2.0", "id": self._next_id(), "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": "1.0.0"},
            },
        }
        status, body = self._raw_call(payload)
        result = self._parse(body)
        if status != 200 or "error" in result:
            raise RuntimeError(f"initialize 失败 status={status}: "
                               f"{json.dumps(result, ensure_ascii=False)[:400]}")
        return result.get("result", {})

    def call(self, tool: str, arguments: dict | None = None) -> dict:
        payload = {
            "jsonrpc": "2.0", "id": self._next_id(), "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
        }
        status, body = self._raw_call(payload)
        result = self._parse(body)
        if status != 200 or "error" in result:
            raise RuntimeError(f"{tool} 调用失败 status={status}: "
                               f"{json.dumps(result, ensure_ascii=False)[:400]}")
        return result.get("result", {})

    def list_tools(self) -> list[dict]:
        payload = {"jsonrpc": "2.0", "id": self._next_id(),
                   "method": "tools/list", "params": {}}
        status, body = self._raw_call(payload)
        return self._parse(body).get("result", {}).get("tools", [])


# ------------------------------------------------------------------ 响应解包

def extract_text(result: dict) -> str:
    """从 MCP content 数组中取出文本正文。"""
    for block in result.get("content", []):
        if block.get("type") == "text":
            return block.get("text", "")
    return ""


def parse_api_envelope(text: str) -> dict:
    """
    MCP 返回带一层 API 包装：
        {"success":true,"code":200,"data":"[160]{字段表}\\n 名称,null,数值,...",...}
    外层 data 是字符串，内层是「表头声明 + 逐行 CSV」格式。

    ★ data 有时是 JSON 数组，有时是这种扁平表格式，两种都要处理——
      这是实测发现的，不能假设格式恒定。
    """
    start = text.find('{"success"')
    if start == -1:
        raise ValueError("响应中未找到 API JSON 包装层")
    # 尾部可能有截断，逐字符回退到完整 JSON
    for end in range(len(text), start, -1):
        try:
            envelope = json.loads(text[start:end])
            break
        except json.JSONDecodeError:
            continue
    else:
        raise ValueError("无法解析 API 包装层JSON")

    payload = envelope.get("data")
    if isinstance(payload, list):
        return {"rows": payload, "envelope": envelope}
    if not isinstance(payload, str):
        raise ValueError(f"未预期的 data 类型：{type(payload)}")

    # 形如 "[160]{a,b,c}:\n  值1,值2,值3\n  ..."
    header_start = payload.find("{")
    body_start = payload.find("}", header_start)
    if header_start == -1 or body_start == -1:
        # 退路：整个字符串当 JSON 数组
        return {"rows": json.loads(payload), "envelope": envelope}

    # ★ 必须以 "}" 而非 ":" 定位表头结束：格式是 "[N]{f1,f2,f3}:\n  行..."
    # 若按 ":" 切分，最后一个字段名会连同结尾的 "}" 一起被吃掉，
    # 变成 "calcium}"，导致该列在所有行上全部对不上（实测 160 行全丢钙值）。
    fields = payload[header_start + 1:body_start].strip().split(",")
    rows: list[dict] = []
    for line in payload[body_start + 1:].splitlines():
        line = line.strip().rstrip(",")
        # 表头后紧跟的 " :" 分隔行不是数据行，必须跳过，
        # 否则会解析出一行字段名全空、productName 为 ":" 的垃圾数据。
        if not line or line in (":", "{}"):
            continue
        cells = line.split(",")
        cells += [""] * (len(fields) - len(cells))   # 补齐缺列
        rows.append({f.strip(): c.strip() for f, c in zip(fields, cells)})
    return {"rows": rows, "envelope": envelope}


def num(value, default=0.0) -> float:
    """把 MCP 的字符串数值转为 float；null/空串返回 default。"""
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() in ("null", "none", "-"):
        return default
    try:
        return float(text)
    except ValueError:
        return default


# ------------------------------------------------------------------ 适配

# MCP 实测字段 -> 脚本逻辑字段（脚本另有别名表，此处做显式映射并保留原样透传）
MAP = {
    "energyKcal": "energy_kcal",
    "protein": "protein_g",
    "fat": "fat_g",
    "carbohydrate": "carbs_g",
    "sodium": "sodium_mg",
    "calcium": "calcium_mg",
}
NAME_KEYS = ("productName", "name", "foodName")


def adapt_food(row: dict) -> dict:
    """MCP 行 -> nutrition_guard 的 food 结构。"""
    name = next((str(row[k]).strip() for k in NAME_KEYS
                 if k in row and str(row[k]).strip()), "未命名餐品")
    out: dict = {"name": name}
    for src, dst in MAP.items():
        if src in row:
            out[dst] = num(row[src])
    # nutritionDescription 目前全为 null，不作为营养依据透传
    return out


def build_payload(rows: list[dict], profile: str) -> dict:
    foods = [adapt_food(r) for r in rows]
    foods = [f for f in foods if f.get("energy_kcal", 0) > 0]   # 丢弃无能量数据的行
    return {"profile": profile, "foods": foods}


# ------------------------------------------------------------------ CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="麦当劳 MCP 数据获取与适配（零依赖）")
    ap.add_argument("--token", default=os.environ.get("MCD_MCP_TOKEN", ""),
                    help="MCP Token，默认读环境变量 MCD_MCP_TOKEN")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--tools", action="store_true", help="列出全部工具后退出")
    ap.add_argument("--list-nutrition", action="store_true", help="拉取营养列表")
    ap.add_argument("--keyword", default="", help="按名称关键词过滤")
    ap.add_argument("--profile", default="general", help="人群画像")
    ap.add_argument("--limit", type=int, default=0, help="限制输出条数，0 为不限")
    ap.add_argument("--out", default="", help="payload 输出路径；缺省打印到 stdout")
    args = ap.parse_args(argv)

    if not args.token:
        print("缺少 MCP Token：请设置环境变量 MCD_MCP_TOKEN 或使用 --token",
              file=sys.stderr)
        return 1

    client = McpClient(args.token, args.url)
    try:
        client.initialize()

        if args.tools:
            tools = client.list_tools()
            print(f"共 {len(tools)} 个工具：")
            for t in tools:
                print(f"  {t['name']}")
            return 0

        if not args.list_nutrition:
            ap.print_help()
            return 1

        result = client.call("list-nutrition-foods")
        parsed = parse_api_envelope(extract_text(result))
        rows = parsed["rows"]
        payload = build_payload(rows, args.profile)

        if args.keyword:
            kw = args.keyword
            payload["foods"] = [f for f in payload["foods"] if kw in f["name"]]
        if args.limit > 0:
            payload["foods"] = payload["foods"][:args.limit]

        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"已写入 {args.out}（{len(payload['foods'])} 项餐品）",
                  file=sys.stderr)
        else:
            print(text)
        return 0

    except Exception as exc:                       # noqa: BLE001
        print(f"调用失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())