# render.py
# Rendert das Video mit Remotion (React-Animationen) statt mit ffmpeg-Standbildern.
#
# Ablauf:
#   1) Manifest (Szenen mit Text, Icon, Stimmung) aus B2 laden
#   2) Pro Szene Sprachausgabe mit Wortzeiten (edge-tts) erzeugen
#   3) Emoji-Grafiken (Noto, SVG) aus node_modules nach public/emoji kopieren
#   4) props.json schreiben und `remotion render` aufrufen
#   5) Video nach B2 hochladen und den Worker informieren

import asyncio
import json
import math
import os
import pathlib
import re
import subprocess
import urllib.error
import urllib.request

import boto3
import edge_tts

VIDEO_ID = os.environ["VIDEO_ID"]
B2_ENDPOINT = os.environ["B2_ENDPOINT"]
B2_BUCKET = os.environ["B2_BUCKET"]
B2_KEY_ID = os.environ["B2_KEY_ID"]
B2_APP_KEY = os.environ["B2_APP_KEY"]
CALLBACK_URL = os.environ["CALLBACK_URL"]
CALLBACK_SECRET = os.environ["CALLBACK_SECRET"]

ROOT = pathlib.Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
WORK = ROOT / "work"
OUT = ROOT / "out"
SPRITE = ROOT / "node_modules" / "@svgmoji" / "noto" / "sprites" / "all.svg"

SCENE_PAD_SECONDS = 0.25  # kurze Pause nach jeder Szene
FALLBACK_EMOJI = "\u2754"  # ❔

s3 = boto3.client(
    "s3",
    endpoint_url=B2_ENDPOINT,
    aws_access_key_id=B2_KEY_ID,
    aws_secret_access_key=B2_APP_KEY,
)


class CallbackError(RuntimeError):
    """Der Callback an den Worker selbst ist fehlgeschlagen."""


def post_callback(payload):
    """Meldet das Ergebnis an den Worker (/internal/render-complete).

    Felder, die der Worker erwartet:
      video_id, status ("success" | "failed"),
      duration_seconds, b2_key (bei success), error (bei failed)
    """
    body = json.dumps({**payload, "secret": CALLBACK_SECRET}).encode("utf-8")
    req = urllib.request.Request(
        CALLBACK_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; VideoPipelineBot/1.0)",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise CallbackError(
            f"Callback an den Worker fehlgeschlagen ({e.code}): {error_body}"
        ) from e


def ffprobe_duration(path):
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


# ---------------------------------------------------------------- Emoji

_sprite_text = None


def _sprite():
    global _sprite_text
    if _sprite_text is None:
        _sprite_text = SPRITE.read_text(encoding="utf-8")
    return _sprite_text


def _find_emoji_id(emoji):
    """Sucht die Sprite-ID zu einem Emoji (z.B. '1F511' oder '1F56F')."""
    sprite = _sprite()
    cps = [f"{ord(c):04X}" for c in emoji]
    candidates = [
        "-".join(cps),
        "-".join(c for c in cps if c != "FE0F"),
    ]
    if len(cps) == 1:
        candidates.append(cps[0] + "-FE0F")
    for cand in candidates:
        if cand and f'id="{cand}"' in sprite:
            return cand
    return None


def emoji_file(emoji):
    """Schreibt die SVG des Emojis nach public/emoji und gibt den Pfad relativ zu public/ zurück."""
    emoji = (emoji or "").strip() or FALLBACK_EMOJI
    emoji_id = _find_emoji_id(emoji) or _find_emoji_id(FALLBACK_EMOJI)
    rel = f"emoji/{emoji_id}.svg"
    target = PUBLIC / rel
    if not target.exists():
        sprite = _sprite()
        idx = sprite.index(f'id="{emoji_id}"')
        start = sprite.rfind("<svg", 0, idx)
        end = sprite.index("</svg>", idx) + len("</svg>")
        svg = sprite[start:end].replace(
            "<svg ", '<svg xmlns:xlink="http://www.w3.org/1999/xlink" ', 1
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(svg, encoding="utf-8")
    return rel


# ---------------------------------------------------------------- Sprache

async def synthesize(text, voice, path):
    """Erzeugt die MP3 und gibt die Wortgrenzen [{text,start,end}] in Sekunden zurück."""
    try:
        comm = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    except TypeError:  # ältere edge-tts-Versionen
        comm = edge_tts.Communicate(text, voice)
    words = []
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                start = chunk["offset"] / 1e7
                words.append(
                    {
                        "text": chunk.get("text", ""),
                        "start": start,
                        "end": start + chunk["duration"] / 1e7,
                    }
                )
    return words


def align_words(text, raw, audio_duration):
    """Ordnet jedem Wort des Originaltexts (mit Satzzeichen) eine Zeit zu."""
    tokens = text.split()
    if not tokens:
        return []
    if raw and len(raw) == len(tokens):
        return [
            {
                "text": tok,
                "start": round(r["start"], 3),
                "end": round(min(r["end"], audio_duration), 3),
            }
            for tok, r in zip(tokens, raw)
        ]
    # Fallback: gleichmäßig nach Wortlänge über den gesprochenen Bereich verteilen
    t0 = raw[0]["start"] if raw else 0.0
    t1 = raw[-1]["end"] if raw else audio_duration
    if t1 <= t0:
        t1 = audio_duration
    weights = [len(t) + 2 for t in tokens]
    total = sum(weights)
    out, cur = [], t0
    for tok, w in zip(tokens, weights):
        span = (t1 - t0) * w / total
        out.append(
            {
                "text": tok,
                "start": round(cur, 3),
                "end": round(min(cur + span, audio_duration), 3),
            }
        )
        cur += span
    return out


# ---------------------------------------------------------------- Stil

def clean_color(value, fallback):
    if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value.strip()):
        return value.strip()
    return fallback


# ---------------------------------------------------------------- Hauptablauf

def main():
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    PUBLIC.mkdir(exist_ok=True)

    # 1) Manifest herunterladen
    manifest_path = WORK / "manifest.json"
    s3.download_file(B2_BUCKET, f"renders/{VIDEO_ID}/manifest.json", str(manifest_path))
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    scenes = manifest["scenes"]
    settings = manifest.get("settings", {})

    voice = settings.get("tts_voice_id") or "de-DE-KatjaNeural"
    fps = int(settings.get("fps") or 30)

    scenes_out = []
    for i, scene in enumerate(scenes):
        # 2) Sprachausgabe mit Wortzeiten
        audio_rel = f"audio/scene-{i}.mp3"
        raw_words = asyncio.run(synthesize(scene["text"], voice, PUBLIC / audio_rel))
        audio_duration = ffprobe_duration(PUBLIC / audio_rel)
        words = align_words(scene["text"], raw_words, audio_duration)

        # 3) Emoji-Grafiken
        icon = emoji_file(scene.get("icon"))
        extra = [emoji_file(e) for e in (scene.get("extra_icons") or [])[:2]]

        scenes_out.append(
            {
                "id": scene.get("id") or f"scene_{i + 1}",
                "icon": icon,
                "extraIcons": extra,
                "mood": scene.get("mood") or "mystery",
                "label": (scene.get("label") or "")[:40],
                "durationInFrames": max(1, math.ceil((audio_duration + SCENE_PAD_SECONDS) * fps)),
                "audio": audio_rel,
                "words": words,
            }
        )

    # 4) Props schreiben und mit Remotion rendern
    props = {
        "fps": fps,
        "scenes": scenes_out,
        "style": {
            "subtitleColor": clean_color(settings.get("subtitle_color"), "#FFFFFF"),
            "accentColor": clean_color(settings.get("subtitle_accent_color"), "#FFD84D"),
            "subtitlePosition": "middle" if settings.get("subtitle_position") == "middle" else "bottom",
        },
    }
    props_path = WORK / "props.json"
    props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")

    final_path = OUT / "final.mp4"
    subprocess.run(
        [
            "npx", "remotion", "render", "src/index.ts", "Main", str(final_path),
            f"--props={props_path}", "--crf=21", "--log=info",
        ],
        cwd=ROOT,
        check=True,
    )

    # 5) Tatsächliche Videodauer messen (Pflichtfeld für den Callback -> Mindestlängen-Check)
    final_duration = ffprobe_duration(final_path)

    # 6) Fertiges Video zu B2 hochladen.
    #    Liegt unter renders/<id>/, damit der B2-Cleanup im Worker es mit löscht.
    final_key = f"renders/{VIDEO_ID}/video.mp4"
    s3.upload_file(str(final_path), B2_BUCKET, final_key, ExtraArgs={"ContentType": "video/mp4"})

    # 7) Worker informieren
    post_callback(
        {
            "video_id": VIDEO_ID,
            "status": "success",
            "duration_seconds": round(final_duration, 3),
            "b2_key": final_key,
        }
    )

    print("Fertig:", final_key, f"({final_duration:.2f}s)")


if __name__ == "__main__":
    try:
        main()
    except CallbackError:
        raise
    except Exception as e:
        # Fehler beim Rendern: Worker informieren, damit das Video nicht ewig auf "rendering" hängt.
        try:
            post_callback({"video_id": VIDEO_ID, "status": "failed", "error": str(e)[:500]})
        except Exception as cb_err:
            print("Fehler-Callback ebenfalls fehlgeschlagen:", cb_err)
        raise
