"""Export transparent masks, green-screen video or PNG sequences with FFmpeg."""
from fractions import Fraction
import json
import math
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
from PIL import Image
from .hud import HUD,render_hud,self_destruct_progress
from .telemetry import Telemetry


def binary(name: str) -> str:
    result = shutil.which(name)
    if not result:
        raise ValueError(f"找不到 {name}，请先安装 FFmpeg 并加入 PATH")
    return result


def probe(path: Path) -> dict:
    result = subprocess.run([binary("ffprobe"), "-v", "error", "-select_streams", "v:0",
                             "-show_entries", "stream=width,height,avg_frame_rate:format=duration", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return dict(width=stream["width"], height=stream["height"],
                fps=stream["avg_frame_rate"], duration=float(data["format"]["duration"]))


def check_output(output: Path, inputs: list[Path], overwrite: bool):
    if any(output.resolve() == p.resolve() for p in inputs):
        raise ValueError("输出路径不能与输入文件相同")
    if output.exists() and not overwrite:
        raise ValueError(f"输出已存在：{output}（使用 --overwrite 替换）")
    output.parent.mkdir(parents=True, exist_ok=True)


def mask(srt: Path, output: Path, width: int, height: int, fps: str,
         duration: float | None = None, opacity: float = .85, window: float = 1,
         offset: float = 0, overwrite: bool = False, line_width: float = 4,
         hud_scale: float = .65, video: Path | None = None, reticle: str = "auto",
         reticle_gain: float = 12, reticle_range: float = .18, pose_model: Path | None = None,
         pose_interval: float = 2, pose_confidence: float = .5, pose_device: str = "cpu",
         self_destruct_last: float = 3, self_destruct_at: float | None = None, self_destruct: bool = True,
         release_prompt: bool = True, release_follow_speed: float = 180, pose_imgsz: int = 960,
         mask_format: str = "transparent"):
    if mask_format not in ("transparent", "green", "png"):
        raise ValueError("mask-format 必须为 transparent、green 或 png")
    if mask_format == "transparent" and output.suffix.lower() != ".mov":
        raise ValueError("透明 mask 请使用 .mov（QuickTime Animation / qtrle + alpha）")
    if mask_format == "green" and output.suffix.lower() not in (".mov", ".mp4"):
        raise ValueError("绿幕 mask 请使用 .mov 或 .mp4")
    if mask_format == "png" and output.exists():
        # Only replace directories created by this exporter, never a footage directory.
        if not output.is_dir() or not (output/"manifest.json").is_file():
            raise ValueError("PNG 序列输出必须为新目录，或本工具生成的序列目录")
        manifest = json.loads((output/"manifest.json").read_text(encoding="utf-8"))
        if manifest.get("generator") != "bird-dji" or any(
                not p.is_file() or (p.name != "manifest.json" and not re.fullmatch(r"frame_\d{6,}\.png",p.name))
                for p in output.iterdir()):
            raise ValueError("序列目录含其他文件，不能覆盖")
    check_output(output, [srt]+([video] if video else []), overwrite)
    telemetry = Telemetry.read(srt, window)
    duration = duration if duration is not None else telemetry.duration
    rate = float(Fraction(fps))
    if not math.isfinite(duration) or not math.isfinite(rate) or duration <= 0 or rate <= 0 or width < 64 or height < 64:
        raise ValueError("时长、帧率及画面尺寸必须为正，画面至少 64×64")
    hud = HUD(width, height, opacity, line_width, hud_scale, telemetry.max_speed, reticle_range)
    danger = HUD(width,height,opacity*.45,line_width*.4,hud_scale,telemetry.max_speed,reticle_range,(228,30,34),alarm=True)
    print(f"整段最高速度：{telemetry.max_speed:.3f} m/s（对应速度条 100%）")
    from .motion import CameraMotion
    motion = CameraMotion.read(video, duration, reticle_gain) if video else None
    if not motion and reticle != "fixed":
        print("未提供视频，无法估计镜头运动；圆圈固定居中。")
    from .pose import PoseTimeline,draw_keypoints
    if pose_model and not video:
        raise ValueError("人体姿态检测需要视频")
    pose = PoseTimeline.read(video,duration,pose_model,pose_interval,pose_confidence,pose_device,pose_imgsz) if pose_model else None
    from .release import ReleasePrompt
    release = ReleasePrompt(width,height,release_follow_speed)
    # Stage in the destination directory: interrupted renders never become final masks.
    with tempfile.TemporaryDirectory(prefix="hud-", dir=output.parent) as directory:
        temporary = Path(directory)/("sequence" if mask_format == "png" else "mask"+output.suffix)
        if mask_format == "png":
            temporary.mkdir()
        with tempfile.TemporaryFile() as errors:
            command = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                       "-f", "rawvideo", "-pixel_format", "rgba", "-video_size", f"{width}x{height}",
                       "-framerate", str(fps), "-i", "pipe:0", "-an"]
            if mask_format == "png":
                command += ["-c:v", "png", "-pix_fmt", "rgba", "-start_number", "1"]
                destination = temporary/"frame_%06d.png"
            elif mask_format == "green" and output.suffix.lower() == ".mp4":
                command += ["-c:v", "libx264", "-preset", "fast", "-crf", "12", "-pix_fmt", "yuv444p"]
                destination = temporary
            else:
                command += ["-c:v", "qtrle", "-pix_fmt", "rgb24" if mask_format == "green" else "argb"]
                destination = temporary
            command += ["-t", str(duration), str(destination)]
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
            try:
                count = math.ceil(duration*rate)
                for i in range(count):
                    frame = render_hud(hud,danger,telemetry.at(i/rate+offset),
                                      motion.at(i/rate) if motion and reticle != "fixed" else (0,0),
                                      motion.heading_at(i/rate) if motion else None,
                                      1-i/(count-1) if count > 1 else 1,
                                      self_destruct_progress(i/rate,duration,self_destruct_last,self_destruct_at,self_destruct))
                    if pose:
                        draw_keypoints(frame,pose.at(i/rate))
                        if release_prompt:
                            aim = hud.reticle_position(motion.at(i/rate) if motion and reticle != "fixed" else (0,0))
                            aim = ((aim[0]+round(hud.ox))/width,(aim[1]+round(hud.oy))/height)
                            release.update(i/rate,pose.boxes_at(i/rate),aim)
                            release.draw(frame,hud)
                    if mask_format == "green":
                        frame = Image.alpha_composite(Image.new("RGBA",frame.size,(0,255,0,255)),frame)
                    process.stdin.write(frame.tobytes())
                    if i % max(1, round(rate)) == 0:
                        print(f"\r生成 mask：{i/count:.0%}", end="", flush=True)
                process.stdin.close()
                code = process.wait()
                if code:
                    errors.seek(0)
                    raise ValueError(errors.read().decode("utf-8", errors="replace"))
            except BaseException:
                if process.poll() is None:
                    process.kill()
                process.wait()
                errors.seek(0)
                log = errors.read().decode("utf-8", errors="replace")
                if log:
                    print(log)
                raise
        metadata = {"generator":"bird-dji", "mask_format":mask_format, "width":width,
                    "height":height, "fps":str(fps), "duration":duration,
                    "self_destruct_start":
                    (max(0,duration-self_destruct_last) if self_destruct_at is None else self_destruct_at) if self_destruct else None}
        if mask_format == "png":
            metadata.update(frame_pattern="frame_%06d.png",start_number=1,
                            frame_count=len(list(temporary.glob("frame_*.png"))))
            (temporary/"manifest.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
            previous = Path(directory)/"previous"
            if output.exists():
                # Verified exporter-owned directory; keep it until the staged result is ready.
                output.replace(previous)
            try:
                temporary.replace(output)
            except OSError:
                if previous.exists():
                    previous.replace(output)
                raise
        else:
            temporary.replace(output)
        if pose:
            pose.save(output.with_suffix(".pose.json"))
            output.with_suffix(".release.json").write_text(json.dumps({"events":release.events},ensure_ascii=False,indent=2),encoding="utf-8")
        output.with_suffix(".hud.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
    print(f"\r生成 mask：100% → {output}")


def overlay(video: Path, hud: Path, output: Path, overwrite: bool = False,
            duration: float | None = None, encoder: str = "libx264", crf: int = 18):
    effects_file = hud.with_suffix(".hud.json")
    metadata = json.loads(effects_file.read_text(encoding="utf-8")) if effects_file.exists() else {}
    if hud.is_dir() or metadata.get("mask_format","transparent") != "transparent":
        raise ValueError("overlay 需要透明 MOV；绿幕请在剪辑软件中抠像，PNG 序列请按帧率导入")
    check_output(output, [video, hud], overwrite)
    info = probe(video)
    hud_info = probe(hud)
    duration = min(duration or info["duration"], info["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("输出时长必须大于零")
    if hud_info["duration"] + 0.1 < duration:
        raise ValueError("mask 比输出视频短，请重新生成足够长的 mask 或使用 --duration")
    w, h = info["width"], info["height"]
    start = metadata.get("self_destruct_start")
    effects = ""
    if start is not None:
        if not isinstance(start,(int,float)) or not math.isfinite(start) or start < 0:
            raise ValueError("mask 的自毁开始时间无效")
        shift = max(1,round(w/1920*4))
        effects = f",rgbashift=rh={shift}:bh={-shift}:enable='gte(t,{start})',vignette=angle=PI/6:enable='gte(t,{start})'"
    command = [binary("ffmpeg"), "-hide_banner", "-y", "-i", str(video), "-i", str(hud),
               "-filter_complex", f"[0:v]setpts=PTS-STARTPTS{effects}[base];[1:v]setpts=PTS-STARTPTS,scale={w}:{h}:flags=lanczos,format=rgba[hud];[base][hud]overlay=0:0:format=auto:alpha=straight[v]",
               "-map", "[v]", "-map", "0:a?", "-c:v", encoder]
    if encoder == "libx264":
        command += ["-preset", "fast", "-crf", str(crf)]
    else:
        command += ["-preset", "p4", "-rc", "vbr", "-cq", str(crf)]
    command += ["-pix_fmt", "yuv420p", "-c:a", "copy", "-t", str(duration), "-movflags", "+faststart"]
    with tempfile.TemporaryDirectory(prefix="compose-", dir=output.parent) as directory:
        staged = Path(directory)/output.name
        subprocess.run(command+[str(staged)], check=True)
        staged.replace(output)
    print(f"合成完成：{output}")
