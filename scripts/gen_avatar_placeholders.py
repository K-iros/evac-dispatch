"""剧情户虚拟头像兜底生成（第十三节第 1 项）。

首选方案是 AI 文生图虚拟人脸（隐私红线：禁用真实照片）；本脚本为
生成服务不可用时的兜底：用 PIL 画扁平插画风虚拟人像（发型/肤色/
衣着按画像与性别参数化），输出 frontend/public/avatars/{id}.png。
前端 mapIcons.loadAvatarIcons 会做圆形裁剪与描边，这里只需方形底图。
服务恢复后直接覆盖同名文件即可无缝替换。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parents[1] / "frontend" / "public" / "avatars"
SIZE = 256

# 剧情户：id → (背景色, 肤色, 发色, 衣色, 发型, 配饰)
# 发型: bun=盘发(奶奶) short=短发(先生) perm=齐耳短卷(阿姨)
CAST: dict[str, dict] = {
    "e-1": dict(bg="#fde8e8", skin="#f5cfa8", hair="#c9c9c9", cloth="#b91c1c", style="bun", extra=None),
    "e-2": dict(bg="#e0ecfd", skin="#eab98a", hair="#4b5563", cloth="#475569", style="short", extra="glasses"),
    "e-8": dict(bg="#fdf3e0", skin="#f2c69b", hair="#6b7280", cloth="#0e7490", style="perm", extra=None),
    "e-16": dict(bg="#e9fbe9", skin="#f5cfa8", hair="#d4d4d4", cloth="#7c3aed", style="bun", extra=None),
    "e-19": dict(bg="#f3e8ff", skin="#f0c294", hair="#e5e5e5", cloth="#15803d", style="bun", extra=None),
}


def draw_avatar(spec: dict) -> Image.Image:
    img = Image.new("RGB", (SIZE, SIZE), spec["bg"])
    d = ImageDraw.Draw(img)
    cx = SIZE // 2

    # 肩部/上衣（底部大弧）
    d.ellipse([cx - 92, 172, cx + 92, 320], fill=spec["cloth"])
    # 颈部
    d.rectangle([cx - 20, 150, cx + 20, 190], fill=spec["skin"])
    # 头部
    d.ellipse([cx - 62, 42, cx + 62, 178], fill=spec["skin"])

    hair = spec["hair"]
    if spec["style"] == "bun":
        # 盘发：头顶发髻 + 两侧鬓发
        d.ellipse([cx - 30, 18, cx + 30, 66], fill=hair)
        d.pieslice([cx - 66, 36, cx + 66, 150], start=180, end=360, fill=hair)
        d.ellipse([cx - 62, 42, cx + 62, 120], outline=None)
        # 露出额头（肤色覆盖回来）
        d.pieslice([cx - 52, 62, cx + 52, 176], start=180, end=360, fill=spec["skin"])
    elif spec["style"] == "perm":
        # 齐耳短卷发
        d.pieslice([cx - 70, 32, cx + 70, 160], start=160, end=380, fill=hair)
        d.ellipse([cx - 72, 84, cx - 40, 140], fill=hair)
        d.ellipse([cx + 40, 84, cx + 72, 140], fill=hair)
        d.pieslice([cx - 52, 60, cx + 52, 174], start=180, end=360, fill=spec["skin"])
    else:  # short
        d.pieslice([cx - 64, 34, cx + 64, 140], start=170, end=370, fill=hair)
        d.pieslice([cx - 54, 58, cx + 54, 168], start=180, end=360, fill=spec["skin"])

    # 眉/眼（视障者画墨镜）
    if spec["extra"] == "glasses":
        d.rounded_rectangle([cx - 46, 96, cx - 8, 124], radius=10, fill="#1f2937")
        d.rounded_rectangle([cx + 8, 96, cx + 46, 124], radius=10, fill="#1f2937")
        d.line([cx - 8, 108, cx + 8, 108], fill="#1f2937", width=4)
    else:
        d.arc([cx - 40, 88, cx - 14, 106], start=200, end=340, fill="#6b7280", width=4)
        d.arc([cx + 14, 88, cx + 40, 106], start=200, end=340, fill="#6b7280", width=4)
        d.ellipse([cx - 34, 102, cx - 20, 116], fill="#3f3f46")
        d.ellipse([cx + 20, 102, cx + 34, 116], fill="#3f3f46")

    # 腮红 + 微笑
    d.ellipse([cx - 50, 126, cx - 32, 140], fill="#f4a9a0")
    d.ellipse([cx + 32, 126, cx + 50, 140], fill="#f4a9a0")
    d.arc([cx - 20, 128, cx + 20, 156], start=20, end=160, fill="#9a3412", width=5)

    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ev_id, spec in CAST.items():
        img = draw_avatar(spec)
        out = OUT_DIR / f"{ev_id}.png"
        img.save(out)
        print(f"saved {out}")


if __name__ == "__main__":
    main()
