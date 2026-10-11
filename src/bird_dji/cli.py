"""Python Fire command line interface for the HUD and Fusion analyzer."""
from fractions import Fraction
from inspect import Parameter, signature
import math
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import fire

from .hud import HUD,render_hud,self_destruct_progress
from .telemetry import Telemetry
from .video import check_output, mask as render_mask, overlay, probe


def _run(command, srt=None, video=None, output=None, directory=None,
         output_dir="outputs", width=None, height=None, fps=None, duration=None,
         self_destruct_last=3, self_destruct_at=None, no_self_destruct=False,
         opacity=.85, line_width=4, hud_scale=.65, reticle="auto",
         reticle_gain=12, reticle_range=.18, pose=False,
         pose_model="models/yolov8n-pose.pt", pose_interval=2, pose_imgsz=960,
         pose_confidence=.5, pose_device="cpu", no_release_prompt=False,
         release_follow_speed=180, window=1, offset=0, overwrite=False,
         time=0, mask_format="transparent", encoder="libx264", crf=18,
         mask=None):
    args = SimpleNamespace(**locals())
    try:
        required = ("directory",) if command == "batch" else ("srt", "output")
        if command == "overlay":
            required = ("video", "mask", "output")
        elif command in ("render", "analyze"):
            required += ("video",)
        for name in required:
            if getattr(args, name) is None:
                raise ValueError(f"需要指定 --{name.replace('_', '-')}")
        for name in ("srt", "video", "output", "directory", "output_dir", "pose_model", "mask"):
            value = getattr(args, name)
            if value is not None:
                setattr(args, name, Path(str(value)))
        # Fire parses literal values, while FFmpeg and YOLO expect text here.
        args.fps = str(args.fps) if args.fps is not None else None
        args.pose_device = str(args.pose_device)
        for name, choices in (("reticle", ("auto", "fixed")),
                              ("mask_format", ("transparent", "green", "png")),
                              ("encoder", ("libx264", "h264_nvenc"))):
            if getattr(args, name) not in choices:
                raise ValueError(f"{name.replace('_', '-')} 必须是 {', '.join(choices)}")
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
        if args.command == "analyze":
            from .analysis import analyze
            analyze(args.video,args.srt,args.output,duration=args.duration,window=args.window,
                    offset=args.offset,gain=args.reticle_gain,
                    pose_model=args.pose_model if args.pose else None,
                    pose_interval=args.pose_interval,pose_confidence=args.pose_confidence,
                    pose_device=args.pose_device,pose_imgsz=args.pose_imgsz,overwrite=args.overwrite)
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
            render_mask(args.srt, args.output, width, height, args.fps or info.get("fps", "30"),
                 args.duration or info.get("duration"), args.opacity, args.window, args.offset, args.overwrite, args.line_width,
                 args.hud_scale, args.video, args.reticle, args.reticle_gain, args.reticle_range,
                 args.pose_model if args.pose else None,args.pose_interval,args.pose_confidence,args.pose_device,
                 args.self_destruct_last,args.self_destruct_at,not args.no_self_destruct,
                 not args.no_release_prompt,args.release_follow_speed,args.pose_imgsz,args.mask_format)
        else:
            produce(args, args.video, args.srt, args.output)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(f"错误：{error}") from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None


def produce(args, video, srt, output):
    info = probe(video)
    hud_path = output.with_name(output.stem+"_mask.mov")
    check_output(output, [video, srt, hud_path], args.overwrite)
    render_mask(srt, hud_path, args.width or info["width"], args.height or info["height"],
         args.fps or info["fps"], min(args.duration or info["duration"], info["duration"]),
         args.opacity, args.window, args.offset, args.overwrite, args.line_width, args.hud_scale, video, args.reticle,
         args.reticle_gain,args.reticle_range,args.pose_model if args.pose else None,
         args.pose_interval,args.pose_confidence,args.pose_device,
         args.self_destruct_last,args.self_destruct_at,not args.no_self_destruct,
         not args.no_release_prompt,args.release_follow_speed,args.pose_imgsz)
    overlay(video, hud_path, output, args.overwrite, args.duration, args.encoder, args.crf)


_COMMAND_HELP = {
    "mask": "生成透明 MOV、绿幕视频或 PNG 序列。",
    "render": "生成透明 mask 并合成视频。",
    "preview": "导出单帧透明 PNG。",
    "batch": "批量配对同名视频和 SRT。",
    "analyze": "导出 Fusion Fuse 使用的遥测、运动和人物缓存。",
    "overlay": "使用已有透明 mask 合成视频。",
}


def _command(name, description):
    """Expose shared defaults through real function signatures for Fire help."""
    def command(*args, **kwargs):
        values = command.__signature__.bind(*args, **kwargs).arguments
        _run(name, **values)

    required = {"srt", "output"}
    if name in ("render", "analyze"):
        required.add("video")
    elif name == "overlay":
        required = {"video", "mask", "output"}
    parameters = []
    for parameter in list(signature(_run).parameters.values())[1:]:
        key = parameter.name
        if key == "directory":
            if name == "batch":
                parameters.insert(0, parameter.replace(default=Parameter.empty))
            continue
        if key == "output_dir" and name != "batch":
            continue
        if name == "batch" and key in ("srt", "video", "output", "mask"):
            continue
        if name == "overlay" and key not in ("video", "mask", "output", "duration", "overwrite", "encoder", "crf"):
            continue
        if key == "mask" and name != "overlay":
            continue
        if key == "time" and name != "preview":
            continue
        if key == "mask_format" and name != "mask":
            continue
        if key in ("encoder", "crf") and name not in ("render", "batch", "overlay"):
            continue
        parameters.append(parameter.replace(kind=Parameter.KEYWORD_ONLY,
                          default=Parameter.empty if key in required else parameter.default))
    command.__signature__ = signature(_run).replace(parameters=parameters)
    command.__name__ = name
    command.__doc__ = description
    return command


def main(argv=None):
    """DJI SRT → 游戏无人机 HUD 透明 mask → FFmpeg 合成。"""
    commands = {name: _command(name, description) for name, description in _COMMAND_HELP.items()}
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Keep existing scripts working; Fire's -o is otherwise ambiguous with opacity.
    arguments = ["--output" if arg == "-o" else arg for arg in arguments]
    if arguments and arguments[0] in commands:
        parameters = commands[arguments[0]].__signature__.parameters
        # Fire can call a function before reporting an unconsumed flag. Reject
        # typos first so an invalid export command cannot create or replace files.
        for argument in arguments[1:]:
            if argument == "--":
                break
            if argument.startswith("-") and len(argument) > 1 and argument.lstrip("-")[0].isalpha():
                key = argument.lstrip("-").split("=", 1)[0].replace("-", "_")
                if len(key) == 1:
                    matches = [name for name in parameters if name.startswith(key)]
                    if len(matches) == 1:
                        key = matches[0]
                if key != "help" and key not in parameters and not (key.startswith("no") and key[2:] in parameters):
                    raise SystemExit(f"错误：未知参数 {argument.split('=', 1)[0]}")
    fire.Fire(commands, command=arguments, name="bird-dji")
