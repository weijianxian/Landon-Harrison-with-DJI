"""YOLOv8 pose scans at a configurable rate, reused between scan times."""
from bisect import bisect_right
from dataclasses import dataclass,field
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import cv2
from PIL import ImageDraw


@dataclass
class PersonBox:
    track: int
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def centre(self):
        return (self.x1+self.x2)/2,(self.y1+self.y2)/2

    def contains(self, point, margin=0):
        return self.x1-margin <= point[0] <= self.x2+margin and self.y1-margin <= point[1] <= self.y2+margin


def box_iou(a,b):
    intersection = max(0,min(a.x2,b.x2)-max(a.x1,b.x1))*max(0,min(a.y2,b.y2)-max(a.y1,b.y1))
    union = (a.x2-a.x1)*(a.y2-a.y1)+(b.x2-b.x1)*(b.y2-b.y1)-intersection
    return intersection/union if union > 0 else 0


@dataclass
class Scan:
    time: float
    points: list[tuple[float,float,float]]
    people: int = 0
    boxes: list[PersonBox] = field(default_factory=list)


class PoseTimeline:
    def __init__(self, scans: list[Scan], interval: float = 1):
        self.scans = scans
        self.times = [s.time for s in scans]
        self.interval = interval

    def at(self, time: float):
        i = bisect_right(self.times,time)-1
        if i < 0 or time >= self.scans[i].time+self.interval:
            return []
        return self.scans[i].points

    def boxes_at(self,time: float):
        i = bisect_right(self.times,time)-1
        if i < 0 or time >= self.scans[i].time+self.interval:
            return []
        return self.scans[i].boxes

    @classmethod
    def read(cls, video: Path, duration: float, model_path: Path,
             interval: float = .1, confidence: float = .5, device: str = "cpu", imgsz: int = 960):
        model = load_model(str(model_path.resolve()))
        capture = cv2.VideoCapture(str(video))
        if not capture.isOpened():
            raise ValueError(f"无法打开姿态检测视频：{video}")
        scans = []
        previous_boxes = []
        next_track = 0
        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
            if fps <= 0:
                raise ValueError("无法读取姿态检测视频帧率")
            for i in range(math.ceil(duration/interval)):
                time = i*interval
                capture.set(cv2.CAP_PROP_POS_FRAMES,math.floor(time*fps+1e-6))
                ok, frame = capture.read()
                if not ok:
                    raise ValueError(f"无法读取 {time:.2f} 秒的姿态检测帧")
                # Resize before inference; normalised output coordinates remain
                # independent of the original 4K frame dimensions.
                h,w = frame.shape[:2]
                if max(w,h) > imgsz:
                    frame = cv2.resize(frame,(round(w*imgsz/max(w,h)),round(h*imgsz/max(w,h))))
                result = model.predict(frame, imgsz=imgsz, conf=.35, device=device, verbose=False)[0]
                points = []
                if result.keypoints is not None and result.keypoints.conf is not None:
                    xy = result.keypoints.xyn.cpu().numpy()
                    scores = result.keypoints.conf.cpu().numpy()
                    for person, confidences in zip(xy,scores):
                        for (x,y), score in zip(person,confidences):
                            if score >= confidence and 0 < x < 1 and 0 < y < 1:
                                points.append((float(x),float(y),float(score)))
                people = len(result.boxes) if result.boxes is not None else 0
                boxes = [PersonBox(-1,*map(float,b)) for b in result.boxes.xyxyn.cpu().numpy()] if result.boxes is not None else []
                matches = sorted(((box_iou(a,b),i,j) for i,a in enumerate(previous_boxes) for j,b in enumerate(boxes)),reverse=True)
                used = set()
                for overlap,i,j in matches:
                    if overlap >= .1 and i not in used and boxes[j].track < 0:
                        boxes[j].track = previous_boxes[i].track
                        used.add(i)
                for box in boxes:
                    if box.track < 0:
                        box.track = next_track
                        next_track += 1
                previous_boxes = boxes
                scans.append(Scan(time,points,people,boxes))
                print(f"YOLOv8 扫描 {time:.1f}s：{people} 人 / {len(points)} 个可信关键点",flush=True)
        finally:
            capture.release()
        return cls(scans,interval)

    def save(self, path: Path):
        path.write_text(json.dumps({"interval_seconds":self.interval,"between_scans":"hold_last",
                                   "scans":[{"time":s.time,"people":s.people,"points":s.points,
                                             "boxes":[vars(b) for b in s.boxes]} for s in self.scans]},
                                  ensure_ascii=False,indent=2),encoding="utf-8")


@lru_cache(maxsize=1)
def load_model(path: str):
    if not Path(path).is_file():
        raise ValueError(f"找不到 YOLOv8 模型：{path}，请下载 yolov8n-pose.pt 或用 --pose-model 指定")
    config = Path.cwd()/".ultralytics"
    config.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR",str(config))
    os.environ.setdefault("MPLCONFIGDIR",str(config/"matplotlib"))
    try:
        from ultralytics import YOLO
    except ImportError as error:
        raise ValueError("请先运行 uv sync --extra pose 安装人体姿态检测依赖") from error
    model = YOLO(path,task="pose")
    if model.task != "pose":
        raise ValueError("请提供人体姿态模型，例如 yolov8n-pose.pt")
    return model


def draw_keypoints(image, points: list[tuple[float,float,float]]):
    """Warm square outline, dark translucent backing, and a small centre diamond."""
    d = ImageDraw.Draw(image)
    width,height = image.size
    scale = min(width/1920,height/1080)
    half = max(3,round(5*scale))
    stroke = max(1,round(1.5*scale))
    dot = max(1,round(1.5*scale))
    for nx,ny,_ in points:
        x,y = round(nx*width),round(ny*height)
        d.rectangle((x-half-1,y-half-1,x+half+1,y+half+1),fill=(28,5,2,100),outline=(28,5,2,150),width=stroke)
        d.rectangle((x-half,y-half,x+half,y+half),outline=(255,92,45,235),width=stroke)
        d.polygon([(x,y-dot),(x+dot,y),(x,y+dot),(x-dot,y)],fill=(255,130,85,245))
    return image
