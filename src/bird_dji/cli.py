import argparse
from fractions import Fraction
import math
from pathlib import Path
import subprocess
from .hud import HUD,render_hud,self_destruct_progress
from .telemetry import Telemetry
from .video import check_output, mask, overlay, probe


def main():
    parser = argparse.ArgumentParser(description="DJI SRT → 游戏无人机 HUD 透明 mask → FFmpeg 合成")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, description in [("mask", "只生成透明 MOV"), ("render", "生成 mask 并合成视频"),
                              ("preview", "导出单帧透明 PNG"), ("batch", "批量配对同名视频和 SRT")]:
        p = sub.add_parser(name, help=description)
        if name == "batch":
            p.add_argument("directory", type=Path)
            p.add_argument("--output-dir", type=Path, default=Path("outputs"))
        else:
            p.add_argument("--srt", type=Path, required=True)
            p.add_argument("--video", type=Path, required=name == "render", help="自动匹配视频尺寸、帧率和时长")
            p.add_argument("-o", "--output", type=Path, required=True)
        p.add_argument("--width", type=int)
        p.add_argument("--height", type=int)
        p.add_argument("--fps", help="例如 30000/1001；默认匹配视频，否则 30")
        p.add_argument("--duration", type=float, help="只处理前 N 秒")
        p.add_argument("--self-destruct-last", type=float, default=3, help="末尾多少秒进入自毁模式，默认 3")
        p.add_argument("--self-destruct-at", type=float, help="指定开始自毁的时间点（秒），优先于末尾秒数")
        p.add_argument("--no-self-destruct", action="store_true", help="关闭自毁模式")
        p.add_argument("--opacity", type=float, default=.85)
        p.add_argument("--line-width", type=float, default=4, help="1920×1080 基准线宽，随分辨率缩放")
        p.add_argument("--hud-scale", type=float, default=.65, help="HUD 占原布局的比例，整体居中")
        p.add_argument("--reticle", choices=["auto","fixed"], default="auto", help="有视频时通过画面运动估计圆圈方向")
        p.add_argument("--reticle-gain", type=float, default=12, help="转镜头响应强度，默认 12")
        p.add_argument("--reticle-range", type=float, default=.18, help="圆圈最大偏移占 HUD 宽/高的比例，默认 0.18")
        p.add_argument("--pose", action="store_true", help="YOLOv8 人体关键点橙黄色方块")
        p.add_argument("--pose-model", type=Path, default=Path("models/yolov8n-pose.pt"))
        p.add_argument("--pose-interval", type=float, default=2, help="检测间隔秒，默认 2 秒（0.5 次/秒）")
        p.add_argument("--pose-imgsz", type=int, default=960, help="检测输入尺寸，默认 960")
        p.add_argument("--pose-confidence", type=float, default=.5, help="关键点置信度阈值")
        p.add_argument("--pose-device", default="cpu", help="cpu 或 CUDA 设备编号，如 0")
        p.add_argument("--no-release-prompt", action="store_true", help="关闭最近人物的释放蜂鸟提示")
        p.add_argument("--release-follow-speed", type=float, default=180, help="提示跟随的速度上限，1080p 像素/秒")
        p.add_argument("--window", type=float, default=1, help="GPS 估算窗口（秒）")
        p.add_argument("--offset", type=float, default=0, help="视频 t 秒使用 SRT t+offset 秒")
        p.add_argument("--overwrite", action="store_true")
        if name == "preview":
            p.add_argument("--time", type=float, default=0)
        if name in ("render", "batch"):
            p.add_argument("--encoder", choices=["libx264", "h264_nvenc"], default="libx264")
            p.add_argument("--crf", type=int, default=18)
    p = sub.add_parser("overlay", help="使用已有透明 mask 合成视频")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--mask", type=Path, required=True)
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("--duration", type=float)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--encoder", choices=["libx264", "h264_nvenc"], default="libx264")
    p.add_argument("--crf", type=int, default=18)
    args = parser.parse_args()
    try:
        if args.command == "overlay":
            overlay(args.video, args.mask, args.output, args.overwrite, args.duration, args.encoder, args.crf)
            return
        if not 0 < args.opacity <= 1 or args.window <= 0 or args.line_width <= 0:
            raise ValueError("opacity 必须在 (0, 1]，window 和 line-width 必须大于 0")
        if not .5 <= args.hud_scale <= 1:
            raise ValueError("hud-scale 必须在 [0.5,1]")
        if not 0 < args.reticle_gain <= 100 or not 0 < args.reticle_range <= .25:
            raise ValueError("reticle-gain 必须在 (0,100]，reticle-range 必须在 (0,0.25]")
        if not 0 < args.pose_interval <= 60 or not 0 < args.pose_confidence <= 1:
            raise ValueError("pose-interval 必须在 (0,60]，pose-confidence 必须在 (0,1]")
        if not 320 <= args.pose_imgsz <= 2560:
            raise ValueError("pose-imgsz 必须在 [320,2560]")
        if not math.isfinite(args.self_destruct_last) or args.self_destruct_last <= 0 or (args.self_destruct_at is not None and (not math.isfinite(args.self_destruct_at) or args.self_destruct_at < 0)):
            raise ValueError("self-destruct-last 必须为正，self-destruct-at 必须非负")
        if not math.isfinite(args.release_follow_speed) or args.release_follow_speed <= 0:
            raise ValueError("release-follow-speed 必须为正")
        if args.pose and args.command != "batch" and not args.video:
            raise ValueError("人体姿态检测需要 --video")
        if (args.width is None) != (args.height is None):
            raise ValueError("--width 和 --height 必须同时指定")
        if args.command == "batch":
            files = list(args.directory.iterdir())
            subtitles = {p.stem.lower(): p for p in files if p.suffix.lower() == ".srt"}
            pairs = [(p, subtitles[p.stem.lower()]) for p in files
                     if p.suffix.lower() in (".mp4", ".mov") and p.stem.lower() in subtitles]
            if not pairs:
                raise ValueError("目录中找不到同名视频和 SRT")
            for video, srt in sorted(pairs):
                produce(args, video, srt, args.output_dir/f"{video.stem}_hud.mp4")
            return
        info = probe(args.video) if args.video else {}
        width, height = args.width or info.get("width", 1920), args.height or info.get("height", 1080)
        if args.command == "preview":
            check_output(args.output, [args.srt]+([args.video] if args.video else []), args.overwrite)
            telemetry = Telemetry.read(args.srt, args.window)
            from .motion import CameraMotion
            motion = CameraMotion.read(args.video,min(info["duration"],args.time+.2),args.reticle_gain) if args.video else None
            duration = min(args.duration or info.get("duration",telemetry.duration),info.get("duration",telemetry.duration))
            rate = float(Fraction(args.fps or info.get("fps","30")))
            last_frame = max(1,math.ceil(duration*rate)-1)
            health = max(0,min(1,1-args.time*rate/last_frame))
            normal = HUD(width,height,args.opacity,args.line_width,args.hud_scale,telemetry.max_speed,args.reticle_range)
            danger = HUD(width,height,args.opacity*.45,args.line_width*.4,args.hud_scale,telemetry.max_speed,args.reticle_range,(228,30,34),alarm=True)
            image = render_hud(normal,danger,
                telemetry.at(args.time+args.offset), motion.at(args.time) if motion and args.reticle != "fixed" else (0,0),
                motion.heading_at(args.time) if motion else None,health,
                self_destruct_progress(args.time,duration,args.self_destruct_last,args.self_destruct_at,not args.no_self_destruct))
            if args.pose:
                from .pose import PoseTimeline,draw_keypoints
                timeline = PoseTimeline.read(args.video,min(info["duration"],args.time+.05),args.pose_model,
                                             args.pose_interval,args.pose_confidence,args.pose_device,args.pose_imgsz)
                draw_keypoints(image,timeline.at(args.time))
                if not args.no_release_prompt:
                    from .release import ReleasePrompt
                    release = ReleasePrompt(width,height,args.release_follow_speed)
                    # Replay causal updates so preview follows the same bounded motion as export.
                    for i in range(max(0,math.floor(args.time*rate))+1):
                        t = i/rate
                        aim = normal.reticle_position(motion.at(t) if motion and args.reticle != "fixed" else (0,0))
                        aim = ((aim[0]+round(normal.ox))/width,(aim[1]+round(normal.oy))/height)
                        release.update(t,timeline.boxes_at(t),aim)
                    release.draw(image,normal)
            image.save(args.output)
            print(f"预览：{args.output}")
        elif args.command == "mask":
            if args.video and args.output.resolve() == args.video.resolve():
                raise ValueError("输出路径不能覆盖输入视频")
            mask(args.srt, args.output, width, height, args.fps or info.get("fps", "30"),
                 args.duration or info.get("duration"), args.opacity, args.window, args.offset, args.overwrite, args.line_width,
                 args.hud_scale, args.video, args.reticle, args.reticle_gain, args.reticle_range,
                 args.pose_model if args.pose else None,args.pose_interval,args.pose_confidence,args.pose_device,
                 args.self_destruct_last,args.self_destruct_at,not args.no_self_destruct,
                 not args.no_release_prompt,args.release_follow_speed,args.pose_imgsz)
        else:
            produce(args, args.video, args.srt, args.output)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"错误：{error}\n")
    except KeyboardInterrupt:
        parser.exit(130, "已取消\n")


def produce(args, video, srt, output):
    info = probe(video)
    hud_path = output.with_name(output.stem+"_mask.mov")
    check_output(output, [video, srt, hud_path], args.overwrite)
    mask(srt, hud_path, args.width or info["width"], args.height or info["height"],
         args.fps or info["fps"], min(args.duration or info["duration"], info["duration"]),
         args.opacity, args.window, args.offset, args.overwrite, args.line_width, args.hud_scale, video, args.reticle,
         args.reticle_gain,args.reticle_range,args.pose_model if args.pose else None,
         args.pose_interval,args.pose_confidence,args.pose_device,
         args.self_destruct_last,args.self_destruct_at,not args.no_self_destruct,
         not args.no_release_prompt,args.release_follow_speed,args.pose_imgsz)
    overlay(video, hud_path, output, args.overwrite, args.duration, args.encoder, args.crf)
