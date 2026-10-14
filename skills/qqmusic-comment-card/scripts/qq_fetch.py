# -*- coding: utf-8 -*-
"""从 QQ 音乐取一首歌的封面和热门评论。

用法：
  python -X utf8 qq_fetch.py search "晴天 周杰伦"
  python -X utf8 qq_fetch.py fetch --keyword "晴天 周杰伦" --song-id 97773 --out-dir OUT --pages 6

不需要登录，不需要任何 Key。评论者的昵称、头像、用户标识（nick / avatar / encrypt_uin）一律不读取、不保存。
歌词只在内存里用来识别"整段抄歌词"的评论，不写入任何文件。
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cardlib as C  # noqa: E402

C.ensure_utf8()
C.bootstrap_deps(front=True)

try:
    from qqmusic_api import Client
except ImportError:
    print("没有找到 QQ 音乐接口库 qqmusic_api。请先征得用户同意，再运行 install_deps.py 安装。")
    sys.exit(2)

VERSION_WORDS = ("live", "dj", "remix", "伴奏", "纯音乐", "铃声", "cover", "翻唱", "钢琴", "女声", "男声",
                 "降调", "升调", "加速", "慢速", "抖音", "片段", "混音", "电音", "重制")
COVER_SIZES = (1500, 1200, 800, 500)


def artists_of(song):
    return [getattr(s, "name", "") for s in (getattr(song, "singer", None) or [])]


def title_of(song):
    return getattr(song, "title", "") or getattr(song, "name", "") or ""


def album_of(song):
    a = getattr(song, "album", None)
    return getattr(a, "name", "") if a else ""


async def with_timeout(coro, seconds):
    return await asyncio.wait_for(coro, seconds)


# ------------------------------------------------------------------ search
async def do_search(args):
    async with Client() as client:
        resp = await with_timeout(client.search.search_by_type(args.keyword, num=args.limit), 90)
    songs = list(getattr(resp, "song", None) or [])
    if not songs:
        print("没有搜到《%s》。请换个写法，或补上歌手名。" % args.keyword)
        return 3
    tokens = [t for t in re.split(r"\s+", args.keyword.strip()) if t]
    rows, recommended = [], None
    for i, s in enumerate(songs, 1):
        names = artists_of(s)
        title = title_of(s)
        tags = [w for w in VERSION_WORDS if w in title.lower()]
        match = any(t in "/".join(names) for t in tokens)
        if recommended is None and match and not tags:
            recommended = i
        rows.append({"index": i, "song_id": s.id, "mid": getattr(s, "mid", ""), "title": title,
                     "artists": names, "album": album_of(s), "version_tags": tags, "artist_match": match})
    print("搜索「%s」的结果（按接口返回顺序）：" % args.keyword)
    for r in rows:
        marks = []
        if r["artist_match"]:
            marks.append("歌手匹配")
        if r["version_tags"]:
            marks.append("可能不是原版：" + "/".join(r["version_tags"]))
        if r["index"] == recommended:
            marks.append("★推荐")
        print("  %d. 《%s》 %s  专辑：%s  歌曲ID=%s  %s" % (
            r["index"], r["title"], " / ".join(r["artists"]), r["album"] or "（无）", r["song_id"],
            ("[" + "；".join(marks) + "]") if marks else ""))
    if not any(r["artist_match"] for r in rows):
        print("⚠ 候选里没有歌手名与你输入相匹配的歌曲：可能没有原唱版权，搜到的多是翻唱。请向用户确认。")
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print("已保存：%s" % args.out)
    return 0


# ------------------------------------------------------------------ fetch
def fetch_cover(song, out_dir):
    attempts, saved = [], None
    for size in COVER_SIZES:
        try:
            url = song.cover_url(size)
        except Exception as e:  # noqa: BLE001
            attempts.append({"size": size, "ok": False, "error": str(e)[:60]})
            continue
        if not url:
            attempts.append({"size": size, "ok": False, "error": "没有封面信息"})
            break
        try:
            data = C.download(url)
            got = C.image_size(data)
            attempts.append({"size": size, "ok": True, "pixels": list(got) if got else None})
            ext = ".png" if data[:4] == b"\x89PNG" else ".jpg"
            path = os.path.join(out_dir, "cover" + ext)
            with open(path, "wb") as f:
                f.write(data)
            saved = (path, list(got) if got else None, url)
            break                               # 从大到小，第一个成功的就是最大的
        except Exception as e:  # noqa: BLE001
            attempts.append({"size": size, "ok": False, "error": str(e)[:60]})
    return saved, attempts


async def do_fetch(args):
    os.makedirs(args.out_dir, exist_ok=True)
    async with Client() as client:
        song = None
        if args.keyword:
            res = await with_timeout(client.search.search_by_type(args.keyword, num=20), 90)
            for s in (getattr(res, "song", None) or []):
                if int(s.id) == int(args.song_id):
                    song = s
                    break
        if song is None:
            detail = await with_timeout(client.song.get_detail(int(args.song_id)), 60)
            song = detail.track
        print("《%s》 %s  歌曲ID=%s" % (title_of(song), " / ".join(artists_of(song)), song.id))

        saved, attempts = fetch_cover(song, args.out_dir)

        req = client.comment.get_hot_comments(int(song.id), page_size=15)
        try:
            pages = await with_timeout(req.collect(limit=args.pages), 45 * args.pages)
        except AttributeError:
            pages = [await with_timeout(req, 60)]

        shingles, lyric_status = None, "已跳过（--no-lyric-check）"
        if not args.no_lyric_check:
            try:
                ly = await with_timeout(client.lyric.get_lyric(song.mid), 40)
                shingles = C.lyric_shingles(getattr(ly, "lyric", "") or "")
                lyric_status = "已比对（歌词只在内存里使用，没有保存）" if shingles else "歌词为空，未比对"
            except Exception as e:  # noqa: BLE001
                lyric_status = "歌词获取失败，未比对（%s）" % str(e)[:60]

    seen, comments = set(), []
    total_hot = None
    for p in pages:
        total_hot = getattr(p, "total", total_hot)
        for c in (getattr(p, "comments", None) or []):
            cmid = str(getattr(c, "cmid", "") or "")
            if cmid in seen:
                continue
            seen.add(cmid)
            raw = getattr(c, "content", "") or ""
            text = C.normalize_comment(raw)
            if not text:
                continue
            comments.append({
                "comment_id": cmid, "text": text, "raw_text": raw,
                "likes": getattr(c, "praise_num", 0) or 0, "replies": getattr(c, "reply_cnt", 0) or 0,
                "lyric_spans": C.lyric_spans(text, shingles) if shingles else [],
                # 故意不保存 nick / avatar / encrypt_uin 等评论者信息
            })
    comments.sort(key=lambda c: -c["likes"])
    for i, c in enumerate(comments, 1):
        c["id"] = i

    if not comments:
        print("这首歌没有取到热门评论。")
        return 3
    out = {
        "schema": 1,
        "source": "QQ音乐（非官方接口，qqmusic-api-python）",
        "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "lyric_check": lyric_status,
        "total_hot_comments": total_hot,
        "song": {
            "id": int(song.id), "mid": getattr(song, "mid", ""), "title": title_of(song),
            "artists": artists_of(song), "artist_display": C.display_artists(artists_of(song)),
            "album": album_of(song), "cover_url": saved[2] if saved else None,
            "cover_file": os.path.abspath(saved[0]) if saved else None,
            "cover_size": saved[1] if saved else None, "cover_attempts": attempts,
        },
        "comments": comments,
    }
    path = os.path.join(args.out_dir, "song.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("热门评论：取到 %d 条（该歌热评总数 %s），点赞最高 %s，最低 %s" % (
        len(comments), total_hot, comments[0]["likes"], comments[-1]["likes"]))
    if saved:
        print("封面：%s  像素 %s" % (saved[0], "x".join(map(str, saved[1])) if saved[1] else "未知"))
    else:
        print("⚠ 没能下载封面，渲染时会用纯色背景加歌名代替。可用 --cover 手动指定封面图。")
    print("歌词比对：%s" % lyric_status)
    print("已保存：%s" % path)
    return 0


def main():
    ap = argparse.ArgumentParser(description="QQ 音乐：搜歌、取封面和热门评论")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="按歌名（可加歌手）搜索，列出候选歌曲")
    s.add_argument("keyword")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--out", help="把候选列表另存为 JSON")
    s.set_defaults(func=do_search)
    f = sub.add_parser("fetch", help="取封面和热门评论，写成 song.json")
    f.add_argument("--song-id", required=True, type=int)
    f.add_argument("--keyword", help="搜歌时用的关键词；提供后会优先从搜索结果里取歌曲信息（封面信息更完整）")
    f.add_argument("--out-dir", required=True)
    f.add_argument("--pages", type=int, default=6, help="取多少页热评，每页约 15 条，默认 6")
    f.add_argument("--no-lyric-check", action="store_true", help="不做歌词比对")
    f.set_defaults(func=do_fetch)
    args = ap.parse_args()
    try:
        return asyncio.run(args.func(args))
    except Exception as e:  # noqa: BLE001
        name = type(e).__name__
        print("出错了：%s：%s" % (name, str(e)[:300]))
        if "ConnectionError" in name or "gaierror" in str(e):
            print("看起来是网络问题：需要能访问 qq.com 和 tencentmusic.com 的本机环境。")
        errs = getattr(e, "errors", None)
        if callable(errs):
            try:
                print("校验失败的字段：%s（接口返回格式可能变了，请把这行告诉维护者）" % [(x.get("loc"), x.get("type")) for x in errs()[:4]])
            except Exception:  # noqa: BLE001
                pass
        return 2


if __name__ == "__main__":
    sys.exit(main())
