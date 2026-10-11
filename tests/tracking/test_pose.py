import unittest
from PIL import Image
from bird_dji.pose import PoseTimeline,Scan,draw_keypoints


class PoseTests(unittest.TestCase):
    def test_one_second_scan_hold_and_missing_detection(self):
        points = [(.5,.5,.9)]
        timeline = PoseTimeline([Scan(0,points,1),Scan(1,[],0),Scan(2,points,1)])
        self.assertEqual(timeline.at(-.1),[])
        self.assertEqual(timeline.at(.999),points)
        self.assertEqual(timeline.at(1),[])
        self.assertEqual(timeline.at(1.999),[])
        self.assertEqual(timeline.at(2),points)
        self.assertEqual(timeline.at(3),[])

    def test_square_coordinates_scale_to_full_frame(self):
        image = draw_keypoints(Image.new("RGBA",(1920,1080)),[(.25,.5,.9)])
        self.assertGreater(image.getpixel((480,540))[3],0)
        self.assertGreater(image.getpixel((475,535))[3],0)
        self.assertEqual(image.getpixel((960,540))[3],0)
        self.assertEqual(image.getpixel((0,0))[3],0)


if __name__ == "__main__":
    unittest.main()
