# -*- coding: utf-8 -*-
"""把 song.json 里的热门评论整理成"候选清单"。

做几件机械的事，让 Agent 专心做编辑判断：
  1. 用真实字体量一量：每条评论要占几条字幕条（作者写的换行会直接变成断行）
  2. 太长的评论，列出能放下的"截取片段"（编号如 3.1、3.2）：先按换行，再按句子，最后按分句
  3. 给每条评论打标记：硬标记（广告、联系方式、抄歌词、表情代码、字体缺字……默认不该选）和软标记（提醒）
  4. 找出重复和近似重复（复制粘贴体）
  5. 给出一份按点赞数凑数的"打包建议"（只用没有硬标记的；Agent 应该按主题重排，不要直接用）

用法：
  python -X utf8 prepare_comments.py --song OUT/song.json --out OUT/candidates.json
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cardlib as C  # noqa: E402

C.ensure_utf8()

LYRIC_HARD = 0.40     # 与歌词重合超过 40%：疑似整段抄歌词
LYRIC_SOFT = 0.20


def key_of(text):
    return re.sub(r"[^\w]", "", text)


def unit_levels(text):
    """从粗到细的切分方式：换行 → 句子 → 分句。"""
    levels = []
    if "\n" in text:
        levels.append(C.line_spans(text))
    s = C.sentence_spans(text)
    if len(s) >= 2:
        levels.append(s)
    c = C.clause_spans(text)
    if len(c) >= 2:
        levels.append(c)
    return levels


def piece_flags(lay, p, lyric_cov):
    hard, soft = C.detect_flags(p, None)
    miss = lay.missing_glyphs(p)
    if miss:
        hard.append("字体缺字:" + "".join(miss))
    if lyric_cov >= LYRIC_HARD:
        hard.append("疑似引用歌词(重合%d%%)" % round(lyric_cov * 100))
    return hard, soft


def make_pieces(text, spans, lay, cap, max_singles=8, max_runs=6):
    """返回第一个能产出结果的切分层级里的片段。片段两端会修剪掉悬空的逗号，不改任何文字。"""
    max_chars = cap * lay.max_chars_per_line
    for level in unit_levels(text):
        singles, runs, seen = [], [], set()
        for i in range(len(level)):
            for j in range(i, len(level)):
                a, b = level[i][0], level[j][1]
                if len(C.strip_ws(text[a:b])) > max_chars:
                    break
                piece = C.trim_piece(text[a:b])
                if not piece or piece == text or piece in seen:
                    continue
                lines = lay.plan_comment(piece, cap)
                if lines is None:
                    continue
                seen.add(piece)
                at = text.find(piece, a)
                cov = C.lyric_coverage(text, spans, at, at + len(piece)) if spans else 0.0
                hard, soft = piece_flags(lay, piece, cov)
                rec = {"start": at, "text": piece, "chars": len(C.strip_ws(piece)), "bands": len(lines),
                       "lines": lines, "break": C.break_quality(lines, piece), "hard": hard, "soft": soft,
                       "lyric_overlap": round(cov, 2)}
                (singles if i == j else runs).append(rec)
        if singles or runs:
            singles.sort(key=lambda p: p["start"])
            runs.sort(key=lambda p: -p["chars"])
            out = singles[:max_singles] + runs[:max_runs]
            out.sort(key=lambda p: (p["start"], -p["chars"]))
            return out
    return []


def short(text, n=60):
    t = text.replace("\n", " ⏎ ")
    return t if len(t) <= n else t[:n] + "…"


def main():
    ap = argparse.ArgumentParser(description="整理候选评论")
    ap.add_argument("--song", required=True, help="qq_fetch.py 生成的 song.json")
    ap.add_argument("--out", required=True, help="输出的 candidates.json")
    ap.add_argument("--bands", type=int, default=4, help="每张卡的字幕条数，默认 4")
    ap.add_argument("--max-bands-per-quote", type=int, default=4, help="单条评论最多占几条字幕条，默认 4（即整张卡）")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--aspect", default="3:4")
    ap.add_argument("--font")
    ap.add_argument("--show", type=int, default=40, help="终端里最多打印多少条（完整内容在 JSON 里），默认 40")
    args = ap.parse_args()

    with open(args.song, encoding="utf-8") as f:
        data = json.load(f)
    lay = C.Layout(width=args.width, aspect=args.aspect, font=args.font)
    cap = args.max_bands_per_quote

    cands = []
    for rank, c in enumerate(data["comments"], 1):
        text = c["text"]
        spans = [tuple(x) for x in c.get("lyric_spans", [])]
        cov = C.lyric_coverage(text, spans) if spans else 0.0
        lines = lay.plan_comment(text, cap)
        hard, soft = C.detect_flags(text, c.get("raw_text"))
        miss = lay.missing_glyphs(text)
        if miss:
            hard.append("字体缺字:" + "".join(miss))
        if cov >= LYRIC_HARD:
            hard.append("疑似引用歌词(重合%d%%)" % round(cov * 100))
        elif cov >= LYRIC_SOFT:
            soft.append("部分与歌词重合(%d%%)" % round(cov * 100))
        rec = {
            "ref": str(c["id"]), "rank": rank, "likes": c["likes"], "replies": c.get("replies", 0),
            "text": text, "chars": len(C.strip_ws(text)), "bands": len(lines) if lines else None,
            "lines": lines, "break": C.break_quality(lines, text), "hard": hard, "soft": soft,
            "lyric_overlap": round(cov, 2), "dup_of": None, "similar_to": None, "pieces": [],
        }
        if len(unit_levels(text)) and (lines is None or len(lines) >= 2):
            rec["pieces"] = make_pieces(text, spans, lay, cap)
            for k, p in enumerate(rec["pieces"], 1):
                p["ref"] = "%s.%d" % (rec["ref"], k)
                p.pop("start", None)
        cands.append(rec)

    # ---- 重复与近似重复：保留点赞高的 ----
    keys = {c["ref"]: key_of(c["text"]) for c in cands}
    for a in cands:
        for b in cands:
            if a is b or a["dup_of"] or b["dup_of"] or (a["likes"] < b["likes"]):
                continue
            ka, kb = keys[a["ref"]], keys[b["ref"]]
            if len(kb) < 6:
                continue
            if kb == ka or (len(kb) >= 8 and kb in ka):
                b["dup_of"] = a["ref"]
            elif len(ka) <= 160 and len(kb) <= 160:
                ratio = difflib.SequenceMatcher(None, ka, kb).ratio()
                if ratio >= 0.85:
                    b["dup_of"] = a["ref"]
                elif ratio >= 0.70 and not b["similar_to"]:
                    b["similar_to"] = a["ref"]

    # ---- 打包建议：只用没有硬标记、不重复的；整条能放就用整条，否则用最长的无硬标记片段 ----
    pool = []
    for c in cands:
        if c["dup_of"] or c["hard"]:
            continue
        if c["bands"]:
            pool.append({"ref": c["ref"], "bands": c["bands"], "likes": c["likes"]})
            continue
        ok = [p for p in c["pieces"] if not p["hard"]]
        if ok:
            best = max(ok, key=lambda p: p["chars"])
            pool.append({"ref": best["ref"], "bands": best["bands"], "likes": c["likes"]})
    pool.sort(key=lambda q: -q["likes"])
    suggestions = []
    while pool:
        first = pool.pop(0)
        chosen, need = [first], args.bands - first["bands"]
        for q in list(pool):
            if need <= 0:
                break
            if q["bands"] <= need and q["ref"].split(".")[0] != first["ref"].split(".")[0]:
                chosen.append(q)
                pool.remove(q)
                need -= q["bands"]
        if need == 0:
            suggestions.append({"name": "卡片%d" % (len(suggestions) + 1), "quotes": [q["ref"] for q in chosen],
                                "avg_likes": round(sum(q["likes"] for q in chosen) / len(chosen))})
        else:
            pool.extend(chosen[1:])
            pool.sort(key=lambda q: -q["likes"])

    result = {
        "layout": {"W": lay.W, "H": lay.H, "band_h": lay.band_h, "usable": lay.usable,
                   "size_min": lay.size_min, "size_max": lay.size_max,
                   "font": lay.font_path, "font_index": lay.font_index},
        "bands_per_card": args.bands, "lyric_check": data.get("lyric_check"),
        "candidates": cands, "suggested_cards": suggestions,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ---- 给人（和 Agent）看的表 ----
    s = data["song"]
    print("《%s》 %s" % (s["title"], s["artist_display"]))
    print("字体：%s   每张卡 %d 条字幕条，单条评论最多占 %d 条   歌词比对：%s" % (
        os.path.basename(lay.font_path), args.bands, cap, data.get("lyric_check")))
    print("")
    print("编号 | 赞 | 字数 | 占条 | 标记 | 内容")
    shown = 0
    for c in cands:
        if shown >= args.show:
            break
        shown += 1
        marks = []
        if c["dup_of"]:
            marks.append("重复于%s" % c["dup_of"])
        elif c["similar_to"]:
            marks.append("近似%s" % c["similar_to"])
        if c["hard"]:
            marks.append("【" + "；".join(c["hard"]) + "】")
        notes = [x for x in c["soft"] if not x.startswith(("分行", "已去除"))]
        if notes:
            marks.append("（" + "；".join(notes) + "）")
        if c["break"] == "midword":
            marks.append("非标点断行")
        if c["bands"] is None:
            marks.append("太长")
        print("%4s | %6s | %4d | %4s | %s | %s" % (c["ref"], c["likes"], c["chars"], c["bands"] or "-",
                                                  " ".join(marks), short(c["text"])))
        if c["bands"] is None and not c["hard"] and not c["dup_of"] and shown <= 25:
            for p in c["pieces"][:5]:
                print("   └ %5s | 占%d条 | %d字 | %s%s%s" % (
                    p["ref"], p["bands"], p["chars"], "【" + "；".join(p["hard"]) + "】" if p["hard"] else "",
                    "[非标点断行] " if p["break"] == "midword" else "", short(p["text"], 50)))
    if len(cands) > shown:
        print("  ……（还有 %d 条没打印，完整内容见 %s）" % (len(cands) - shown, args.out))
    usable = sum(1 for c in cands if c["bands"] and not c["hard"] and not c["dup_of"])
    print("")
    print("共 %d 条：整条可直接用 %d 条；太长需截取 %d 条；有硬标记 %d 条；重复 %d 条" % (
        len(cands), usable, sum(1 for c in cands if c["bands"] is None),
        sum(1 for c in cands if c["hard"]), sum(1 for c in cands if c["dup_of"])))
    print("按点赞的打包建议（共 %d 张，只是机械凑数，请按主题重排）：" % len(suggestions))
    for g in suggestions[:8]:
        print("  %s：%s  平均 %s 赞" % (g["name"], " + ".join(g["quotes"]), g["avg_likes"]))
    print("已保存：%s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
