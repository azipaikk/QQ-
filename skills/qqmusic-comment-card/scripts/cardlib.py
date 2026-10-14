# -*- coding: utf-8 -*-
"""qqmusic-comment-card 的共享工具。

只放"确定性"的部分：依赖目录、评论文字规范化与标记检测、断句、字体查找、版面计算。
需要判断的事（选哪几条评论）交给 Agent。
"""
from __future__ import annotations

import os
import re
import struct
import sys
import urllib.request
from functools import lru_cache

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPS_DIR = os.path.join(SKILL_DIR, ".deps")          # 第三方库只装在这里，不动用户的 Python 环境
LIB_SPEC = "qqmusic-api-python==0.7.3"               # 固定版本：发布一个多月、依赖审计无已知漏洞
PILLOW_SPEC = "Pillow>=9.2"
UA = {"User-Agent": "Mozilla/5.0"}


def ensure_utf8():
    """Windows 上管道输出默认可能是 GBK，遇到特殊符号会报错，统一成 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def bootstrap_deps(front=False):
    """把技能目录下的 .deps 加进 import 路径。
    front=True：放最前面（QQ 音乐库及其依赖优先用这里的版本，避免和系统里的旧版本冲突）。
    front=False：放最后面（Pillow 等优先用系统已装的）。"""
    if not os.path.isdir(DEPS_DIR):
        return
    if DEPS_DIR in sys.path:
        sys.path.remove(DEPS_DIR)
    if front:
        sys.path.insert(0, DEPS_DIR)
    else:
        sys.path.append(DEPS_DIR)


bootstrap_deps(front=False)


def download(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def image_size(data):
    """不依赖 Pillow，直接从文件头读出 PNG / JPEG 的宽高；读不出返回 None。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + seg_len
    return None


# --------------------------------------------------------------------------
# 评论文字：规范化
# --------------------------------------------------------------------------
END_PUNCT = "。！？!?；…"
CLOSERS = "”’」』）)》】\"'"
OPENERS = "“‘「『（(《【"
NO_LINE_START = "，。！？、；：,.!?;:”’」』）)》】…—"
SOFT_BREAK = "，、；：。！？,;:"
BINDS_LEFT = "的了着过地得吗呢吧啊么们"      # 这些字紧贴前一个字，不要放在行首
PARTICLES = "的了着过地得"                    # 在它们后面断行比较自然
LEADERS = "在于对把被从向与和及而但却并因所"  # 在它们前面断行比较自然
TRIM_EDGE = "，、；：,;: "

# 零宽字符、方向控制符、韩文填充符等：看不见，但会撑出空白或空行
INVISIBLE_RE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\u00ad\u180e\u3164\u115f\u1160\u2800]")
# 表情符号（字体里没有这些字形）。★☆ 不算，它们常见于中文评论里，字体通常能显示
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u2604\u2607-\u27BF\u2B50\u2B55\u231A\u231B\u23E9-\u23F3\ufe0f\u20e3]")
_NOSPACE_BEFORE = "，。！？、；：）”’》】…,.!?;:)"
_NOSPACE_AFTER = "（“‘《【("


def normalize_comment(raw):
    """把评论整理成适合排字幕的样子。只做"符号层面"的整理，不改任何文字：

    - 被转义成字面量的换行（反斜杠加 n）还原成真换行
    - 去掉看不见的字符和表情符号（字体显示不了）
    - 折叠多余空格；去掉全角标点前后的空格
    - 保留换行：评论里的换行是作者有意的"诗行"，后面会直接变成字幕条的断行
    """
    s = raw or ""
    s = s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = INVISIBLE_RE.sub("", s)
    s = EMOJI_RE.sub("", s)
    s = s.replace("\u00a0", " ").replace("\u3000", " ")
    out = []
    for ln in s.split("\n"):
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        ln = re.sub(" +(?=[%s])" % re.escape(_NOSPACE_BEFORE), "", ln)
        ln = re.sub("(?<=[%s]) +" % re.escape(_NOSPACE_AFTER), "", ln)
        if ln:
            out.append(ln)
    return "\n".join(out)


def strip_ws(s):
    return re.sub(r"\s+", "", s or "")


def has_emoji(raw):
    return bool(EMOJI_RE.search(raw or ""))


# --------------------------------------------------------------------------
# 评论标记：给 Agent 的提示，不是最终判决
# --------------------------------------------------------------------------
BRACKET_CODE_RE = re.compile(r"\[em\][^\[\]]*\[/em\]|\[[^\[\]\s]{1,8}\]")
CONTACT_RE = re.compile(
    r"https?://|www\.|(?<![\d.])\d{7,}(?!\d)|[Qq][Qq]\s*[:：]?\s*\d{5,}|[\w.+-]+@[\w-]+\.\w+|[Vv][Xx]|微信号|加微|加我|私聊|私信")
AD_WORDS = ("点击", "链接", "下方", "⬇", "试试手气", "抽到", "SSR", "歌词卡", "语音祝福", "领取", "福利", "扫码",
            "抽奖", "兑换", "优惠", "谁要", "一个个发", "下载", "转发")
AI_STYLE = ("好评用户", "中立用户", "综上所述", "值得一提的是", "不仅仅是一首歌")
NAME_HINT_RE = re.compile(r"(?:他叫|她叫|名叫|名字叫|叫做)[\u4e00-\u9fff]{2,4}")   # 只是提醒：可能提到了私人姓名


def detect_flags(text, raw=None):
    """返回 (hard, soft)。hard = 默认不该选（Agent 要选必须有理由）；soft = 提醒。"""
    hard, soft = [], []
    if BRACKET_CODE_RE.search(text):
        hard.append("含表情/音频代码")
    if CONTACT_RE.search(text):
        hard.append("含联系方式或链接")
    if any(w in text for w in AD_WORDS):
        hard.append("疑似广告/推广")
    if raw is not None:
        blank = sum(1 for ln in re.split(r"\\n|\n", raw) if not INVISIBLE_RE.sub("", ln).strip())
        if blank >= 3:
            hard.append("疑似占位刷屏")
        if has_emoji(raw):
            soft.append("已去除表情符号")
    if any(w in text for w in AI_STYLE):
        soft.append("疑似AI腔")
    if NAME_HINT_RE.search(text):
        soft.append("可能提到具体人名")
    n_lines = text.count("\n") + 1
    if n_lines >= 2:
        soft.append("分行%d句" % n_lines)
    return hard, soft


# --------------------------------------------------------------------------
# 歌词比对：识别"整段抄歌词"的评论（歌词有版权）。歌词只在内存里用，不写入任何文件
# --------------------------------------------------------------------------
def _core_chars(s):
    """只留文字和数字，返回 (字符串, 每个字符在原文里的下标)。"""
    chars, idx = [], []
    for i, ch in enumerate(s):
        if ch.isalnum():
            chars.append(ch)
            idx.append(i)
    return "".join(chars), idx


def lyric_shingles(lyric_text, n=4):
    body = re.sub(r"\[[^\]]*\]", "", lyric_text or "")         # 去掉 [00:12.34] 之类的时间标签
    core, _ = _core_chars(body)
    return {core[i:i + n] for i in range(len(core) - n + 1)}


def lyric_spans(text, shingles, n=4):
    """评论里与歌词重合的字符区间 [(a, b)]。只存位置，不存歌词内容。"""
    if not shingles:
        return []
    core, idx = _core_chars(text)
    covered = set()
    for i in range(len(core) - n + 1):
        if core[i:i + n] in shingles:
            covered.update(idx[i:i + n])
    spans, start, prev = [], None, None
    for k in sorted(covered):
        if start is None:
            start = prev = k
        elif k - prev <= 3:             # 中间隔着标点和空格也算连续
            prev = k
        else:
            spans.append((start, prev + 1))
            start = prev = k
    if start is not None:
        spans.append((start, prev + 1))
    return spans


def lyric_coverage(text, spans, a=0, b=None):
    """text[a:b] 里有多大比例的文字与歌词重合（0~1）。"""
    b = len(text) if b is None else b
    core = [i for i in range(a, b) if text[i].isalnum()]
    if not core:
        return 0.0
    hit = sum(1 for i in core if any(s <= i < e for s, e in spans))
    return hit / len(core)


# --------------------------------------------------------------------------
# 断句
# --------------------------------------------------------------------------
def sentence_spans(text):
    """按句末标点切句，返回 [(start, end)]。句末标点后面的引号、括号归前一句。"""
    spans = []
    n = len(text)
    start = 0
    i = 0
    while i < n:
        ch = text[i]
        if ch in END_PUNCT:
            j = i + 1
            while j < n and (text[j] in END_PUNCT or text[j] in CLOSERS):
                j += 1
            tail = text[i + 1:j]
            if ch in "？！?!" and tail and tail[-1] in "”’」』" and j < n and text[j] not in OPENERS:
                i = j
                continue
            spans.append((start, j))
            start = j
            i = j
            continue
        i += 1
    if start < n and text[start:n].strip():
        spans.append((start, n))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def line_spans(text):
    out, pos = [], 0
    for ln in text.split("\n"):
        if ln.strip():
            out.append((pos, pos + len(ln)))
        pos += len(ln) + 1
    return out


def clause_spans(text):
    """更细的分句：在 ，、；：和空格处切开。很多评论没有标点，用空格当停顿。"""
    spans, start, n = [], 0, len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch in "，、；：。！？…\n" or ch == " ":
            j = i + 1
            if ch != " ":
                while j < n and (text[j] in CLOSERS or text[j] in "，、；：。！？…"):
                    j += 1
            if text[start:j].strip():
                spans.append((start, j))
            start = j
            i = j
            continue
        i += 1
    if start < n and text[start:n].strip():
        spans.append((start, n))
    return spans


def trim_piece(piece):
    """截取片段时修剪两端：去掉悬空的逗号等，以及落单的收尾引号/开头引号。不动任何文字。"""
    p = piece.strip(TRIM_EDGE + "\n")
    p = p.lstrip(CLOSERS + TRIM_EDGE)
    p = p.rstrip(OPENERS + TRIM_EDGE)
    return p.strip()


# --------------------------------------------------------------------------
# 字体
# --------------------------------------------------------------------------
def _font_candidates():
    win = os.environ.get("WINDIR", "C:/Windows").replace("\\", "/") + "/Fonts/"
    return [
        (win + "msyhbd.ttc", 0), (win + "msyh.ttc", 0), (win + "Dengb.ttf", 0),
        (win + "simhei.ttf", 0), (win + "simsun.ttc", 0),
        ("/System/Library/Fonts/PingFang.ttc", 0),
        ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
        ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
        ("/Library/Fonts/Arial Unicode.ttf", 0),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 2),
        ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
        ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),
    ]


def resolve_font(explicit=None):
    """返回 (路径, 字体序号)。用户指定的字体不存在时直接报错，不悄悄换。"""
    if explicit:
        if not os.path.exists(explicit):
            raise FileNotFoundError("指定的字体不存在：%s" % explicit)
        return explicit, 0
    env = os.environ.get("QQCARD_FONT", "").strip()
    if env:
        if not os.path.exists(env):
            raise FileNotFoundError("环境变量 QQCARD_FONT 指向的字体不存在：%s" % env)
        return env, 0
    for path, idx in _font_candidates():
        if os.path.exists(path):
            return path, idx
    raise FileNotFoundError(
        "没有找到可用的中文字体。请用 --font 指定一个中文字体文件（.ttf/.ttc/.otf），"
        "或设置环境变量 QQCARD_FONT。"
    )


@lru_cache(maxsize=128)
def load_font(path, index, size):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(path, size, index=index)
    except Exception:  # noqa: BLE001
        return ImageFont.truetype(path, size, index=0)


# --------------------------------------------------------------------------
# 版面
# --------------------------------------------------------------------------
def parse_aspect(s):
    try:
        a, b = s.replace("x", ":").split(":")
        return float(a), float(b)
    except Exception:  # noqa: BLE001
        raise ValueError("比例格式应为 3:4 这样的写法，收到：%r" % s)


class Layout:
    """3:4 版式：主图约 70%，每条字幕条约 7.5%，条间距为 0。"""

    BAND_FRAC = 0.075

    def __init__(self, width=1440, aspect="3:4", font=None):
        aw, ah = parse_aspect(aspect)
        self.W = int(width)
        self.H = round(self.W * ah / aw)
        self.band_h = round(self.H * self.BAND_FRAC)
        self.pad_x = round(self.W * 0.045)
        self.usable = self.W - 2 * self.pad_x
        self.size_max = round(self.band_h * 0.44)
        self.size_min = round(self.band_h * 0.36)
        self.font_path, self.font_index = resolve_font(font)
        self.max_chars_per_line = int(self.usable // self.size_min) + 2   # 一行最多放多少字的上限，用来剪枝

    def main_h(self, nbands):
        return self.H - self.band_h * nbands

    def font(self, size):
        return load_font(self.font_path, self.font_index, int(size))

    @staticmethod
    def stroke(size):
        return max(2, round(size * 0.06))

    def line_width(self, text, size):
        return self.font(size).getlength(text) + 2 * self.stroke(size)

    def fit_size(self, text):
        """这一行能放进单条字幕条的最大字号；放不下返回 None。"""
        sizes = list(range(self.size_max, self.size_min, -2)) + [self.size_min]
        for s in sizes:
            if self.line_width(text, s) <= self.usable:
                return s
        return None

    @staticmethod
    def _boundary_cost(a, b):
        """相邻两行 a、b 之间断开的代价；不允许这样断返回 None。"""
        if not a or not b or a[-1] in OPENERS or b[0] in NO_LINE_START:
            return None
        cost = 0.0
        tail = a[-2] if (a[-1] in CLOSERS and len(a) > 1) else a[-1]
        if tail not in SOFT_BREAK:
            cost += 0.80                                   # 不在标点后断：强烈不推荐
            if b[0] in BINDS_LEFT:
                cost += 0.50                               # 把"的/了/着"留到下一行开头：更差
            if a[-1] in PARTICLES or b[0] in LEADERS:
                cost -= 0.25                               # 在"的/了"后或"在/把/但"前断：相对自然
        return cost

    def _split_n(self, text, n):
        """把 text 分成恰好 n 行，每行都放得下单条字幕条；返回得分最好的分法，没有则 None。"""
        L, smin = len(text), self.size_min
        maxc = self.max_chars_per_line
        if L > maxc * n:
            return None
        fit_cache = {}

        def fit(s_, e_):
            k = (s_, e_)
            if k not in fit_cache:
                seg = text[s_:e_].strip()
                fit_cache[k] = self.fit_size(seg) if seg else None
            return fit_cache[k]

        def cuts_iter(start, remaining, cuts):
            if remaining == 1:
                if fit(start, L) is not None:
                    yield cuts
                return
            for e_ in range(start + 2, L - 2 * (remaining - 1) + 1):
                if fit(start, e_) is None:
                    break                                  # 行越长越放不下，后面不用再试
                if L - e_ > maxc * (remaining - 1):
                    continue                               # 剩下的字太多，后面的行放不下
                yield from cuts_iter(e_, remaining - 1, cuts + [e_])

        best, best_score = None, None
        for cuts in cuts_iter(0, n, []):
            bounds = [0] + cuts + [L]
            lines = [text[bounds[k]:bounds[k + 1]].strip() for k in range(n)]
            if any(not ln for ln in lines):
                continue
            cost, ok = 0.0, True
            for k in range(n - 1):
                c = self._boundary_cost(lines[k], lines[k + 1])
                if c is None:
                    ok = False
                    break
                cost += c
            if not ok:
                continue
            widths = [self.line_width(ln, smin) for ln in lines]
            score = (max(widths) - min(widths)) / self.usable + cost   # 各行尽量等长
            if min(len(ln) for ln in lines) < 6:
                score += 0.30                              # 避免一行只剩几个字
            sizes = [self.fit_size(ln) for ln in lines]
            score -= 0.5 * (min(sizes) - smin) / max(1, self.size_max)
            if best_score is None or score < best_score:
                best, best_score = lines, score
        return best

    def plan_quote(self, text, max_lines=2):
        """把一段没有换行的文字分成 1~max_lines 行。先试 1 行，再 2 行、3 行……尽量用最少的条数。"""
        text = text.strip()
        if self.fit_size(text) is not None:
            return [text]
        for n in range(2, max_lines + 1):
            lines = self._split_n(text, n)
            if lines:
                return lines
        return None

    def plan_comment(self, text, max_lines=4):
        """评论的断行：作者写的换行直接当字幕条的断行，每一行再按需要拆成 1~2 条。放不下返回 None。"""
        if "\n" not in text:
            return self.plan_quote(text, max_lines)
        segs = [s.strip() for s in text.split("\n") if s.strip()]
        lines = []
        for k, seg in enumerate(segs):
            room = max_lines - len(lines) - (len(segs) - k - 1)   # 给后面每一行至少留 1 条
            if room < 1:
                return None
            p = self.plan_quote(seg, min(2, room))
            if p is None:
                return None
            lines += p
        return lines if len(lines) <= max_lines else None

    def missing_glyphs(self, text):
        try:
            f = self.font(self.size_max)
            nd = f.getmask("\U0010FFFF")
            nd_key = (nd.size, nd.tobytes())
            miss = []
            for ch in sorted(set(text)):
                if ch.isspace():
                    continue
                m = f.getmask(ch)
                if (m.size, m.tobytes()) == nd_key:
                    miss.append(ch)
            return miss
        except Exception:  # noqa: BLE001
            return []


def break_quality(lines, text):
    """占 2 条以上时：每个断点要么在标点后，要么本来就是作者的换行 → punct；否则 midword。单条返回 None。"""
    if not lines or len(lines) < 2:
        return None
    pos = 0
    for a in lines[:-1]:
        at = text.find(a, pos)
        if at < 0:
            return "midword"
        end = at + len(a)
        pos = end
        tail = a[-2] if (a[-1] in CLOSERS and len(a) > 1) else a[-1]
        author_break = text[end:].lstrip(" ").startswith("\n")
        if tail not in SOFT_BREAK and not author_break:
            return "midword"
    return "punct"


def display_artists(names, limit=3):
    names = [n for n in (names or []) if n]
    s = " / ".join(names[:limit])
    return s + (" 等" if len(names) > limit else "")


def safe_name(s, limit=40):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s or "").strip(" ._")
    return (s or "song")[:limit]
