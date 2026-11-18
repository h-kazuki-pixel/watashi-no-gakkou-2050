#!/usr/bin/env python3
"""アプリに同梱する書体（woff2）を、使う文字だけにしぼって作る。

    pip install -r tools/requirements-fonts.txt
    python3 tools/build_fonts.py <TTF のフォルダ>

TTF のフォルダには BIZUDPGothic-Regular.ttf、BIZUDPGothic-Bold.ttf、YuseiMagic-Regular.ttf を置く
（google/fonts の ofl/bizudpgothic と ofl/yuseimagic。TTF はリポジトリに入れない）。
出力は app/fonts/ の3つの woff2。

収録する文字：
- app/index.html、app/css/ の全ファイル、app/js/*.js に出てくる全文字（制御文字を除く）
- app/data/*.js の "name" の値の全文字（sample.js は引用符なしの name: も拾う）
- U+0020〜U+007E、U+3000〜U+30FF、U+FF01〜U+FF5E
同じ入力なら同じ文字集合になるよう、文字は並べ替えて pyftsubset に渡す。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
OUT = APP / "fonts"
FONTS = ["BIZUDPGothic-Regular", "BIZUDPGothic-Bold", "YuseiMagic-Regular"]
RANGES = [(0x20, 0x7E), (0x3000, 0x30FF), (0xFF01, 0xFF5E)]
# "name": "…" と name: "…"（JSON の文字列。\" や \uXXXX のエスケープも読む）
NAME_RE = re.compile(r'(?:"name"|\bname)\s*:\s*("(?:[^"\\]|\\.)*")')


def _keep(ch: str) -> bool:
    return not unicodedata.category(ch).startswith("C")  # 制御文字・書式文字・サロゲートなどを除く


def collect_chars(app: Path = APP) -> list[str]:
    chars: set[str] = set()
    files = [app / "index.html"]
    files += sorted(p for p in (app / "css").rglob("*") if p.is_file())
    files += sorted((app / "js").glob("*.js"))
    for p in files:
        chars.update(p.read_text(encoding="utf-8"))
    for p in sorted((app / "data").glob("*.js")):
        for m in NAME_RE.finditer(p.read_text(encoding="utf-8")):
            chars.update(json.loads(m.group(1)))
    for lo, hi in RANGES:
        chars.update(chr(c) for c in range(lo, hi + 1))
    return sorted((c for c in chars if _keep(c)), key=ord)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ttf_dir", type=Path, help="元の TTF を置いたフォルダ")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    from fontTools import subset  # pyftsubset の本体

    chars = collect_chars()
    unicodes = ",".join("U+%04X" % ord(c) for c in chars)
    args.out.mkdir(parents=True, exist_ok=True)
    total = 0
    for name in FONTS:
        src = args.ttf_dir / (name + ".ttf")
        if not src.exists():
            print("見つからない:", src, file=sys.stderr)
            return 1
        dst = args.out / (name + ".woff2")
        subset.main([str(src), "--unicodes=" + unicodes, "--layout-features=*",
                     "--flavor=woff2", "--output-file=" + str(dst)])
        size = dst.stat().st_size
        total += size
        print(f"{dst.relative_to(ROOT)}  {size:,} バイト")
    print(f"合計 {total:,} バイト、収録 {len(chars):,} 文字")
    return 0


if __name__ == "__main__":
    sys.exit(main())
