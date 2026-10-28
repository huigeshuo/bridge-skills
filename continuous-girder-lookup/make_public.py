# -*- coding: utf-8 -*-
"""生成对外分享版：桥名脱敏为拼音首字母代号，源表名与内部批注一并替换。

构成：data.json（脱敏） + template.html（替换几处文案） -> publish/连续刚构箱梁尺寸速查-辉歌说.html
内部版 index.html 不受影响。
"""
import json, os, re
from pypinyin import lazy_pinyin

here = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(here, "data.json"), encoding="utf-8"))
tpl = open(os.path.join(here, "template.html"), encoding="utf-8").read()

HAN = lambda ch: "\u4e00" <= ch <= "\u9fff"
FUSHI = ("中幅", "左幅", "右幅")

# 桥名地名的多音字惯用读法（右侧为首字母）。只收确实会读错的字，宁少勿多。
HETERO = {
    "长": "c",   # 长兜港 cháng
}


def zh_code(seg):
    """中文段取拼音首字母；用整段取音修正多音字（如 长兜港 -> CDG）。"""
    pys = lazy_pinyin(seg)
    if len(pys) != len(seg):                      # 长度不齐则回退逐字
        pys = [(lazy_pinyin(ch) or [ch])[0] for ch in seg]
    out = []
    for ch, py in zip(seg, pys):
        if ch in HETERO:
            out.append(HETERO[ch].upper())
        elif HAN(ch):
            out.append(py[0].upper() if py and py[0].isalnum() else "")
        elif ch in "-— ":
            out.append("")
        else:
            out.append(ch)
    return "".join(out)


def make_code(name):
    s = re.sub(r"连续梁$", "", name.strip())       # 体系已由页面标签表达
    # 1) 末尾幅别 -> 括号中文，便于区分左右幅而同名
    tail = ""
    m = re.search(r"(中幅|左幅|右幅)$", s)
    if m:
        tail = "（%s）" % m.group(1)
        s = s[:m.start()]
    # 2) 括号内容：幅别保留中文，其他按首字母
    def _paren(mm):
        inner = mm.group(1)
        return "（%s）" % (inner if inner in FUSHI else zh_code(inner))
    s = re.sub(r"[（(]([^）)]*)[）)]", _paren, s)
    # 3) 主体首字母化；括号占位保护
    parts = re.split(r"（[^）]*）", s)
    holder = re.findall(r"（[^）]*）", s)
    body = ""
    for i, p in enumerate(parts):
        body += zh_code(p)
        if i < len(holder):
            body += holder[i]
    return body + tail


def dedup(rows):
    """同一代号出现多次时加序号，按主跨升序编号。"""
    groups = {}
    for x in rows:
        groups.setdefault(x["name"], []).append(x)
    n = 0
    for code, items in groups.items():
        if len(items) == 1:
            continue
        items.sort(key=lambda x: (x["L"] or 0, x["row"]))
        for i, x in enumerate(items, 1):
            x["name"] = "%s-%d" % (code, i)
            n += 1
    return n


# ---------- 代号对照表（内部文件，切勿外发） ----------
# 以「原桥名 -> 代号」固定下来，源表增删改后重跑，已分享过的桥代号不变。
MAP_PATH = os.path.join(here, "code_map.csv")


def load_map():
    m = {}
    if os.path.exists(MAP_PATH):
        with open(MAP_PATH, encoding="utf-8-sig") as fh:
            for line in fh:
                parts = [p.strip() for p in line.rstrip("\n").split(",")]
                if len(parts) >= 2 and parts[0] and parts[0] != "原桥名":
                    m[parts[0]] = parts[1]
    return m


def save_map(m):
    with open(MAP_PATH, "w", encoding="utf-8-sig") as fh:
        fh.write("原桥名,对外代号\n")
        for k in sorted(m):
            fh.write("%s,%s\n" % (k, m[k]))


CODES = load_map()                     # 已固定的代号
# 源表存在同名不同桥（如两座「沱江二桥」），映射键用「桥名#同名序号」
from collections import Counter
_tot, _seen = Counter(x["name"] for x in data["rows"]), Counter()
fresh = 0
for x in data["rows"]:
    raw = x["name"]
    if _tot[raw] > 1:
        _seen[raw] += 1
        key = "%s#%d" % (raw, _seen[raw])
    else:
        key = raw
    x["_key"] = key
    if key in CODES:
        x["name"] = CODES[key]
    else:
        x["name"] = make_code(raw)     # 先给基础代号，重名统一由 dedup 加序号
        fresh += 1
dup = dedup(data["rows"])
for x in data["rows"]:                 # 最终代号回写对照表，下次运行保持不变
    CODES[x.pop("_key")] = x["name"]
save_map(CODES)


# ---------- 1) 脱敏 ----------
data["meta"]["src"] = "本人参与设计的实桥技术总结（内部整理）"

# 内部口径用语对外换成中性说法
for x in data["rows"]:
    if x.get("q_na"):
        x.pop("q_na", None)          # 不再区分「待补/不补」，统一由标签表达
    info = x.get("info") or []
    x["info"] = [re.sub(r"已作废，不再补录", "工程量暂缺", t) for t in info]

# ---------- 2) 模板文案 ----------
rep = [
    # 页脚：去掉源表文件名（页头已交代数据来源），只留脱敏说明与署名
    ('''数据源：连续刚构箱梁尺寸2025.06-整理.xls · <span id="fSrc"></span><br>
 生成于 2026-10-26 · 辉歌说''',
     '''为便于对外交流，桥名以<b>拼音首字母代号</b>表示（幅别保留中文，同名加序号区分）；尺寸与工程量均为原表实测记录，未作修改。<br>
 生成于 2026-10-26 · 辉歌说'''),
    # 上方 fSrc 元素已删除，赋值改为容错
    ('''$("#fSrc").textContent = `实桥 ${META.n_rows} 座 · 主跨 ${META.L_min}~${META.L_max} m`;''',
     '''const _fs = $("#fSrc"); if (_fs) _fs.textContent = `实桥 ${META.n_rows} 座 · 主跨 ${META.L_min}~${META.L_max} m`;'''),
    # 页头「源表」-> 「数据源」
    ('''源表 <b>${META.src}</b>''', '''数据源 <b>${META.src}</b>'''),
    # 桥名后的「无工程量」标签对外删掉：指标列本就显示「—」，逐行重复只是噪音
    ('''\n      + (r.noq ? ` <span class="tag d">${r.q_na ? "量缺·不补" : "量待补"}</span>` : "") + `</td>`;''',
     ''' + `</td>`;'''),
    # 列头 n -> 腹板数（对外不熟悉内部缩写）
    ('''"n_par":"n"''', '''"n_par":"腹板数"'''),
    # 命中行：整行淡蓝底即可，去掉每列左侧竖线（会把表格切碎）
    ('''tr.hit td{background:#f2f8ff!important;box-shadow:inset 3px 0 0 #3b7ddd}''',
     '''tr.hit td{background:#f2f8ff!important}\ntr.hit td:first-child{box-shadow:inset 3px 0 0 #3b7ddd}'''),
    # 页头：口径说明改成中性
    ('''+ `刚构通过 <b>${META.n_clean}</b> 座（量 ${META.n_quant} 座）`''',
     '''+ `连续刚构 <b>${META.n_clean}</b> 座（含工程量 ${META.n_quant} 座）`'''),
    # 去掉内部校核状态标签（对外只在校核不通过时才提示）
    ('''        extra = ` <span class="tag ${r.bad?"w":"g"}">${r.bad?"待核":"校核通过"}</span>`;''',
     '''        extra = r.bad ? ` <span class="tag w">数据待核</span>` : "";'''),
    ('''      + ` <span class="tag ${r.bad ? "w" : "g"}">${r.bad ? "待核" : "通过"}</span>`''',
     '''      + (r.bad ? ` <span class="tag w">数据待核</span>` : "")'''),
    # 去掉「仅校核通过」勾选框，并让监听代码容错
    ('''   <label class="small" style="margin-left:8px;cursor:pointer"><input type="checkbox" id="fClean"> 仅校核通过</label>\n''',
     ''''''),
    ('''$("#fClean").addEventListener("change", e=>{ F.clean = e.target.checked; renderAll(parseFloat($("#L").value)||100); });''',
     '''const _fc = $("#fClean"); if (_fc) _fc.addEventListener("change", e=>{ F.clean = e.target.checked; renderAll(parseFloat($("#L").value)||100); });'''),
    # 推荐表副标题：去掉内部校核口径
    ('''按全库比值统计（校核通过项），已按输入主跨换算''',
     '''按全库连续刚构比值中位值换算，已取整到 5 cm'''),
]

# 全库无待核记录时，图例里的「待核」说明一并去掉
if not any(x.get("bad") for x in data["rows"]):
    rep += [
        (''' <div class="legend"><span><span class="dot" style="background:#f0a04b"></span>黄色底 = 源表数据待核（尺寸仍可参考，工程量慎用）</span></div>\n''',
         ''''''),
        ('''  <span><span class="dot" style="background:#9aa4ae"></span>砼含量（空心=数据待核）</span>''',
         '''  <span><span class="dot" style="background:#9aa4ae"></span>砼含量</span>'''),
    ]
for a, b in rep:
    if a not in tpl:
        raise SystemExit("模板片段未找到：" + a[:60])
    tpl = tpl.replace(a, b)

# ---------- 3) 注入输出 ----------
payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
html = tpl.replace("/*__DATA__*/", payload)

outdir = os.path.join(here, "publish")
os.makedirs(outdir, exist_ok=True)
out = os.path.join(outdir, "连续刚构箱梁尺寸速查-辉歌说.html")
open(out, "w", encoding="utf-8").write(html)

print("脱敏 %d 座，重名加序号 %d 条" % (len(data["rows"]), dup))
print("输出:", out, round(len(html) / 1024, 1), "KB")
print("\n代号对照（仅本机核对用，不随文件外发）：")
for x in data["rows"]:
    print("  r%-3d %-12s L=%-5s %s" % (x["row"], x["name"], x["L"], x["sys"]))
