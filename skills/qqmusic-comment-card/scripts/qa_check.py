# -*- coding: utf-8 -*-
"""对渲染结果做自动质检。它不信任渲染脚本的自述，而是重新核对：

  1. 文字：卡面每一条评论拼起来，必须与 QQ 音乐返回的评论原文逐字一致（忽略空白；原文只经过
     '去掉表情符号、不可见字符、转义换行还原' 这类符号层面的整理，QA 会重新核对这一步）
  2. 版面：图片尺寸、主图占比、每行宽度不超出、字体没有缺字
  3. 封面：放大倍数是否过大
  4. 像素：每条字幕条里确实有白色文字，且底色够暗
  5. 重复：同一张卡或不同卡之间没有重复金句

自动检查不能替代肉眼。通过后仍要逐张打开图片看一遍。

用法：
  python -X utf8 qa_check.py --manifest OUT/cards/render_manifest.json --song OUT/song.json
退出码：0 = 没有 FAIL；1 = 有 FAIL
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cardlib as C  # noqa: E402

C.ensure_utf8()

try:
    from PIL import Image
except ImportError:
    print("缺少 Pillow。请先运行：python -m pip install -r requirements.txt")
    sys.exit(2)

results = []


def rec(level, card, msg):
    results.append((level, card, msg))


def main():
    ap = argparse.ArgumentParser(description="金句卡片质检")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--song", required=True, help="qq_fetch.py 生成的 song.json")
    ap.add_argument("--out", help="把质检报告另存为 JSON")
    args = ap.parse_args()

    with open(args.manifest, encoding="utf-8") as f:
        man = json.load(f)
    with open(args.song, encoding="utf-8") as f:
        book = json.load(f)
    originals = {str(h["id"]): C.strip_ws(h["text"]) for h in book["comments"]}
    # 重新跑一遍整理流程，确认存下来的 text 确实是从 QQ 音乐的原文整理出来的，没有被人改过
    drift = [str(h["id"]) for h in book["comments"] if C.normalize_comment(h.get("raw_text") or "") != h["text"]]
    if drift:
        rec("FAIL", "数据", "song.json 里这些评论的 text 与原文整理结果不一致：%s" % ",".join(drift[:8]))

    used = {}
    for card in man["cards"]:
        tag = "卡片%d" % card["index"]
        # --- 文件与尺寸 ---
        path = card["file"]
        if not os.path.exists(path):
            rec("FAIL", tag, "图片文件不存在：%s" % path)
            continue
        im = Image.open(path).convert("RGB")
        if list(im.size) != card["size"]:
            rec("FAIL", tag, "图片尺寸 %s 与记录 %s 不一致" % (im.size, card["size"]))
        else:
            rec("PASS", tag, "尺寸 %dx%d" % im.size)

        # --- 主图占比 ---
        expected = 1 - man["layout"]["band_h"] * card["bands"] / card["size"][1]
        if abs(card["main_fraction"] - expected) > 0.01:
            rec("FAIL", tag, "主图占比 %.3f 与预期 %.3f 不符" % (card["main_fraction"], expected))
        else:
            rec("PASS", tag, "主图占比 %.1f%%，字幕条 %d 条" % (card["main_fraction"] * 100, card["bands"]))

        # --- 文字逐字比对 ---
        flat = []
        for q in card["quotes"]:
            joined = C.strip_ws("".join(q["lines"]))
            if joined != C.strip_ws(q["text"]):
                rec("FAIL", tag, "编号 %s：卡面文字与候选文字不一致" % q["ref"])
            parent = q["ref"].split(".")[0]
            orig = originals.get(parent)
            if orig is None:
                rec("FAIL", tag, "编号 %s：在 song.json 里找不到原始评论" % q["ref"])
            elif joined in orig:
                rec("PASS", tag, "编号 %s 与评论原文逐字一致（%s 赞）" % (q["ref"], q["likes"]))
            else:
                rec("FAIL", tag, "编号 %s：卡面文字不是评论原文的片段" % q["ref"])
            if q.get("hard"):
                rec("WARN", tag, "编号 %s 带有硬标记：%s。除非有充分理由，不要选" % (q["ref"], "；".join(q["hard"])))
            flat.extend(q["lines"])
            if q["ref"] in used:
                rec("WARN", tag, "编号 %s 在卡片%d 里已经用过" % (q["ref"], used[q["ref"]]))
            used[q["ref"]] = card["index"]
        if flat != card["band_lines"]:
            rec("FAIL", tag, "字幕条文字顺序与评论顺序不一致")

        # --- 每行宽度 / 字形 ---
        fk = (card["font"]["path"], card["font"]["index"])
        size = card["font"]["size"]
        font = C.load_font(fk[0], fk[1], size)
        stroke = card["font"]["stroke"]
        usable = man["layout"]["usable"]
        widest = max(font.getlength(t) + 2 * stroke for t in flat)
        if widest > usable + 0.5:
            rec("FAIL", tag, "最宽的一行 %.0fpx 超出可用宽度 %dpx" % (widest, usable))
        else:
            rec("PASS", tag, "最宽一行 %.0fpx，可用 %dpx，字号 %dpx" % (widest, usable, size))
        for w in card.get("warnings", []):
            rec("WARN", tag, "渲染时提示：" + w)

        # --- 封面清晰度 ---
        cv = card.get("cover") or {}
        if cv.get("size") is None:
            rec("WARN", tag, "没有使用封面（纯色背景）")
        else:
            up = cv.get("upscale") or 0
            if up > 3.5:
                rec("WARN", tag, "封面放大 %.1f 倍，明显偏糊，建议换更大的封面或减小 --cover-ratio" % up)
            else:
                rec("PASS", tag, "封面 %sx%s，放大 %.1f 倍" % (cv["size"][0], cv["size"][1], up))

        # --- 像素层面：字幕条是否有字、底色是否够暗 ---
        W, H = im.size
        bh = man["layout"]["band_h"]
        main_h = card["main_h"]
        for i in range(card["bands"]):
            band = im.crop((0, main_h + i * bh, W, main_h + (i + 1) * bh)).convert("L")
            hist = band.histogram()
            total = W * bh
            bright = sum(hist[235:]) / total
            mean = sum(v * c for v, c in enumerate(hist)) / total
            if bright < 0.004:
                rec("FAIL", tag, "第 %d 条字幕条里几乎没有白色文字" % (i + 1))
            elif mean > 130:
                rec("WARN", tag, "第 %d 条字幕条底色偏亮（均值 %.0f），白字可能不够清晰" % (i + 1, mean))
        rec("PASS", tag, "每条字幕条都检测到文字像素")

    # 汇总输出
    order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    for level in ("FAIL", "WARN"):
        for lv, tag, msg in results:
            if lv == level:
                print("[%s] %s：%s" % (lv, tag, msg))
    passes = [r for r in results if r[0] == "PASS"]
    print("[PASS] 共 %d 项通过" % len(passes))
    print("")
    print("结论：%d 个 FAIL，%d 个 WARN。" % (len(fails), len(warns)))
    print("提醒：自动检查不能替代肉眼。请逐张打开图片，确认封面完整不变形、字幕条文字清晰、手机缩略图下也能读。")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump([{"level": a, "card": b, "message": c} for a, b, c in sorted(results, key=lambda r: order[r[0]])],
                      f, ensure_ascii=False, indent=2)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
