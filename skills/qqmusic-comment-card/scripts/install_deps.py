# -*- coding: utf-8 -*-
"""把第三方库装进技能目录下的 .deps 文件夹（不动你电脑上已有的 Python 环境）。

装之前必须先征得用户同意。要装的东西：
  - qqmusic-api-python（固定 0.7.3，GPL-3.0 许可）：访问 QQ 音乐
  - Pillow：渲染图片
以及它们依赖的十几个常见组件。删掉 .deps 文件夹就等于卸载。

用法： python -X utf8 install_deps.py
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cardlib as C  # noqa: E402

C.ensure_utf8()


def main():
    if sys.version_info < (3, 10):
        print("当前 Python 是 %d.%d，QQ 音乐接口库需要 3.10 或更新。请先到 https://www.python.org/downloads/ 安装较新的版本。" % sys.version_info[:2])
        return 1
    print("将要安装到：%s" % C.DEPS_DIR)
    print("  - %s（GPL-3.0）\n  - %s" % (C.LIB_SPEC, C.PILLOW_SPEC))
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--target", C.DEPS_DIR,
           C.LIB_SPEC, C.PILLOW_SPEC]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print("安装失败。pip 的最后几行输出：")
        print("\n".join((proc.stdout + proc.stderr).strip().splitlines()[-12:]))
        return 1
    print("安装完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
