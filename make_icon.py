# -*- coding: utf-8 -*-
"""生成 app.ico:深蓝圆角方块 + 白色鼠标 + 点击波纹(多尺寸)"""
from PIL import Image, ImageDraw


def make(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 256.0

    # 背景圆角方块(深蓝)
    d.rounded_rectangle([8 * s, 8 * s, 248 * s, 248 * s], radius=52 * s,
                        fill=(30, 58, 95, 255))
    # 鼠标本体
    d.rounded_rectangle([94 * s, 48 * s, 162 * s, 172 * s], radius=34 * s,
                        fill=(240, 246, 255, 255))
    # 鼠标中缝
    d.line([128 * s, 54 * s, 128 * s, 108 * s], fill=(30, 58, 95, 255),
           width=max(1, int(5 * s)))
    # 点击波纹(三道弧线)
    for i, (rr, w, a) in enumerate([(46, 8, 255), (68, 7, 200), (90, 6, 140)]):
        d.arc([128 * s - rr * s, 152 * s - rr * s, 128 * s + rr * s, 152 * s + rr * s],
              start=28, end=152, fill=(110, 180, 255, a), width=max(1, int(w * s)))
    return img


if __name__ == "__main__":
    out = __file__.replace("make_icon.py", "app.ico")
    make(256).save(out, format="ICO",
                   sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon generated:", out)
