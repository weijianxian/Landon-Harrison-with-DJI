import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from PIL import Image
from bird_dji.video import mask


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required for export tests")
class ExportTests(unittest.TestCase):
    def test_encoded_alpha_green_and_png_sequence(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory)
            srt = root/"input.srt"
            srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n[rel_alt: 2] [h_speed: 3]\n",encoding="utf-8")
            def export(path,mode="transparent",duration=.3,overwrite=False):
                mask(srt,path,320,180,"10",duration=duration,reticle="fixed",
                     self_destruct=False,mask_format=mode,overwrite=overwrite)
            def decode(path):
                result = subprocess.run([shutil.which("ffmpeg"),"-v","error","-i",str(path),
                    "-frames:v","1","-f","rawvideo","-pix_fmt","rgba","pipe:1"],
                    capture_output=True,check=True)
                return Image.frombytes("RGBA",(320,180),result.stdout)
            transparent = root/"alpha.mov"
            export(transparent)
            frame = decode(transparent)
            self.assertEqual(frame.getpixel((0,0))[3],0)
            self.assertGreater(frame.getchannel("A").getextrema()[1],0)
            for extension in ("mov","mp4"):
                green = root/f"green.{extension}"
                export(green,"green")
                pixel = decode(green).getpixel((0,0))
                self.assertLess(pixel[0],5)
                self.assertGreater(pixel[1],250)
                self.assertLess(pixel[2],5)
                self.assertEqual(pixel[3],255)
            sequence = root/"frames"
            export(sequence,"png")
            self.assertEqual(len(list(sequence.glob("frame_*.png"))),3)
            with Image.open(sequence/"frame_000001.png") as image:
                self.assertEqual(image.mode,"RGBA")
                self.assertEqual(image.tobytes(),frame.tobytes())
            manifest = json.loads((sequence/"manifest.json").read_text())
            self.assertEqual(manifest["fps"],"10")
            self.assertEqual(manifest["frame_count"],3)
            export(sequence,"png",duration=.1,overwrite=True)
            self.assertEqual(len(list(sequence.glob("frame_*.png"))),1)
            valuable = sequence/"do-not-delete.txt"
            valuable.write_text("keep",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"其他文件"):
                export(sequence,"png",overwrite=True)
            self.assertEqual(valuable.read_text(),"keep")
