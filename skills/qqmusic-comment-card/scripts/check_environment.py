# -*- coding: utf-8 -*-
"""只读的环境检查：告诉你缺什么、怎么补。不会修改系统，也不会安装任何东西。

用法：
  python -X utf8 check_environment.py            # 基本检查
  python -X utf8 check_environment.py --network  # 再测一下能否连上 QQ 音乐
"""
from __future__ import annotations

import argparse
import os
import platform
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cardlib as C  # noqa: E402

C.ensure_utf8()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--network", action="store_true", help="测试能否连上 QQ 音乐相关域名（不带任何账号信息）")
    ap.add_argument("--font")
    args = ap.parse_args()
    py = "python" if platform.system() == "Windows" else "python3"
    problems = []

    v = sys.version_info
    ok = v >= (3, 10)
    print("[%s] Python %d.%d.%d（%s）" % ("OK" if ok else "缺", v.major, v.minor, v.micro, platform.system()))
    if not ok:
        problems.append("需要 Python 3.10 或更新版本（QQ 音乐接口库的要求）：https://www.python.org/downloads/")

    C.bootstrap_deps(front=True)
    try:
        import qqmusic_api  # noqa: F401
        print("[OK] QQ 音乐接口库 qqmusic_api 已可用")
    except ImportError:
        print("[缺] QQ 音乐接口库未安装")
        problems.append("征得用户同意后运行：%s -X utf8 \"%s\"（会装进技能目录下的 .deps，不动系统环境）" % (
            py, os.path.join(os.path.dirname(os.path.abspath(__file__)), "install_deps.py")))
    C.bootstrap_deps(front=False)
    try:
        import PIL
        print("[OK] Pillow %s" % PIL.__version__)
    except ImportError:
        print("[缺] Pillow 未安装（install_deps.py 会一并安装）")
        problems.append("Pillow 缺失：运行 install_deps.py，或 %s -m pip install Pillow" % py)

    try:
        path, idx = C.resolve_font(args.font)
        print("[OK] 中文字体：%s" % path)
    except FileNotFoundError as e:
        print("[缺] 中文字体")
        problems.append(str(e))

    if args.network:
        for url in ("https://y.qq.com/", "https://api.tencentmusic.com/", "https://y.gtimg.cn/"):
            try:
                urllib.request.urlopen(urllib.request.Request(url, headers=C.UA), timeout=15)
                print("[OK] 能连上 %s" % url)
            except urllib.error.HTTPError as e:
                print("[OK] 能连上 %s（返回 HTTP %s，说明网络是通的）" % (url, e.code))
            except Exception as e:  # noqa: BLE001
                print("[缺] 连不上 %s：%s" % (url, e))
                msg = "需要能访问 qq.com / tencentmusic.com 的本机环境；沙箱或受限网络里无法使用。"
                if msg not in problems:
                    problems.append(msg)

    print("")
    print("建议的 Python 命令：%s -X utf8 ..." % py)
    if problems:
        print("")
        print("还需要处理：")
        for p in problems:
            print("  - " + p)
        return 1
    print("环境就绪。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
