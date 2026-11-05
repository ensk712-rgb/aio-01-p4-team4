# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright>=1.48"]
# ///
"""예시 민원을 웹앱에서 자동 재생하고 GIF로 저장한다 (발표 자료용).

  python3 webapp/app.py &                                   # 먼저 웹앱을 띄운다 (TM_TARGET=vm 이면 VM n8n)
  uv run webapp/record_gif.py                               # 예시 전체 → webapp/gif/<id>.gif
  uv run webapp/record_gif.py ex1-qr ex4-urgent --url http://127.0.0.1:8091

ffmpeg가 필요하다. 같은 질문을 60초에 6번 넘게 보내면 TM-09 반복 요청 차단에 걸리므로 연달아 여러 번 녹화하지 않는다.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "gif"
SIZE = {"width": 1280, "height": 720}


def record(page_url: str, video_dir: Path, timeout_s: int) -> Path:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport=SIZE, device_scale_factor=1, locale="ko-KR",
                                  record_video_dir=str(video_dir), record_video_size=SIZE)
        page = ctx.new_page()
        page.goto(page_url)
        page.wait_for_selector('body[data-done="1"]', timeout=timeout_s * 1000)
        page.wait_for_timeout(2500)  # 마지막 화면을 잠깐 보여 준다
        video = page.video.path()
        ctx.close()
        browser.close()
    return Path(video)


def to_gif(video: Path, gif: Path, fps: int, width: int) -> None:
    filters = (f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];"
               "[a]palettegen=max_colors=160:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
    # 첫 0.6초(빈 화면 로딩)는 자른다
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.6", "-i", str(video), "-vf", filters, "-loop", "0", str(gif)],
                   check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="예시 id (비우면 전체)")
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--timeout", type=int, default=120, help="예시 하나 최대 초")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg가 없다")
    with urllib.request.urlopen(args.url + "/api/config", timeout=5) as res:
        cfg = json.load(res)
    examples = [e for e in cfg["examples"] if not args.ids or e["id"] in args.ids]
    if not examples:
        sys.exit(f"예시 없음: {args.ids}")
    print(f"대상 {cfg['target']} n8n ({cfg['n8n_host']}) · {len(examples)}개")
    OUT.mkdir(exist_ok=True)
    for ex in examples:
        with tempfile.TemporaryDirectory() as tmp:
            video = record(f"{args.url}/?example={ex['id']}&autoplay=1", Path(tmp), args.timeout)
            gif = OUT / f"{ex['id']}.gif"
            to_gif(video, gif, args.fps, args.width)
        print(f"  ✓ {gif.relative_to(OUT.parent.parent)}  {gif.stat().st_size / 1e6:.1f}MB  · {ex['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
