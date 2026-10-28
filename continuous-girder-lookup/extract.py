# -*- coding: utf-8 -*-
"""
连续刚构箱梁构造尺寸速查 —— 数据提取
源表：F:\\SZH 文件夹\\技术总结整理2018\\连续刚构箱梁尺寸2025.06-整理.xls
输出：data.json（供 index.html 内嵌）
口径：主跨/桥宽单位 m；其余构造尺寸单位 cm；面积 m2；砼 m3；钢束/钢筋 kg
"""
import json, re, os, statistics as st

SRC = r"F:/SZH 文件夹/技术总结整理2018/连续刚构箱梁尺寸2025.06-整理.xls"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

import xlrd
bk = xlrd.open_workbook(SRC)
sh = bk.sheet_by_index(0)

# 人工核定的口径说明（用户 2026-10-26 确认）
#  q_excl：该桥工程量口径与其他桥不同，含量指标不进统计池，但构造尺寸仍可用
KNOWN = {
    "狗耳峡": dict(q_excl="构造含 0# 块（不拆分），砼/钢束含量偏大，不与纯主梁记录同池统计；构造尺寸正常可用"),
}
# 源表工程量区为空且已确认不再补录
NOQ_NOTE = {
    "五一河大桥": "原工程量口径不成立（面积按单幅、量按双幅），已作废，不再补录",
    "佛山大桥": "原工程量口径不成立（面积按单幅、量按双幅），已作废，不再补录",
}

C = dict(main=0, name=1, spans=2, width=3, sys=4, sect=5, hroot=6, hmid=7,
         web=8, bbot=9, top=10, bot=11, cant=12, cantt=13,
         npar=15, ratio_root=16, ratio_mid=17, edge=18, transv=19, note1=20,
         pierh=21, pier=22, pierd=23, blk0=24, capt=25, pile=26,
         pierh2=27, pier2=28, capt2=29, pile2=30, note2=31,
         area=32, conc=33, strand=34, conc_r=35, strand_m3=36, strand_m2=37,
         rebar=38, rebar_m3=39, rebar_m2=40)


def val(r, key):
    v = sh.cell_value(r, C[key])
    if isinstance(v, str):
        v = v.strip()
        return v if v else None
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v if v != "" else None


def num(r, key):
    v = val(r, key)
    return float(v) if isinstance(v, (int, float)) else None


def txt(r, key):
    v = val(r, key)
    return str(v) if v is not None else ""


def parse_spans(s):
    """'29+40+4x60+40' / '50+3×90+50' / '2*23.25' -> [29,40,60,60,60,60,40]"""
    if not s:
        return []
    s = str(s).replace("×", "x").replace("*", "x").replace("X", "x")
    s = s.replace("＋", "+").replace(" ", "")
    out = []
    for part in s.split("+"):
        if not part:
            continue
        m = re.match(r"^(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)$", part)
        if m:
            out += [float(m.group(2))] * int(float(m.group(1)))
        else:
            try:
                out.append(float(part))
            except ValueError:
                pass
    return out


def rng(s):
    """'40～50' -> (40,50)；'26,50' -> (26,50)；'40' -> (40,40)"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return (float(s), float(s))
    t = str(s).replace("～", "~").replace("–", "~").replace("-", "~").replace("，", ",")
    nums = re.findall(r"\d+(?:\.\d+)?", t)
    if not nums:
        return None
    a = [float(x) for x in nums]
    return (min(a), max(a))


rows = []
for r in range(1, sh.nrows):
    name = txt(r, "name")
    if not name:
        continue
    rec = dict(row=r + 1, name=name)
    sp = parse_spans(txt(r, "spans"))
    main = num(r, "main")
    derive = False
    if main is None and sp:
        main = max(sp)
        derive = True
    rec["spans_raw"] = txt(r, "spans")
    rec["spans"] = sp
    rec["L"] = main                      # 主跨 m
    rec["L_derive"] = derive
    rec["length"] = round(sum(sp), 3) if sp else None
    w = num(r, "width")
    rec["B"] = round(w / 100.0, 2) if w else None      # 桥宽 m
    rec["B_cm"] = w
    # 结构形式：优先取源表「结构形式」列；空则由桥名判别（源表该列多为空）
    sysv = txt(r, "sys")
    if not sysv:
        if "连续梁" in name:
            sysv = "连续梁"
        elif "刚构" in name:
            sysv = "连续刚构"
        elif "连续箱梁" in name:
            sysv = "连续梁"
        else:
            sysv = "连续刚构"
    rec["sys"] = sysv
    rec["sect"] = txt(r, "sect")

    # 构造尺寸（cm）
    for k, key in [("h_root", "hroot"), ("h_mid", "hmid"), ("b_bot", "bbot"),
                   ("t_cant", "cantt"), ("cant", "cant")]:
        v = num(r, key)
        rec[k] = v
    # 底宽单位混用修正：<100 视为 m
    if rec["b_bot"] and rec["b_bot"] < 100:
        rec["b_bot"] = rec["b_bot"] * 100
        rec.setdefault("flags", []).append("底宽按 m 录入，已×100")
    rec["web"] = txt(r, "web")
    rec["top"] = txt(r, "top")
    rec["bot"] = txt(r, "bot")
    rec["n_par"] = num(r, "npar")
    rec["edge"] = num(r, "edge")
    rec["transv"] = txt(r, "transv")
    rec["note1"] = txt(r, "note1")
    rec["note2"] = txt(r, "note2")

    # 下部构造
    rec["pier_h"] = num(r, "pierh")
    rec["pier"] = txt(r, "pier")
    rec["pier_d"] = num(r, "pierd")
    rec["blk0"] = num(r, "blk0")
    rec["cap_t"] = num(r, "capt")
    rec["pile"] = txt(r, "pile")
    rec["pier_h2"] = num(r, "pierh2")
    rec["pier2"] = txt(r, "pier2")
    rec["cap2"] = txt(r, "capt2")
    rec["pile2"] = txt(r, "pile2")

    # 工程量与指标
    for k, key in [("area", "area"), ("conc", "conc"), ("strand", "strand"),
                   ("rebar", "rebar")]:
        rec[k] = num(r, key)
    for k, key in [("conc_r", "conc_r"), ("strand_m3", "strand_m3"),
                   ("strand_m2", "strand_m2"), ("rebar_m3", "rebar_m3"),
                   ("rebar_m2", "rebar_m2")]:
        rec[k] = num(r, key)
    rec["noq"] = not rec["conc_r"]        # 源表该桥工程量区为空
    if rec["noq"] and name in NOQ_NOTE:
        rec["q_na"] = True                # 已确认不再补录

    # 派生比值
    warn = rec.setdefault("warn", [])
    info = rec.setdefault("info", [])
    if rec["L"] and rec["h_root"]:
        rec["r_root"] = round(rec["L"] * 100.0 / rec["h_root"], 2)     # 跨径/根部梁高
        rec["k_root"] = round(rec["h_root"] / (rec["L"] * 100.0), 4)   # 根部梁高/主跨
    if rec["L"] and rec["h_mid"]:
        rec["r_mid"] = round(rec["L"] * 100.0 / rec["h_mid"], 2)
        rec["k_mid"] = round(rec["h_mid"] / (rec["L"] * 100.0), 4)
    # 底宽与悬臂自洽校核
    if rec["B_cm"] and rec["b_bot"] and rec["cant"]:
        pred = rec["B_cm"] - 2 * rec["cant"]
        if abs(pred - rec["b_bot"]) > 60:
            warn.append("底宽 %g 与「桥宽−2×悬臂」%g 不符，疑录入错" % (rec["b_bot"], pred))
    if rec["cant"] and rec["t_cant"]:
        rec["r_cant"] = round(rec["cant"] / rec["t_cant"], 2)
    # 主梁平均断面积 m²（= 砼 ÷ 联长）；用 conc_r×B 计，双幅记录自动归一为单幅
    if rec["conc_r"] and rec["B"]:
        rec["conc_m"] = round(rec["conc_r"] * rec["B"], 2)
    elif rec["conc"] and rec["length"]:
        rec["conc_m"] = round(rec["conc"] / rec["length"], 2)
    # 人工核定的口径差异（含量不参与统计，尺寸照用）
    kn = KNOWN.get(name)
    if kn and kn.get("q_excl"):
        rec["q_excl"] = kn["q_excl"]
        info.append(kn["q_excl"])
    if rec["noq"] and name in NOQ_NOTE:
        info.append(NOQ_NOTE[name])
    # 含钢量校核（已核定口径差异的不再报警）
    if rec["conc_r"]:
        if rec["conc_r"] > 1.55 and not rec.get("q_excl"):
            warn.append("砼含量 %.2f m³/m² 偏高（全库 1.0~1.3），疑含墩身或量/面积口径不一致" % rec["conc_r"])
        elif rec["conc_r"] < 0.6:
            warn.append("砼含量 %.2f m³/m² 偏低" % rec["conc_r"])
    if rec["strand_m2"] and rec["strand_m2"] > 90 and not rec.get("q_excl"):
        warn.append("钢束 %.0f kg/m² 偏高" % rec["strand_m2"])
    if rec["area"] and rec["length"] and rec["B"]:
        ratio = rec["area"] / (rec["length"] * rec["B"])
        if 1.85 <= ratio <= 2.15:
            info.append("面积与砼按双幅统计（=联长×桥宽的 %.1f 倍），含量指标不受影响" % ratio)
        elif ratio < 0.85 or ratio > 2.3:
            warn.append("桥梁面积为「联长×桥宽」的 %.2f 倍，口径待核" % ratio)
        elif ratio > 1.06:
            info.append("面积比「联长×桥宽」大 %.0f%%（含加宽段？）" % ((ratio - 1) * 100))

    rec["bad"] = bool(warn)
    if not warn:
        rec.pop("warn")
    if not info:
        rec.pop("info")
    rows.append(rec)


def q(vals, p):
    vals = sorted(vals)
    if not vals:
        return None
    i = (len(vals) - 1) * p
    lo, hi = int(i), min(int(i) + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (i - lo), 3)


def band_stats(lo, hi, clean=True):
    sub = [x for x in rows if x["L"] and lo <= x["L"] < hi
           and (not clean or not x["bad"]) and x["sys"] == "连续刚构"]
    out = {"n": len(sub)}
    subq = [x for x in sub if not x.get("q_excl")]      # 含量池：剔除含 0#块等口径不同的记录
    out["nq"] = len([x for x in subq if x.get("conc_r")])
    for key in ["k_root", "k_mid", "edge", "r_root", "r_mid", "cant", "t_cant"]:
        v = [x[key] for x in sub if x.get(key)]
        if v:
            out[key] = {"p10": q(v, .1), "med": q(v, .5), "p90": q(v, .9),
                        "min": round(min(v), 4), "max": round(max(v), 4), "n": len(v)}
    for key in ["conc_r", "conc_m", "strand_m2", "strand_m3", "rebar_m2", "rebar_m3"]:
        v = [x[key] for x in subq if x.get(key)]
        if v:
            out[key] = {"p10": q(v, .1), "med": q(v, .5), "p90": q(v, .9), "n": len(v)}
    return out


bands = [("≤80", 0, 80), ("80~120", 80, 120), ("120~160", 120, 160), ("≥160", 160, 999)]
stats = {b[0]: band_stats(b[1], b[2]) for b in bands}
stats_all = {b[0]: band_stats(b[1], b[2], clean=False) for b in bands}
stats["全部"] = band_stats(0, 999)
stats_all["全部"] = band_stats(0, 999, clean=False)

clean = [x for x in rows if not x["bad"] and x["sys"] == "连续刚构"]
n_lianxu = sum(1 for x in rows if x["sys"] != "连续刚构")
allroot = [x["k_root"] for x in clean if x.get("k_root")]
allmid = [x["k_mid"] for x in clean if x.get("k_mid")]

meta = {
    "src": os.path.basename(SRC),
    "n_rows": len(rows),
    "n_span": sum(1 for x in rows if x["L"]),
    "n_quant": sum(1 for x in rows if x.get("conc_r") and x["sys"] == "连续刚构"
                   and not x.get("q_excl")),
    "n_qexcl": sum(1 for x in rows if x.get("q_excl")),
    "n_flag": sum(1 for x in rows if x["bad"]),
    "n_clean": len(clean),
    "n_lianxu": n_lianxu,
    "k_root": {"p10": q(allroot, .1), "med": q(allroot, .5), "p90": q(allroot, .9)},
    "k_mid": {"p10": q(allmid, .1), "med": q(allmid, .5), "p90": q(allmid, .9)},
    "L_min": min(x["L"] for x in rows if x["L"]),
    "L_max": max(x["L"] for x in rows if x["L"]),
    "n_par": {},
}
# 抛物线次数取值分布
for x in rows:
    if x.get("n_par"):
        k = str(x["n_par"])
        meta["n_par"][k] = meta["n_par"].get(k, 0) + 1
# 断面形式分布
meta["sect"] = {}
for x in rows:
    k = x["sect"] or "未注"
    meta["sect"][k] = meta["sect"].get(k, 0) + 1

payload = {"meta": meta, "stats": stats, "stats_all": stats_all, "rows": rows}
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=1)

print("rows=%d span=%d quant=%d clean=%d warn=%d" % (
    meta["n_rows"], meta["n_span"], meta["n_quant"], meta["n_clean"], meta["n_flag"]))
print("k_root p10/med/p90 =", meta["k_root"])
print("k_mid  p10/med/p90 =", meta["k_mid"])
print("n_par", meta["n_par"], "sect", meta["sect"])
for b in bands + [("全部", 0, 999)]:
    s = stats[b[0]]
    sa = stats_all[b[0]]
    print("%-8s n=%-3d k_root=%s conc=%s kg/m2=%s" % (
        b[0], s["n"],
        s.get("r_root", {}).get("med"), s.get("conc_r", {}).get("med"),
        s.get("strand_m2", {}).get("med")), " | all n=", sa["n"])
print("\n-- warn --")
for x in rows:
    if x.get("warn"):
        print(" r%-3d %-16s L=%-5s %s" % (x["row"], x["name"][:14], x["L"], "; ".join(x["warn"])))
print("\n-- info --")
for x in rows:
    if x.get("info"):
        print(" r%-3d %-16s L=%-5s %s" % (x["row"], x["name"][:14], x["L"], "; ".join(x["info"])))
