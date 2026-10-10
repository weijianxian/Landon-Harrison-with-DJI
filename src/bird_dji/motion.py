"""Estimate a bounded look indicator from image motion, not aircraft GPS track."""
from bisect import bisect_right
from dataclasses import dataclass
import math
from pathlib import Path
import subprocess
import tempfile
import cv2
import numpy as np


@dataclass
class Look:
    time: float
    x: float = 0
    y: float = 0
    heading: float = 0


class CameraMotion:
    def __init__(self, samples: list[Look]):
        self.samples = samples
        self.times = [s.time for s in samples]

    def at(self, time: float) -> tuple[float, float]:
        i = bisect_right(self.times, time)-1
        if i < 0 or not self.samples:
            return 0, 0
        a = self.samples[i]
        if i+1 >= len(self.samples):
            return a.x, a.y
        b = self.samples[i+1]
        ratio = (time-a.time)/(b.time-a.time)
        return a.x+(b.x-a.x)*ratio, a.y+(b.y-a.y)*ratio

    def heading_at(self, time: float) -> float:
        """Continuous relative visual direction; it does not recenter on release."""
        i = bisect_right(self.times,time)-1
        if i < 0 or not self.samples:
            return 0
        a = self.samples[i]
        if i+1 >= len(self.samples):
            return a.heading
        b = self.samples[i+1]
        ratio = (time-a.time)/(b.time-a.time)
        return a.heading+(b.heading-a.heading)*ratio

    @classmethod
    def read(cls, video: Path, duration: float, gain: float = 12):
        from .video import binary
        width, height, fps = 320, 180, 10
        command = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", str(video),
                   "-t", str(duration), "-vf", f"fps={fps},scale={width}:{height}",
                   "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"]
        samples = []
        previous = None
        x = y = heading = 0.0
        print("分析画面运动（圆圈方向为视觉估计）…", flush=True)
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
            try:
                while True:
                    raw = process.stdout.read(width*height)
                    if not raw:
                        break
                    if len(raw) != width*height:
                        raise ValueError("读取镜头分析帧失败")
                    current = np.frombuffer(raw, dtype=np.uint8).reshape(height,width)
                    tx = ty = 0.0
                    if previous is not None:
                        points = cv2.goodFeaturesToTrack(previous, maxCorners=250, qualityLevel=.02, minDistance=8)
                        if points is not None and len(points) >= 12:
                            following, status, _ = cv2.calcOpticalFlowPyrLK(previous, current, points, None)
                            if following is not None:
                                valid = status.ravel() == 1
                                a, b = points[valid].reshape(-1,2), following[valid].reshape(-1,2)
                                if len(a) >= 12:
                                    affine, inliers = cv2.estimateAffinePartial2D(a,b,method=cv2.RANSAC,ransacReprojThreshold=2)
                                    if affine is not None and inliers.sum() >= max(12,len(a)*.45):
                                        # Evaluate global scene shift at the optical centre. Moving
                                        # foreground subjects are rejected by the robust fit.
                                        centre = np.array([width/2,height/2])
                                        shift = affine[:,:2] @ centre + affine[:,2]-centre
                                        if np.linalg.norm(shift) < width*.12 and .9 < math.hypot(affine[0,0],affine[1,0]) < 1.1:
                                            tx = float(np.clip(-shift[0]/width*fps*gain,-1,1))
                                            ty = float(np.clip(-shift[1]/height*fps*gain,-1,1))
                                            # An artistic relative compass: a full-width scene
                                            # shift maps to 180 degrees. This is not calibrated yaw.
                                            heading += float(-shift[0]/width*180)
                    # Fast response to turning, slower spring-like release toward centre.
                    # Reversing direction should respond promptly rather than linger.
                    def follow(value, target):
                        responding = abs(target) > abs(value) or value*target < 0
                        tau = .18 if responding else .8
                        return value + (1-math.exp(-1/fps/tau))*(target-value)
                    x = follow(x,tx)
                    y = follow(y,ty)
                    samples.append(Look(len(samples)/fps,x,y,heading))
                    previous = current
                process.stdout.close()
                code = process.wait()
                if code:
                    errors.seek(0)
                    raise ValueError(errors.read().decode("utf-8",errors="replace"))
            except BaseException:
                if process.poll() is None:
                    process.kill()
                process.wait()
                raise
        return cls(samples)
