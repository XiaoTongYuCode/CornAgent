"""Record the real /rendering sequence as English, looping README GIFs.

Run after `make dev`: uv run --python 3.12 python scripts/record_readme_demo.py
Requires Node.js/npx and ffmpeg (including ffprobe). No model calls or app edits.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/screenshots"
BROWSER = ["npx", "--yes", "agent-browser@0.36.0", "--session", "cornagent-readme-recording"]
URL = "http://127.0.0.1:5173/rendering"
WIDTH, HEIGHT, FPS = 960, 560, 25

# Presentation-only CSS lives in the isolated recording browser, never in the app.
# The extra strip is cropped out. Its green frame marks the exact playback start,
# so loading frames and the surrounding workspace can never enter the GIF.
RECORD = r"""
(async () => {
const settings = document.querySelectorAll('.transition-preview__settings button');
if (document.documentElement.lang !== 'en') settings[1].click();
if (document.documentElement.dataset.theme !== '__THEME__') settings[2].click();
await new Promise(resolve => setTimeout(resolve, 300));
await document.fonts.ready;
const style = document.createElement('style');
style.textContent = `
  .transition-preview {
    position: fixed; inset: 0 0 24px; z-index: 9999;
    width: 100vw; height: calc(100vh - 24px); max-width: none;
    margin: 0; padding: 36px 44px; background: var(--bg);
  }
  .transition-preview__header p, .transition-preview__controls { display: none; }
  .transition-preview h1 { font-size: 20px; }
  .transition-preview__message { margin-top: 28px; overflow: hidden; }
`;
document.head.append(style);
const marker = document.createElement('div');
marker.style.cssText = 'position:fixed;inset:auto 0 0;height:24px;background:#ff00ff;z-index:10000';
document.body.append(marker);
const {createPreviewScript, initialPreviewParts} =
  await import('/src/previews/messagePreviewScript.ts');
const sequenceMs = createPreviewScript('sequence', 'recording', initialPreviewParts)
  .reduce((total, step) => total + step.duration, 0);
await new Promise(resolve => setTimeout(resolve, 300));
marker.style.background = '#00ff00';
document.querySelector('.transition-preview__playback').click();
await new Promise(resolve => setTimeout(resolve, sequenceMs + 3000));
const message = document.querySelector('.transition-preview__message');
return JSON.stringify({
  duration: (sequenceMs + 3000) / 1000,
  locale: document.documentElement.lang,
  theme: document.documentElement.dataset.theme,
  clipped: message.scrollHeight > message.clientHeight,
  text: message.innerText,
});
})()
"""


def run(args, *, source=None):
    result = subprocess.run(
        args, cwd=ROOT, input=source, capture_output=True, text=True, timeout=60, check=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def browser(*args, source=None):
    return run([*BROWSER, *args], source=source)


def decode_eval(value):
    value = json.loads(value)
    return json.loads(value) if isinstance(value, str) else value


def export_gif(video, target, duration):
    # Sample the synchronization strip, on the same 25 fps grid as the GIF.
    pixels = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps={FPS},format=rgb24,crop=1:1:0:{HEIGHT + 12}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=60,
    ).stdout
    start = next(
        i // 3 / FPS
        for i in range(0, len(pixels), 3)
        if pixels[i] < 40 and pixels[i + 1] > 220 and pixels[i + 2] < 40
    )
    filters = (
        # Chromium records full-range video; make RGB conversion explicit so
        # pale borders and dark backgrounds retain their original contrast.
        "scale=in_range=pc:out_range=pc,format=rgb24,"
        f"fps={FPS},crop={WIDTH}:{HEIGHT}:0:0,trim=start={start}:duration={duration},"
        "setpts=PTS-STARTPTS,split[a][b];"
        "[a]palettegen=stats_mode=full[p];"
        "[b][p]paletteuse=dither=none:diff_mode=rectangle"
    )
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(video),
            "-filter_complex",
            filters,
            "-loop",
            "0",
            str(target),
        ]
    )
    probe = json.loads(
        run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,size:stream=width,height",
                "-of",
                "json",
                str(target),
            ]
        )
    )
    assert probe["streams"][0] == {"width": WIDTH, "height": HEIGHT}, probe
    assert abs(float(probe["format"]["duration"]) - duration) < 0.1, probe
    assert b"NETSCAPE2.0\x03\x01\x00\x00" in target.read_bytes(), "GIF must loop forever"
    print(
        f"{target.relative_to(ROOT)}: {duration:.1f}s, "
        f"{int(probe['format']['size']) / 1024 / 1024:.2f} MiB",
        flush=True,
    )


def main():
    for command in ("npx", "ffmpeg", "ffprobe"):
        if not shutil.which(command):
            raise SystemExit(f"Missing required command: {command}")
    OUTPUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cornagent-readme-") as temporary:
        try:
            browser("open", URL)
            for theme in ("light", "dark"):
                print(f"Recording English sequence ({theme})…", flush=True)
                browser("set", "viewport", str(WIDTH), str(HEIGHT + 24))
                video = Path(temporary) / f"{theme}.webm"
                browser("record", "start", str(video), URL)
                result = decode_eval(
                    browser("eval", "--stdin", source=RECORD.replace("__THEME__", theme))
                )
                browser("record", "stop")
                assert result["locale"] == "en" and result["theme"] == theme, result
                assert not result["clipped"], result
                assert "Verification results" in result["text"], result
                export_gif(video, OUTPUT / f"rendering-{theme}.gif", result["duration"])
        finally:
            browser("close")


if __name__ == "__main__":
    main()
