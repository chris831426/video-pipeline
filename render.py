# render.py
# github.com/video-pipeline

import asyncio
import json
import os
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

WIDTH, HEIGHT = 1080, 1920  # 9:16, TikTok/Reels Hochformat

s3 = boto3.client(
    "s3",
    endpoint_url=B2_ENDPOINT,
    aws_access_key_id=B2_KEY_ID,
    aws_secret_access_key=B2_APP_KEY,
)

os.makedirs("work", exist_ok=True)
os.chdir("work")


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
            "-of", "default=noprint_wrappers=1:nokey=1", path,
        ],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def srt_timestamp(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def hex_to_ass_color(hex_color, fallback="&HFFFFFF&"):
    """Wandelt '#RRGGBB' in ASS/libass-Farbformat '&HBBGGRR&' um (umgekehrte Byte-Reihenfolge)."""
    if not hex_color:
        return fallback
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        return fallback
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{b}{g}{r}&".upper()


def main():
    # 1) Manifest herunterladen (v2: Titel, Caption, Production Bible, Szenen, globale Settings)
    s3.download_file(B2_BUCKET, f"renders/{VIDEO_ID}/manifest.json", "manifest.json")
    manifest = json.load(open("manifest.json", encoding="utf-8"))
    scenes = manifest["scenes"]
    settings = manifest.get("settings", {})

    voice = settings.get("tts_voice_id") or "de-DE-KatjaNeural"
    fps = int(settings.get("fps") or 30)
    font_name = settings.get("subtitle_font") or "Arial"
    font_size = settings.get("subtitle_font_size") or "16"
    primary_color = hex_to_ass_color(settings.get("subtitle_color"), "&HFFFFFF&")
    position = settings.get("subtitle_position") or "bottom"
    alignment = "5" if position == "middle" else "2"  # ASS: 2 = unten-mittig, 5 = mittig

    clip_files = []
    srt_blocks = []
    t_cursor = 0.0

    for i, scene in enumerate(scenes):
        # 2) Szenenbild herunterladen
        img_path = f"scene-{i}.jpg"
        s3.download_file(B2_BUCKET, scene["image_key"], img_path)

        # 3) Sprachausgabe erzeugen (edge-tts)
        audio_path = f"scene-{i}.mp3"
        asyncio.run(edge_tts.Communicate(scene["text"], voice).save(audio_path))
        duration = ffprobe_duration(audio_path)
        frames = max(1, round(duration * fps))

        # 4) Bild -> Videoclip mit Ken-Burns-Zoom, passend zur tatsächlichen Sprachdauer
        clip_path = f"clip-{i}.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y", "-loop", "1", "-i", img_path, "-i", audio_path,
                "-filter_complex",
                f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={WIDTH}:{HEIGHT},"
                f"zoompan=z='min(zoom+0.0015,1.2)':d={frames}:s={WIDTH}x{HEIGHT},"
                f"format=yuv420p[v]",
                "-map", "[v]", "-map", "1:a",
                "-t", str(duration), "-r", str(fps),
                "-c:v", "libx264", "-c:a", "aac", "-shortest", clip_path,
            ],
            check=True,
        )
        clip_files.append(clip_path)

        # 5) Untertitel-Block für diese Szene (ganzer Satz für die Szenendauer)
        start, end = t_cursor, t_cursor + duration
        srt_blocks.append(f"{i + 1}\n{srt_timestamp(start)} --> {srt_timestamp(end)}\n{scene['text']}\n")
        t_cursor = end

    with open("subs.srt", "w", encoding="utf-8") as f:
        f.write("\n".join(srt_blocks))

    # 6) Alle Szenen-Clips verketten
    with open("concat.txt", "w", encoding="utf-8") as f:
        for c in clip_files:
            f.write(f"file '{c}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", "combined.mp4"],
        check=True,
    )

    # 7) Untertitel einbrennen (Schrift/Größe/Farbe/Position aus dem globalen Kanalstil)
    force_style = (
        f"Fontname={font_name},Fontsize={font_size},"
        f"PrimaryColour={primary_color},Outline=1,Alignment={alignment}"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", "combined.mp4",
            "-vf", f"subtitles=subs.srt:force_style='{force_style}'",
            "-c:a", "copy", "final.mp4",
        ],
        check=True,
    )

    # 8) Tatsächliche Videodauer messen (Pflichtfeld für den Callback -> Mindestlängen-Check)
    final_duration = ffprobe_duration("final.mp4")

    # 9) Fertiges Video zu B2 hochladen.
    #    Liegt unter renders/<id>/, damit der B2-Cleanup im Worker es mit löscht.
    final_key = f"renders/{VIDEO_ID}/video.mp4"
    s3.upload_file("final.mp4", B2_BUCKET, final_key, ExtraArgs={"ContentType": "video/mp4"})

    # 10) Worker informieren (setzt Status auf "draft" oder stößt bei zu kurzer Dauer eine Regenerierung an)
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
