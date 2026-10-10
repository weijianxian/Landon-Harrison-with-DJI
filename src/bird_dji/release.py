"""Nearest-person visual prompt, with bounded movement and no action binding."""
import math
from PIL import ImageDraw


class ReleasePrompt:
    def __init__(self,width,height,speed=180):
        self.width,self.height = width,height
        self.speed = speed*min(width/1920,height/1080)
        self.track = None
        self.position = None
        self.time = None
        self.events = []

    def update(self,time,boxes,aim):
        dt = max(0,time-self.time) if self.time is not None else 0
        self.time = time
        # Measure screen distance in pixels, not normalised coordinates, so
        # wide frames do not distort which person is visually nearest.
        target = min(boxes,key=lambda b: ((b.centre[0]-aim[0])*self.width)**2+
                     ((b.centre[1]-aim[1])*self.height)**2) if boxes else None
        if target is None:
            self.track = self.position = None
            return None
        desired = (target.centre[0]*self.width,target.centre[1]*self.height)
        if self.track != target.track or self.position is None:
            self.position = desired
            self.track = target.track
            self.events.append({"time":time,"track":target.track,"initial_position":desired})
        else:
            dx,dy = desired[0]-self.position[0],desired[1]-self.position[1]
            distance = math.hypot(dx,dy)
            step = min(distance*(1-math.exp(-dt/.2)),self.speed*dt)
            if distance > 0:
                self.position = self.position[0]+dx/distance*step,self.position[1]+dy/distance*step
        return self.position

    def draw(self,image,hud):
        if self.position is None:
            return image
        d = ImageDraw.Draw(image)
        s = hud.scale
        label = "释放蜂鸟" if hud.chinese else "Release Hummingbird"
        text_width = d.textbbox((0,0),label,font=hud.font)[2]
        total = 25*s+9*s+text_width
        x,y = self.position
        x = max(total/2+2*s,min(self.width-total/2-2*s,x))
        y = max(16*s,min(self.height-16*s,y))
        left = x-total/2
        d.rectangle((left-4*s,y-17*s,left+total+4*s,y+17*s),fill=(12,15,16,110))
        d.rectangle((left,y-13*s,left+25*s,y+13*s),fill=(225,230,227,230))
        d.text((left+12.5*s,y),"X",font=hud.font,fill=(22,25,25,255),anchor="mm")
        d.text((left+34*s,y),label,font=hud.font,fill=(238,241,238,230),anchor="lm")
        return image
