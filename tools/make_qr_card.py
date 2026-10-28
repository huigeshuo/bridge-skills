#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成工具入口二维码与竖版分享卡片（PNG）。

依赖：pip install qrcode pillow

用法：
    python tools/make_qr_card.py \
      --url https://example.github.io/repo/tools.html \
      --title "桥梁设计小工具" \
      --desc "连续刚构箱梁尺寸速查 · 箱梁技术指标速查" \
      --out "分享卡片.png"

输出为 750x1000 竖版，适合微信发送、朋友圈、PPT 与打印。
若只想拿纯二维码，加 --qr-only。
"""

import argparse
import os

import qrcode
from PIL import Image, ImageDraw, ImageFont

FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_REG = "C:/Windows/Fonts/msyh.ttc"


def font(size, bold=False):
    path = FONT_BOLD if bold else FONT_REG
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def centered(draw, y, text, f, fill):
    w = draw.textbbox((0, 0), text, font=f)[2]
    draw.text(((750 - w) / 2, y), text, font=f, fill=fill)


def make_qr(url, px=420):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#101820", back_color="white").convert("RGB")
    return img.resize((px, px), Image.NEAREST)


def build_card(url, title, desc, out):
    W, H = 750, 1000
    canvas = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(canvas)

    # 顶部色带
    d.rectangle([0, 0, W, 9], fill="#2c62c9")

    centered(d, 62, title, font(52, True), "#152233")
    centered(d, 136, desc, font(25), "#68737d")

    # 细分隔线
    d.line([(150, 190), (W - 150, 190)], fill="#e6eaef", width=1)

    # 二维码（带浅灰边框，留白足够才扫得出）
    qr = make_qr(url, 400)
    qx, qy = (W - 400) // 2, 236
    d.rectangle([qx - 14, qy - 14, qx + 414, qy + 414], fill="#ffffff", outline="#e6eaef", width=2)
    canvas.paste(qr, (qx, qy))

    centered(d, 676, "手机扫码打开，无需安装", font(26, True), "#2c62c9")
    centered(d, 716, "微信、浏览器、相机均可识别", font(21), "#93a0ac")

    # 底部
    d.line([(120, 790), (W - 120, 790)], fill="#e6eaef", width=1)
    centered(d, 818, "辉歌说 · 桥梁设计辅助工具", font(27, True), "#33475c")
    centered(d, 862, "数据已脱敏，供设计阶段参考，不替代结构计算", font(19), "#93a0ac")

    canvas.save(out)
    return out


def main():
    ap = argparse.ArgumentParser(description="生成二维码与分享卡片")
    ap.add_argument("--url", required=True)
    ap.add_argument("--title", default="桥梁设计小工具")
    ap.add_argument("--desc", default="打开即用，无需安装")
    ap.add_argument("--out", default="分享卡片.png")
    ap.add_argument("--qr-only", action="store_true", help="只输出纯二维码")
    a = ap.parse_args()

    if a.qr_only:
        make_qr(a.url, 600).save(a.out)
        print("已生成纯二维码：%s" % a.out)
    else:
        print("已生成分享卡片：%s" % build_card(a.url, a.title, a.desc, a.out))

    # 顺带打印二维码内容，便于核对
    print("二维码指向：%s" % a.url)


if __name__ == "__main__":
    main()
