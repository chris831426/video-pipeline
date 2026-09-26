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
VOICE = os.environ.get("TTS_VOICE_ID") or "de-DE-KatjaNeural"
CALLBACK_URL = os.environ["CALLBACK_URL"]
CALLBACK_SECRET = os.environ["CALLBACK_SECRET"]

FPS = 25
WIDTH, HEIGHT = 1080, 1920  # TikTok/Reels Hochformat

s3 = boto3.client(
    "s3",
    endpoint_url=B2_ENDPOINT,
    aws_access_key_id=B2_KEY_ID,
    aws_secret_access_key=B2_APP_KEY,
)

os.makedirs("work", exist_ok=True)
os.chdir("work")


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


def main():
    # 1) Manifest herunterladen
    s3.download_file(B2_BUCKET, f"renders/{VIDEO_ID}/manifest.json", "manifest.json")
    manifest = json.load(open("manifest.json", encoding="utf-8"))
    scenes = manifest["scenes"]
    title = manifest.get("title", "Generiertes Video")
    manifest_settings = manifest.get("settings", {})
    voice = manifest_settings.get("tts_voice_id") or VOICE
    font_size = manifest_settings.get("subtitle_font_size") or "16"

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
        frames = max(1, round(duration * FPS))

        # 4) Bild -> Videoclip mit Ken-Burns-Zoom, passend zur Sprachdauer
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
                "-t", str(duration), "-r", str(FPS),
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

    # 7) Untertitel einbrennen
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", "combined.mp4",
            "-vf", f"subtitles=subs.srt:force_style='Fontsize={font_size},PrimaryColour=&HFFFFFF&,Outline=1,Alignment=2'",
            "-c:a", "copy", "final.mp4",
        ],
        check=True,
    )

    # 8) Fertiges Video zu B2 hochladen
    final_key = f"videos/{VIDEO_ID}.mp4"
    s3.upload_file("final.mp4", B2_BUCKET, final_key, ExtraArgs={"ContentType": "video/mp4"})

    # 9) Worker informieren, damit der D1-Eintrag auf "draft" gesetzt wird
    payload = json.dumps(
        {
            "id": VIDEO_ID,
            "key": final_key,
            "title": title,
            "script": " ".join(s["text"] for s in scenes),
            "secret": CALLBACK_SECRET,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        CALLBACK_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; VideoPipelineBot/1.0)",
        },
    )
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Callback an den Worker fehlgeschlagen ({e.code}): {error_body}"
        ) from e

    print("Fertig:", final_key)


if __name__ == "__main__":
    main()
