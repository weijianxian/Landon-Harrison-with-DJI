import math
import unittest
from bird_dji.pose import PersonBox
from bird_dji.release import ReleasePrompt


class ReleaseTests(unittest.TestCase):
    def test_nearest_initial_bbox_centre_and_bounded_follow(self):
        prompt = ReleasePrompt(1920,1080,speed=180)
        box = PersonBox(1,.4,.4,.7,.7)
        start = prompt.update(0,[box],(.1,.1))
        self.assertAlmostEqual(start[0],1056)
        self.assertAlmostEqual(start[1],594)
        moved = PersonBox(1,.45,.4,.75,.7)
        end = prompt.update(1/30,[moved],(.5,.5))
        self.assertGreater(end[0],start[0])
        self.assertLessEqual(math.dist(start,end),180/30+1e-8)
        self.assertIsNone(prompt.update(.2,[],(.5,.5)))

    def test_switch_target_resets_to_new_bbox_centre(self):
        prompt = ReleasePrompt(1920,1080)
        prompt.update(0,[PersonBox(1,.4,.4,.6,.6)],(.5,.5))
        centre = prompt.update(1,[PersonBox(2,.7,.4,.9,.6)],(.8,.5))
        self.assertEqual(centre,(1536,540))
        self.assertEqual(len(prompt.events),2)

    def test_nearest_person_does_not_require_aim_inside_bbox(self):
        prompt = ReleasePrompt(1920,1080)
        boxes = [PersonBox(1,.2,.4,.3,.6),PersonBox(2,.7,.4,.8,.6)]
        prompt.update(0,boxes,(.6,.5))
        self.assertEqual(prompt.track,2)
        prompt.update(1,boxes,(.4,.5))
        self.assertEqual(prompt.track,1)
