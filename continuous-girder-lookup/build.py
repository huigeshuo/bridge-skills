# -*- coding: utf-8 -*-
"""把 data.json 注入 template.html，产出单文件 index.html"""
import json, os

here = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(here, "data.json"), encoding="utf-8"))
tpl = open(os.path.join(here, "template.html"), encoding="utf-8").read()

payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
html = tpl.replace("/*__DATA__*/", payload)
out = os.path.join(here, "index.html")
open(out, "w", encoding="utf-8").write(html)
print("->", out, round(len(html) / 1024, 1), "KB")
