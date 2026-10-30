"""Real 9:16 renders. Vector artwork is rasterized only at the video boundary."""
from __future__ import annotations
from functools import lru_cache
import io
import math
from pathlib import Path
import random
import subprocess
from PIL import Image, ImageDraw, ImageFont
from .config import ROOT, WORK, font
from .media import ffmpeg, duration, has_audio, video_filter, output_args, check_cancel

HEART_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="90" viewBox="0 0 100 90"><path fill="#ef849b" d="M50 85 C40 74 5 50 5 27 C5 2 36 -2 50 19 C64 -2 95 2 95 27 C95 50 60 74 50 85 Z"/></svg>'


@lru_cache(maxsize=32)
def _font(size, style):
    return ImageFont.truetype(font(style), size)


def wrap(draw, text, face, width):
    result = []
    for paragraph in str(text).splitlines():
        line = ""
        for word in paragraph.split():
            test = (line + " " + word).strip()
            if draw.textlength(test, font=face) <= width:
                line = test
            else:
                if line:
                    result.append(line)
                line = word
        result.append(line)
    return result


def _text_center(draw, lines, face, center, y, fill, spacing=18, stroke=0):
    for line in lines:
        box = draw.textbbox((0, 0), line, font=face, stroke_width=stroke)
        h = box[3]-box[1]
        draw.text((center, y), line, font=face, fill=fill, anchor="mt", stroke_width=stroke, stroke_fill="#15202b")
        y += h + spacing
    return y


def poem_card(data: dict, path: Path):
    import cairosvg
    image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    # Upper ribbon/title; all text is kept away from Shorts right-side controls.
    ribbon = str(data.get("ribbon", "RUANG MERASA")).upper()
    title_font = _font(49, "bold")
    title_lines = wrap(d, ribbon, title_font, 810)[:2]
    ribbon_h = 68 + len(title_lines)*67
    d.rounded_rectangle((74, 215, 1006, 215+ribbon_h), radius=10, fill=(244, 188, 100, 245))
    d.polygon([(74, 215+ribbon_h-5), (40, 215+ribbon_h+35), (74, 215+ribbon_h+35)], fill="#b87831")
    _text_center(d, title_lines, title_font, 540, 248, "#172335", 16)
    face = _font(54, "serif")
    lines = []
    for line in data.get("lines", [])[:5]:
        lines.extend(wrap(d, line, face, 825))
    height = len(lines)*80 + 135
    top = max(625, 970-height//2)
    d.rounded_rectangle((85, top, 995, top+height), radius=30, fill=(9, 20, 34, 158))
    _text_center(d, lines, face, 540, top+65, "#fff9ec", 27, 1)
    signature = str(data.get("signature", "ruang miring"))[:35]
    sf = _font(38, "italic")
    while d.textlength(signature, font=sf) > 670:
        signature = signature[:-1]
    d.text((955, 1570), signature, font=sf, fill="#fff8e9", anchor="rs", stroke_width=1, stroke_fill="#263040")
    png = cairosvg.svg2png(bytestring=HEART_SVG.encode(), output_width=66, output_height=60)
    heart = Image.open(io.BytesIO(png)).convert("RGBA")
    image.alpha_composite(heart, (888, 1595))
    image.save(path)


def banner_card(text: str, path: Path):
    im = Image.new("RGBA", (1080, 1920))
    d = ImageDraw.Draw(im)
    face = _font(49, "bold")
    lines = wrap(d, text.upper(), face, 840)[:2]
    h = 70+len(lines)*65
    d.rounded_rectangle((65, 145, 1015, 145+h), radius=25, fill=(249, 191, 86, 245))
    _text_center(d, lines, face, 540, 179, "#152238", 16)
    d.text((540, 145+h+17), "REAKSI WARGA +62", font=_font(25, "bold"), anchor="mt", fill="white", stroke_width=2, stroke_fill="#142033")
    im.save(path)


def particles(kind: str, folder: Path, seed=42, frames=72):
    """Seamless 6-second alpha PNG loop, 12 fps; low overhead compared to per-frame Python at 1080p."""
    folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    items = [(rng.random(), rng.random(), rng.uniform(.5, 1.5), rng.random()) for _ in range({"rain": 90, "petals": 30, "snow": 60, "embers": 42}.get(kind, 45))]
    for f in range(frames):
        im = Image.new("RGBA", (540, 960))
        d = ImageDraw.Draw(im)
        t = f/frames
        for x0, y0, speed, phase in items:
            if kind == "rain":
                x = int((x0*600 - t*60*speed) % 600)-30
                y = int((y0+t*2*speed) % 1 * 1060)-50
                d.line((x, y, x-7, y+28), fill=(188, 220, 248, 115), width=1)
            elif kind == "petals":
                x = int((x0 + .09*math.sin(2*math.pi*(t+phase))) * 540)
                y = int(((y0+t*speed) % 1)*1040)-40
                a = 2*math.pi*(t+phase)
                pts = [(x+math.cos(a)*10, y+math.sin(a)*10), (x+math.cos(a+1.7)*6, y+math.sin(a+1.7)*6),
                       (x-math.cos(a)*10, y-math.sin(a)*10), (x-math.cos(a+1.7)*6, y-math.sin(a+1.7)*6)]
                d.polygon(pts, fill=(250, 172, 186, 190))
            elif kind == "snow":
                x = int((x0*580 + 15*math.sin(2*math.pi*(t+phase))) % 580)-20
                y = int(((y0+t*speed) % 1)*1000)-20
                r = 2+int(phase*3)
                d.ellipse((x-r, y-r, x+r, y+r), fill=(245, 251, 255, 190))
            else:
                x = int((x0*600 + 18*math.sin(2*math.pi*(t+phase))) % 600)-30
                y = int(((y0-t*speed) % 1)*1020)-30
                r = 2+int(phase*3)
                d.ellipse((x-r*3, y-r*3, x+r*3, y+r*3), fill=(255, 104, 28, 35))
                d.ellipse((x-r, y-r, x+r, y+r), fill=(255, 198, 83, 225))
        im.save(folder / f"{f:04d}.png")


def prepare_music(path: str | None, output: Path, seconds: float, volume=.32, cancel=None):
    if path:
        ffmpeg(["-stream_loop", "-1", "-i", path, "-t", f"{seconds:.3f}", "-vn", "-af",
                f"volume={volume},afade=t=in:st=0:d=0.6,afade=t=out:st={max(0,seconds-1.3):.3f}:d=1.3,aresample=48000",
                "-ac", "2", "-c:a", "pcm_s16le", str(output)], timeout=300, cancel=cancel)
    else:
        ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(seconds),
                "-c:a", "pcm_s16le", str(output)], timeout=60, cancel=cancel)


def motion_video(image: str, output: str, folder: Path, effect="rain", seconds=15, music=None,
                 card=None, width=1080, height=1920, cancel=None, progress=None):
    check_cancel(cancel)
    folder.mkdir(parents=True, exist_ok=True)
    card_path = folder / "card.png"
    if card:
        poem_card(card, card_path)
    else:
        Image.new("RGBA", (1080, 1920)).save(card_path)
    pdir = folder / "particles"
    particles(effect, pdir)
    wav = folder / "music.wav"
    prepare_music(music, wav, seconds, cancel=cancel)
    fps = 30
    filters = (f"[0:v]scale={width*2}:{height*2}:force_original_aspect_ratio=increase:flags=lanczos,"
               f"crop={width*2}:{height*2},zoompan=z='1+0.07*on/{max(1,seconds*fps)}':"
               f"x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={width}x{height}:fps={fps}[bg];"
               f"[1:v]scale={width}:{height}:flags=bilinear[p];[bg][p]overlay=0:0:shortest=1[v1];"
               f"[2:v]scale={width}:{height}[card];[v1][card]overlay=0:0:shortest=1,format=yuv420p[v]")
    args = ["-loop", "1", "-framerate", str(fps), "-i", image,
            "-stream_loop", "-1", "-framerate", "12", "-i", str(pdir / "%04d.png"),
            "-loop", "1", "-framerate", str(fps), "-i", str(card_path), "-i", str(wav),
            "-filter_complex_threads", "1", "-filter_complex", filters,
            "-map", "[v]", "-map", "3:a", "-t", f"{seconds:.3f}", *output_args(fps), "-shortest", str(output)]
    ffmpeg(args, timeout=2400, cancel=cancel, progress=progress, duration=seconds)


def ass_time(t: float):
    cs = int(round(t*100))
    return f"{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}"


def ass_escape(text: str):
    return str(text).replace("\\", " ").replace("{", "(").replace("}", ")").replace("\n", " ")


def make_ass(segments: list[dict], path: Path, width=1080, height=1920):
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Reaction,DejaVu Sans,{int(width*.047)},&H00FFFFFF,&H000000FF,&H00152132,&H90000000,-1,0,0,0,100,100,0,0,1,4,2,2,70,100,{int(height*.16)},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for s in segments:
        text = ass_escape(s["text"])
        lines.append(f"Dialogue: 0,{ass_time(s['start'])},{ass_time(s['end'])},Reaction,,0,0,0,,{text}")
    path.write_text(header+"\n".join(lines)+"\n", encoding="utf-8")


def srt_text(segments):
    def stamp(t):
        ms = int(round(t*1000))
        return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"
    return "\n\n".join(f"{i+1}\n{stamp(s['start'])} --> {stamp(s['end'])}\n{s['text']}" for i,s in enumerate(segments))+"\n"


def build_narration(segments: list[dict], folder: Path, seconds: float, cancel=None):
    """Concatenate complete TTS lines with gaps; fit speed WITHOUT truncating speech."""
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / "voice-concat.txt"
    parts = []
    for i, s in enumerate(segments):
        wav = folder / f"voice-normalized-{i:02d}.wav"
        ffmpeg(["-i", s["path"], "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)], cancel=cancel, timeout=120)
        parts.append(wav)
        gap = folder / f"gap-{len(parts)}.wav"
        ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.22", "-c:a", "pcm_s16le", str(gap)], cancel=cancel, timeout=30)
        parts.append(gap)
    raw.write_text("\n".join("file '"+str(p.resolve()).replace("'", "'\\''")+"'" for p in parts), encoding="utf-8")
    joined = folder / "voice-joined.wav"
    ffmpeg(["-f", "concat", "-safe", "0", "-i", str(raw), "-c:a", "pcm_s16le", str(joined)], cancel=cancel, timeout=120)
    total = duration(joined)
    available = max(1, seconds-1.1)
    speed = max(1.0, total/available)
    if speed > 1.6:
        raise ValueError("Naskah TTS terlalu panjang untuk klip. Pendekkan naskah atau pilih durasi lebih panjang (maks. 60 dtk).")
    filters = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2
    if remaining > 1.001:
        filters.append(f"atempo={remaining:.6f}")
    filters += ["adelay=600|600", "apad", "atrim=0:"+str(seconds), "aresample=48000"]
    output = folder / "narration.wav"
    ffmpeg(["-i", str(joined), "-af", ",".join(filters), "-ac", "2", "-c:a", "pcm_s16le", str(output)], cancel=cancel, timeout=180)
    cursor = .6
    timed = []
    for s in segments:
        end = cursor+s["duration"]/speed
        timed.append({"text": s["text"], "start": round(cursor, 3), "end": round(end, 3)})
        cursor = end+.22/speed
    return str(output), timed


def reaction_video(source: str, output: str, folder: Path, banner: str, narration: str,
                   segments: list[dict], seconds: float, width=1080, height=1920,
                   crop=True, cancel=None, progress=None):
    folder.mkdir(parents=True, exist_ok=True)
    banner_path, ass_path = folder / "banner.png", folder / "reaction.ass"
    banner_card(banner, banner_path)
    make_ass(segments, ass_path, width, height)
    original_audio = has_audio(source)
    args = ["-i", source, "-i", narration, "-loop", "1", "-framerate", "30", "-i", str(banner_path)]
    if not original_audio:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    original = "0:a" if original_audio else "3:a"
    # TTS remains on an independent branch; sidechaincompress ducks ONLY the original audio.
    filters = (f"[0:v]{video_filter(width,height,30,crop)}[base];"
               f"[2:v]scale={width}:{height}[banner];[base][banner]overlay=0:0:shortest=1,"
               f"ass=filename='{str(ass_path.resolve())}'[v];"
               f"[{original}]aresample=48000,apad,atrim=0:{seconds},volume=0.85[orig];"
               f"[1:a]aresample=48000,apad,atrim=0:{seconds},volume=1.2[voice];"
               f"[voice]asplit=2[voice1][key];[orig][key]sidechaincompress=threshold=0.035:ratio=7:attack=25:release=400[duck];"
               f"[duck][voice1]amix=inputs=2:duration=longest:normalize=0,"
               f"loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.95[a]")
    args += ["-filter_complex_threads", "1", "-filter_complex", filters, "-map", "[v]", "-map", "[a]",
             "-t", f"{seconds:.3f}", *output_args(), str(output)]
    ffmpeg(args, cwd=folder, timeout=2400, cancel=cancel, progress=progress, duration=seconds)