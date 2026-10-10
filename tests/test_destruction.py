import unittest
from bird_dji.hud import HUD,render_hud,self_destruct_progress
from bird_dji.telemetry import Sample


class DestructionTests(unittest.TestCase):
    def test_last_three_seconds_and_custom_start(self):
        self.assertEqual(self_destruct_progress(6.9,10),0)
        self.assertAlmostEqual(self_destruct_progress(7.06,10),.5)
        self.assertEqual(self_destruct_progress(8,10),1)
        self.assertEqual(self_destruct_progress(8,10,enabled=False),0)
        self.assertEqual(self_destruct_progress(3,10,at=2),1)
        self.assertEqual(self_destruct_progress(1,2),1)

    def test_alarm_is_thinner_fainter_red_and_contains_badge(self):
        normal = HUD(1920,1080)
        alarm = HUD(1920,1080,opacity=.85*.4,line_width=4*.4,color=(235,42,55))
        sample = Sample(0,1)
        a = normal.frame(sample).crop((520,320,620,760))
        b = render_hud(normal,alarm,sample,destruction=1).crop((520,320,620,760))
        self.assertLess(b.getchannel("A").getextrema()[1],a.getchannel("A").getextrema()[1])
        self.assertLess(sum(b.getchannel("A").histogram()[1:]),sum(a.getchannel("A").histogram()[1:]))
        self.assertTrue(any(color==(235,42,55,87) for count,color in b.getcolors(b.width*b.height)))
