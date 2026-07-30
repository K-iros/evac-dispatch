"""CV 半真闭环街景图兜底生成（第十五节第 2 项）。

首选方案是 AI 文生图的阳朔风格街景照片（ImageGen 服务持续 40500
故障，同第十三节头像的处置）；本脚本为兜底：用 PIL 画扁平插画风
街景示意图（喀斯特峰林 + 老城街巷 + 台阶/陡坎障碍物），输出
frontend/public/streetview/{id}.png，供无障碍对比卡片的「街景 AI
识别」演示与后端 Qwen-VL 多模态判定共用。
服务恢复后直接覆盖同名文件即可无缝替换。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parents[1] / "frontend" / "public" / "streetview"
W, H = 800, 600

#: 案例户 → 场景参数（与 cv_access.TEMPLATE_VERDICTS 口径一致）
SCENES: dict[str, dict] = {
    # e-8 卢阿姨（西街）：巷口连续石阶约 5 级
    "e-8": dict(kind="steps", sky="#dbeafe", hill="#94a3b8", wall="#f5f0e6"),
    # e-14 秦阿婆（桂花路）：路缘陡坎 + 破损路面
    "e-14": dict(kind="kerb", sky="#e0f2fe", hill="#9ca3af", wall="#efe9dc"),
    # e-19 欧奶奶（画山路）：临街台阶带残缺护栏
    "e-19": dict(kind="stairs_rail", sky="#d6e6f5", hill="#8b9bb0", wall="#f2ece0"),
}


def draw_backdrop(d: ImageDraw.ImageDraw, spec: dict) -> None:
    """天空 + 喀斯特峰林 + 街面 + 沿街白墙黛瓦。"""
    d.rectangle([0, 0, W, 340], fill=spec["sky"])
    # 喀斯特峰林剪影（圆顶尖峰交错）
    hill = spec["hill"]
    for cx, r, top in [(90, 130, 120), (250, 100, 160), (420, 150, 100),
                       (600, 110, 150), (740, 140, 110)]:
        d.pieslice([cx - r, top, cx + r, top + 2 * r + 160], 180, 360, fill=hill)
    # 街面（透视梯形）
    d.rectangle([0, 340, W, H], fill="#b8b2a6")
    d.polygon([(300, 340), (500, 340), (640, H), (160, H)], fill="#cfc9bc")
    # 沿街建筑：白墙黛瓦两层小楼
    for x0, x1 in [(0, 290), (510, 800)]:
        d.rectangle([x0, 180, x1, 420], fill=spec["wall"])
        d.rectangle([x0, 160, x1, 190], fill="#374151")  # 瓦檐
        d.rectangle([x0, 300, x1, 312], fill="#4b5563")  # 层间瓦线
        for wx in range(x0 + 30, x1 - 30, 90):
            d.rectangle([wx, 210, wx + 44, 280], fill="#7c8ba1")  # 窗
            d.rectangle([wx, 330, wx + 44, 404], fill="#8a6f4d")  # 门/铺板


def draw_steps(d: ImageDraw.ImageDraw) -> None:
    """巷口连续石阶（约 5 级，无坡道）。"""
    x0, x1, y = 300, 500, 340
    for i in range(5):
        d.rectangle([x0 - i * 14, y + i * 26, x1 + i * 14, y + (i + 1) * 26],
                    fill="#a3a3a3", outline="#6b7280", width=3)
    # 阶沿阴影强调
    for i in range(5):
        d.line([x0 - i * 14, y + (i + 1) * 26, x1 + i * 14, y + (i + 1) * 26],
               fill="#52525b", width=4)


def draw_kerb(d: ImageDraw.ImageDraw) -> None:
    """高路缘陡坎（约 20cm）+ 破损路面裂缝。"""
    d.rectangle([120, 430, 680, 470], fill="#9ca3af", outline="#4b5563", width=4)
    d.rectangle([120, 400, 680, 434], fill="#d4d4d8", outline="#6b7280", width=3)
    # 裂缝
    for seg in [[(240, 480), (300, 520), (280, 570)],
                [(480, 476), (450, 530), (500, 580)]]:
        d.line(seg, fill="#57534e", width=5)
    # 缺失的坡道位置（虚线框提示视觉焦点）
    for x in range(340, 460, 24):
        d.line([(x, 396), (x + 12, 396)], fill="#dc2626", width=4)


def draw_stairs_rail(d: ImageDraw.ImageDraw) -> None:
    """临街上行台阶 + 残缺锈蚀护栏。"""
    x0, y0 = 330, 470
    for i in range(6):
        d.rectangle([x0 - i * 10, y0 - (i + 1) * 22, x0 + 180 + i * 6, y0 - i * 22],
                    fill="#b0aaa0" if i % 2 else "#a09a90",
                    outline="#57534e", width=3)
    # 残缺护栏：立柱缺一根、横杆断裂
    rail = "#8a5a3b"
    for i, px in enumerate([x0 - 40, x0 + 30, x0 + 170]):
        py = y0 - 22 * (i * 2) - 10
        d.rectangle([px, py - 70, px + 10, py + 10], fill=rail)
    d.line([x0 - 36, y0 - 90, x0 + 90, y0 - 130], fill=rail, width=8)  # 断裂横杆
    d.line([x0 + 120, y0 - 145, x0 + 176, y0 - 162], fill=rail, width=8)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ev_id, spec in SCENES.items():
        img = Image.new("RGB", (W, H), "#ffffff")
        d = ImageDraw.Draw(img)
        draw_backdrop(d, spec)
        if spec["kind"] == "steps":
            draw_steps(d)
        elif spec["kind"] == "kerb":
            draw_kerb(d)
        else:
            draw_stairs_rail(d)
        out = OUT_DIR / f"{ev_id}.png"
        img.save(out)
        print(f"saved {out}")


if __name__ == "__main__":
    main()
