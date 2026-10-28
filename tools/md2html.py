#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Markdown 转成单文件 HTML（无第三方依赖）。

只覆盖技术文档常用语法：# 标题、``` 代码块、| 表格、- / 1. 列表、
> 引用、--- 分隔线、**加粗**、`行内代码`、[文字](链接)。

用法：
    python tools/md2html.py 输入.md 输出.html --title "页面标题" --sub "副标题"

设计目标是"文档能看"，不是完整 CommonMark 实现。
"""

import argparse
import html
import io
import re

CSS = """
*{box-sizing:border-box}
body{margin:0;padding:0;background:#f6f7f9;color:#1c2530;
 font:15px/1.75 "Microsoft YaHei",system-ui,-apple-system,sans-serif}
.page{max-width:900px;margin:0 auto;padding:34px 26px 80px}
header{border-bottom:2px solid #e3e7ec;padding-bottom:16px;margin-bottom:26px}
h1{font-size:25px;margin:0 0 6px;font-weight:600;letter-spacing:.3px}
.sub{color:#68737d;font-size:13.5px;line-height:1.6}
h2{font-size:19px;margin:42px 0 14px;padding-left:11px;border-left:4px solid #2c62c9;
 font-weight:600}
h3{font-size:16px;margin:26px 0 10px;color:#20313f;font-weight:600}
p{margin:10px 0}
a{color:#2c62c9;text-decoration:none}
a:hover{text-decoration:underline}
code{background:#eef1f5;color:#1c4f8f;padding:1.5px 5px;border-radius:3px;
 font:13px/1.5 "Consolas","Courier New",monospace}
pre{background:#1f2733;color:#dfe6ee;padding:14px 16px;border-radius:6px;
 overflow-x:auto;margin:14px 0;font:13px/1.6 "Consolas","Courier New",monospace}
pre code{background:none;color:inherit;padding:0;font-size:13px}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:13.5px;
 background:#fff;box-shadow:0 1px 2px rgba(20,40,70,.06)}
th,td{border:1px solid #e3e7ec;padding:8px 11px;text-align:left;vertical-align:top}
th{background:#eef2f7;font-weight:600;color:#20313f;white-space:nowrap}
tr:nth-child(even) td{background:#fafbfc}
blockquote{margin:14px 0;padding:11px 16px;background:#eef4fd;
 border-left:4px solid #2c62c9;color:#33475c;font-size:14px}
blockquote p{margin:4px 0}
ul,ol{margin:10px 0;padding-left:26px}
li{margin:5px 0}
hr{border:0;border-top:1px solid #e3e7ec;margin:34px 0}
footer{margin-top:50px;padding-top:16px;border-top:1px solid #e3e7ec;
 color:#8b96a1;font-size:12.5px}
.toc{background:#fff;border:1px solid #e3e7ec;border-radius:6px;
 padding:14px 20px;margin:22px 0 8px;font-size:13.5px}
.toc b{display:block;margin-bottom:7px;color:#20313f}
.toc ol{margin:0;padding-left:20px;columns:2;column-gap:30px}
.toc li{margin:3px 0;break-inside:avoid}
@media(max-width:680px){.toc ol{columns:1}.page{padding:22px 16px 60px}}
"""

INLINE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
AUTOLINK = re.compile(r"&lt;(https?://[^&\s]+?)&gt;")


def inline(text):
    """行内语法。先转义 HTML，再逐条替换，避免标签被当成源码。"""
    s = html.escape(text)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = INLINE_LINK.sub(lambda m: '<a href="%s">%s</a>' % (m.group(2), m.group(1)), s)
    s = AUTOLINK.sub(r'<a href="\1">\1</a>', s)
    return s


def slug(text):
    """中文标题做锚点时保留中文字符，去掉标点。"""
    t = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text).strip("-")
    return t or "sec"


def convert(md):
    lines = md.split("\n")
    out = []
    toc = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # 围栏代码块
        if line.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>%s</code></pre>" % html.escape("\n".join(buf)))
            continue

        # 表格：当前行以 | 开头且下一行是分隔行
        if line.startswith("|") and i + 1 < n and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            rows = [line]
            i += 2
            while i < n and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            head = cells[0]
            body = cells[1:]
            html_t = ["<table><thead><tr>"]
            html_t += ["<th>%s</th>" % inline(c) for c in head]
            html_t.append("</tr></thead><tbody>")
            for r in body:
                html_t.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in r) + "</tr>")
            html_t.append("</tbody></table>")
            out.append("".join(html_t))
            continue

        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if level == 1:
                i += 1
                continue  # 一级标题由 <header> 承载
            sid = slug(text)
            if level == 2:
                toc.append((sid, text))
            out.append('<h%d id="%s">%s</h%d>' % (level, sid, inline(text), level))
            i += 1
            continue

        # 分隔线
        if re.match(r"^-{3,}\s*$", line.strip()):
            out.append("<hr>")
            i += 1
            continue

        # 引用
        if line.startswith(">"):
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            body = "".join("<p>%s</p>" % inline(x) for x in buf if x)
            out.append("<blockquote>%s</blockquote>" % body)
            continue

        # 列表
        if re.match(r"^\s*[-*]\s+", line) or re.match(r"^\s*\d+\.\s+", line):
            ordered = bool(re.match(r"^\s*\d+\.\s+", line))
            tag = "ol" if ordered else "ul"
            items = []
            while i < n:
                cur = lines[i]
                mu = re.match(r"^\s*[-*]\s+(.*)$", cur)
                mo = re.match(r"^\s*\d+\.\s+(.*)$", cur)
                if mu and not ordered:
                    items.append(mu.group(1))
                elif mo and ordered:
                    items.append(mo.group(1))
                elif cur.strip() and cur.startswith("  ") and items:
                    items[-1] += " " + cur.strip()   # 续行
                else:
                    break
                i += 1
            out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % inline(x) for x in items), tag))
            continue

        # 空行
        if not line.strip():
            i += 1
            continue

        # 段落（合并连续非空行）
        buf = []
        while i < n and lines[i].strip() and not re.match(
            r"^(#{1,4}\s|```|>|\||\s*[-*]\s|\s*\d+\.\s|-{3,}\s*$)", lines[i]
        ):
            buf.append(lines[i].strip())
            i += 1
        if buf:
            out.append("<p>%s</p>" % inline("".join(buf)))
        else:
            i += 1

    return "\n".join(out), toc


def build(src, dst, title, sub):
    md = io.open(src, encoding="utf-8").read()
    body, toc = convert(md)
    toc_html = ""
    if toc:
        items = "".join('<li><a href="#%s">%s</a></li>' % (s, html.escape(t)) for s, t in toc)
        toc_html = '<div class="toc"><b>本文目录</b><ol>%s</ol></div>' % items

    doc = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s</title>
<style>%s</style></head><body><div class="page">
<header><h1>%s</h1><div class="sub">%s</div></header>
%s
%s
<footer>本文由 Markdown 转换生成 · 如需修改请编辑源文件 <code>%s</code></footer>
</div></body></html>
""" % (html.escape(title), CSS, html.escape(title), sub, toc_html, body,
       html.escape(src.replace("\\", "/").split("/")[-1]))

    io.open(dst, "w", encoding="utf-8").write(doc)
    return len(doc.encode("utf-8"))


def main():
    ap = argparse.ArgumentParser(description="Markdown → 单文件 HTML")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--title", default="")
    ap.add_argument("--sub", default="")
    a = ap.parse_args()
    size = build(a.src, a.dst, a.title or a.src, a.sub)
    print("已生成 %s（%.1f KB）" % (a.dst, size / 1024))


if __name__ == "__main__":
    main()
