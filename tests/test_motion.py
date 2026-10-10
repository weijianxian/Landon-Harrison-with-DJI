from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import numpy as np
from bird_dji.motion import CameraMotion


class MotionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"),"FFmpeg required for camera movement test")
    def test_camera_turn_moves_reticle_and_static_scene_recenters(self):
        # Scene shifting left/up corresponds to camera turning right/down.
        rng = np.random.default_rng(42)
        texture = rng.integers(0,256,(180,320),dtype=np.uint8)
        frames = [np.roll(texture,(-min(i,9),-2*min(i,9)),axis=(0,1)) for i in range(30)]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory)/"motion.avi"
            subprocess.run([shutil.which("ffmpeg"),"-hide_banner","-loglevel","error","-y",
                            "-f","rawvideo","-pix_fmt","gray","-s","320x180","-r","10",
                            "-i","pipe:0","-c:v","ffv1",str(path)],
                           input=b"".join(f.tobytes() for f in frames),check=True)
            motion = CameraMotion.read(path,3)
        mx,my = motion.at(.8)
        self.assertGreater(mx,.6)
        self.assertGreater(my,.5)
        # Releasing the controls eases back rather than snapping to centre.
        self.assertGreater(motion.at(1.1)[0],mx*.5)
        self.assertLess(abs(motion.at(2.9)[0]),mx*.15)
        self.assertLess(abs(motion.at(2.9)[1]),my*.15)
        self.assertEqual(motion.at(-1),(0,0))
        self.assertGreater(motion.heading_at(.8),8)
        self.assertAlmostEqual(motion.heading_at(2.9),motion.heading_at(1.2),places=1)
        self.assertEqual(motion.heading_at(-1),0)


if __name__ == "__main__":
    unittest.main()
