"""Transparent, resolution-independent rendering of the four requested HUD parts."""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from .telemetry import Sample


class HUD:
    def __init__(self, width: int, height: int, opacity: float = 0.85, line_width: float = 4,
                 hud_scale: float = .65, max_speed: float = 0, reticle_range: float = .18,
                 color: tuple[int,int,int] = (240,248,245), alarm: bool = False):
        self.width, self.height = width, height
        self.scale = min(width / 1920, height / 1080)
        self.hud_scale = hud_scale
        self.max_speed = max_speed
        self.reticle_range = reticle_range
        self.alarm = alarm
        # Compress geometry around the screen centre; keep line thickness readable.
        width, height = width*hud_scale, height*hud_scale
        self.layout_width, self.layout_height = width, height
        self.ox, self.oy = (self.width-width)/2, (self.height-height)/2
        self.ink = (*color, round(255 * opacity))
        self.dim = (*color, round(150 * opacity))
        self.strong = (*color,min(255,round(self.ink[3]*2.1))) if alarm else self.ink
        self.stroke = max(1, round(self.scale * line_width))
        self.bar_width = max(1,round(7*self.scale*(1 if alarm else min(1,line_width/4))))
        fonts = [Path("C:/Windows/Fonts/msyh.ttc"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
        self.chinese = fonts[0].exists()
        font = next((str(p) for p in fonts if p.exists()), None)
        self.font = ImageFont.truetype(font, round(17 * self.scale)) if font else ImageFont.load_default(size=round(17 * self.scale))
        self.small = ImageFont.truetype(font, round(13 * self.scale)) if font else ImageFont.load_default(size=round(13 * self.scale))
        self.base = Image.new("RGBA", (math.ceil(width), math.ceil(height)))
        d = ImageDraw.Draw(self.base)
        cx, cy = width / 2, height / 2
        # Split side arcs, with open notches at the middle.
        rx, ry = width * .33, height * .60
        for side in (-1, 1):
            for start, end in ((-30, -1), (1, 30)):
                points = [(cx + side * rx * math.cos(math.radians(t)),
                           cy + ry * math.sin(math.radians(t))) for t in range(start, end + 1)]
                d.line(points, fill=self.ink, width=self.stroke)
                px, py = points[0] if start == -30 else points[-1]
                d.line((px, py, px-side*7*self.scale, py), fill=self.ink, width=self.stroke)
            d.line((cx+side*rx, cy-5*self.scale, cx+side*(rx-8*self.scale), cy-5*self.scale), fill=self.ink, width=self.stroke)
            d.line((cx+side*rx, cy+5*self.scale, cx+side*(rx-8*self.scale), cy+5*self.scale), fill=self.ink, width=self.stroke)
            d.line((cx+side*width*.155, cy, cx+side*width*.165, cy), fill=self.strong, width=self.stroke)
            d.line((cx+side*width*.18, cy, cx+side*width*.225, cy), fill=self.strong, width=self.stroke)
        self.x = width * .085
        self.y1, self.y2 = height * .31, height * .74
        d.text((self.x, self.y1-40*self.scale), "SPD", font=self.font, fill=self.ink, anchor="mm")
        d.line((self.x, self.y1, self.x, self.y2), fill=self.dim, width=self.stroke)
        for y in (self.y1, self.y2):
            d.line((self.x-5*self.scale, y, self.x+5*self.scale, y), fill=self.ink, width=self.stroke)
        self.ax = width * .915
        d.text((self.ax, self.y1-40*self.scale), "ALT", font=self.font, fill=self.ink, anchor="mm")
        for i in range(25):
            y = self.y1 + (self.y2-self.y1)*i/24
            d.line((self.ax-3*self.scale, y, self.ax+3*self.scale, y), fill=self.dim, width=self.stroke)
        for y in (self.y1, self.y2):
            d.line((self.ax-5*self.scale, y, self.ax+5*self.scale, y), fill=self.ink, width=self.stroke)
        for x in (width*.32, width*.68):
            d.line((x, height*.895, x, height*.905), fill=self.ink, width=self.stroke)
        for x in (width*.15, width*.85):
            for y in (height*.11, height*.95):
                r = 4*self.scale
                d.rectangle((x-r,y-r,x+r,y+r), outline=self.dim, width=self.stroke)

    def speed_y(self, speed: float | None) -> float:
        fraction = 0 if speed is None or self.max_speed <= 0 else min(1,max(0,speed/self.max_speed))
        return self.y2-fraction*(self.y2-self.y1)

    def reticle_position(self, look: tuple[float,float]) -> tuple[float,float]:
        return (self.layout_width/2 + max(-1,min(1,look[0]))*self.layout_width*self.reticle_range,
                self.layout_height/2 + max(-1,min(1,look[1]))*self.layout_height*self.reticle_range)

    def frame(self, sample: Sample, look: tuple[float,float] = (0,0),
              visual_heading: float | None = None, health: float = 1):
        im = self.base.copy()
        d = ImageDraw.Draw(im)
        s, w, h = self.scale, self.layout_width, self.layout_height
        # Fill shrinks symmetrically toward the centre; retain a faint empty rail.
        life = max(0,min(1,health))
        left, right, y = w*.35,w*.65,h*.90
        bar_width = self.bar_width
        d.line((left,y,right,y),fill=(*self.ink[:3],round(self.ink[3]*.22)),width=bar_width)
        if life > 0:
            midpoint = (left+right)/2
            half_fill = (right-left)*life/2
            d.line((midpoint-half_fill,y,midpoint+half_fill,y),fill=self.strong,width=bar_width)
        cx, cy = self.reticle_position(look)
        r = 18*s
        centre_x, centre_y = w/2, h/2
        dx, dy = cx-centre_x, cy-centre_y
        distance = math.hypot(dx,dy)
        # Tether the look indicator to the optical centre, stopping at the
        # near edge of the ring so its hollow centre stays clear.
        if distance > r+self.stroke:
            end_x = cx-dx/distance*r
            end_y = cy-dy/distance*r
            d.line((centre_x,centre_y,end_x,end_y), fill=self.dim if self.alarm else self.ink,
                   width=max(1,self.stroke//2))
        d.ellipse((cx-r,cy-r,cx+r,cy+r), outline=self.dim if self.alarm else self.ink, width=self.stroke)
        # Each clip's maximum speed is full scale, with a safe all-zero case.
        speed = sample.speed
        y = self.speed_y(speed)
        if speed is not None:
            d.line((self.x, self.y2, self.x, y), fill=self.strong, width=self.stroke)
            d.polygon([(self.x+8*s, y), (self.x+17*s, y-5*s), (self.x+17*s, y+5*s)], fill=self.strong)
        bx = self.x-47*s
        d.rectangle((bx-34*s, y-12*s, bx+34*s, y+12*s), outline=self.dim, width=self.stroke)
        d.text((bx, y), "--" if speed is None else f"{speed:.1f}", fill=self.ink, font=self.font, anchor="mm")
        d.text((bx, y+23*s), "M/S", fill=self.ink, font=self.small, anchor="mm")
        altitude = sample.altitude
        ay = self.y2 if altitude is None else self.y2 - min(1, max(0, altitude/100))*(self.y2-self.y1)
        if altitude is not None:
            d.polygon([(self.ax-9*s, ay), (self.ax-18*s, ay-5*s), (self.ax-18*s, ay+5*s)], fill=self.ink)
            d.rectangle((self.ax-2*s, ay-2*s, self.ax+2*s, ay+2*s), fill=self.ink)
        abx = self.ax+48*s
        d.rectangle((abx-34*s, ay-12*s, abx+34*s, ay+12*s), outline=self.dim, width=self.stroke)
        d.text((abx, ay), "--" if altitude is None else f"{altitude:.0f}", fill=self.ink, font=self.font, anchor="mm")
        d.text((abx, ay+23*s), "M", fill=self.ink, font=self.small, anchor="mm")
        # Sliding compass ribbon, with the wrap at north handled explicitly.
        cx, top = w/2, h*.10
        relative = visual_heading is not None
        heading = visual_heading if relative else sample.heading
        degrees = heading if heading is not None else 0
        spacing = w*.35/120
        for tick in range(math.floor((degrees-60)/5)*5, math.ceil((degrees+60)/5)*5+1, 5):
            x = cx + (tick-degrees)*spacing
            if abs(x-cx) > w*.175:
                continue
            major = tick % 30 == 0
            d.line((x, top, x, top+(8 if major else 4)*s), fill=self.ink if heading is not None else self.dim, width=self.stroke)
            if major and heading is not None:
                cardinal = {0:"北",90:"东",180:"南",270:"西"} if self.chinese else {0:"N",90:"E",180:"S",270:"W"}
                if relative:
                    value = (tick+180)%360-180
                    label = f"{value:+d}°" if value else "0°"
                else:
                    label = cardinal.get(tick%360, f"{tick%360:03}")
                d.text((x, top-16*s), label, font=self.font, fill=self.ink, anchor="mm")
        d.polygon([(cx, top+17*s), (cx-4*s, top+25*s), (cx+4*s, top+25*s)], fill=self.ink)
        d.text((cx, top-17*s), "--" if heading is None else "", font=self.font, fill=self.ink, anchor="mm")
        canvas = Image.new("RGBA", (self.width,self.height))
        canvas.paste(im,(round(self.ox),round(self.oy)))
        return canvas

    def self_destruct_badge(self, image):
        d = ImageDraw.Draw(image)
        s = self.scale
        x,y = self.width/2,self.oy+self.layout_height*.79
        half = 70*s if self.chinese else 96*s
        d.rectangle((x-half,y-14*s,x+half,y+14*s),fill=(210,20,25,220))
        tx = x-half+16*s
        d.polygon([(tx,y-10*s),(tx-10*s,y+9*s),(tx+10*s,y+9*s)],fill=(15,2,2,245))
        d.line((tx,y-4*s,tx,y+2*s),fill=(245,75,70,255),width=max(1,round(2*s)))
        d.ellipse((tx-s,y+5*s,tx+s,y+7*s),fill=(245,75,70,255))
        d.text((x+10*s,y),"自毁模式" if self.chinese else "SELF DESTRUCT",font=self.font,fill=(255,215,215,235),anchor="mm")
        return image


def self_destruct_progress(time: float, duration: float, last: float = 3,
                           at: float | None = None, enabled: bool = True) -> float:
    if not enabled:
        return 0
    start = max(0,duration-last) if at is None else at
    t = min(1,max(0,(time-start)/.12))
    return t*t*(3-2*t)


def render_hud(normal: HUD, danger: HUD, sample: Sample, look=(0,0),
               heading=None, health=1, destruction=0):
    if destruction <= 0:
        return normal.frame(sample,look,heading,health)
    alarm = danger.frame(sample,look,heading,health)
    if destruction < 1:
        alarm = Image.blend(normal.frame(sample,look,heading,health),alarm,destruction)
    return danger.self_destruct_badge(alarm)
