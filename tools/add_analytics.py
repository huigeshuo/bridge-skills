#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给静态 HTML 页面批量注入 GoatCounter 访问统计脚本（幂等，可反复运行）。

为什么单独做一个脚本而不是手改 HTML：
docs/ 下的页面大多是由模板或 Markdown 生成的（build.py / md2html.py），
直接改生成物，下次重新生成就被覆盖了。正确做法是生成完统一跑一次本脚本。

用法：
    python tools/add_analytics.py --code huigeshuo
    python tools/add_analytics.py --code huigeshuo docs/index.html docs/box-girder.html
    python tools/add_analytics.py --code huigeshuo --dry-run      # 只看会改哪些，不写入
    python tools/add_analytics.py --code huigeshuo --remove       # 批量移除统计脚本

不传文件列表时，默认处理仓库内 docs/ 目录下所有 .html。
"""

import argparse
import glob
import io
import os
import re
import sys

TEMPLATE = ('<script data-goatcounter="https://{code}.goatcounter.com/count" '
            'async src="https://gc.zgo.at/count.js"></script>')

# 识别已有的统计脚本（不论是哪个站点代码），用于幂等判断与移除
EXISTING = re.compile(
    r'[ \t]*<script[^>]*data-goatcounter=[^>]*>\s*</script>\s*\n?',
    re.I)


def inject(html, code):
    """返回 (新内容, 状态)。状态：added / replaced / exists"""
    snippet = TEMPLATE.format(code=code)
    if EXISTING.search(html):
        old = EXISTING.search(html).group(0)
        if code in old:
            return html, "exists"
        # 站点代码变了：替换掉旧的，避免两个账号各记一份
        return html.replace(old, snippet + "\n", 1), "replaced"
    if "</head>" in html:
        return html.replace("</head>", snippet + "\n</head>", 1), "added"
    m = re.search(r'<body[^>]*>', html, re.I)
    if m:
        i = m.end()
        return html[:i] + "\n" + snippet + html[i:], "added"
    return snippet + "\n" + html, "added"


def strip(html):
    new, n = EXISTING.subn("", html)
    return new, n


def main():
    ap = argparse.ArgumentParser(description="批量注入 GoatCounter 统计脚本")
    ap.add_argument("--code", required=True, help="GoatCounter 站点代码，如 huigeshuo")
    ap.add_argument("files", nargs="*", help="要处理的 HTML，默认 docs/*.html")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写入")
    ap.add_argument("--remove", action="store_true", help="移除统计脚本")
    a = ap.parse_args()

    files = a.files
    if not files:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        files = sorted(glob.glob(os.path.join(here, "docs", "*.html")))
    if not files:
        sys.exit("没有找到要处理的 HTML 文件")

    stat = {}
    for p in files:
        if not os.path.isfile(p):
            print("  跳过（不存在）: %s" % p)
            continue
        html = io.open(p, encoding="utf-8").read()
        if a.remove:
            new, n = strip(html)
            status = "removed" if n else "clean"
        else:
            new, status = inject(html, a.code)
        changed = new != html
        if changed and not a.dry_run:
            io.open(p, "w", encoding="utf-8", newline="\n").write(new)
        stat[status] = stat.get(status, 0) + 1
        try:
            shown = os.path.relpath(p)
        except ValueError:      # 跨盘符时 relpath 会报错
            shown = p
        print("  %-9s %s" % (status, shown))

    print("\n汇总: " + ", ".join("%s %d" % kv for kv in sorted(stat.items())))
    if a.dry_run and any(k in stat for k in ("added", "replaced", "removed")):
        print("（dry-run，未写入任何文件）")
    if not a.remove and stat.get("added", 0) + stat.get("replaced", 0):
        print("提醒：docs/ 页面若由模板生成，重新生成后记得再跑一次本脚本。")


if __name__ == "__main__":
    main()
