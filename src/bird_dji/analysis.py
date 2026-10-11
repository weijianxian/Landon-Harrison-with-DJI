"""Export data, not rendered pixels, for the Fusion Fuse frontend."""
from bisect import bisect_right
from fractions import Fraction
import json
import math
from pathlib import Path
import tempfile
from .motion import CameraMotion
from .pose import PoseTimeline
from .telemetry import Telemetry
from .video import check_output, probe


def analyze(video: Path, srt: Path, output: Path, *, duration=None, window=1,
            offset=0, gain=12, pose_model=None, pose_interval=2,
            pose_confidence=.5, pose_device="cpu", pose_imgsz=960, overwrite=False):
    if output.suffix.lower() != ".json":
        raise ValueError("Fusion 分析缓存请使用 .json")
    check_output(output,[video,srt],overwrite)
    info = probe(video)
    if duration is not None and (not math.isfinite(duration) or duration<=0):
        raise ValueError("分析时长必须为正且有限")
    duration = min(info["duration"],duration if duration is not None else info["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("分析时长必须为正")
    telemetry = Telemetry.read(srt,window)
    motion = CameraMotion.read(video,duration,gain)
    pose = PoseTimeline.read(video,duration,pose_model,pose_interval,pose_confidence,
                             pose_device,pose_imgsz) if pose_model else None
    fps = float(Fraction(info["fps"]))
    frames = []
    count = math.ceil(duration*fps)
    # Container duration is rounded; use a known source frame count to avoid a phantom final frame.
    if info.get("frames",0)>0:
        count = min(count,info["frames"])
    for i in range(count):
        t = i/fps
        sample = telemetry.at(t+offset)
        pose_index = bisect_right(pose.times,t) if pose else 0
        if pose_index and t >= pose.scans[pose_index-1].time+pose.interval:
            pose_index = 0
        frames.append(dict(time=t,speed=sample.speed,altitude=sample.altitude,
                           heading=sample.heading,look=list(motion.at(t)),
                           visual_heading=motion.heading_at(t),pose_scan=pose_index))
    data = dict(schema="bird-dji.fusion.v1",generator="bird-dji",coordinates="normalized-top-left",
                width=info["width"],height=info["height"],fps=info["fps"],duration=duration,
                frame_count=len(frames),max_speed=telemetry.max_speed,
                source=dict(video=video.name,srt=srt.name),
                analysis=dict(window=window,offset=offset,motion_gain=gain,
                              pose_interval=pose_interval,pose_confidence=pose_confidence,
                              pose_imgsz=pose_imgsz,pose_device=pose_device,pose_enabled=pose is not None),
                frames=frames,scans=[dict(time=s.time,points=[list(p) for p in s.points],
                    boxes=[vars(b) for b in s.boxes]) for s in pose.scans] if pose else [])
    # A failed analysis never replaces an existing usable cache.
    with tempfile.TemporaryDirectory(prefix="analysis-",dir=output.parent) as directory:
        staged = Path(directory)/"cache.json"
        staged.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(",",":")),encoding="utf-8")
        staged.replace(output)
    print(f"Fusion 分析缓存：{output}（{len(frames)} 帧，{len(data['scans'])} 次人物扫描）")
    return data
