# -*- coding: utf-8 -*-
"""把封面和选好的评论渲染成"电影字幕"风格的 3:4 卡片。

版式（与参考 skill 一致）：主图约占 70%，4 条字幕条各约 7.5%，条间距为 0。
主图 = 模糊放大的封面做背景 + 居中的清晰封面（专辑封面通常是正方形） + 歌名歌手署名。
字幕条 = 从封面提取的深色底，白字加描边，每条只放一行。

文字永远来自 candidates.json，Agent 只写"选了哪几条"的编号，不重新打字。
署名只有歌名、歌手和来源，不显示评论者的任何信息。

用法：
  python -X utf8 render_card.py --song OUT/song.json --candidates OUT/candidates.json \
      --cards OUT/cards.json --out-dir OUT/cards
cards.json 的写法：
  {"cards": [{"name": "孤独", "quotes": ["1", "3.2", "10"]}]}
"""
from __future__ import annotations

import argparse
import colorsys
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cardlib as C  # noqa: E402

C.ensure_utf8()

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
except ImportError:
    print("缺少 Pillow。请先运行：python -m pip install -r requirements.txt")
    sys.exit(2)


# ------------------------------------------------------------------ 颜色
def dominant_color(img):
    small = img.convert("RGB").resize((64, 96))
    q = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    best, best_score = None, -1.0
    for count, idx in q.getcolors():
        r, g, b = pal[idx * 3:idx * 3 + 3]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if (v > 0.95 and s < 0.10) or v < 0.08:
            continue  # 纯白、纯黑不当主色
        score = count * (0.35 + s)
        if score > best_score:
            best, best_score = (r, g, b), score
    return best or (60, 70, 90)


def band_base_color(rgb):
    h, s, _ = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    s = s if s < 0.12 else min(max(s, 0.30), 0.65)
    r, g, b = colorsys.hsv_to_rgb(h, s, 0.25)
    return (int(r * 255), int(g * 255), int(b * 255))


def scale_rgb(rgb, k):
    return tuple(max(0, min(255, int(c * k))) for c in rgb)


# ------------------------------------------------------------------ 文字
def draw_text_centered(draw, cx, cy, text, font, fill, stroke, stroke_fill):
    """按"墨迹"而不是字体行高居中，中文字幕看起来更正。"""
    ref = font.getbbox("国", anchor="ls")
    y_base = cy - (ref[1] + ref[3]) / 2
    draw.text((cx, y_base), text, font=font, fill=fill, anchor="ms",
              stroke_width=stroke, stroke_fill=stroke_fill)


def fit_font(lay, text, start, minimum, max_width):
    size = start
    while size > minimum and lay.font(size).getlength(text) > max_width:
        size -= 2
    return lay.font(size), size


# ------------------------------------------------------------------ 主图
def build_main(lay, nbands, cover, book_info, cover_ratio):
    W, main_h = lay.W, lay.main_h(nbands)
    meta = {"display": None, "upscale": None}
    title = "《%s》" % book_info.get("title", "")
    author = book_info.get("artist_display") or ""
    credit2 = (author + "  ·  QQ音乐热评") if author else "QQ音乐热评"

    if cover is None:
        bg = Image.new("RGB", (W, main_h), (24, 30, 44))
        grad = Image.linear_gradient("L").resize((W, main_h))
        bg = Image.composite(Image.new("RGB", (W, main_h), (12, 15, 24)), bg, grad)
        canvas = bg.convert("RGBA")
        d = ImageDraw.Draw(canvas)
        f1, _ = fit_font(lay, title, round(W * 0.09), 40, W * 0.84)
        f2, _ = fit_font(lay, credit2, round(W * 0.03), 22, W * 0.84)
        draw_text_centered(d, W / 2, main_h * 0.46, title, f1, (255, 255, 255), 2, (0, 0, 0))
        draw_text_centered(d, W / 2, main_h * 0.46 + round(W * 0.09), credit2, f2, (225, 225, 225), 2, (0, 0, 0))
        return canvas.convert("RGB"), meta

    cw, ch = cover.size
    # 背景：封面铺满并模糊、压暗
    scale = max(W / cw, main_h / ch)
    bg = cover.resize((max(W, round(cw * scale)), max(main_h, round(ch * scale))), Image.LANCZOS)
    left, top = (bg.width - W) // 2, (bg.height - main_h) // 2
    bg = bg.crop((left, top, left + W, top + main_h))
    small = bg.resize((W // 4, main_h // 4), Image.LANCZOS).filter(ImageFilter.GaussianBlur(radius=W * 0.07 / 4))
    bg = small.resize((W, main_h), Image.BICUBIC)
    bg = Image.blend(bg, Image.new("RGB", bg.size, (0, 0, 0)), 0.40)
    canvas = bg.convert("RGBA")

    # 署名区高度
    credit_h = round(W * 0.07) + round(W * 0.045)
    gap = round(W * 0.025)
    margin = round(main_h * 0.045)
    avail = main_h - 2 * margin - gap - credit_h
    cover_h = min(round(main_h * cover_ratio), avail)
    cover_w = round(cw * cover_h / ch)
    if cover_w > W * 0.78:
        cover_w = round(W * 0.78)
        cover_h = round(ch * cover_w / cw)
    upscale = cover_h / ch
    fg = cover.resize((cover_w, cover_h), Image.LANCZOS)
    if upscale > 2:
        fg = fg.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
    block_h = cover_h + gap + credit_h
    x0 = (W - cover_w) // 2
    y0 = (main_h - block_h) // 2

    shadow = Image.new("RGBA", (W, main_h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle([x0, y0 + 18, x0 + cover_w, y0 + cover_h + 18], fill=(0, 0, 0, 175))
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(26)))
    canvas.paste(fg.convert("RGBA"), (x0, y0))

    d = ImageDraw.Draw(canvas)
    cy1 = y0 + cover_h + gap + round(W * 0.035)
    f1, _ = fit_font(lay, title, round(W * 0.032), 24, W * 0.86)
    f2, _ = fit_font(lay, credit2, round(W * 0.024), 20, W * 0.86)
    draw_text_centered(d, W / 2, cy1, title, f1, (255, 255, 255), 2, (0, 0, 0))
    draw_text_centered(d, W / 2, cy1 + round(W * 0.05), credit2, f2, (215, 215, 215), 2, (0, 0, 0))
    meta["display"] = [cover_w, cover_h]
    meta["upscale"] = round(upscale, 2)
    return canvas.convert("RGB"), meta


# ------------------------------------------------------------------ 字幕条
def draw_band(lay, y0, color, shade, text, font, stroke):
    W, bh = lay.W, lay.band_h
    col = scale_rgb(color, shade)
    top, bottom = scale_rgb(col, 1.07), scale_rgb(col, 0.93)
    mask = Image.linear_gradient("L").resize((W, bh))  # 上黑下白
    band = Image.composite(Image.new("RGB", (W, bh), bottom), Image.new("RGB", (W, bh), top), mask)
    d = ImageDraw.Draw(band)
    d.line([(0, 0), (W, 0)], fill=scale_rgb(col, 0.55), width=2)
    draw_text_centered(d, W / 2, bh / 2, text, font, (255, 255, 255), stroke, (0, 0, 0))
    return band


# ------------------------------------------------------------------ 主流程
def load_cover(args, book, book_dir):
    path = args.cover or book["song"].get("cover_file")
    cands = [path] if path else []
    for name in ("cover.jpg", "cover.png"):
        cands.append(os.path.join(book_dir, name))
    for p in cands:
        if p and os.path.exists(p):
            return p, Image.open(p).convert("RGB")
    return None, None


def index_candidates(cdata):
    idx = {}
    for c in cdata["candidates"]:
        idx[c["ref"]] = {"text": c["text"], "lines": c.get("lines"), "likes": c["likes"],
                         "hard": c.get("hard", []), "parent": c["ref"], "dup_of": c.get("dup_of"),
                         "piece_refs": [p["ref"] for p in c["pieces"]]}
        for p in c["pieces"]:
            idx[p["ref"]] = {"text": p["text"], "lines": p.get("lines"), "likes": c["likes"],
                             "hard": p.get("hard", []), "parent": c["ref"], "dup_of": c.get("dup_of"),
                             "piece_refs": []}
    return idx


def main():
    ap = argparse.ArgumentParser(description="渲染金句卡片")
    ap.add_argument("--song", required=True, help="qq_fetch.py 生成的 song.json")
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--cards", required=True, help='形如 {"cards":[{"name":"..","quotes":["1","3.2"]}]}')
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--aspect", default="3:4")
    ap.add_argument("--bands", type=int, default=4, help="每张卡字幕条数，默认 4")
    ap.add_argument("--flex", action="store_true", help="允许每张卡 3~6 条（默认必须正好是 --bands）")
    ap.add_argument("--cover", help="手动指定封面图，覆盖 song.json 里的封面")
    ap.add_argument("--cover-ratio", type=float, default=0.80, help="封面占主图高度的比例，默认 0.80（专辑封面是正方形，可以放大一些）")
    ap.add_argument("--font")
    ap.add_argument("--format", choices=["jpg", "png"], default="jpg")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    with open(args.song, encoding="utf-8") as f:
        book = json.load(f)
    with open(args.candidates, encoding="utf-8") as f:
        cdata = json.load(f)
    with open(args.cards, encoding="utf-8") as f:
        cards = json.load(f)["cards"]
    idx = index_candidates(cdata)
    lay = C.Layout(width=args.width, aspect=args.aspect, font=args.font)
    binfo = book["song"]
    book_dir = os.path.dirname(os.path.abspath(args.song))

    # ---- 先校验所有卡片，再动手渲染 ----
    plans, errors = [], []
    seen_refs = {}
    for k, card in enumerate(cards, 1):
        quotes, lines_all = [], []
        for ref in card["quotes"]:
            ref = str(ref)
            q = idx.get(ref)
            if q is None:
                errors.append("卡片%d：找不到编号 %s" % (k, ref))
                continue
            if q["dup_of"]:
                errors.append("卡片%d：%s 与 %s 重复，请换一条" % (k, ref, q["dup_of"]))
            lines = q["lines"] or lay.plan_comment(q["text"], 4)
            if not lines:
                opts = q.get("piece_refs") or []
                errors.append("卡片%d：%s 太长放不下，%s" % (
                    k, ref, ("可改用它的完整句子选项：" + "、".join(opts)) if opts else "它也没有可用的完整句子选项，请放弃这条"))
                continue
            if ref in seen_refs:
                errors.append("卡片%d：%s 已经用在卡片%d" % (k, ref, seen_refs[ref]))
            seen_refs[ref] = k
            quotes.append({"ref": ref, "text": q["text"], "likes": q["likes"], "hard": q["hard"], "lines": lines})
            lines_all.extend(lines)
        n = len(lines_all)
        ok = (3 <= n <= 6) if args.flex else (n == args.bands)
        if quotes and not ok:
            errors.append("卡片%d：这些金句共占 %d 条字幕条，需要正好 %d 条%s。各条占用：%s" % (
                k, n, args.bands, "（--flex 允许 3~6）" if not args.flex else "",
                ", ".join("%s=%d" % (q["ref"], len(q["lines"])) for q in quotes)))
        plans.append({"name": card.get("name") or "卡片%d" % k, "quotes": quotes, "lines": lines_all})
    if errors:
        print("渲染前检查没通过：")
        for e in errors:
            print("  - " + e)
        return 2

    base = C.safe_name(binfo.get("title") or "song")
    ext = ".jpg" if args.format == "jpg" else ".png"
    os.makedirs(args.out_dir, exist_ok=True)
    targets = [os.path.join(args.out_dir, "%s_卡片%d%s" % (base, k, ext)) for k in range(1, len(plans) + 1)]
    sheet_path = os.path.join(args.out_dir, "contact_sheet.jpg")
    manifest_path = os.path.join(args.out_dir, "render_manifest.json")
    existing = [p for p in targets + [sheet_path, manifest_path] if os.path.exists(p)]
    if existing and not args.overwrite:
        print("这些文件已存在，默认不覆盖：")
        for p in existing:
            print("  - " + p)
        print("确认要替换时加 --overwrite，或换一个 --out-dir。")
        return 2

    cover_path, cover = load_cover(args, book, book_dir)
    if cover is None:
        print("⚠ 没找到封面图，使用纯色背景加歌名代替。")
    dom = dominant_color(cover) if cover is not None else (60, 70, 90)
    base_col = band_base_color(dom)

    manifest = {"song": {k: binfo.get(k) for k in ("id", "title", "artist_display")}, "layout": {
        "W": lay.W, "H": lay.H, "band_h": lay.band_h, "usable": lay.usable}, "cards": []}
    rendered = []
    for k, (plan, target) in enumerate(zip(plans, targets), 1):
        lines = plan["lines"]
        nb = len(lines)
        sizes = [lay.fit_size(t) for t in lines]
        warnings = []
        if any(s is None for s in sizes):
            warnings.append("有一行在最小字号下仍放不下")
            size = lay.size_min
        else:
            size = min(sizes)
        font, stroke = lay.font(size), lay.stroke(size)
        miss = lay.missing_glyphs("".join(lines))
        if miss:
            warnings.append("字体缺少字形：%s" % "".join(miss))

        main_img, meta = build_main(lay, nb, cover, binfo, args.cover_ratio)
        canvas = Image.new("RGB", (lay.W, lay.H))
        canvas.paste(main_img, (0, 0))
        main_h = lay.main_h(nb)
        for i, text in enumerate(lines):
            shade = 1.0 if i % 2 == 0 else 0.86
            canvas.paste(draw_band(lay, main_h + i * lay.band_h, base_col, shade, text, font, stroke),
                         (0, main_h + i * lay.band_h))
        if meta["upscale"] and meta["upscale"] > 3:
            warnings.append("封面放大 %.1f 倍，会偏糊" % meta["upscale"])
        save_kw = {"quality": 95, "subsampling": 0, "optimize": True} if args.format == "jpg" else {}
        canvas.save(target, **save_kw)
        rendered.append(canvas)
        manifest["cards"].append({
            "index": k, "name": plan["name"], "file": os.path.abspath(target), "size": [lay.W, lay.H],
            "bands": nb, "main_h": main_h, "main_fraction": round(main_h / lay.H, 4),
            "font": {"path": lay.font_path, "index": lay.font_index, "size": size, "stroke": stroke},
            "quotes": plan["quotes"], "band_lines": lines,
            "cover": {"file": cover_path, "size": list(cover.size) if cover else None,
                      "display": meta["display"], "upscale": meta["upscale"]},
            "colors": {"dominant": list(dom), "band": list(base_col)},
            "warnings": warnings,
        })
        print("已生成：%s  字号 %dpx  %d 条字幕条%s" % (target, size, nb,
              ("  ⚠ " + "；".join(warnings)) if warnings else ""))

    # 总览图
    th_w = 360
    th_h = round(th_w * lay.H / lay.W)
    gap = 16
    sheet = Image.new("RGB", (gap + len(rendered) * (th_w + gap), th_h + 2 * gap), (245, 245, 245))
    for i, im in enumerate(rendered):
        sheet.paste(im.resize((th_w, th_h), Image.LANCZOS), (gap + i * (th_w + gap), gap))
    sheet.save(sheet_path, quality=90)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("总览图：%s" % sheet_path)
    print("渲染记录：%s" % manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
