from pathlib import Path
import tempfile
import unittest
from bird_dji.telemetry import Sample, Telemetry
from bird_dji.hud import HUD


class TelemetryTests(unittest.TestCase):
    def test_real_dji_fields_and_timestamp(self):
        text = '''1
00:00:01,200 --> 00:00:01,233
<font size="28">FrameCnt: 1, DiffTime: 33ms
2026-10-02 10:25:03.645
[latitude: 26.059150] [longitude: 119.186151] [rel_alt: 2.500 abs_alt: -24.023]</font>

2
00:00:01,233 --> 00:00:01,266
[latitude: 26.059150] [longitude: 119.186151] [rel_alt: 3.500 abs_alt: -23.023]
'''
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory)/"test.srt"
            path.write_text(text, encoding="utf-8-sig")
            telemetry = Telemetry.read(path)
        self.assertEqual(len(telemetry.samples), 2)
        self.assertEqual(telemetry.samples[0].time, 1.2)
        self.assertEqual(telemetry.samples[0].altitude, 2.5)
        self.assertEqual(telemetry.samples[0].speed, 0)
        self.assertIsNone(telemetry.samples[0].heading)
        self.assertIsNone(telemetry.at(0).speed)
        self.assertIsNone(telemetry.at(3).altitude)

    def test_gps_motion_and_missing_gap(self):
        telemetry = Telemetry([Sample(i, i+1, 0, i*.00001) for i in range(5)], 2)
        self.assertAlmostEqual(telemetry.at(2).speed, 1.11195, places=4)
        self.assertAlmostEqual(telemetry.at(2).heading, 90)
        missing = Telemetry([Sample(0,.1,0,0), Sample(4,4.1,0,.1)], 10)
        self.assertIsNone(missing.at(0).speed)

    def test_heading_interpolates_across_north(self):
        telemetry = Telemetry([Sample(0,1,speed=3,heading=359), Sample(1,2,speed=5,heading=1)])
        self.assertAlmostEqual(telemetry.at(.5).heading, 0)
        self.assertAlmostEqual(telemetry.at(.5).speed, 4)

    def test_mask_is_transparent_and_contains_only_overlay(self):
        image = HUD(1920,1080).frame(Sample(0,1,speed=10,heading=180,altitude=2))
        self.assertEqual(image.mode,"RGBA")
        self.assertEqual(image.getpixel((0,0))[3],0)
        self.assertEqual(image.getpixel((960,540))[3],0)
        self.assertGreater(image.getpixel((960,558))[3],0)
        self.assertLess(image.getchannel("A").getextrema()[1],255)

    def test_full_speed_mapping_and_zero_clip(self):
        telemetry = Telemetry([Sample(0,1,speed=.1),Sample(1,2,speed=.6)])
        hud = HUD(1920,1080,max_speed=telemetry.max_speed)
        self.assertEqual(hud.speed_y(.6),hud.y1)
        self.assertEqual(hud.speed_y(0),hud.y2)
        self.assertAlmostEqual(hud.speed_y(.3),(hud.y1+hud.y2)/2)
        self.assertEqual(HUD(1920,1080,max_speed=0).speed_y(0),hud.y2)

    def test_compact_layout_and_moving_reticle(self):
        hud = HUD(1920,1080)
        x0,y0 = hud.reticle_position((0,0))
        x1,y1 = hud.reticle_position((1,-1))
        self.assertGreater(x1,x0)
        self.assertLess(y1,y0)
        self.assertGreater(x1-x0,hud.layout_width*.15)
        self.assertGreater(y0-y1,hud.layout_height*.15)
        self.assertEqual(hud.reticle_position((100,-100)),(x1,y1))
        sample = Sample(0,1,speed=.5)
        self.assertNotEqual(hud.frame(sample).tobytes(),hud.frame(sample,(1,-1)).tobytes())
        bounds = hud.frame(sample).getchannel("A").getbbox()
        self.assertGreater(bounds[0],1920*.17)
        self.assertLess(bounds[2],1920*.83)

    def test_relative_compass_rotates_even_without_gps_heading(self):
        hud = HUD(1920,1080)
        sample = Sample(0,1)
        a = hud.frame(sample,visual_heading=0).crop((650,200,1270,330))
        b = hud.frame(sample,visual_heading=20).crop((650,200,1270,330))
        self.assertNotEqual(a.tobytes(),b.tobytes())

    def test_life_bar_full_half_and_empty(self):
        hud = HUD(1920,1080)
        sample = Sample(0,1)
        y = round(hud.oy+hud.layout_height*.90)
        left = round(hud.ox+hud.layout_width*.35)
        right = round(hud.ox+hud.layout_width*.65)
        counts = []
        for life in (1,.5,0):
            image = hud.frame(sample,health=life)
            counts.append(sum(image.getpixel((x,y))[3]==hud.ink[3] for x in range(left,right)))
        self.assertGreater(counts[0],350)
        self.assertAlmostEqual(counts[1]/counts[0],.5,delta=.01)
        self.assertEqual(counts[2],0)


if __name__ == "__main__":
    unittest.main()
