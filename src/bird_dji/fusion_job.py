"""File-based worker for the in-app Fusion analysis button (no Resolve API)."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import tempfile

from .analysis import analyze


def resolve_device(device="auto", enabled=True):
    if not enabled:
        return "cpu"
    if str(device).lower() != "auto":
        return str(device)
    import torch
    return "0" if torch.cuda.is_available() else "cpu"


def _number(job, key, default, low, high):
    value = float(job.get(key, default))
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{key} must be between {low} and {high}")
    return value


def prepare(job):
    video = Path(job["video"]).resolve(strict=True)
    subtitle = job.get("srt", "")
    if subtitle:
        srt = Path(subtitle).resolve(strict=True)
    else:
        srt = next((p for p in video.parent.iterdir()
                    if p.is_file() and p.suffix.lower() == ".srt" and
                    p.stem.lower() == video.stem.lower()), None)
        if srt is None:
            raise ValueError("没有找到同名 SRT，请将 DJI 字幕放在视频旁边")
    rate = _number(job, "detection_rate", .5, 1/60, 120)
    duration = _number(job, "duration", 0, 0, 36000)
    model = Path(job.get("model") or "models/yolov8n-pose.pt")
    if not model.is_absolute():
        model = Path(job["bundle_dir"])/model
    options = dict(duration=duration or None,
        window=_number(job, "window", 1, .01, 60),
        offset=_number(job, "offset", 0, -3600, 3600),
        gain=_number(job, "motion_gain", 12, .01, 100),
        pose_model=model.resolve(strict=True) if job.get("pose_enabled", True) else None,
        pose_interval=1/rate,
        pose_confidence=_number(job, "confidence", .5, .01, 1),
        pose_imgsz=int(_number(job, "image_size", 960, 320, 2560)),
        pose_device=resolve_device(job.get("device", "auto"),job.get("pose_enabled",True)))
    def stamp(path):
        stat = path.stat()
        return [str(path),stat.st_size,stat.st_mtime_ns]
    fingerprint = dict(version=1,video=stamp(video),srt=stamp(srt),
        model=stamp(options["pose_model"]) if options["pose_model"] else None,
        options={k:str(v) if isinstance(v,Path) else v for k,v in options.items()})
    key = hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest()[:20]
    directory = Path(job["cache_dir"]).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    output = directory/f"{video.stem}-{key}.fusion.json"
    return video,srt,output,options


def run_job(job_file):
    job_file = Path(job_file)
    result = Path(str(job_file)+".result")
    lock = None
    owned = False
    try:
        job = json.loads(job_file.read_text(encoding="utf-8-sig"))
        video,srt,output,options = prepare(job)
        if output.is_file():
            try:
                cached = json.loads(output.read_text(encoding="utf-8"))
                usable = cached.get("schema") == "bird-dji.fusion.v1" and cached.get("frame_count",0)>0
            except (ValueError,OSError):
                usable = False
        else:
            usable = False
        if usable and not job.get("force",False):
            message = "已复用分析缓存"
        else:
            lock = output.with_suffix(".lock")
            try:
                with lock.open("x",encoding="utf-8") as f:
                    f.write(str(job_file))
                owned = True
            except FileExistsError:
                raise ValueError("相同素材和参数正在分析，请等待该任务完成") from None
            analyze(video,srt,output,**options,overwrite=True)
            device = "CUDA" if options['pose_device'] != 'cpu' else "CPU"
            message = f"分析完成（{device}），已自动加载"
        content = f"OK\n{output}\n{message}\n"
        success = True
    except Exception as error:
        content = "ERROR\n\n"+str(error).replace("\r"," ").replace("\n"," ")+"\n"
        success = False
    finally:
        if owned:
            lock.unlink(missing_ok=True)
    with tempfile.NamedTemporaryFile(dir=result.parent,delete=False) as f:
        staged = Path(f.name)
        f.write(content.encode("utf-8"))
    staged.replace(result)
    return success


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job",type=Path,required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run_job(args.job) else 1)


if __name__ == "__main__":
    main()
