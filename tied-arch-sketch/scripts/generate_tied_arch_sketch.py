# -*- coding: utf-8 -*-
"""
系杆拱桥立面示意图生成器（SVG · 横竖向同比例）

从「菜园坝长江大桥」专用脚本泛化而来，按参数生成任意系杆拱桥（下承式 / 中承式）
的立面布置草图。坐标体系以「桥面（上弦）= 0.000」为基准的相对标高。

用法：
    python generate_tied_arch_sketch.py --spans "88+102+420+102+88" --output out.svg
    python generate_tied_arch_sketch.py --preset caiyuanba --output out.svg
    python generate_tied_arch_sketch.py --json-str '{"spans":"76+360+76","arch_span":360}' --output out.svg

参数优先级：默认值 < --preset < 显式命令行参数 / --json-str
"""
from __future__ import annotations

import argparse
import json
import math
import sys

# ---------------------------------------------------------------- 样式常量
C_MAIN, C_SUB, C_THIN, C_DIM = "#1a1a1a", "#555555", "#8c8c8c", "#333333"
C_WAT, C_TENDON = "#2f6f9f", "#8a2d2d"
HALO = 'paint-order="stroke" stroke="#ffffff" stroke-width="3.2" stroke-linejoin="round"'
FONT = "Microsoft YaHei, SimHei, sans-serif"

# ---------------------------------------------------------------- 默认参数
DEFAULTS = dict(
    # —— 桥名与文字 ——
    name="",
    bridge_type="",
    title="",
    subtitle="",
    info_lines="",
    deck_notes="",
    # —— 跨径布置 ——
    spans="",
    ext_left=0.0,
    ext_right=0.0,
    approach_pier=True,
    # —— 主拱 ——
    arch_span=None,
    rise=None,
    axis="parabola",            # parabola | catenary | circle | power
    axis_n=2.0,                 # power 模式的指数（2 = 二次抛物线）
    cosh_m=1.167,               # 悬链线拱轴系数 m
    arch_offset=0.0,            # 拱跨中心相对主跨中心的偏移（m，正=向右）
    arch_foot_drop=0.0,         # 拱脚低于桥面的高差（m）；0 = 拱脚在桥面（下承式）
    arch_box_h=None,            # 拱肋立面高度（m），默认 arch_span/80
    arch_box_w=None,            # 拱肋横断宽度（m，仅用于文字），默认 0.6*box_h
    arch_material="钢箱",
    arch_lean=0.0,              # 拱肋内倾角（°，提篮拱），仅用于文字
    n_brace=0,                  # 横撑道数，仅用于文字
    # —— 主梁 / 桥面 ——
    deck_depth=2.0,
    girder="box",               # box | truss
    segment=None,               # 节段长度（m），默认 = 吊杆间距
    dual_deck=False,            # 是否画公路面 / 轨道面示意线
    # —— 吊杆 ——
    hanger_spacing=8.0,
    hanger_start=None,          # 首根吊杆距拱脚的距离（m），默认 = 吊杆间距
    # —— 系杆 ——
    tie_offset=2.5,             # 系杆低于拱脚/下弦的高差（m）
    side_tie="auto",            # yes | no | auto（auto：有 Y 构时画）
    # —— 桥墩 / 刚构 ——
    y_frame="auto",             # none | main | auto（auto：拱跨小于主跨时自动加）
    y_front=None,               # 前肢水平投影（m），默认 (主跨-拱净跨)/2
    y_back=None,                # 后肢水平投影（m），默认 0.8*前肢
    y_to_deck=True,             # 肢端是否延伸至桥面
    main_pier_drop=None,        # 桥面至主墩墩顶的高差（m）
    pier_w_main=14.0,
    pier_wt_main=12.0,
    pier_w=8.0,
    pier_wt=6.0,
    # —— 水位 / 高程 ——
    deck_level=0.0,             # 桥面绝对标高（m）。给水位的绝对标高时必须一并给出
    water="",                   # "名称=标高;名称=标高"
    bed_level=None,             # 河床绝对标高；默认 = 最低水位下 bed_below_water
    bed_below_water=14.0,
    ground_depth=30.0,          # 无水位时，河床/地面低于桥面的深度（m）
    river_note="",              # 河槽/水道文字（画在常水位附近）
    river_note_pos=0.42,        # 文字水平位置（占全宽比例）
    bed_note="",                # 河床/岸线文字（画在河床线上方）
    bed_note_pos=0.85,
    # —— 标注开关 ——
    show_span_dims=True,
    show_arch_span_dim=True,
    arch_span_dim_offset=1.5,   # 拱净跨标注线低于拱脚的高差（m），避免压住梁体时可调大
    show_rise_dim=False,
    show_elev_marks=False,
    show_water_labels=True,
    show_girder_depth_dim=True,
    show_pier_labels=True,
    show_info_box=True,
    show_leaders=True,
    # —— 画布 ——
    width=1830.0,               # 画布宽度上限（px）
    max_height=660.0,           # 画布高度上限（px），短跨桥自动缩尺
    margin_x=24.0,
    scale=None,                 # 显式指定比例（px/m），一般留空自动计算
    output="",
)


def parse_spans(text):
    """把 "88+102+420+102+88" 解析为列表。"""
    parts = [p for p in str(text).replace("×", "x").split("+") if p.strip()]
    return [float(p) for p in parts]


def parse_named_levels(text):
    """把 "枯水位=162.960;100 年一遇=193.230" 解析为 [(名称, 标高), ...]。"""
    out = []
    for seg in str(text).replace(",", ";").split(";"):
        seg = seg.strip()
        if not seg:
            continue
        if "=" not in seg:
            raise ValueError(f"水位参数需写成 名称=标高，收到：{seg!r}")
        k, v = seg.split("=", 1)
        out.append((k.strip(), float(v)))
    return out


# ---------------------------------------------------------------- 预设
PRESETS = {
    # 重庆菜园坝长江大桥：中承式提篮钢箱系杆拱 + Y 型刚构 + 公轨两用钢桁梁
    "caiyuanba": dict(
        name="重庆菜园坝长江大桥（公轨两用）",
        bridge_type="Y型刚构 + 提篮式钢箱系杆拱 + 正交异性板钢桁梁（公轨两用）",
        title="重庆菜园坝长江大桥 · 结构立面示意图",
        spans="88+102+420+102+88",
        ext_left=70.0,
        ext_right=70.0,
        arch_span=320.0,
        rise=56.44,
        axis="parabola",
        arch_foot_drop=0.0,
        arch_box_h=4.0,
        arch_box_w=2.4,
        arch_material="钢箱",
        arch_lean=10.67,
        n_brace=6,
        deck_depth=11.2,
        girder="truss",
        segment=16.0,
        dual_deck=True,
        deck_notes="上层：双向六车道 + 双侧人行道（桥面净宽 30.5 m）;"
                   "下层：双线轻轨（重庆轨道交通 3 号线，净宽 8.6 m）",
        hanger_spacing=16.0,
        y_frame="main",
        y_front=50.0,
        y_back=40.0,
        y_to_deck=True,
        main_pier_drop=37.84,
        pier_w_main=14.0,
        pier_wt_main=12.0,
        deck_level=232.0,
        water="100 年一遇洪水位=193.230;20 年一遇洪水位=189.330;枯水位=162.960",
        river_note="长江主河槽",
        bed_note="南岸滨江路（示意）",
        bed_level=148.96,
    ),
    # 典型下承式简支系杆拱（单跨）
    "simply-supported": dict(
        bridge_type="下承式简支系杆拱",
        deck_depth=2.0,
        girder="box",
        hanger_spacing=8.0,
        y_frame="none",
        ground_depth=30.0,
    ),
}


# ---------------------------------------------------------------- 主体
def build(args):
    p = dict(DEFAULTS)
    for key, val in vars(args).items():
        if val is None:
            continue
        p[key] = val

    # 跨径
    spans = parse_spans(p["spans"])
    if not spans:
        raise SystemExit("错误：必须给出 --spans，例如 --spans \"88+102+420+102+88\"")
    total = sum(spans)
    pier_x = [0.0]
    for s in spans:
        pier_x.append(pier_x[-1] + s)
    main_idx = max(range(len(spans)), key=lambda i: spans[i])
    main_span = spans[main_idx]
    main_pier_l, main_pier_r = pier_x[main_idx], pier_x[main_idx + 1]

    # 主拱
    arch_span = float(p["arch_span"]) if p["arch_span"] else main_span
    rise = float(p["rise"]) if p["rise"] else arch_span / 5.0
    arch_cx = (main_pier_l + main_pier_r) / 2.0 + float(p["arch_offset"])
    ax1, ax2 = arch_cx - arch_span / 2.0, arch_cx + arch_span / 2.0
    box_h = float(p["arch_box_h"]) if p["arch_box_h"] else max(1.5, arch_span / 80.0)
    box_w = float(p["arch_box_w"]) if p["arch_box_w"] else round(0.6 * box_h, 2)

    # 梁 / 吊杆
    segment = float(p["segment"]) if p["segment"] else float(p["hanger_spacing"])
    spacing = float(p["hanger_spacing"])
    h_start = float(p["hanger_start"]) if p["hanger_start"] else spacing
    deck_depth = float(p["deck_depth"])

    # 刚构（Y 型）
    y_front = float(p["y_front"]) if p["y_front"] is not None else max(0.0, (main_span - arch_span) / 2.0)
    y_back = float(p["y_back"]) if p["y_back"] is not None else 0.8 * y_front
    y_frame = p["y_frame"]
    if y_frame == "auto":
        y_frame = "main" if y_front > 0.5 else "none"

    # —— 相对标高（桥面 = 0）——
    L_TOP = 0.0
    L_BOT = -deck_depth
    L_FOOT = -float(p["arch_foot_drop"])
    L_APEX = L_FOOT + rise
    deck_level = float(p["deck_level"])

    waters = parse_named_levels(p["water"])
    wl = [(nm, lv - deck_level) for nm, lv in waters]      # 转相对标高
    wl.sort(key=lambda k: k[1], reverse=True)              # 从高到低

    if p["bed_level"] is not None:
        L_BED = float(p["bed_level"]) - deck_level
    elif wl:
        L_BED = min(l for _, l in wl) - float(p["bed_below_water"])
    else:
        L_BED = -float(p["ground_depth"])

    # 主墩墩顶
    if p["main_pier_drop"] is not None:
        L_MAIN_PIER = -float(p["main_pier_drop"])
    elif y_frame == "main":
        # Y 型刚构：墩顶需低于拱脚，才能张开前后肢
        L_MAIN_PIER = min(-(deck_depth + 10.0), L_FOOT - 10.0)
    else:
        # 拱脚直接支承于墩顶：墩身顶到梁底（中承式时拱脚嵌入墩顶，不出现梁底悬空）
        L_MAIN_PIER = L_BOT

    # 肢端标高
    L_Y_TOP = L_TOP if p["y_to_deck"] else L_FOOT

    # —— 拱轴线 ——
    axis = p["axis"]

    def axis_level(x):
        t = (x - arch_cx) / (arch_span / 2.0)
        t = max(-1.0, min(1.0, t))
        if axis == "parabola":
            return L_FOOT + rise * (1.0 - t * t)
        if axis == "power":
            n = float(p["axis_n"])
            return L_FOOT + rise * (1.0 - abs(t) ** n)
        if axis == "circle":
            R = (arch_span ** 2 / 4.0 + rise ** 2) / (2.0 * rise)
            return L_FOOT + math.sqrt(max(R * R - (t * arch_span / 2.0) ** 2, 0.0)) - (R - rise)
        if axis == "catenary":
            m = float(p["cosh_m"])
            if m <= 1.0001:                            # m→1 时退化为二次抛物线
                return L_FOOT + rise * (1.0 - t * t)
            k = math.acosh(m)
            # 拱轴系数 m；|t| 为自拱顶量起的相对水平距离（拱顶 0、拱脚 1）
            return L_FOOT + rise - rise / (m - 1.0) * (math.cosh(k * abs(t)) - 1.0)
        raise ValueError(f"未知拱轴线类型：{axis}")

    axis_name = {"parabola": "二次抛物线", "power": f"幂函数（n={p['axis_n']}）",
                 "circle": "圆弧线", "catenary": f"悬链线（m={p['cosh_m']}）"}[axis]

    # —— 吊杆 ——
    def rib_bottom(xv):
        """拱肋下缘标高（按拱轴线法向等厚偏移，拱脚处受坡度影响略高）"""
        e = max(0.5, arch_span / 200.0)
        xa, xb = max(xv - e, ax1), min(xv + e, ax2)
        dxw = xb - xa
        dyw = axis_level(xb) - axis_level(xa)
        ln = math.hypot(dxw, dyw) or 1.0
        return axis_level(xv) - (dxw / ln) * box_h / 2.0

    hangers = []
    x = ax1 + h_start
    while x < ax2 - spacing / 2.0:
        if rib_bottom(x) > L_TOP + 0.8:             # 中承式：拱肋出桥面后才有吊杆
            hangers.append(x)
        x += spacing

    # —— 画布（横竖向同比例）——
    world_x0, world_x1 = -float(p["ext_left"]), total + float(p["ext_right"])
    lv_dim_spans = max(L_APEX + box_h / 2.0, L_TOP) + 6.0
    lv_dim_total = lv_dim_spans + 6.0
    world_top = lv_dim_total + 4.0
    world_bot = L_BED

    # 说明条文字
    if p["info_lines"]:
        info_lines = [(s.strip(), i == 0) for i, s in enumerate(str(p["info_lines"]).split(";")) if s.strip()]
    else:
        name = p["name"] or p["title"] or "系杆拱桥"
        l1 = f"{name} — {p['bridge_type']}" if p["bridge_type"] else name
        arch_desc = f"{p['arch_material']} {box_w}×{box_h} m"
        if p["arch_lean"]:
            arch_desc += f"、内倾 {p['arch_lean']}°"
        if p["n_brace"]:
            arch_desc += f"、{int(p['n_brace'])} 道横撑"
        girder_desc = "桁梁" if p["girder"] == "truss" else "系杆梁（箱形）"
        if y_frame == "main":
            frame_desc = f"Y 型刚构前肢 {y_front:g} m / 后肢 {y_back:g} m" + ("、肢端延伸至桥面" if p["y_to_deck"] else "")
        else:
            frame_desc = "拱脚直接支承于桥墩"
        l2 = (f"跨径 {'+'.join(f'{s:g}' for s in spans)} m（主桥 {total:g} m）｜ 主拱：净跨 {arch_span:g} m、矢高 {rise:g} m"
              f"（矢跨比 1/{arch_span / rise:.2f}）、拱轴线{axis_name} ｜ 拱肋：{arch_desc}")
        l3 = (f"{girder_desc}：高 {deck_depth:g} m、标准节段 {segment:g} m（吊杆间距 {spacing:g} m，共 {len(hangers)} 根）"
              f" ｜ {frame_desc}")
        l4 = ""
        if wl:
            l4 = "标高（m）：" + " ｜ ".join(f"{nm} {lv + deck_level:.3f}" for nm, lv in sorted(wl, key=lambda k: k[1]))
        l5 = "示意简笔画，横竖向同比例，非施工图；几何按给定参数推算，供方案比选与建模前参数核对。"
        info_lines = [(t, i == 0) for i, t in enumerate([l1, l2, l3, l4, l5]) if t]

    info_h = (26.0 + 19.0 * len(info_lines)) if p["show_info_box"] else 0.0

    # —— 画布（横竖向同比例；按宽度与高度上限双向约束）——
    W_max = float(p["width"])
    MX = float(p["margin_x"])
    top_reserve = 62.0
    fixed_v = top_reserve + 22.0 + info_h + 14.0
    H_max = float(p["max_height"])
    world_w = world_x1 - world_x0
    content_h = world_top - world_bot
    if p["scale"]:
        S = float(p["scale"])
    else:
        S = min((W_max - 2.0 * MX) / world_w, (H_max - fixed_v) / content_h)
    W = world_w * S + 2.0 * MX
    H = fixed_v + content_h * S
    OX = MX - world_x0 * S
    OY = top_reserve + world_top * S

    def X(xv):
        return OX + xv * S

    def Y(level):
        return OY - level * S

    return dict(p=p, spans=spans, total=total, pier_x=pier_x, main_idx=main_idx, main_span=main_span,
                main_pier_l=main_pier_l, main_pier_r=main_pier_r, arch_span=arch_span, rise=rise,
                arch_cx=arch_cx, ax1=ax1, ax2=ax2, box_h=box_h, box_w=box_w, segment=segment,
                spacing=spacing, h_start=h_start, deck_depth=deck_depth, y_front=y_front, y_back=y_back,
                y_frame=y_frame, L_TOP=L_TOP, L_BOT=L_BOT, L_FOOT=L_FOOT, L_APEX=L_APEX,
                L_BED=L_BED, L_MAIN_PIER=L_MAIN_PIER, L_Y_TOP=L_Y_TOP, wl=wl, deck_level=deck_level,
                axis_level=axis_level, axis_name=axis_name, hangers=hangers, rib_bottom=rib_bottom,
                world_x0=world_x0, world_x1=world_x1, world_top=world_top, world_bot=world_bot,
                lv_dim_spans=lv_dim_spans, lv_dim_total=lv_dim_total,
                W=W, H=H, S=S, OX=OX, OY=OY, X=X, Y=Y, info_lines=info_lines, info_h=info_h)


def render(g):
    p, X, Y, S = g["p"], g["X"], g["Y"], g["S"]
    W, H = g["W"], g["H"]
    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
               f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="{FONT}">')
    svg.append(f'<rect width="{W:.0f}" height="{H:.0f}" fill="#ffffff"/>')
    svg.append('<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
               'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#333"/>'
               '</marker></defs>')

    # ---------------- 标题 ----------------
    title = p["title"] or (p["name"] + " · 结构立面示意图" if p["name"] else "系杆拱桥 · 结构立面示意图")
    svg.append(f'<text x="{W/2:.0f}" y="28" font-size="20" font-weight="bold" fill="{C_MAIN}" '
               f'text-anchor="middle">{title}</text>')
    sub = p["subtitle"] or (f"{'+'.join(f'{s:g}' for s in g['spans'])} m ｜ {p['bridge_type']}".strip(" ｜")
                            if p["bridge_type"] else "")
    if sub:
        svg.append(f'<text x="{W/2:.0f}" y="48" font-size="11" fill="{C_SUB}" text-anchor="middle">{sub}</text>')

    ext_l, ext_r = g["world_x0"], g["world_x1"]
    L_TOP, L_BOT = g["L_TOP"], g["L_BOT"]

    # ---------------- 主梁 ----------------
    if p["girder"] == "truss":
        svg.append(f'<line x1="{X(ext_l)}" y1="{Y(L_TOP)}" x2="{X(ext_r)}" y2="{Y(L_TOP)}" stroke="{C_MAIN}" stroke-width="3"/>')
        svg.append(f'<line x1="{X(ext_l)}" y1="{Y(L_BOT)}" x2="{X(ext_r)}" y2="{Y(L_BOT)}" stroke="{C_MAIN}" stroke-width="3"/>')
        i0, i1 = int(ext_l // g["segment"]), int(ext_r // g["segment"])
        for i in range(i0, i1 + 1):
            xv = i * g["segment"]
            svg.append(f'<line x1="{X(xv)}" y1="{Y(L_BOT)}" x2="{X(xv)}" y2="{Y(L_TOP)}" stroke="{C_THIN}" stroke-width="0.85"/>')
        for i in range(i0, i1):
            x0, x1 = i * g["segment"], (i + 1) * g["segment"]
            a, b = (L_BOT, L_TOP) if i % 2 == 0 else (L_TOP, L_BOT)
            svg.append(f'<line x1="{X(x0)}" y1="{Y(a)}" x2="{X(x1)}" y2="{Y(b)}" stroke="{C_THIN}" stroke-width="0.85"/>')
    else:
        svg.append(f'<line x1="{X(ext_l)}" y1="{Y(L_TOP)}" x2="{X(ext_r)}" y2="{Y(L_TOP)}" stroke="{C_MAIN}" stroke-width="3"/>')
        svg.append(f'<line x1="{X(ext_l)}" y1="{Y(L_BOT)}" x2="{X(ext_r)}" y2="{Y(L_BOT)}" stroke="{C_MAIN}" stroke-width="3"/>')
        n = max(1, int((ext_r - ext_l) // g["segment"]))
        for i in range(1, n):
            xv = ext_l + i * (ext_r - ext_l) / n
            svg.append(f'<line x1="{X(xv)}" y1="{Y(L_BOT)}" x2="{X(xv)}" y2="{Y(L_TOP)}" stroke="{C_THIN}" stroke-width="0.7" stroke-dasharray="3,4"/>')

    if p["dual_deck"]:
        svg.append(f'<line x1="{X(ext_l)}" y1="{Y(L_TOP + 1.2)}" x2="{X(ext_r)}" y2="{Y(L_TOP + 1.2)}" stroke="{C_MAIN}" stroke-width="1.5"/>')
        svg.append(f'<line x1="{X(ext_l)}" y1="{Y(L_BOT - 1.2)}" x2="{X(ext_r)}" y2="{Y(L_BOT - 1.2)}" stroke="{C_SUB}" stroke-width="1.1" stroke-dasharray="4,3"/>')
    for xc in (X(ext_l), X(ext_r)):
        svg.append(f'<path d="M{xc-7:.1f},{Y(L_TOP)-3:.1f} L{xc+7:.1f},{Y(L_TOP)+7:.1f} '
                   f'M{xc-7:.1f},{Y(L_BOT)+9:.1f} L{xc+7:.1f},{Y(L_BOT)+19:.1f}" stroke="{C_MAIN}" stroke-width="1.6"/>')

    # ---------------- 水位 / 河床 ----------------
    if g["wl"]:
        for k, (nm, lv) in enumerate(g["wl"]):
            if "枯" in nm:
                wave = f'M{X(ext_l)-6:.1f},{Y(lv):.1f} '
                t = ext_l - 6
                while t < ext_r:
                    wave += "q7.6,-2.4 15.2,0 q7.6,2.4 15.2,0 "
                    t += 30.4
                svg.append(f'<path d="{wave}" fill="none" stroke="{C_WAT}" stroke-width="1.4"/>')
            else:
                dash = ["12,5", "7,4,2,4", "5,3"][k % 3]
                svg.append(f'<line x1="{X(ext_l)-6:.1f}" y1="{Y(lv):.1f}" x2="{X(ext_r):.1f}" y2="{Y(lv):.1f}" '
                           f'stroke="{C_WAT}" stroke-width="1.2" stroke-dasharray="{dash}"/>')
    svg.append(f'<line x1="{X(ext_l)-6:.1f}" y1="{Y(g["L_BED"]):.1f}" x2="{X(ext_r):.1f}" y2="{Y(g["L_BED"]):.1f}" '
               f'stroke="{C_THIN}" stroke-width="1.1" stroke-dasharray="14,5,3,5"/>')

    # ---------------- 桥墩 ----------------
    def pier(xc, top_level, wb, wt, pile=True, cap=False):
        svg.append(f'<polygon points="{X(xc-wb/2):.1f},{Y(g["L_BED"]):.1f} {X(xc+wb/2):.1f},{Y(g["L_BED"]):.1f} '
                   f'{X(xc+wt/2):.1f},{Y(top_level):.1f} {X(xc-wt/2):.1f},{Y(top_level):.1f}" '
                   f'fill="#e8e8e8" stroke="{C_MAIN}" stroke-width="2.2"/>')
        if cap:
            svg.append(f'<rect x="{X(xc-wb/2-2.5):.1f}" y="{Y(g["L_BED"]):.1f}" width="{(wb+5)*S:.1f}" '
                       f'height="{3.2*S:.1f}" fill="#dcdcdc" stroke="{C_MAIN}" stroke-width="1.8"/>')
        if pile:
            top = g["L_BED"] - 3.2 if cap else g["L_BED"]
            for i in (-1, 0, 1):
                px = xc + i * (wb * 0.3)
                svg.append(f'<line x1="{X(px):.1f}" y1="{Y(top):.1f}" x2="{X(px):.1f}" y2="{Y(g["L_BED"]-8):.1f}" stroke="{C_MAIN}" stroke-width="1.6"/>')
                svg.append(f'<polygon points="{X(px-0.9):.1f},{Y(g["L_BED"]-8):.1f} {X(px+0.9):.1f},{Y(g["L_BED"]-8):.1f} '
                           f'{X(px):.1f},{Y(g["L_BED"]-11):.1f}" fill="#cfcfcf" stroke="{C_MAIN}" stroke-width="1.2"/>')

    pier_labels = []
    for i, px in enumerate(g["pier_x"]):
        if i in (g["main_idx"], g["main_idx"] + 1):
            pier(px, g["L_MAIN_PIER"], p["pier_w_main"], p["pier_wt_main"], cap=False)
            pier_labels.append((px, "主墩", p["pier_wt_main"]))
        else:
            pier(px, L_BOT, p["pier_w"], p["pier_wt"], cap=True)
            pier_labels.append((px, "过渡墩" if i in (0, len(g["pier_x"]) - 1) else "边墩", p["pier_wt"]))
    if p["approach_pier"] and float(p["ext_left"]) > 0:
        pier(-float(p["ext_left"]) * 0.7, L_BOT, 7, 5.5, cap=True)
        pier_labels.append((-float(p["ext_left"]) * 0.7, "引桥墩", 5.5))
    if p["approach_pier"] and float(p["ext_right"]) > 0:
        pier(g["total"] + float(p["ext_right"]) * 0.7, L_BOT, 7, 5.5, cap=True)
        pier_labels.append((g["total"] + float(p["ext_right"]) * 0.7, "引桥墩", 5.5))

    # ---------------- Y 型刚构 ----------------
    if g["y_frame"] == "main":
        for px, side in ((g["main_pier_l"], +1), (g["main_pier_r"], -1)):
            ftx = px + side * g["y_front"]
            btx = px - side * g["y_back"]
            pw = p["pier_wt_main"] / 2.0
            for tx in (ftx, btx):
                svg.append(f'<polygon points="{X(px-pw):.1f},{Y(g["L_MAIN_PIER"]):.1f} {X(px+pw):.1f},{Y(g["L_MAIN_PIER"]):.1f} '
                           f'{X(tx+2.4):.1f},{Y(g["L_Y_TOP"]):.1f} {X(tx-2.4):.1f},{Y(g["L_Y_TOP"]):.1f}" '
                           f'fill="#d4d4d4" stroke="{C_MAIN}" stroke-width="2.2"/>')
            # 肢端到底（拱脚）的锚固块
            if g["L_Y_TOP"] > g["L_FOOT"] + 0.5:
                svg.append(f'<polygon points="{X(ftx-3.4):.1f},{Y(g["L_Y_TOP"]):.1f} {X(ftx+3.4):.1f},{Y(g["L_Y_TOP"]):.1f} '
                           f'{X(ftx+2.4):.1f},{Y(g["L_FOOT"]-1.6):.1f} {X(ftx-2.4):.1f},{Y(g["L_FOOT"]-1.6):.1f}" '
                           f'fill="#c9c9c9" stroke="{C_MAIN}" stroke-width="2.0"/>')
            # 拱脚锚固三角
            for fx in (g["ax1"], g["ax2"]):
                if abs(fx - ftx) < 1.0:
                    svg.append(f'<polygon points="{X(fx-3):.1f},{Y(g["L_FOOT"]+0.6):.1f} {X(fx+3):.1f},{Y(g["L_FOOT"]+0.6):.1f} '
                               f'{X(fx):.1f},{Y(g["L_FOOT"]-3.2):.1f}" fill="#bbbbbb" stroke="{C_MAIN}" stroke-width="1.6"/>')

    # ---------------- 主拱（拱肋按拱轴线法向等厚偏移） ----------------
    N = 160
    xs = [g["ax1"] + i * g["arch_span"] / N for i in range(N + 1)]
    ys = [g["axis_level"](xv) for xv in xs]
    pts_u, pts_d = [], []
    for i in range(N + 1):
        i0, i1 = max(0, i - 1), min(N, i + 1)
        dxw, dyw = xs[i1] - xs[i0], ys[i1] - ys[i0]
        ln = math.hypot(dxw, dyw) or 1.0
        hx, hy = -dyw / ln * g["box_h"] / 2.0, dxw / ln * g["box_h"] / 2.0
        pts_u.append((X(xs[i] + hx), Y(ys[i] + hy)))
        pts_d.append((X(xs[i] - hx), Y(ys[i] - hy)))
    poly = ("M" + " L".join(f"{a:.1f},{b:.1f}" for a, b in pts_u)
            + " L" + " L".join(f"{a:.1f},{b:.1f}" for a, b in reversed(pts_d)) + " Z")
    svg.append(f'<path d="{poly}" fill="#d9d9d9" stroke="{C_MAIN}" stroke-width="3.2"/>')
    for fx in (g["ax1"], g["ax2"]):
        svg.append(f'<circle cx="{X(fx):.1f}" cy="{Y(g["L_FOOT"]):.1f}" r="3.4" fill="#ffffff" stroke="{C_MAIN}" stroke-width="1.5"/>')

    # ---------------- 吊杆 ----------------
    for xv in g["hangers"]:
        svg.append(f'<line x1="{X(xv):.1f}" y1="{Y(g["rib_bottom"](xv)):.1f}" x2="{X(xv):.1f}" y2="{Y(L_TOP):.1f}" stroke="{C_SUB}" stroke-width="1.05"/>')

    # ---------------- 系杆 ----------------
    tie_off = float(p["tie_offset"])
    svg.append(f'<line x1="{X(g["ax1"]):.1f}" y1="{Y(g["L_FOOT"]-tie_off):.1f}" x2="{X(g["ax2"]):.1f}" y2="{Y(g["L_FOOT"]-tie_off):.1f}" '
               f'stroke="{C_TENDON}" stroke-width="1.8" stroke-dasharray="16,4,3,4"/>')
    side_tie = p["side_tie"]
    if side_tie == "auto":
        side_tie = (g["y_frame"] == "main")
    if side_tie is True or side_tie == "yes":
        lv = L_BOT - tie_off - 1.5
        if g["y_frame"] == "main":
            svg.append(f'<line x1="{X(g["main_pier_l"]-g["y_back"]-1):.1f}" y1="{Y(lv):.1f}" x2="{X(g["pier_x"][g["main_idx"]-1]+3):.1f}" y2="{Y(lv):.1f}" stroke="{C_TENDON}" stroke-width="1.8" stroke-dasharray="16,4,3,4"/>')
            svg.append(f'<line x1="{X(g["main_pier_r"]+g["y_back"]+1):.1f}" y1="{Y(lv):.1f}" x2="{X(g["pier_x"][g["main_idx"]+2]-3):.1f}" y2="{Y(lv):.1f}" stroke="{C_TENDON}" stroke-width="1.8" stroke-dasharray="16,4,3,4"/>')

    # ---------------- 尺寸标注 ----------------
    def dim_h(x1, x2, level, label, fs=11.5):
        yy = Y(level)
        svg.append(f'<path d="M{X(x1):.1f},{yy:.1f} L{X(x2):.1f},{yy:.1f}" stroke="{C_DIM}" stroke-width="1" marker-start="url(#ar)" marker-end="url(#ar)"/>')
        svg.append(f'<path d="M{X(x1):.1f},{yy-6:.1f} L{X(x1):.1f},{yy+6:.1f} M{X(x2):.1f},{yy-6:.1f} L{X(x2):.1f},{yy+6:.1f}" stroke="{C_DIM}" stroke-width="0.7"/>')
        svg.append(f'<text x="{X((x1+x2)/2):.1f}" y="{yy+13:.1f}" font-size="{fs}" fill="{C_DIM}" text-anchor="middle" {HALO}>{label}</text>')

    def dim_v(xv, l1, l2, label, fs=11.5, side=1):
        xx = X(xv)
        svg.append(f'<path d="M{xx:.1f},{Y(l1):.1f} L{xx:.1f},{Y(l2):.1f}" stroke="{C_DIM}" stroke-width="1" marker-start="url(#ar)" marker-end="url(#ar)"/>')
        svg.append(f'<text x="{xx+side*6:.1f}" y="{Y((l1+l2)/2)+4:.1f}" font-size="{fs}" fill="{C_DIM}" text-anchor="{"start" if side > 0 else "end"}" {HALO}>{label}</text>')

    def elev_mark(xv, level, text, side="right", fs=11):
        xx, yy = X(xv), Y(level)
        svg.append(f'<line x1="{xx:.1f}" y1="{yy:.1f}" x2="{xx+12:.1f}" y2="{yy:.1f}" stroke="{C_DIM}" stroke-width="1"/>')
        svg.append(f'<polygon points="{xx+6:.1f},{yy:.1f} {xx+1:.1f},{yy-9:.1f} {xx+11:.1f},{yy-9:.1f}" fill="none" stroke="{C_DIM}" stroke-width="1.1"/>')
        anc = "start" if side == "right" else "end"
        dx = 15 if side == "right" else -6
        svg.append(f'<text x="{xx+dx:.1f}" y="{yy-4:.1f}" font-size="{fs}" fill="{C_DIM}" text-anchor="{anc}" {HALO}>{text}</text>')

    if p["show_span_dims"]:
        a = 0.0
        for s in g["spans"]:
            dim_h(a, a + s, g["lv_dim_spans"], f"{s:g}")
            a += s
        dim_h(0, g["total"], g["lv_dim_total"], f"主桥全长 {g['total']:g} m", fs=11)
    if p["show_arch_span_dim"]:
        dim_h(g["ax1"], g["ax2"], g["L_FOOT"] - float(p["arch_span_dim_offset"]), f"拱净跨 {g['arch_span']:g} m")
    if p["show_rise_dim"]:
        dim_v(g["arch_cx"], g["L_FOOT"], g["L_APEX"], f"矢高 {g['rise']:g} m")
    if p["show_girder_depth_dim"]:
        nm = "桁高" if p["girder"] == "truss" else "梁高"
        dim_v(g["total"] * 0.94, L_BOT, L_TOP, f"{nm} {g['deck_depth']:g} m", fs=10.5)
    if p["show_elev_marks"]:
        elev_mark(g["arch_cx"], g["L_APEX"], f"{g['L_APEX']+g['deck_level']:.2f}（拱顶）")
        elev_mark(g["total"] * 0.9, L_TOP, f"{g['L_TOP']+g['deck_level']:.2f}（桥面）")
        elev_mark(g["main_pier_l"], g["L_MAIN_PIER"], f"{g['L_MAIN_PIER']+g['deck_level']:.2f}（主墩墩顶）", side="left")

    # ---------------- 水位文字 ----------------
    if g["wl"]:
        x_lab = g["world_x0"] + float(p["river_note_pos"]) * (g["world_x1"] - g["world_x0"])
        step = max(g["arch_span"] * 0.34, 20.0)
        if p["show_water_labels"]:
            for k, (nm, lv) in enumerate(g["wl"]):
                txt = f"{nm} {lv + g['deck_level']:.3f} m"
                xx = X(x_lab + k * step)
                if "枯" in nm:
                    svg.append(f'<text x="{xx:.1f}" y="{Y(lv)+16:.1f}" font-size="11.5" fill="{C_WAT}" {HALO}>{txt}</text>')
                else:
                    svg.append(f'<text x="{xx:.1f}" y="{Y(lv)-7:.1f}" font-size="11.5" fill="{C_WAT}" {HALO}>{txt}</text>')
        base_lv = g["wl"][-1][1] if g["wl"] else g["L_BED"]
        if p["river_note"]:
            svg.append(f'<text x="{X(x_lab + len(g["wl"]) * step):.1f}" y="{Y(base_lv)+16:.1f}" '
                       f'font-size="11" fill="{C_WAT}" {HALO}>{p["river_note"]}</text>')
    if p["bed_note"]:
        xb = g["world_x0"] + float(p["bed_note_pos"]) * (g["world_x1"] - g["world_x0"])
        svg.append(f'<text x="{X(xb):.1f}" y="{Y(g["L_BED"])+16:.1f}" font-size="10.5" fill="{C_SUB}" {HALO}>{p["bed_note"]}</text>')

    # ---------------- 引出标注 ----------------
    def leader(xa, ya, xt, yt, text, anchor="start", color=C_SUB, fs=11):
        svg.append(f'<path d="M{X(xa):.1f},{Y(ya):.1f} L{xt:.1f},{yt:.1f}" stroke="{color}" stroke-width="0.9"/>')
        svg.append(f'<circle cx="{X(xa):.1f}" cy="{Y(ya):.1f}" r="2.2" fill="{color}"/>')
        dx = 4 if anchor == "start" else -4
        svg.append(f'<text x="{xt+dx:.1f}" y="{yt+4:.1f}" font-size="{fs}" fill="{color}" text-anchor="{anchor}" {HALO}>{text}</text>')

    if p["show_leaders"] and p["deck_notes"]:
        notes = [s.strip() for s in str(p["deck_notes"]).split(";") if s.strip()]
        for i, nt in enumerate(notes):
            lvl = L_TOP + 1.2 if i == 0 else L_BOT - 1.0
            est = sum(11.0 if ord(c) > 127 else 6.2 for c in nt) + 8.0
            xt = max(X(g["total"] * 0.9) + 40.0, W - 14.0 - est)
            leader(g["total"] * 0.72 + i * g["total"] * 0.05, lvl, xt, 84 + i * 24, nt, "start")

    if p["show_pier_labels"]:
        for px, nm, wt in pier_labels:
            anc = "end" if X(px) > X(g["total"] / 2) else "start"
            dx = (float(wt) / 2.0) * S + 14.0
            dx = -dx if anc == "end" else dx
            svg.append(f'<text x="{X(px)+dx:.1f}" y="{Y(L_BOT)+16:.1f}" font-size="10.5" fill="{C_SUB}" text-anchor="{anc}" {HALO}>{nm}</text>')

    # ---------------- 说明条 ----------------
    if p["show_info_box"]:
        bx, by, bw, bh = 14.0, Y(g["world_bot"]) + 16.0, W - 28.0, g["info_h"]
        svg.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="#fafafa" stroke="#999" stroke-width="1" rx="4"/>')
        for i, (txt, bold) in enumerate(g["info_lines"]):
            fs = 11.5 if bold else 10.8
            svg.append(f'<text x="{bx+14:.1f}" y="{by+22+i*19:.1f}" font-size="{fs}" '
                       f'font-weight="{"bold" if bold else "normal"}" fill="{C_MAIN if bold else C_SUB}">{txt}</text>')

    svg.append("</svg>")
    return "\n".join(svg)


def main(argv=None):
    ap = argparse.ArgumentParser(description="系杆拱桥立面示意图生成器（SVG）")
    ap.add_argument("--preset", choices=sorted(PRESETS), help="预设桥型参数")
    ap.add_argument("--json-str", help="JSON 参数串（键名同长参数，如 arch_span / deck_depth）")
    ap.add_argument("--output", "-o", help="输出 SVG 路径")
    for key, val in DEFAULTS.items():
        if key == "output":
            continue
        flag = "--" + key.replace("_", "-")
        if isinstance(val, bool):
            ap.add_argument(flag, dest=key, action="store_true", default=None)
            ap.add_argument("--no-" + key.replace("_", "-"), dest=key, action="store_false", default=None)
        elif isinstance(val, (int, float)) and val is not None:
            ap.add_argument(flag, dest=key, type=float, default=None)
        else:
            ap.add_argument(flag, dest=key, type=str, default=None)
    args = ap.parse_args(argv)

    cli = {k: v for k, v in vars(args).items() if v is not None and k not in ("preset", "json_str")}
    merged = {}
    if args.preset:
        merged.update(PRESETS[args.preset])
    if args.json_str:
        merged.update(json.loads(args.json_str))
    merged.update(cli)

    # 还原成 argparse 命名空间（补默认）
    full = dict(DEFAULTS)
    full.update(merged)
    if args.output:
        full["output"] = args.output
    if not full.get("output"):
        raise SystemExit("错误:必须给出 --output 输出路径")

    ns = argparse.Namespace(**full)
    g = build(ns)
    out = render(g)
    with open(full["output"], "w", encoding="utf-8") as f:
        f.write(out)

    # —— 汇总 ——
    print(f"输出：{full['output']}（{len(out)} 字节，画布 {g['W']:.0f}×{g['H']:.0f}，比例 {g['S']:.3f} px/m）")
    print(f"跨径：{'+'.join(f'{s:g}' for s in g['spans'])} m  主桥全长 {g['total']:g} m")
    print(f"主拱：净跨 {g['arch_span']:g} m  矢高 {g['rise']:g} m  矢跨比 1/{g['arch_span']/g['rise']:.2f}  拱轴线 {g['axis_name']}")
    print(f"拱肋：立面高 {g['box_h']:g} m  拱脚标高（相对桥面）{g['L_FOOT']:+.3f} m  拱顶（相对桥面）{g['L_APEX']:+.3f} m")
    print(f"吊杆：{len(g['hangers'])} 根 @ {g['spacing']:g} m")
    print(f"刚构：{g['y_frame']}（前肢 {g['y_front']:g} m / 后肢 {g['y_back']:g} m）")
    if g["wl"]:
        print("水位：" + " ｜ ".join(f"{nm} {lv + g['deck_level']:.3f}" for nm, lv in g["wl"]))
    print(f"河床（相对桥面）：{g['L_BED']:+.3f} m")
    warn = []
    if g["box_h"] / 2.0 > g["rise"] / 3.0:
        warn.append("拱肋立面高度偏大（超过矢高 2/3），图中拱肋可能显得过厚")
    if g["spacing"] <= 0:
        warn.append("吊杆间距必须为正")
    if g["L_APEX"] <= max(g["L_TOP"], 0.0):
        warn.append("拱顶未高出桥面，检查 rise / arch_foot_drop 取值")
    if warn:
        print("提示：\n  - " + "\n  - ".join(warn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
