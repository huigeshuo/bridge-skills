#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
箱梁技术指标库 —— Excel 汇总表自动提取与校核
=====================================================
把"钢束含量汇总表 / 桥梁技术指标表"一类的 Excel，自动归集成结构化指标库。

支持的表形态（设计院常见）：
  * 一个 sheet 内多个区块（如"现浇箱梁"块 +"钢箱梁"块），区块标题行以合并单元格给出
  * 桥名/匝道名为纵向合并单元格（值只写在首行，需向下填充）
  * 跨径写成 "24.732+3*30.005" / "3*33.5" / "分叉2*23.25" 等自由文本
  * 表头写"砼数量(m3)"、实际值却是钢板 kg（钢箱梁块常见的表头复制残留）

用法：
  python extract_indicators.py --input 表1.xlsx [表2.xls ...] \
         --lib <指标库.json>  --outdir <输出目录> [--project 默认工程名]

输出：
  <lib>                    累积指标库（JSON，去重合并）
  <outdir>/指标库.csv      Excel 可直接打开（UTF-8 BOM）
  <outdir>/指标库.md       人读报告（含统计与校核）
  <outdir>/指标库.html     可视化看板（离线，无外链）
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------- 依赖检查
try:
    import openpyxl
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover
    sys.exit("缺少 openpyxl，请先安装：pip install openpyxl")

try:
    import xlrd  # .xls 支持（可选）
except ImportError:  # pragma: no cover
    xlrd = None


# ---------------------------------------------------------------- 表头识别
# 键 -> 匹配用的关键字（按优先级从高到低，命中即取）
HEADER_KEYS = {
    "bridge_name":   ["桥名", "桥梁名称", "桥名/匝道", "部位"],
    "route":         ["匝道", "互通", "工区", "标段", "地名"],
    "unit_no":       ["联号", "联次", "孔号"],
    "span_raw":      ["跨径", "孔跨", "跨径布置"],
    "total_length":  ["联长", "桥长", "全长"],
    "w_start":       ["起点宽度", "起点宽", "起点"],
    "w_end":         ["终点宽度", "终点宽", "终点"],
    "w_uniform":     ["宽度", "桥宽", "标准宽度", "桥面宽"],
    "area":          ["桥梁面积", "桥面面积", "面积"],
    "steel_plate":   ["钢板数量", "钢板重量", "钢板"],
    "concrete":      ["砼数量", "混凝土数量", "砼方量", "混凝土方量", "砼(m3)", "砼"],
    "strand":        ["钢绞线数量", "钢绞线含量(kg)", "钢绞线(kg)", "钢绞线", "钢束"],
    "rebar":         ["钢筋数量", "钢筋(kg)", "钢筋"],
    "src_conc_ratio": ["砼含量", "混凝土含量"],
    "src_strand_m2": ["钢绞线含量(kg/m2)", "钢绞线含量(kg/m²)"],
    "src_strand_m3": ["钢绞线含量(kg/m3)", "钢绞线含量(kg/m³)"],
    "remark":        ["备注", "说明"],
}

TITLE_COLS = 4          # 合并跨度 >= 该值且能写文字 -> 视为区块标题行
FILL_KEYS = ("bridge_name",)   # 需要向下填充的纵向合并列

# 校核阈值（可按工程习惯调整，见 references/指标口径与校核规则.md）
TOL_LEN = 0.02          # 跨径和 vs 联长，相对误差
TOL_AREA = 0.03         # 面积 vs 联长×平均宽，相对误差
WIDTH_RATIO = 2.0       # 起/终点宽度比值超过此值 -> 疑似小数点错位（分叉联除外）
RANGE = {               # 合理区间，越界即标记
    "conc_ratio": (0.45, 1.30),      # 现浇预应力砼箱梁 砼含量 m3/m2（分叉联可到 1.2）
    "strand_m2":  (6.0, 75.0),       # 钢绞线 kg/m2
    "strand_m3":  (10.0, 75.0),      # 钢绞线 kg/m3（分叉联分母大，可低至 12）
    "plate_m2":   (100.0, 800.0),    # 钢箱梁 钢板 kg/m2
}

# 名称代号映射：入库前统一替换（工程名/互通名/桥名），便于对外分享时脱敏。
# 例："武大高速" -> "WD高速"，"汉口北大道高架" -> "HKB大道高架"。
# 注：source_file（源文件名）不参与替换，保留真实文件名以便回表溯源。
NAME_ALIAS = {
    "武大高速": "WD高速",   # 长词在前，避免被短词先吃掉
    "武大":     "WD",
    "汉口北":   "HKB",
}

# 对外精简版（对外分享用）页面上显示的品牌署名，会拼进标题与页脚。
# 留空则标题只显示「箱梁技术指标速查」。
PUBLIC_BRAND = "辉歌说"

# 桥名是否转「汉字拼音首字母」代号（对外分享脱敏）。
# 例：滠口高架 -> SKGJ，主线右幅桥 -> ZXYFQ；已含拉丁字母/数字的部分原样保留。
# 命令行 --no-pinyin 可临时关闭。转换幂等：代号再跑一次不会变。
BRIDGE_PINYIN = True

# 单个拼音字母白名单外的一字多音处理：用 pypinyin 默认（常用读音），
# 若某桥名读音特殊，可在下方登记原名 -> 期望代号，优先级最高。
BRIDGE_CODE_FIX = {
    # "滠口高架": "SKGJ",
}


def pinyin_code(name):
    """汉字 -> 拼音首字母代号；非汉字（字母/数字/符号）原样保留。"""
    if name in (None, ""):
        return name
    s = str(name)
    if s in BRIDGE_CODE_FIX:
        return BRIDGE_CODE_FIX[s]
    try:
        from pypinyin import Style, lazy_pinyin
        return "".join(lazy_pinyin(s, style=Style.FIRST_LETTER)).upper()
    except ImportError:
        return s          # 没装 pypinyin 就保持原名，不报错


CODE_CACHE_NAME = "name_code_map.json"   # 原名 -> 代号 缓存，放在指标库 JSON 同目录


def load_code_cache(path):
    """读取原名->代号缓存；不存在或损坏则返回空结构。"""
    if path and Path(path).exists():
        try:
            c = json.loads(Path(path).read_text(encoding="utf-8"))
            return {"route": c.get("route", {}), "bridge": c.get("bridge", {})}
        except Exception:
            pass
    return {"route": {}, "bridge": {}}


def _code_group(items, used, cache=None):
    """items: [(原名, [记录...])] -> [(原名, 代号, 记录...)]，撞车加 -2/-3 后缀。

    cache 非空时优先沿用既有代号，保证同一原名多次入库代号稳定；
    新名字生成后写回 cache，使报告里的「原名」列始终可回溯到最初的中文名。
    """
    out = []
    for name, recs in items:
        code = (cache or {}).get(name) or pinyin_code(name)
        if code in used and used[code] != name:          # 缩写撞车
            i = 2
            while f"{code}-{i}" in used:
                i += 1
            code = f"{code}-{i}"
        used[code] = name
        if cache is not None and name not in cache:
            cache[name] = code
        out.append((name, code, recs))
    return out


def apply_name_codes(records, cache_path=None):
    """互通名 / 桥名 -> 拼音首字母代号（对外分享脱敏）。

    判重范围：route 在全库内判重，bridge 在同一互通内判重。
    幂等：已是代号（纯 ASCII）的记录再跑一次结果不变。
    返回 {"route": [(原名, 代号)], "bridge": [(route, 原名, 代号)]}。
    """
    if not BRIDGE_PINYIN:
        return {}

    cache = load_code_cache(cache_path)

    r_groups: dict = {}
    for r in records:
        r_groups.setdefault(r.get("route") or "—", []).append(r)
    used_g, route_pairs = {}, []
    for name, code, recs in _code_group(sorted(r_groups.items()), used_g,
                                        cache["route"]):
        for r in recs:
            r["route"] = code
        src = next((x.get("route_src") for x in recs if x.get("route_src")), name)
        route_pairs.append((src, code))

    b_groups: dict = {}
    for r in records:                                    # 此时 route 已是代号
        b_groups.setdefault((r.get("route") or "—", r.get("bridge") or ""), []).append(r)
    per_route: dict = {}
    for (route, name), recs in sorted(b_groups.items()):
        per_route.setdefault(route, []).append((name, recs))
    bridge_pairs = []
    for route in sorted(per_route):
        used = {}
        for name, code, recs in _code_group(per_route[route], used,
                                            cache["bridge"]):
            for r in recs:
                r["bridge"] = code
            src = next((x.get("bridge_src") for x in recs if x.get("bridge_src")), name)
            bridge_pairs.append((route, src, code))

    if cache_path:
        try:
            Path(cache_path).write_text(
                json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            print(f"[警告] 代号缓存写入失败：{e}")

    return {"route": sorted(route_pairs), "bridge": sorted(bridge_pairs)}


def alias(s):
    """按 NAME_ALIAS 做子串替换；空值原样返回。"""
    if s in (None, ""):
        return s
    t = str(s)
    for a, b in NAME_ALIAS.items():
        t = t.replace(a, b)
    return t


def norm(s) -> str:
    """表头/文字归一化：去空白、全角括号转半角、去单位后缀外的符号。"""
    if s is None:
        return ""
    t = str(s)
    t = t.replace("\u3000", "").replace(" ", "").replace("\n", "")
    t = t.replace("（", "(").replace("）", ")").replace("²", "2").replace("³", "3")
    t = t.replace("m²", "m2").replace("m³", "m3")
    return t.strip()


def tidy_id(v):
    """联号统一：1.0 -> 1；'1.0' -> 1；其余原样。"""
    n = to_num(v)
    if n is not None and float(n).is_integer():
        return int(n)
    return v if v is not None and str(v).strip() != "" else ""


def to_num(v):
    """单元格 -> float；空/文本/破折号 -> None。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if not (isinstance(v, float) and math.isnan(v)) else None
    s = str(v).strip().replace(",", "").replace("，", "")
    if s in ("", "-", "—", "–", "/", "无"):
        return None
    m = re.match(r"^-?\d+(\.\d+)?$", s)
    return float(s) if m else None


# ---------------------------------------------------------------- 跨径解析
TOKEN_RE = re.compile(r"^(?:分叉)?\s*(?:(\d+)\s*[*xX×]\s*)?(\d+(?:\.\d+)?)\s*(?:分叉)?$")


def parse_spans(text):
    """'24.732+3*30.005' -> [24.732, 30.005, 30.005, 30.005]；解析失败返回 ([], False)"""
    if text is None:
        return [], False
    s = norm(text).replace("＋", "+").replace("＊", "*").replace(" ", "")
    if not s:
        return [], False
    spans, ok = [], True
    for tok in re.split(r"[+]", s):
        tok = tok.strip()
        if not tok:
            continue
        m = TOKEN_RE.match(tok)
        if not m:
            ok = False
            continue
        cnt = int(m.group(1)) if m.group(1) else 1
        val = float(m.group(2))
        spans.extend([val] * cnt)
    return spans, ok and bool(spans)


def is_fork(text) -> bool:
    return "分叉" in norm(text)


# ---------------------------------------------------------------- 工作簿读取
def iter_sheets(path: Path):
    """统一返回 ([(sheet_name, rows)], {sheet_name: worksheet|None})。
    .xls 无 openpyxl 对象，合并信息不可得（返回 None）。"""
    if path.suffix.lower() == ".xls":
        if xlrd is None:
            raise RuntimeError("需要 xlrd 才能读 .xls：pip install xlrd")
        book = xlrd.open_workbook(str(path))
        out = []
        for sh in book.sheets():
            rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
            out.append((sh.name, rows))
        return out, {n: None for n, _ in out}

    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=False)
    out = []
    for ws in wb.worksheets:
        rows = [[ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
                for r in range(1, ws.max_row + 1)]
        out.append((ws.title, rows))
    return out, {ws.title: ws for ws in wb.worksheets}


def merged_lookup(ws):
    """(row, col) -> 合并区左上角的值所在坐标，用于向下/向右填充。"""
    span = {}
    for rng in ws.merged_cells.ranges:
        r0, c0 = rng.min_row, rng.min_col
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                span[(r, c)] = (r0, c0)
    return span


def merged_titles(ws):
    """区块标题行：横向合并跨度 >= TITLE_COLS 的行 -> {row: text}"""
    titles = {}
    for rng in ws.merged_cells.ranges:
        if rng.max_col - rng.min_col + 1 >= TITLE_COLS and rng.min_row == rng.max_row:
            v = ws.cell(rng.min_row, rng.min_col).value
            if v is not None and str(v).strip():
                titles[rng.min_row] = str(v).strip()
        # 纵向合并的多行标题（如 A50:M51）取首行
        if rng.max_col - rng.min_col + 1 >= TITLE_COLS and rng.max_row > rng.min_row:
            v = ws.cell(rng.min_row, rng.min_col).value
            if v is not None and str(v).strip():
                titles[rng.min_row] = str(v).strip()
    return titles


def match_header_row(row_vals):
    """返回 {key: col_index0}；不像表头则返回 {}。

    两轮匹配：先按**完全相等**占位（避免"联"误吃"联长"列），
    再按"包含"兜底，且所有 key 都不得重复占用同一列。"""
    cells = [norm(v) for v in row_vals]
    mapping, taken = {}, set()

    def scan(key, keys, exact_only):
        for kw in keys:                       # 关键字按精确度从高到低
            kw_n = norm(kw)
            for i, c in enumerate(cells):
                if not c or i in taken:
                    continue
                if c == kw_n or (not exact_only and kw_n in c and len(c) <= len(kw_n) + 8):
                    return i
        return None

    for key, keys in HEADER_KEYS.items():     # 轮 1：精确相等
        i = scan(key, keys, True)
        if i is not None:
            mapping[key], taken = i, taken | {i}
    for key, keys in HEADER_KEYS.items():     # 轮 2：包含兜底
        if key in mapping:
            continue
        i = scan(key, keys, False)
        if i is not None:
            mapping[key], taken = i, taken | {i}
    return mapping if len(mapping) >= 3 else {}


def guess_struct_type(title: str, rows_data) -> str:
    t = norm(title)
    if "钢箱" in t or "钢混" in t:
        return "钢箱梁"
    if "预制" in t or "小箱梁" in t:
        return "预制箱梁"
    if "现浇" in t:
        return "现浇箱梁"
    if "连续梁" in t or "刚构" in t:
        return "连续刚构"
    return "现浇箱梁"      # 兜底：预应力砼箱梁汇总表以现浇为主


# ---------------------------------------------------------------- 主提取
def extract_file(path: Path, project: str | None, default_route: str | None = None):
    sheets, ws_objs = iter_sheets(path)
    records = []
    skipped = 0

    for sheet_name, rows in sheets:
        ws = ws_objs.get(sheet_name)
        titles = merged_titles(ws) if ws is not None else {}
        span = merged_lookup(ws) if ws is not None else {}
        header_rows = []
        for i, rv in enumerate(rows, start=1):
            hm = match_header_row(rv)
            if hm:
                header_rows.append((i, hm))

        for hi, (hrow, hm) in enumerate(header_rows):
            # 数据区终点：下一个表头 / 下一个区块标题 / 表尾
            nxt_header = header_rows[hi + 1][0] if hi + 1 < len(header_rows) else len(rows) + 1
            nxt_title = min([t for t in titles if t > hrow] or [10 ** 9])
            end = min(nxt_header, nxt_title)
            block_title = ""
            for t in sorted([t for t in titles if t < hrow], reverse=True):
                block_title = titles[t]
                break
            struct = guess_struct_type(block_title, rows)
            cur_name = ""
            cur_route = ""

            for r in range(hrow + 1, end):
                rv = rows[r - 1]
                if all(v is None or str(v).strip() == "" for v in rv):
                    continue

                def cell(key):
                    c = hm.get(key)
                    if c is None or c >= len(rv):
                        return None
                    v = rv[c]
                    # 纵向合并：取合并区左上角的值
                    if (v is None) and span:
                        src = span.get((r, c + 1))
                        if src:
                            v = rows[src[0] - 1][src[1] - 1]
                    return v

                name_raw = cell("bridge_name")
                if name_raw not in (None, ""):
                    cur_name = str(name_raw).replace("\n", "").strip()
                name = cur_name or f"{sheet_name}行{r}"
                route_raw = cell("route")
                if route_raw not in (None, ""):
                    cur_route = str(route_raw).replace("\n", "").strip()
                route = cur_route or (default_route or "")

                area = to_num(cell("area"))
                conc = to_num(cell("concrete"))
                strand = to_num(cell("strand"))
                plate = to_num(cell("steel_plate"))
                L = to_num(cell("total_length"))
                w1 = to_num(cell("w_start"))
                w2 = to_num(cell("w_end"))
                wu = to_num(cell("w_uniform"))     # 单宽度列写法：起终点同值
                if w1 is None and w2 is None and wu is not None:
                    w1 = w2 = wu
                span_txt = cell("span_raw")
                spans, span_ok = parse_spans(span_txt)
                span_sum = round(sum(spans), 3) if spans else None

                if conc is None and strand is None:
                    # 只有桥名/跨径/面积、砼与钢绞线都空 -> 占位行（未统计），不入库
                    skipped += 1
                    continue

                # ---- 钢箱梁误填砼列：值 / 面积 明显超过砼含量上限 -> 视为钢板 kg
                struct_row = struct
                if plate is None and conc is not None and area and conc / area > 5:
                    plate, conc = conc, None
                    struct_row = "钢箱梁"

                rec = {
                    "project": alias(project or path.stem),
                    "source_file": path.name,          # 不替换，保留真实文件名
                    "sheet": sheet_name,
                    "row": r,
                    "block": alias(block_title or sheet_name),
                    "struct_type": struct_row,
                    "route": alias(route),
                    "route_src": route,          # 源表原始互通名（未代号化）
                    "bridge": alias(name),
                    "bridge_src": name,          # 源表原始桥名（未代号化）
                    "unit_no": tidy_id(cell("unit_no")),
                    "span_raw": str(span_txt).replace("\n", "").strip() if span_txt else "",
                    "spans": spans,
                    "n_spans": len(spans) or None,
                    "max_span": max(spans) if spans else None,
                    "length_m": L,
                    "span_sum": span_sum,
                    "width_start": w1,
                    "width_end": w2,
                    "width_avg": round((w1 + w2) / 2, 3) if (w1 is not None and w2 is not None) else None,
                    "area_m2": area,
                    "concrete_m3": conc,
                    "strand_kg": strand,
                    "steel_plate_kg": plate,
                    "fork": is_fork(span_txt),
                    "remark": (str(cell("remark")).strip() if cell("remark") else ""),
                    "src_conc_ratio": to_num(cell("src_conc_ratio")),
                    "src_strand_m2": to_num(cell("src_strand_m2")),
                    "src_strand_m3": to_num(cell("src_strand_m3")),
                }
                rec.update(derive(rec))
                rec["flags"] = check(rec)
                records.append(rec)

    # 区块内重复砼数量 -> 疑似复制错误
    by_block = {}
    for rec in records:
        key = (rec["source_file"], rec["sheet"], rec["block"])
        by_block.setdefault(key, []).append(rec)
    for grp in by_block.values():
        seen = {}
        for rec in grp:
            v = rec.get("concrete_m3")
            if v is None:
                continue
            if v in seen and abs((seen[v].get("area_m2") or 0) - (rec.get("area_m2") or 0)) > 1:
                for x in (seen[v], rec):
                    if "砼数量与本区块另一联重复" not in x["flags"]:
                        x["flags"].append("砼数量与本区块另一联重复")
            seen.setdefault(v, rec)
    if skipped:
        print(f"  （跳过 {skipped} 行：砼与钢绞线均为空的占位行）")
    return records


def derive(rec):
    """计算派生指标（唯一口径，见 references）。"""
    a, c, s, p = rec["area_m2"], rec["concrete_m3"], rec["strand_kg"], rec["steel_plate_kg"]
    L = rec["length_m"]
    d = {
        "conc_ratio": round(c / a, 4) if (c and a) else None,          # 砼 m3/m2
        "strand_m2": round(s / a, 3) if (s is not None and a) else None,  # 钢绞线 kg/m2
        "strand_m3": round(s / c, 3) if (s is not None and c) else None,  # 钢绞线 kg/m3
        "plate_m2": round(p / a, 2) if (p and a) else None,           # 钢板 kg/m2
        "conc_per_m": round(c / L, 3) if (c and L) else None,         # 延米砼 m3/m
        "strand_per_m": round(s / L, 2) if (s is not None and L) else None,
    }
    return d


def check(rec):
    f = []
    a, L = rec["area_m2"], rec["length_m"]
    if rec["span_sum"] and L and abs(rec["span_sum"] - L) > max(0.05, TOL_LEN * L):
        f.append(f"跨径和{rec['span_sum']:g}≠联长{L:g}")
    if a and L and rec["width_avg"]:
        a_expect = L * rec["width_avg"]
        if abs(a - a_expect) / a_expect > TOL_AREA:
            f.append(f"面积{a:.1f}与联长×均宽{a_expect:.1f}不符")
    w1, w2 = rec["width_start"], rec["width_end"]
    if w1 and w2 and not rec["fork"]:
        ratio = max(w1, w2) / min(w1, w2)
        if ratio > WIDTH_RATIO:
            f.append(f"起终点宽度异常({w1:g}/{w2:g})疑似小数点错位")
    cr = rec.get("conc_ratio")
    if rec["struct_type"] != "钢箱梁":
        if cr is not None:
            lo, hi = RANGE["conc_ratio"]
            if not (lo <= cr <= hi):
                f.append(f"砼含量{cr:.3f}越界({lo}~{hi})")
        if rec["concrete_m3"] in (0, None):
            f.append("缺砼数量")
    if rec["strand_kg"] == 0:
        # 钢箱梁可无预应力（纯钢板梁段），不算缺陷；砼箱梁为 0 则多半是源表未填
        if rec["struct_type"] != "钢箱梁":
            f.append("钢绞线为0")
    for k, rng in (("strand_m2", RANGE["strand_m2"]), ("strand_m3", RANGE["strand_m3"])):
        v = rec.get(k)
        if v:
            if not (rng[0] <= v <= rng[1]):
                f.append(f"{k}={v:.1f}越界({rng[0]}~{rng[1]})")
    pm = rec.get("plate_m2")
    if pm:
        lo, hi = RANGE["plate_m2"]
        if not (lo <= pm <= hi):
            f.append(f"钢板含量{pm:.0f}越界({lo}~{hi})")
    return f


# ---------------------------------------------------------------- 统计
def pct(vals, q):
    if not vals:
        return None
    vals = sorted(vals)
    k = (len(vals) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return vals[f] if f == c else vals[f] * (c - k) + vals[c] * (k - f)


def stats(records):
    out = {}
    groups = {}
    for r in records:
        if r["flags"]:
            continue
        groups.setdefault(r["struct_type"], []).append(r)
    for st, rs in groups.items():
        d = {"n": len(rs), "n_span": {}, "conc_ratio": {}, "strand_m2": {}, "strand_m3": {}, "plate_m2": {}}
        for key in ("conc_ratio", "strand_m2", "strand_m3", "plate_m2"):
            vals = [r[key] for r in rs if r.get(key)]
            if vals:
                d[key] = {
                    "min": round(min(vals), 2), "p25": round(pct(vals, .25), 2),
                    "median": round(statistics.median(vals), 2),
                    "p75": round(pct(vals, .75), 2), "max": round(max(vals), 2),
                    "mean": round(statistics.fmean(vals), 2),
                }
        # 分档口径统一为「左闭右开」：lo <= max_span < hi，与网页端 BANDS 完全一致
        for band, lo, hi in (("20m以下", 0, 20), ("20~30m", 20, 30),
                             ("30~40m", 30, 40), ("40m以上", 40, 9999)):
            sub = [r["conc_ratio"] for r in rs if r.get("max_span") and lo <= r["max_span"] < hi and r.get("conc_ratio")]
            if sub:
                d["n_span"][band] = {"n": len(sub), "conc": round(statistics.median(sub), 3)}
        out[st] = d
    return out


def stats_by_route(records):
    """按 (互通/工区, 结构类型) 分组的中位值，用于横向对比各互通的设计水平。"""
    g = {}
    for r in records:
        if r["flags"]:
            continue
        g.setdefault((r.get("route") or "", r["struct_type"]), []).append(r)
    out = {}
    for k, rs in g.items():
        if len(rs) < 2:
            continue
        d = {"n": len(rs)}
        for key in ("conc_ratio", "strand_m2", "strand_m3"):
            vals = [r[key] for r in rs if r.get(key)]
            d[key] = statistics.median(vals) if vals else None
        out[k] = d
    return dict(sorted(out.items()))


# ---------------------------------------------------------------- 输出
CSV_COLS = [
    ("project", "工程"), ("route", "互通/工区"), ("struct_type", "结构类型"),
    ("bridge", "桥名/匝道"), ("unit_no", "联号"),
    ("span_raw", "跨径"), ("n_spans", "跨数"), ("max_span", "最大跨(m)"), ("length_m", "联长(m)"),
    ("width_start", "起点宽(m)"), ("width_end", "终点宽(m)"), ("width_avg", "平均宽(m)"),
    ("area_m2", "桥梁面积(m2)"), ("concrete_m3", "砼(m3)"), ("strand_kg", "钢绞线(kg)"),
    ("steel_plate_kg", "钢板(kg)"), ("conc_ratio", "砼含量(m3/m2)"), ("strand_m2", "钢绞线(kg/m2)"),
    ("strand_m3", "钢绞线(kg/m3)"), ("plate_m2", "钢板(kg/m2)"),
    ("conc_per_m", "延米砼(m3/m)"), ("strand_per_m", "延米钢绞线(kg/m)"),
    ("remark", "备注"), ("flags", "校核标记"), ("source_file", "源文件"), ("row", "源行号"),
]


def write_csv(records, path: Path):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([c[1] for c in CSV_COLS])
        for r in records:
            row = []
            for k, _ in CSV_COLS:
                v = r.get(k)
                # 展示层也做代号替换（源文件名另有一份真实值供回表溯源，见 MD 待核清单）
                if isinstance(v, str):
                    v = alias(v)
                row.append("、".join(v) if isinstance(v, list) else v)
            w.writerow(row)


def fmt(v, nd=2):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def write_md(records, st, path: Path, lib_path: Path, code_map=None):
    good = [r for r in records if not r["flags"]]
    bad = [r for r in records if r["flags"]]
    L = []
    L.append("---")
    L.append("tags:\n  - 桥梁\n  - 材料指标\n  - 箱梁\n  - 指标库\n  - Excel自动化")
    L.append("aliases:\n  - 箱梁技术指标库\n  - 箱梁材料含量指标库")
    L.append(f"created: {date.today()}\nupdated: {date.today()}")
    L.append("type: 指标库")
    L.append("---\n")
    L.append("# 箱梁技术指标库\n")
    L.append(f"> 由技能 `box-girder-index` 自动生成，共 **{len(records)}** 条记录"
             f"（有效 {len(good)} 条 / 待核 {len(bad)} 条）。数据源："
             f"{', '.join(sorted({alias(r['source_file']) for r in records}))}。\n")
    if NAME_ALIAS:
        L.append(f"> 名称代号：{'、'.join(f'{a} → {b}' for a, b in NAME_ALIAS.items())}"
                 f"（源文件名另保留真值，见第七节待核清单）。\n")

    L.append("## 一、指标口径\n")
    L.append("| 指标 | 公式 | 单位 |")
    L.append("|---|---|---|")
    L.append("| 砼含量 | 砼方量 ÷ 桥梁面积 | m³/m² |")
    L.append("| 钢绞线含量(面积) | 钢绞线重量 ÷ 桥梁面积 | kg/m² |")
    L.append("| 钢绞线含量(体积) | 钢绞线重量 ÷ 砼方量 | kg/m³ |")
    L.append("| 钢板含量 | 钢板重量 ÷ 桥梁面积 | kg/m² |")
    L.append("| 延米砼 | 砼方量 ÷ 联长 | m³/m |")
    L.append("")

    L.append("## 二、分类统计（仅取校核通过的记录）\n")
    L.append("| 结构类型 | 样本 | 砼含量 P25/中位/P75 | 钢绞线 kg/m² P25/中位/P75 | 钢绞线 kg/m³ P25/中位/P75 | 钢板 kg/m² |")
    L.append("|---|---|---|---|---|---|")
    for k, d in st.items():
        def trip(key):
            x = d.get(key) or {}
            if not x:
                return "—"
            return f"{x['p25']:.2f} / **{x['median']:.2f}** / {x['p75']:.2f}"
        pl = d.get("plate_m2") or {}
        pl_txt = f"{pl['median']:.0f}" if pl else "—"
        L.append(f"| {k} | {d['n']} | {trip('conc_ratio')} | {trip('strand_m2')} | "
                 f"{trip('strand_m3')} | {pl_txt} |")
    L.append("")

    L.append("## 三、按最大跨径分档（砼含量中位值 m³/m²）\n")
    bands = [b for d in st.values() for b in d["n_span"]]
    uniq = []
    for b in ("20m以下", "20~30m", "30~40m", "40m以上"):
        if b in bands:
            uniq.append(b)
    if uniq:
        L.append("| 结构类型 | " + " | ".join(uniq) + " |")
        L.append("|---" * (len(uniq) + 1) + "|")
        for k, d in st.items():
            cells = []
            for b in uniq:
                v = d["n_span"].get(b)
                cells.append(f"{v['conc']:.3f} (n={v['n']})" if v else "—")
            L.append(f"| {k} | " + " | ".join(cells) + " |")
        L.append("")

    br = stats_by_route(records)
    if br:
        L.append("## 四、按互通/工区分组（仅取校核通过的记录）\n")
        L.append("| 互通/工区 | 结构 | 样本 | 砼含量中位 m³/m² | 钢绞线中位 kg/m² | 钢绞线中位 kg/m³ |")
        L.append("|---|---|---|---|---|---|")
        for (rt, stt), d in br.items():
            cr = f"{d['conc_ratio']:.3f}" if d.get("conc_ratio") else "—"
            s2 = f"{d['strand_m2']:.1f}" if d.get("strand_m2") else "—"
            s3 = f"{d['strand_m3']:.1f}" if d.get("strand_m3") else "—"
            L.append(f"| {rt or '（未标）'} | {stt} | {d['n']} | {cr} | {s2} | {s3} |")
        L.append("")

    L.append("## 五、逐联指标表（已排序）\n")
    L.append("| 互通 | 结构 | 桥名 | 联号 | 跨径 | 联长 | 面积 | 砼 | 钢绞线 | 砼 m³/m² | 钢绞线 kg/m² | 钢绞线 kg/m³ | 标记 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(records, key=lambda x: (x["struct_type"], x.get("route") or "",
                                            x["bridge"], x["row"])):
        flag = "⚠ " + "；".join(r["flags"]) if r["flags"] else ""
        L.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            r.get("route") or "", r["struct_type"], r["bridge"], fmt(r["unit_no"], 0),
            r["span_raw"], fmt(r["length_m"]), fmt(r["area_m2"], 1), fmt(r["concrete_m3"], 2),
            fmt(r["strand_kg"], 1), fmt(r["conc_ratio"], 3), fmt(r["strand_m2"], 2),
            fmt(r["strand_m3"], 2), flag))
    L.append("")

    if bad:
        L.append("## 六、待核记录（建议回源表确认后修正）\n")
        for r in bad:
            L.append(f"- **{r['bridge']} 第{r['unit_no']}联**（`{r['source_file']}` 第 {r['row']} 行，"
                     f"跨径 {r['span_raw']}）：" + "；".join(r["flags"]))
        L.append("")
    L.append(f"---\n")
    if code_map:
        L.append("## 七、名称代号对照表\n")
        L.append("> 互通名与桥名均按汉字拼音首字母代号化；缩写重复时自动加 `-2` / `-3` 后缀"
                 "（互通名全库判重，桥名互通内判重）。\n")
        if code_map.get("route"):
            L.append("### 互通 / 工区\n")
            L.append("| 原名称 | 代号 |")
            L.append("|---|---|")
            for name, code in code_map["route"]:
                L.append(f"| {name} | **{code}** |")
            L.append("")
        if code_map.get("bridge"):
            L.append("### 桥名\n")
            L.append("| 互通 | 原桥名 | 代号 |")
            L.append("|---|---|---|")
            for route, name, code in code_map["bridge"]:
                L.append(f"| {route} | {name} | **{code}** |")
            L.append("")
    L.append("## 八、技能入口\n")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    L.append("| 技能 | `box-girder-index`（箱梁技术指标库） |")
    L.append("| 技能生效目录 | `C:/Users/Administrator/.workbuddy/skills/box-girder-index/` |")
    L.append(f"| 指标库数据 | `{lib_path}` |")
    L.append("| 知识库备份 | `13 工具开发/箱梁技术指标库/源文件/`（SKILL.md + 脚本 + 口径文档） |")
    L.append("| 重新生成 | 见 SKILL.md「三、怎么跑」，重跑会自动覆盖本文件 |")
    L.append("| 口径/阈值 | 技能目录 `references/指标口径与校核规则.md` |")
    L.append("")
    path.write_text("\n".join(L), encoding="utf-8")


HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>箱梁技术指标库</title>
<style>
*{box-sizing:border-box}body{margin:0;padding:28px 32px;background:#f6f7f9;color:#1c2530;
font:14px/1.6 "Microsoft YaHei",system-ui,sans-serif}
h1{font-size:22px;margin:0 0 4px;font-weight:600}
.sub{color:#68737d;font-size:13px;margin-bottom:20px}
.cards{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:22px}
.card{background:#fff;border:1px solid #e3e7ec;border-radius:10px;padding:14px 18px;min-width:190px;flex:1}
.card .k{font-size:12px;color:#68737d}.card .v{font-size:24px;font-weight:600;margin-top:2px}
.card .u{font-size:12px;color:#8b949e;margin-left:3px;font-weight:400}
.panel{background:#fff;border:1px solid #e3e7ec;border-radius:10px;padding:16px 18px;margin-bottom:20px}
.panel h2{font-size:15px;margin:0 0 12px;font-weight:600}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{border-bottom:1px solid #eef1f4;padding:6px 8px;text-align:right;white-space:nowrap}
th{background:#fafbfc;color:#4a5560;font-weight:600;position:sticky;top:0}
td.l,th.l{text-align:left}
tr.warn td{background:#fff8f2}
tr:hover td{background:#f3f8ff}
.tag{display:inline-block;font-size:11px;padding:1px 6px;border-radius:4px;background:#eef4ff;color:#2c62c9}
.tag.g{background:#eafaf0;color:#1a7f4b}.tag.w{background:#fff1e6;color:#b35309}
.scroll{max-height:460px;overflow:auto;-webkit-overflow-scrolling:touch}
@media(max-width:820px){
 body{padding:14px 12px 26px;font-size:15px}
 h1{font-size:20px}
 .sub{margin-bottom:12px}
 .card{min-width:100%}
 .scroll{max-height:70vh}
}
.legend{font-size:12px;color:#68737d;margin-top:8px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}
</style></head><body>
<h1>箱梁技术指标库</h1>
<div class="sub" id="sub"></div>
<div class="cards" id="cards"></div>
<div class="panel"><h2>砼含量 — 最大跨径关系</h2>
<svg id="scatter" width="100%" height="300"></svg>
<div class="legend"><span class="dot" style="background:#3b7ddd"></span>现浇箱梁
<span class="dot" style="background:#e8730c;margin-left:14px"></span>钢箱梁
<span class="dot" style="background:#8b949e;margin-left:14px"></span>预制箱梁　｜　空心点 = 校核未通过</div></div>
<div class="panel"><h2>逐联指标<span class="sub" style="margin-left:10px" id="cnt"></span></h2>
<div class="scroll"><table id="tbl"></table></div></div>
<script>
const DATA = __DATA__, STATS = __STATS__;
const f=(v,n=2)=>v==null?'—':(+v).toFixed(n);
document.getElementById('sub').textContent =
  `共 ${DATA.length} 条 · 有效 ${DATA.filter(d=>!(d.flags&&d.flags.length)).length} 条 · ${new Set(DATA.map(d=>d.project)).size} 个工程 / ${new Set(DATA.map(d=>d.route||'—')).size} 个互通 · 生成于 ${new Date().toLocaleDateString('zh-CN')}`;
// 卡片：按结构类型给中位值
const c=document.getElementById('cards');
Object.entries(STATS).forEach(([k,s])=>{
  const isSteel = !(s.conc_ratio&&s.conc_ratio.median);
  const main = isSteel ? (s.plate_m2?s.plate_m2.median.toFixed(0):'—') : s.conc_ratio.median.toFixed(3);
  const unit = isSteel ? 'kg/m² 钢板' : 'm³/m² 砼';
  const sub  = isSteel
     ? `样本 ${s.n} 联 · 钢板梁无预应力`
     : `钢绞线 ${s.strand_m2&&s.strand_m2.median?s.strand_m2.median.toFixed(1):'—'} kg/m² · n=${s.n}`;
  c.insertAdjacentHTML('beforeend',`<div class="card"><div class="k">${k} · ${isSteel?'钢板含量中位':'砼含量中位'}</div>
   <div class="v">${main}<span class="u">${unit}</span></div>
   <div class="k" style="margin-top:6px">${sub}</div></div>`);
});
// 散点
const bad=DATA.filter(d=>d.flags&&d.flags.length);
const ok=DATA.filter(d=>!(d.flags&&d.flags.length));
document.getElementById('cnt').textContent = `有效 ${ok.length} · 待核 ${bad.length}`;
const W=Math.max(640, document.getElementById('scatter').clientWidth||900), H=300, P={l:52,r:16,t:14,b:34};
// 纵轴只按有效记录定标，越界的待核点不画（避免 2.11 这种脏值压扁其余点）
const okRows=DATA.filter(d=>!(d.flags&&d.flags.length));
const xs=DATA.map(d=>d.max_span).filter(v=>v), ys=okRows.map(d=>d.conc_ratio).filter(v=>v);
if(xs.length&&ys.length){
 const x0=0, x1=Math.max(...xs)*1.08, y0=0, y1=Math.max(...ys)*1.15;
 const sx=v=>P.l+(v-x0)/(x1-x0)*(W-P.l-P.r), sy=v=>H-P.b-(v-y0)/(y1-y0)*(H-P.t-P.b);
 const col=t=>t==='钢箱梁'?'#e8730c':t==='预制箱梁'?'#8b949e':'#3b7ddd';
 let s='';
 for(let i=0;i<=4;i++){const v=y1*i/4, y=sy(v);
  s+=`<line x1="${P.l}" y1="${y}" x2="${W-P.r}" y2="${y}" stroke="#eef1f4"/>`;
  s+=`<text x="${P.l-8}" y="${y+4}" font-size="11" fill="#8b949e" text-anchor="end">${v.toFixed(2)}</text>`;}
 for(let i=0;i<=5;i++){const v=x1*i/5, x=sx(v);
  s+=`<text x="${x}" y="${H-12}" font-size="11" fill="#8b949e" text-anchor="middle">${v.toFixed(0)}</text>`;}
 s+=`<text x="${(W)/2}" y="${H-1}" font-size="11" fill="#68737d" text-anchor="middle">最大跨径 (m)</text>`;
 DATA.forEach(d=>{if(!d.max_span||!d.conc_ratio||d.conc_ratio>y1)return;const w=d.flags&&d.flags.length;
  s+=`<circle cx="${sx(d.max_span)}" cy="${sy(d.conc_ratio)}" r="${w?4.5:4}" fill="${w?'#fff':col(d.struct_type)}"
      stroke="${col(d.struct_type)}" stroke-width="1.6" opacity=".9"><title>${d.bridge} ${d.unit_no}联 ${d.span_raw}
砼 ${f(d.conc_ratio,3)} m³/m² · 钢绞线 ${f(d.strand_m2,1)} kg/m²${w?'\\n⚠ '+d.flags.join('；'):''}</title></circle>`;});
 document.getElementById('scatter').innerHTML=s;
}
// 表
const cols=[['route','互通',1],['struct_type','结构',1],['bridge','桥名',1],['unit_no','联号',1],['span_raw','跨径',1],
 ['length_m','联长',0],['area_m2','面积',0],['concrete_m3','砼',0],['strand_kg','钢绞线',0],
 ['conc_ratio','砼 m³/m²',0],['strand_m2','钢绞线 kg/m²',0],['strand_m3','钢绞线 kg/m³',0],['plate_m2','钢板 kg/m²',0]];
const t=document.getElementById('tbl');
t.innerHTML='<thead><tr>'+cols.map(c=>`<th class="${c[2]?'l':''}">${c[1]}</th>`).join('')+'<th class="l">校核</th></tr></thead><tbody>'+
 DATA.slice().sort((a,b)=>((a.struct_type||'')+(a.route||'')+a.bridge)
   .localeCompare((b.struct_type||'')+(b.route||'')+b.bridge,'zh')).map(d=>{
  const w=d.flags&&d.flags.length;
  return `<tr class="${w?'warn':''}">`+cols.map(c=>{
   let v=d[c[0]]; if(v==null||v==='')v='—';
   else if(typeof v==='number') v = Number.isInteger(v)? String(v)
      : (+v).toFixed(c[1].includes('m³/m²')?3:2);
   return `<td class="${c[2]?'l':''}">${v}</td>`;}).join('')+
  `<td class="l">${w?'<span class="tag w">'+d.flags.join('；')+'</span>':'<span class="tag g">通过</span>'}</td></tr>`;}).join('')+'</tbody>';
</script></body></html>"""


# ------------------------------------------------- 演示版看板（视频录屏用）
# 与正式看板同源数据，差别只在呈现：大字号、少列、筛选实时联动、行高亮。
PUBLIC_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>箱梁技术指标速查 · __BRAND__</title>
<style>
*{box-sizing:border-box}body{margin:0;padding:26px 30px 40px;background:#f6f7f9;color:#1c2530;
font:18px/1.7 "Microsoft YaHei",system-ui,sans-serif}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:28px;margin:0 0 4px;font-weight:600}
h1 .brand{color:#3b7ddd;font-weight:500}
.sub{color:#68737d;font-size:15px;margin:0 0 20px}
.kpis{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:20px}
.kpi{background:#fff;border:1px solid #e3e7ec;border-radius:12px;padding:12px 20px;min-width:130px;flex:1}
.kpi .k{font-size:14px;color:#68737d}
.kpi .v{font-size:27px;font-weight:600;margin-top:1px;letter-spacing:-.4px}
.kpi .u{font-size:14px;color:#8b949e;margin-left:4px;font-weight:400}
.cards{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:20px}
.card{background:#fff;border:1px solid #e3e7ec;border-radius:12px;padding:16px 20px;min-width:300px;flex:1}
.card .hd{font-size:17px;font-weight:600;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #f0f2f5}
.card .k{font-size:14px;color:#68737d;margin-top:10px}
.card .v{font-size:34px;font-weight:600;margin-top:0;letter-spacing:-.5px}
.card .u{font-size:14px;color:#8b949e;margin-left:5px;font-weight:400}
.card .s{font-size:14px;color:#68737d;margin-top:3px}
.panel{background:#fff;border:1px solid #e3e7ec;border-radius:12px;padding:16px 18px;margin-bottom:18px}
.panel h2{font-size:19px;margin:0 0 12px;font-weight:600}
table{border-collapse:collapse;width:100%;font-size:17px}
th,td{border-bottom:1px solid #eef1f4;padding:9px 12px;text-align:right;white-space:nowrap}
th{background:#fafbfc;color:#4a5560;font-weight:600;font-size:15px}
td.l,th.l{text-align:left}
.legend{font-size:14px;color:#68737d;margin-top:10px}
.dot{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:6px}
.note{font-size:15px;color:#4a5560}
.note ul{margin:6px 0 0;padding-left:22px}
.note li{margin-bottom:4px}
.qbar{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end}
.qf{display:flex;flex-direction:column;gap:3px}
.qf label{font-size:13px;color:#68737d}
.qf input,.qf select{font-size:17px;padding:8px 10px;border:1px solid #d8dee6;border-radius:8px;background:#fff;color:#1c2530;min-height:40px}
.qf input{width:104px}
.qf .u{font-size:13px;color:#8b949e}
.q button,#qGo{font-size:16px;padding:9px 20px;border:0;border-radius:8px;background:#3b7ddd;color:#fff;cursor:pointer;min-height:40px}
#qGo:hover{background:#2f6ec4}
.qpreset{font-size:14px;color:#68737d;margin-top:10px}
.qpreset a{color:#2c62c9;text-decoration:none;margin-right:12px;white-space:nowrap}
.qpreset a:hover{text-decoration:underline}
.qout{margin-top:14px;font-size:16px;color:#4a5560}
.qout .row{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px}
.qout .box{background:#f7f9fc;border:1px solid #e3e7ec;border-radius:10px;padding:11px 16px;min-width:180px;flex:1}
.qout .box .k{font-size:13px;color:#68737d}
.qout .box .v{font-size:26px;font-weight:600;letter-spacing:-.4px}
.qout .box .v small{font-size:14px;font-weight:400;color:#8b949e;margin-left:4px}
.qout .box .s{font-size:13px;color:#68737d;margin-top:2px}
.qout .warn{background:#fff6ee;border:1px solid #f2d9bd;color:#a34908;border-radius:8px;padding:9px 13px;font-size:14px;margin-top:10px}
.qout .empty{color:#8b949e;font-size:15px;margin-top:8px}
.qhint{font-size:13px;color:#8b949e;margin-top:12px;line-height:1.6}
.foot{color:#98a1aa;font-size:13px;text-align:center;margin-top:22px}
.scroll{max-height:520px;overflow:auto;-webkit-overflow-scrolling:touch}
@media(max-width:820px){
 body{padding:16px 14px 28px;font-size:16px}
 h1{font-size:22px}
 .sub{font-size:13px;margin-bottom:14px}
 .kpi{padding:10px 14px;min-width:104px}
 .kpi .v{font-size:22px}.kpi .k{font-size:12px}
 .card{padding:14px 16px;min-width:100%}
 .card .v{font-size:30px}
 .panel{padding:13px 14px;margin-bottom:14px}
 .panel h2{font-size:16px;margin-bottom:9px}
 table{font-size:15px}
 th,td{padding:8px 9px}
 .note{font-size:14px}
 .qbar{gap:10px}
 .qf input,.qf select{font-size:16px;min-height:42px}
 .qf input{width:88px}
 #qGo{width:100%;margin-top:4px}
 .qout .box{min-width:100%}
}
</style></head><body>
<noscript><div style="background:#fff4e5;border:1px solid #f0b357;color:#8a4b00;
padding:14px 18px;margin-bottom:18px;border-radius:10px;font-size:16px;line-height:1.65">
<b>⚠ 请用浏览器打开本页。</b><br>
当前是用「文件预览」方式打开的，下面的速查功能是关着的（页面脚本没执行）。<br>
<b>安卓</b>：文件管理里长按本文件 → 更多 → 「其他应用打开」→ 选 <b>夸克浏览器</b>（推荐）或 Chrome。<br>
华为 / 鸿蒙手机若列表里没有浏览器，先装个夸克再回来选（自带浏览器打开本地文件会白屏）；<br>
<b>iPhone</b>：在「文件」App 里长按本文件 → 分享 → 用 Safari 打开。
</div></noscript>
<div class="wrap">
<h1>箱梁技术指标速查<span class="brand"> · __BRAND__</span></h1>
<p class="sub" id="sub"></p>
<div class="kpis" id="kpis"></div>
<div class="panel q"><h2>经验值速查</h2>
<div class="qbar">
 <div class="qf"><label>最大跨径</label><input id="qL" type="number" step="0.5" value="30"><span class="u">m</span></div>
 <div class="qf"><label>桥面宽度</label><input id="qW" type="number" step="0.5" value="10"><span class="u">m</span></div>
 <div class="qf"><label>结构类型</label><select id="qT"></select></div>
 <button id="qGo" type="button">查一下</button>
</div>
<div class="qpreset">常用：<a href="#" data-l="30" data-w="10">30m × 10m 匝道</a>
<a href="#" data-l="30" data-w="25">30m × 25m 主线</a>
<a href="#" data-l="30" data-w="33">30m × 33m 宽主线</a>
<a href="#" data-l="40" data-w="16">40m × 16m</a></div>
<div id="qOut" class="qout"></div>
<div class="qhint">在样本里找跨径、桥宽都接近的联，给出中位值与 P25~P75 区间。样本不足时会自动放宽范围，<b>结果仅供参考，不作施工图依据</b>。</div></div>
<div class="cards" id="cards"></div>
<div class="panel"><h2>砼含量 — 最大跨径关系</h2>
<svg id="scatter" width="100%" height="360"></svg>
<div class="legend"><span class="dot" style="background:#3b7ddd"></span>现浇箱梁
<span class="dot" style="background:#e8730c;margin-left:16px"></span>钢箱梁　｜　空心点 = 数据校核未通过，已排除出统计</div></div>
<div class="panel"><h2>按最大跨径分档（砼 / 钢绞线含量中位值）</h2>
<div class="scroll"><table id="band"></table></div></div>
<div class="panel"><h2>各互通指标对比（中位值）</h2>
<div class="scroll"><table id="route"></table></div></div>
<div class="panel note"><h2>口径说明</h2><ul>
<li><b>砼含量</b> = 砼数量 ÷ 桥梁面积（m³/m²）；<b>钢绞线含量</b>分别按桥面面积（kg/m²）与砼方量（kg/m³）给出。</li>
<li>统计仅计入<b>通过自动校核</b>的记录；校核项含跨径和与联长是否一致、面积与跨径×宽度是否相符、指标是否越界等。</li>
<li>本页为<b>统计摘要</b>，不含逐联明细，也不含工程名、桥名、互通名等可溯源信息。</li>
<li>数值为已建成/在建工程实测汇总，仅供前期估算与方案比选参考，不作为施工图设计依据。</li>
</ul></div>
<div class="foot" id="foot"></div>
</div>
<script>
const S=__SUMMARY__;
const f=(v,n=2)=>(v==null||v==='')?'—':(+v).toFixed(n);
const col=t=>t==='钢箱梁'?'#e8730c':t==='预制箱梁'?'#8b949e':'#3b7ddd';
const o=S.overview;
document.getElementById('sub').textContent =
  `样本 ${o.total} 条（有效 ${o.ok} · 待核 ${o.pending}） · ${o.projects} 个工程 / ${o.routes} 个互通 · 自动生成于 ${S.generated}`;
document.getElementById('foot').textContent =
  `箱梁技术指标速查 · __BRAND__ · ${S.generated}`;

// KPI 条
const kpis=[
 ['样本总量', o.total, '条'],
 ['有效样本', o.ok, '条'],
 ['校核剔除', o.pending, '条'],
 ['跨径范围', (f(o.span_min,0)+'~'+f(o.span_max,0)), 'm'],
 ['桥宽范围', (f(o.width_min,1)+'~'+f(o.width_max,1)), 'm'],
];
const kc=document.getElementById('kpis');
kpis.forEach(function(a){
 kc.insertAdjacentHTML('beforeend',
  `<div class="kpi"><div class="k">${a[0]}</div><div class="v">${a[1]}<span class="u">${a[2]}</span></div></div>`);
});

// 统计卡片
const cc=document.getElementById('cards');
S.cards.forEach(function(c){
 const isSteel = !c.conc && c.plate;
 let body = '';
 if (isSteel) {
  body = `<div class="k">钢板含量中位</div>
   <div class="v">${f(c.plate.median,0)}<span class="u">kg/m²</span></div>
   <div class="s">区间 ${f(c.plate.min,0)} ~ ${f(c.plate.max,0)} kg/m² · 钢箱梁无预应力</div>`;
 } else {
  const cr=c.conc, s2=c.strand_m2, s3=c.strand_m3;
  body = `<div class="k">砼含量中位</div>
   <div class="v">${f(cr.median,3)}<span class="u">m³/m²</span></div>
   <div class="s">P25 ${f(cr.p25,3)} · P75 ${f(cr.p75,3)} · 区间 ${f(cr.min,3)}~${f(cr.max,3)}</div>
   <div class="k">钢绞线（按桥面面积）</div>
   <div class="v">${f(s2.median,1)}<span class="u">kg/m²</span></div>
   <div class="s">P25 ${f(s2.p25,1)} · P75 ${f(s2.p75,1)} · 区间 ${f(s2.min,1)}~${f(s2.max,1)}</div>
   <div class="k">钢绞线（按砼方量）</div>
   <div class="v">${f(s3.median,1)}<span class="u">kg/m³</span></div>
   <div class="s">P25 ${f(s3.p25,1)} · P75 ${f(s3.p75,1)} · 区间 ${f(s3.min,1)}~${f(s3.max,1)}</div>`;
 }
 cc.insertAdjacentHTML('beforeend',
  `<div class="card"><div class="hd">${c.type} · 样本 ${c.n} 联</div>${body}</div>`);
});

// 散点
(function(){
 const svg=document.getElementById('scatter');
 const W=Math.max(700, svg.clientWidth||980), H=360, P={l:62,r:22,t:16,b:42};
 const pts=S.points;
 if(!pts.length){svg.innerHTML='';return;}
 const x1=Math.max.apply(null, pts.map(function(d){return d.x;}))*1.08;
 const y1=Math.max.apply(null, pts.map(function(d){return d.y;}))*1.15;
 const sx=function(v){return P.l+(v-0)/(x1-0)*(W-P.l-P.r);};
 const sy=function(v){return H-P.b-(v-0)/(y1-0)*(H-P.t-P.b);};
 let s='';
 for(let i=0;i<=4;i++){
  const v=y1*i/4, y=sy(v);
  s+='<line x1="'+P.l+'" y1="'+y+'" x2="'+(W-P.r)+'" y2="'+y+'" stroke="#eef1f4"/>';
  s+='<text x="'+(P.l-10)+'" y="'+(y+5)+'" font-size="14" fill="#8b949e" text-anchor="end">'+v.toFixed(2)+'</text>';
 }
 for(let i=0;i<=5;i++){
  const v=x1*i/5, x=sx(v);
  s+='<text x="'+x+'" y="'+(H-14)+'" font-size="14" fill="#8b949e" text-anchor="middle">'+v.toFixed(0)+'</text>';
 }
 s+='<text x="'+(W/2)+'" y="'+(H-2)+'" font-size="14" fill="#68737d" text-anchor="middle">最大跨径 (m)</text>';
 s+='<text x="16" y="'+((H-P.b)/2)+'" font-size="14" fill="#68737d" text-anchor="middle" transform="rotate(-90 16 '+((H-P.b)/2)+')">砼 m³/m²</text>';
 pts.forEach(function(d){
  s+='<circle cx="'+sx(d.x)+'" cy="'+sy(d.y)+'" r="'+(d.w?6:5.5)+'" fill="'+(d.w?'#fff':col(d.t))+
      '" stroke="'+col(d.t)+'" stroke-width="'+(d.w?1.8:1.8)+'" opacity="0.9">'+
      '<title>最大跨 '+f(d.x,1)+' m · 砼含量 '+f(d.y,3)+' m³/m²'+
      (d.w?'（校核未通过）':'')+'</title></circle>';
 });
 svg.innerHTML=s;
})();

// 分档表
(function(){
 const t=document.getElementById('band');
 let h='<thead><tr><th class="l">跨径档</th><th class="l">结构</th><th>样本</th><th>砼 m³/m²</th><th>钢绞线 kg/m²</th><th>钢绞线 kg/m³</th><th>钢板 kg/m²</th></tr></thead><tbody>';
 S.bands.forEach(function(b){
  const c1=b.conc?b.conc.median:null, c2=b.strand_m2?b.strand_m2.median:null,
        c3=b.strand_m3?b.strand_m3.median:null, c4=b.plate?b.plate.median:null;
  h+='<tr><td class="l"><b>'+b.name+'</b></td><td class="l">'+b.type+'</td><td>'+b.n+
     '</td><td>'+f(c1,3)+'</td><td>'+f(c2,1)+'</td><td>'+f(c3,1)+'</td><td>'+f(c4,0)+'</td></tr>';
 });
 h+='</tbody>';
 t.innerHTML=h;
})();

// 互通对比表
(function(){
 const t=document.getElementById('route');
 let h='<thead><tr><th class="l">互通</th><th class="l">结构</th><th>样本</th><th>砼 m³/m²</th><th>钢绞线 kg/m²</th><th>钢绞线 kg/m³</th><th>钢板 kg/m²</th></tr></thead><tbody>';
 S.routes.forEach(function(r){
  const c1=r.conc?r.conc.median:null, c2=r.strand_m2?r.strand_m2.median:null,
        c3=r.strand_m3?r.strand_m3.median:null, c4=r.plate?r.plate.median:null;
  h+='<tr><td class="l"><b>'+r.name+'</b></td><td class="l">'+r.type+'</td><td>'+r.n+
     '</td><td>'+f(c1,3)+'</td><td>'+f(c2,1)+'</td><td>'+f(c3,1)+'</td><td>'+f(c4,0)+'</td></tr>';
 });
 h+='</tbody>';
 t.innerHTML=h;
})();

// 经验值速查：按 跨径±dL、桥宽±dW 找相近样本，逐级放宽
(function(){
 const S2=(S.samples||[]).filter(function(d){return d.s!=null;});
 const sel=document.getElementById('qT'), out=document.getElementById('qOut');
 const types=[];
 S2.forEach(function(d){ if(types.indexOf(d.t)<0) types.push(d.t); });
 sel.innerHTML=types.map(function(t){return '<option>'+t+'</option>';}).join('');
 if(types.length) sel.value=types[0];
 const pct=function(a,q){ if(!a.length) return null;
  const b=a.slice().sort(function(x,y){return x-y;});
  const i=Math.min(b.length-1,Math.max(0,Math.round((b.length-1)*q)));
  return b[i]; };
 const med=function(a){ return pct(a,.5); };
 function box(k,v,u,s){ return '<div class="box"><div class="k">'+k+'</div><div class="v">'+v+
   '<small>'+u+'</small></div><div class="s">'+s+'</div></div>'; }
 function run(){
  const L=parseFloat(document.getElementById('qL').value);
  const W=parseFloat(document.getElementById('qW').value);
  const T=sel.value;
  if(isNaN(L)||isNaN(W)){ out.innerHTML='<div class="empty">请填写跨径与桥宽。</div>'; return; }
  const pool=S2.filter(function(d){return d.t===T;});
  const steps=[[5,3],[8,5],[12,8],[999,999]];
  let hit=[], used=null;
  for(const st of steps){
   const sub=pool.filter(function(d){
     return Math.abs(d.s-L)<=st[0] && (d.w==null? false : Math.abs(d.w-W)<=st[1]); });
   if(sub.length>=5){ hit=sub; used=st; break; }
   if(!hit.length){ hit=sub; used=st; }
  }
  if(!hit.length){
   out.innerHTML='<div class="empty">没有跨径、桥宽都接近的样本，试试放宽条件或改用下面的统计卡片。</div>';
   return;
  }
  const cc=hit.map(function(d){return d.c;}).filter(function(v){return v!=null;});
  const m2=hit.map(function(d){return d.m2;}).filter(function(v){return v!=null&&v>0;});
  const m3=hit.map(function(d){return d.m3;}).filter(function(v){return v!=null&&v>0;});
  const pp=hit.map(function(d){return d.p;}).filter(function(v){return v!=null&&v>0;});
  let h='<div>命中 <b>'+hit.length+'</b> 联'+
    (used&&used[0]!==999? '（跨径 ±'+used[0]+'m、桥宽 ±'+used[1]+'m 内）':'（全库同类型）')+
    ' · 结构 '+T+'</div><div class="row">';
  if(cc.length) h+=box('砼含量中位',f(med(cc),3),'m³/m²','P25 '+f(pct(cc,.25),3)+' ~ P75 '+f(pct(cc,.75),3));
  if(m2.length) h+=box('钢绞线（按面积）',f(med(m2),1),'kg/m²','P25 '+f(pct(m2,.25),1)+' ~ P75 '+f(pct(m2,.75),1));
  if(m3.length) h+=box('钢绞线（按方量）',f(med(m3),1),'kg/m³','P25 '+f(pct(m3,.25),1)+' ~ P75 '+f(pct(m3,.75),1));
  if(pp.length) h+=box('钢板含量中位',f(med(pp),0),'kg/m²','P25 '+f(pct(pp,.25),0)+' ~ P75 '+f(pct(pp,.75),0));
  h+='</div>';
  if(hit.length<8) h+='<div class="warn">样本偏少（'+hit.length+' 联），离散度大，仅作量级参考。</div>';
  out.innerHTML=h;
 }
 document.getElementById('qGo').addEventListener('click',run);
 ['qL','qW'].forEach(function(id){
  document.getElementById(id).addEventListener('input',run);
  document.getElementById(id).addEventListener('change',run);
 });
 sel.addEventListener('change',run);
 const ps=document.querySelectorAll('.qpreset a');
 for(let i=0;i<ps.length;i++){
  ps[i].onclick=function(e){
   e.preventDefault();
   document.getElementById('qL').value=this.getAttribute('data-l');
   document.getElementById('qW').value=this.getAttribute('data-w');
   run();
  };
 }
 run();
})();
</script></body></html>"""


DEMO_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>箱梁技术指标库 · 演示版</title>
<style>
*{box-sizing:border-box}body{margin:0;padding:24px 28px;background:#f6f7f9;color:#1c2530;
font:18px/1.7 "Microsoft YaHei",system-ui,sans-serif}
h1{font-size:27px;margin:0 0 4px;font-weight:600}
.sub{color:#68737d;font-size:15px;margin-bottom:18px}
.bar{background:#fff;border:1px solid #e3e7ec;border-radius:12px;padding:14px 18px;margin-bottom:18px;
display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.f{display:flex;align-items:center;gap:8px}
.f label{font-size:15px;color:#4a5560}
select,input{font:15px "Microsoft YaHei",system-ui,sans-serif;padding:7px 10px;border:1px solid #d6dbe1;
border-radius:8px;background:#fff;color:#1c2530}
input{width:74px}
.hit{margin-left:auto;font-size:16px;color:#1c2530}
.hit b{font-size:22px;color:#185fa5;font-weight:600}
.cards{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:18px}
.card{background:#fff;border:1px solid #e3e7ec;border-radius:12px;padding:16px 20px;min-width:230px;flex:1}
.card .k{font-size:15px;color:#68737d}
.card .v{font-size:38px;font-weight:600;margin-top:2px;letter-spacing:-.5px}
.card .u{font-size:15px;color:#8b949e;margin-left:5px;font-weight:400}
.card .s{font-size:15px;color:#68737d;margin-top:6px}
.panel{background:#fff;border:1px solid #e3e7ec;border-radius:12px;padding:16px 18px;margin-bottom:18px}
.panel h2{font-size:19px;margin:0 0 12px;font-weight:600}
table{border-collapse:collapse;width:100%;font-size:18px}
th,td{border-bottom:1px solid #eef1f4;padding:10px 12px;text-align:right;white-space:nowrap}
th{background:#fafbfc;color:#4a5560;font-weight:600;position:sticky;top:0;z-index:2;font-size:16px}
td.l,th.l{text-align:left}
tr.warn td{background:#fff6ee}
tr:hover td{background:#eaf2fd}
tr.sel td{background:#d9e8fb;outline:2px solid #378add;outline-offset:-2px}
.tag{display:inline-block;font-size:14px;padding:2px 9px;border-radius:6px;background:#eef4ff;color:#2c62c9}
.tag.g{background:#e7f6ee;color:#1a7f4b}.tag.w{background:#fff0e2;color:#a34908}
.scroll{max-height:520px;overflow:auto;-webkit-overflow-scrolling:touch}
.legend{font-size:15px;color:#68737d;margin-top:10px}
.dot{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:6px}
.hint{font-size:15px;color:#8b949e;margin-top:6px}
@media(max-width:820px){
 body{padding:14px 12px 26px;font-size:16px}
 h1{font-size:21px}
 .sub{font-size:13px;margin-bottom:12px}
 .bar{padding:11px 13px;gap:11px;margin-bottom:14px}
 .f label{font-size:13px}
 select,input{font-size:14px;padding:9px 11px;min-height:40px}
 input{width:64px}
 .hit{font-size:14px;margin-left:0;width:100%}
 .hit b{font-size:19px}
 .card{min-width:100%;padding:13px 15px}
 .card .v{font-size:31px}
 .panel{padding:13px 14px;margin-bottom:14px}
 .panel h2{font-size:16px}
 table{font-size:15px}
 th,td{padding:8px 9px}
 .scroll{max-height:70vh}
}
</style></head><body>
<h1>箱梁技术指标库 · 演示版</h1>
<div class="sub" id="sub">92 条逐联记录 · 自动校核 · 按跨径/桥宽检索经验区间</div>
<div class="bar">
 <div class="f"><label>结构</label><select id="fStruct"></select></div>
 <div class="f"><label>互通</label><select id="fRoute"></select></div>
 <div class="f"><label>跨径档</label><select id="fSpan"></select></div>
 <div class="f"><label>桥宽</label><input id="fW1" placeholder="最小">~<input id="fW2" placeholder="最大">m</div>
 <div class="hit">命中 <b id="hitN">92</b> 条</div>
</div>
<div class="cards" id="cards"></div>
<div class="panel"><h2>砼含量 — 最大跨径关系</h2>
<svg id="scatter" width="100%" height="360"></svg>
<div class="legend"><span class="dot" style="background:#3b7ddd"></span>现浇箱梁
<span class="dot" style="background:#e8730c;margin-left:16px"></span>钢箱梁　｜　空心点 = 校核未通过</div>
<div class="hint">点击表格任意一行可锁定高亮，对应的点会在散点图上放大显示</div></div>
<div class="panel"><h2>逐联指标明细<span class="sub" style="margin-left:12px" id="cnt"></span></h2>
<div class="scroll"><table id="tbl"></table></div></div>
<script>
const DATA=__DATA__;
const f=(v,n=2)=>v==null?'—':(+v).toFixed(n);
const q=(a,p)=>{if(!a.length)return null;const s=a.slice().sort((x,y)=>x-y),k=(s.length-1)*p;
 const lo=Math.floor(k),hi=Math.ceil(k);return lo===hi?s[lo]:s[lo]*(hi-k)+s[hi]*(k-lo);};
const med=a=>q(a,.5);
const uniq=k=>[...new Set(DATA.map(d=>d[k]||'—'))].sort((a,b)=>a.localeCompare(b,'zh'));
const opt=(sel,arr,first)=>{sel.innerHTML=[first,...arr].map(v=>`<option>${v}</option>`).join('')};
const inBand=(v,band)=>!band||(band[0]==null||v>=band[0])&&(band[1]==null||v<band[1]);
const BANDS={'全部':null,'20m以下':[0,20],'20~30m':[20,30],'30~40m':[30,40],'40m以上':[40,null]};
let selRow=null;
opt(document.getElementById('fStruct'),uniq('struct_type'),'全部');
opt(document.getElementById('fRoute'),uniq('route'),'全部');
opt(document.getElementById('fSpan'),Object.keys(BANDS),'全部');
['fStruct','fRoute','fSpan','fW1','fW2'].forEach(id=>{
 document.getElementById(id).addEventListener('change',refresh);
 document.getElementById(id).addEventListener('input',refresh);
});
function current(){
 const s=document.getElementById('fStruct').value;
 const r=document.getElementById('fRoute').value;
 const b=BANDS[document.getElementById('fSpan').value];
 const w1=parseFloat(document.getElementById('fW1').value);
 const w2=parseFloat(document.getElementById('fW2').value);
 return DATA.filter(function(d){
  if(s!=='全部' && d.struct_type!==s) return false;
  if(r!=='全部' && (d.route||'\u2014')!==r) return false;
  if(d.max_span && !inBand(d.max_span,b)) return false;
  if(d.width_avg){
   if(!isNaN(w1) && d.width_avg<w1) return false;
   if(!isNaN(w2) && d.width_avg>w2) return false;
  }
  return true;
 });
}
function refresh(){
 const rows=current(), ok=rows.filter(d=>!(d.flags&&d.flags.length));
 document.getElementById('hitN').textContent=rows.length;
 document.getElementById('cnt').textContent=`有效 ${ok.length} · 待核 ${rows.length-ok.length}`;
 // 卡片：按结构类型给中位值
 const c=document.getElementById('cards'); c.innerHTML='';
 const g={};
 rows.forEach(d=>{(g[d.struct_type]=g[d.struct_type]||[]).push(d)});
 Object.entries(g).forEach(([k,arr])=>{
  const cr=med(arr.map(d=>d.conc_ratio).filter(v=>v!=null));
  const s2=med(arr.map(d=>d.strand_m2).filter(v=>v!=null));
  const s3=med(arr.map(d=>d.strand_m3).filter(v=>v!=null));
  const pl=med(arr.map(d=>d.plate_m2).filter(v=>v!=null));
  const isSteel=!cr&&pl;
  const main=isSteel?pl.toFixed(0):(cr==null?'—':cr.toFixed(3));
  const unit=isSteel?'kg/m² 钢板':'m³/m² 砼';
  const sub=isSteel?`样本 ${arr.length} 联 · 钢板梁无预应力`
   :`钢绞线 ${s2==null?'—':s2.toFixed(1)} kg/m² · ${s3==null?'—':s3.toFixed(1)} kg/m³ · n=${arr.length}`;
  c.insertAdjacentHTML('beforeend',`<div class="card"><div class="k">${k} · ${isSteel?'钢板含量中位':'砼含量中位'}</div>
   <div class="v">${main}<span class="u">${unit}</span></div><div class="s">${sub}</div></div>`);
 });
 drawScatter(rows);
 drawTable(rows);
}
// 散点
function drawScatter(rows){
 const svg=document.getElementById('scatter');
 const W=Math.max(700,svg.clientWidth||960), H=360, P={l:60,r:20,t:16,b:40};
 const pts=rows.filter(d=>d.max_span&&d.conc_ratio);
 if(!pts.length){svg.innerHTML='';return;}
 const x0=0,x1=Math.max(...pts.map(d=>d.max_span))*1.08;
 const y0=0,y1=Math.max(...pts.map(d=>d.conc_ratio))*1.15;
 const sx=v=>P.l+(v-x0)/(x1-x0)*(W-P.l-P.r), sy=v=>H-P.b-(v-y0)/(y1-y0)*(H-P.t-P.b);
 const col=t=>t==='钢箱梁'?'#e8730c':t==='预制箱梁'?'#8b949e':'#3b7ddd';
 let s='';
 for(let i=0;i<=4;i++){const v=y1*i/4,y=sy(v);
  s+=`<line x1="${P.l}" y1="${y}" x2="${W-P.r}" y2="${y}" stroke="#eef1f4"/>`;
  s+=`<text x="${P.l-10}" y="${y+5}" font-size="14" fill="#8b949e" text-anchor="end">${v.toFixed(2)}</text>`;}
 for(let i=0;i<=5;i++){const v=x1*i/5,x=sx(v);
  s+=`<text x="${x}" y="${H-14}" font-size="14" fill="#8b949e" text-anchor="middle">${v.toFixed(0)}</text>`;}
 s+=`<text x="${W/2}" y="${H-2}" font-size="14" fill="#68737d" text-anchor="middle">最大跨径 (m)</text>`;
 s+=`<text x="14" y="${(H-P.b)/2}" font-size="14" fill="#68737d" text-anchor="middle" transform="rotate(-90 14 ${(H-P.b)/2})">砼 m³/m²</text>`;
 pts.forEach((d,i)=>{const w=d.flags&&d.flags.length, key=d.source_file+'|'+d.row;
  const big=(selRow===key);
  s+=`<circle cx="${sx(d.max_span)}" cy="${sy(d.conc_ratio)}" r="${big?9:(w?6:5.5)}" fill="${w?'#fff':col(d.struct_type)}"
      stroke="${col(d.struct_type)}" stroke-width="${big?3:1.8}" opacity="${big?1:.9}"><title>${d.bridge} ${d.unit_no}联 ${d.span_raw}
砼 ${f(d.conc_ratio,3)} m³/m² · 钢绞线 ${f(d.strand_m2,1)} kg/m²${w?'\\n⚠ '+d.flags.join('；'):''}</title></circle>`;});
 svg.innerHTML=s;
}
const cols=[['route','互通',1],['bridge','桥名',1],['unit_no','联号',1],['span_raw','跨径布置',1],
 ['max_span','最大跨',0],['width_avg','桥宽',0],['area_m2','面积',0],['concrete_m3','砼 m³',0],
 ['strand_kg','钢绞线 kg',0],['conc_ratio','砼 m³/m²',0],['strand_m2','钢绞线 kg/m²',0],
 ['strand_m3','钢绞线 kg/m³',0]];
function drawTable(rows){
 const t=document.getElementById('tbl');
 t.innerHTML='<thead><tr>'+cols.map(c=>`<th class="${c[2]?'l':''}">${c[1]}</th>`).join('')+
  '<th class="l">校核</th></tr></thead><tbody>'+
  rows.slice().sort((a,b)=>((a.route||'')+a.bridge).localeCompare((b.route||'')+b.bridge,'zh')
   || (+a.unit_no||0)-(+b.unit_no||0)).map(d=>{
   const w=d.flags&&d.flags.length, key=d.source_file+'|'+d.row;
   return `<tr class="${w?'warn':''} ${selRow===key?'sel':''}" data-k="${key}">`+cols.map(c=>{
    let v=d[c[0]]; if(v==null||v==='')v='—';
    else if(typeof v==='number') v=(+v).toFixed(c[1].includes('m³/m²')?3:2);
    return `<td class="${c[2]?'l':''}">${v}</td>`;}).join('')+
   `<td class="l">${w?'<span class="tag w">'+d.flags.join('；')+'</span>':'<span class="tag g">通过</span>'}</td></tr>`;}).join('')+
  '</tbody>';
 t.querySelectorAll('tr[data-k]').forEach(tr=>tr.onclick=()=>{
  selRow = (selRow===tr.dataset.k)?null:tr.dataset.k;
  const rs=current(); drawTable(rs); drawScatter(rs);
 });
}
refresh();
</script></body></html>"""


def build_public_summary(records):
    """对外分享用的**聚合摘要**——只含统计量，不含任何逐联记录。

    注入 HTML 的仅此一份数据，因此页面源码里不存在明细行，
    也不含 source_file / row / *_src 等溯源字段。
    """
    ok = [r for r in records if not r["flags"]]
    spans = [r["max_span"] for r in records if r.get("max_span")]
    widths = [r["width_avg"] for r in records if r.get("width_avg")]

    def pick(rs, key):
        """取整列指标值；钢箱梁无预应力，钢绞线按「不适用」处理（返回空→显示 —）。"""
        vals = [r.get(key) for r in rs]
        if key.startswith("strand") and not [v for v in vals if v]:
            return []
        return vals

    def five(vals):
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        return {
            "min": round(min(vals), 3), "p25": round(pct(vals, .25), 3),
            "median": round(statistics.median(vals), 3),
            "p75": round(pct(vals, .75), 3), "max": round(max(vals), 3),
        }

    def block(name, stype, rs):
        return {
            "name": name, "type": stype, "n": len(rs),
            "conc": five(pick(rs, "conc_ratio")),
            "strand_m2": five(pick(rs, "strand_m2")),
            "strand_m3": five(pick(rs, "strand_m3")),
            "plate": five(pick(rs, "plate_m2")),
        }

    cards = []
    g = {}
    for r in ok:
        g.setdefault(r["struct_type"], []).append(r)
    for k, rs in g.items():
        cards.append(block(k, k, rs))

    bands = []
    for name, lo, hi in (("20m以下", 0, 20), ("20~30m", 20, 30),
                         ("30~40m", 30, 40), ("40m以上", 40, 9999)):
        sub = [r for r in ok if r.get("max_span") and lo <= r["max_span"] < hi]
        if not sub:
            continue
        bg = {}
        for r in sub:
            bg.setdefault(r["struct_type"], []).append(r)
        for stype, rs in sorted(bg.items()):
            bands.append(block(name, stype, rs))

    routes = []
    rg = {}
    for r in ok:
        rg.setdefault((r.get("route") or "—", r["struct_type"]), []).append(r)
    for (route, stype), rs in sorted(rg.items()):
        if len(rs) < 2:
            continue
        routes.append(block(route, stype, rs))

    points = [{"x": round(r["max_span"], 2), "y": round(r["conc_ratio"], 3),
               "t": r["struct_type"], "w": 1 if r["flags"] else 0}
              for r in records if r.get("max_span") and r.get("conc_ratio")]

    # 速查样本：只含数值，无桥名/互通名/源文件名，供页面端「经验值速查」实时检索
    samples = []
    for r in ok:
        if not r.get("max_span"):
            continue
        samples.append({
            "s": round(r["max_span"], 2),
            "w": round(r["width_avg"], 2) if r.get("width_avg") else None,
            "c": round(r["conc_ratio"], 4) if r.get("conc_ratio") else None,
            "m2": round(r["strand_m2"], 2) if r.get("strand_m2") else None,
            "m3": round(r["strand_m3"], 2) if r.get("strand_m3") else None,
            "p": round(r["plate_m2"], 1) if r.get("plate_m2") else None,
            "t": r["struct_type"],
        })

    return {
        "generated": date.today().isoformat(),
        "overview": {
            "total": len(records), "ok": len(ok), "pending": len(records) - len(ok),
            "projects": len({r.get("project") for r in records}),
            "routes": len({r.get("route") or "—" for r in records}),
            "span_min": round(min(spans), 1) if spans else None,
            "span_max": round(max(spans), 1) if spans else None,
            "width_min": round(min(widths), 2) if widths else None,
            "width_max": round(max(widths), 2) if widths else None,
        },
        "cards": cards, "bands": bands, "routes": routes, "points": points,
        "samples": samples,
    }


def write_public_html(records, path: Path):
    """对外精简版：只有统计卡片 / 散点图 / 分档表，不注入逐联明细数据。"""
    summary = build_public_summary(records)
    payload = json.dumps(summary, ensure_ascii=False)
    html = PUBLIC_HTML.replace("__SUMMARY__", payload)
    brand = (PUBLIC_BRAND or "").strip()
    html = html.replace(" · __BRAND__", f" · {brand}" if brand else "")
    html = html.replace("__BRAND__", brand)
    path.write_text(html, encoding="utf-8")


def write_demo_html(records, path: Path):
    """生成演示版看板：大字号、关键列、筛选联动，适合 1080p 录屏。"""
    safe = []
    for r in records:
        d = {k: v for k, v in r.items() if k not in ("route_src", "bridge_src")}
        d["source_file"] = alias(r.get("source_file"))
        safe.append(d)
    payload = json.dumps(safe, ensure_ascii=False)
    path.write_text(DEMO_HTML.replace("__DATA__", payload), encoding="utf-8")


def write_html(records, st, path: Path):
    # 看板对外分享：剥掉原始中文字段、源文件名换成代号，页面源码内不残留真名
    safe = []
    for r in records:
        d = {k: v for k, v in r.items() if k not in ("route_src", "bridge_src")}
        d["source_file"] = alias(r.get("source_file"))
        safe.append(d)
    payload = json.dumps(safe, ensure_ascii=False)
    stats_payload = json.dumps(st, ensure_ascii=False)
    html = HTML.replace("__DATA__", payload).replace("__STATS__", stats_payload)
    path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------- main
def dedupe(records):
    """按 (源文件, 工作表, 行号) 去重；同一位置以**后写入的**为准（便于重跑覆盖旧结果）。"""
    seen, out = set(), []
    for r in reversed(records):
        k = (r["source_file"], r["sheet"], r["row"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    out.reverse()
    return out


def main():
    ap = argparse.ArgumentParser(description="箱梁技术指标库：Excel → 指标库")
    ap.add_argument("--input", nargs="+", required=True, help="一个或多个 Excel 文件")
    ap.add_argument("--lib", default=None, help="指标库 JSON 路径（可累积）")
    ap.add_argument("--outdir", default=None, help="输出目录")
    ap.add_argument("--project", default=None, help="默认工程名（缺省用文件名）")
    ap.add_argument("--route", default=None,
                    help="表内无「匝道/互通」列时，用该值填充互通名（如 汉口北）")
    ap.add_argument("--no-pinyin", action="store_true",
                    help="关闭桥名拼音首字母代号化，保留原始桥名")
    args = ap.parse_args()
    global BRIDGE_PINYIN
    if args.no_pinyin:
        BRIDGE_PINYIN = False

    all_recs = []
    if args.lib and Path(args.lib).exists():
        try:
            all_recs = json.loads(Path(args.lib).read_text(encoding="utf-8"))
            print(f"[库] 读入已有 {len(all_recs)} 条")
        except Exception as e:
            print(f"[警告] 指标库读取失败，忽略：{e}")

    for p in args.input:
        path = Path(p)
        rs = extract_file(path, args.project, args.route)
        print(f"[提取] {path.name}: {len(rs)} 条")
        all_recs.extend(rs)

    all_recs = dedupe(all_recs)
    code_map = apply_name_codes(
        all_recs,
        Path(args.lib).parent / CODE_CACHE_NAME if args.lib else None,
    )                                            # 互通名/桥名 -> 拼音首字母代号
    st = stats(all_recs)

    outdir = Path(args.outdir) if args.outdir else Path(args.input[0]).parent
    outdir.mkdir(parents=True, exist_ok=True)
    lib = Path(args.lib) if args.lib else outdir / "指标库.json"
    lib.parent.mkdir(parents=True, exist_ok=True)

    lib.write_text(json.dumps(all_recs, ensure_ascii=False, indent=1), encoding="utf-8")
    write_csv(all_recs, outdir / "指标库.csv")
    write_md(all_recs, st, outdir / "指标库.md", lib.resolve(), code_map)
    write_html(all_recs, st, outdir / "指标库.html")
    write_demo_html(all_recs, outdir / "指标库-演示版.html")
    write_public_html(all_recs, outdir / "指标库-对外精简版.html")

    good = sum(1 for r in all_recs if not r["flags"])
    print(f"[完成] 共 {len(all_recs)} 条（有效 {good} / 待核 {len(all_recs)-good}）")
    print(f"  库: {lib}")
    print(f"  输出: {outdir}")
    for k, d in st.items():
        cr = d.get("conc_ratio") or {}
        s2 = d.get("strand_m2") or {}
        s3 = d.get("strand_m3") or {}
        print(f"  [{k}] n={d['n']}  砼 {cr.get('median','—')} m3/m2  "
              f"钢绞线 {s2.get('median','—')} kg/m2 / {s3.get('median','—')} kg/m3")


if __name__ == "__main__":
    main()
