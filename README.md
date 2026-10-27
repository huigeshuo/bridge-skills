# bridge-skills

> 桥梁设计辅助技能集：**参数化出草图，Excel 出指标**。
> 三个独立可用的 Python 脚本，同时内嵌 AI 助手（WorkBuddy / Claude Skill）的技能描述文件。

## 包含什么

| 目录 | 作用 | 输入 → 输出 |
|---|---|---|
| `bridge-sketch/` | 斜拉桥立面布置草图，按跨径与索距自动排索 | 跨径 / 塔高 / 索距 → SVG |
| `tied-arch-sketch/` | 系杆拱桥（下承式 / 中承式）立面草图 | 净跨 / 矢高 / 吊杆间距 → SVG |
| `box-girder-index/` | 箱梁材料指标库，从汇总表提取砼与钢绞线含量 | 钢束含量汇总表.xlsx → 指标 JSON + 看板 |

三者互不依赖，可单独取用。

## 环境

- Python 3.9+
- `pip install openpyxl` —— 箱梁指标库必装（读 xlsx）
- `pip install pypinyin` —— 可选，用于桥名转拼音首字母代号（对外脱敏）

草图脚本只依赖标准库，装好 Python 即可直接跑。

## 快速开始

### 1. 斜拉桥立面草图

```bash
python bridge-sketch/scripts/generate_bridge_sketch.py \
  --main-span 280 --side-span-left 130 --side-span-right 90 \
  -o out/cable-stayed.svg
```

常用参数（全部可省略，省略即取默认值）：
`--main-span`、`--side-span-left`、`--side-span-right`、`--tower-height`、
`--d-tower`（塔上索距）、`--d-deck`（梁上索距）、`--tower-width`、`--deck-depth`。

也可用 `--preset dongshuimen` 直接调出重庆东水门长江大桥的实测参数作为起点。

运行时脚本会打印每索面根数与**拉索总数**，方便与设计资料对账——索距不要去凑图面好看，按真实根数画。

### 2. 系杆拱桥立面草图

```bash
# 用内置实桥预设
python tied-arch-sketch/scripts/generate_tied_arch_sketch.py --preset caiyuanba -o out/arch.svg

# 或按参数自定（--spans 必填，跨径布置用 + 号连接）
python tied-arch-sketch/scripts/generate_tied_arch_sketch.py \
  --spans "88+102+420+102+88" --arch-span 320 --rise 56.44 --axis parabola \
  -o out/arch.svg
```

内置预设：`caiyuanba`（重庆菜园坝长江大桥，中承式提篮钢箱系杆拱）、`simply-supported`。
不指定 `--preset` 时 `--spans` 为必填项。

### 3. 箱梁技术指标库

```bash
# 首次提取
python box-girder-index/scripts/extract_indicators.py \
  --input 钢束含量汇总表.xlsx --outdir out

# 累积到已有指标库
python box-girder-index/scripts/extract_indicators.py \
  --input 本次.xlsx --lib box-girder-index/data/box_girder_indicators.json --outdir out
```

每条记录包含跨径、桥面面积、砼方量、钢绞线重量，并换算出
**砼含量 m³/m²、钢绞线含量 kg/m² 与 kg/m³、钢板含量 kg/m²**，
同时给出校核 flags（例如「砼数量与本区块另一联重复」这类汇总表常见问题）。

指标口径与校核阈值见 `box-girder-index/references/指标口径与校核规则.md`。

## 在 AI 助手里用

三个目录都是标准 Skill 结构（`SKILL.md` + `scripts/` + `references/`），
整目录放进助手的 skills 目录即可被自动识别调用：

- WorkBuddy：`~/.workbuddy/skills/`
- Claude Code：`~/.claude/skills/`

`SKILL.md` 里的 description 就是触发条件，直接说「画一张 130+280+90 的斜拉桥立面草图」即可。

## 关于数据

仓库中的 `box-girder-index/data/example_indicators.json` 是**虚构示例**，
工程名、桥名、工程量均已脱敏，只用于演示数据格式。

真实指标库（含具体工程名与工程量）不入库——`.gitignore` 已排除
`box-girder-index/data/*.json` 和所有 `*.xlsx`，只放行 example 那份。

脚本本身也内置了脱敏能力：桥名、工程名可统一替换为拼音首字母代号（如 `SKGJ`），
`--no-pinyin` 可临时关闭。

## 目录结构

```
bridge-skills/
├── bridge-sketch/
│   ├── SKILL.md
│   ├── references/cable_stayed_bridge_geometry.md
│   └── scripts/generate_bridge_sketch.py
├── tied-arch-sketch/
│   ├── SKILL.md
│   ├── references/tied_arch_bridge_geometry.md
│   └── scripts/generate_tied_arch_sketch.py
└── box-girder-index/
    ├── SKILL.md
    ├── references/指标口径与校核规则.md
    ├── scripts/extract_indicators.py
    ├── scripts/make_share_pack.py
    └── data/example_indicators.json
```

## 许可

MIT License。工具仅作设计辅助，输出结果须经注册工程师复核，不作为竣工或施工依据。
