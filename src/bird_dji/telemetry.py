"""DJI SRT parsing and conservative GPS-derived horizontal telemetry."""
from bisect import bisect_right
from dataclasses import dataclass
import math
from pathlib import Path
import re


@dataclass
class Sample:
    time: float
    end: float
    lat: float | None = None
    lon: float | None = None
    speed: float | None = None
    heading: float | None = None
    altitude: float | None = None


def seconds(value: str) -> float:
    h, m, s = value.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def displacement(a: Sample, b: Sample) -> tuple[float, float]:
    """Return distance in metres and initial GPS bearing, clockwise from north."""
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dl = math.radians(b.lon - a.lon)
    dp = p2 - p1
    hav = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    distance = 6371008.8 * 2 * math.asin(math.sqrt(min(1, max(0, hav))))
    bearing = math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
                                     math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360
    return distance, bearing


class Telemetry:
    def __init__(self, samples: list[Sample], window: float = 1.0):
        if not samples:
            raise ValueError("SRT 中没有可读取的字幕时间段")
        self.samples = sorted(samples, key=lambda s: s.time)
        self.times = [s.time for s in self.samples]
        self.duration = max(s.end for s in self.samples)
        for sample in self.samples:
            if sample.lat is None or sample.lon is None:
                continue
            lo = max(0, bisect_right(self.times, sample.time - window / 2) - 1)
            hi = min(len(self.times) - 1, bisect_right(self.times, sample.time + window / 2))
            a, b = self.samples[lo], self.samples[hi]
            dt = b.time - a.time
            if dt <= 0 or any(v is None for v in (a.lat, a.lon, b.lat, b.lon)):
                continue
            # Do not estimate across a missing telemetry section.
            if any(self.samples[i + 1].time - self.samples[i].end > 0.2 for i in range(lo, hi)):
                continue
            distance, bearing = displacement(a, b)
            if sample.speed is None:
                sample.speed = distance / dt
            # Small GPS movements cannot determine a reliable track direction.
            if sample.heading is None and distance >= 0.5 and distance / dt >= 0.5:
                sample.heading = bearing
        self.max_speed = max((s.speed for s in self.samples if s.speed is not None), default=0.0)

    @classmethod
    def read(cls, path: Path, window: float = 1.0):
        raw = path.read_bytes()
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        text = raw.decode(encoding)
        samples = []
        pattern = r"(\d{2}:\d{2}:\d{2}[,.]\d+)\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d+)([^\n]*\n.*?)(?=\n\s*\n|\Z)"
        for match in re.finditer(pattern, text.replace("\r\n", "\n"), re.S):
            body = re.sub(r"<[^>]*>", "", match[3])
            fields = {key.lower(): float(value) for key, value in re.findall(
                r"([A-Za-z_]+)\s*:\s*([-+]?\d+(?:\.\d+)?)", body)}
            def get(*names):
                return next((fields[n] for n in names if n in fields), None)
            lat, lon = get("latitude", "lat"), get("longitude", "lon", "lng")
            # Older DJI files sometimes use GPS(longitude,latitude,altitude).
            gps = re.search(r"GPS\s*\(\s*([-+\d.]+)\s*,\s*([-+\d.]+)", body, re.I)
            if gps and lat is None and lon is None:
                lon, lat = float(gps[1]), float(gps[2])
            if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                lat = lon = None
            speed = get("h_speed", "hspeed", "horizontal_speed")
            heading = get("yaw", "heading", "flight_yaw")
            samples.append(Sample(seconds(match[1]), seconds(match[2]), lat, lon,
                                  speed if speed is None or speed >= 0 else None,
                                  heading % 360 if heading is not None else None,
                                  get("rel_alt", "relative_altitude", "height")))
        return cls(samples, window)

    def at(self, time: float) -> Sample:
        index = bisect_right(self.times, time) - 1
        if index < 0 or time >= self.samples[index].end + 0.1:
            return Sample(time, time)
        a = self.samples[index]
        if index + 1 == len(self.samples) or time >= a.end:
            return a
        b = self.samples[index + 1]
        if b.time <= a.time or b.time - a.end > 0.1:
            return a
        ratio = min(1, max(0, (time - a.time) / (b.time - a.time)))
        speed = None if a.speed is None else a.speed
        if a.speed is not None and b.speed is not None:
            speed = a.speed + (b.speed - a.speed) * ratio
        heading = a.heading
        if a.heading is not None and b.heading is not None:
            heading = (a.heading + ((b.heading - a.heading + 180) % 360 - 180) * ratio) % 360
        altitude = a.altitude
        if a.altitude is not None and b.altitude is not None:
            altitude += (b.altitude-a.altitude) * ratio
        return Sample(time, time, speed=speed, heading=heading, altitude=altitude)
