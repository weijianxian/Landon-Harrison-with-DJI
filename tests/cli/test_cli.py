import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from bird_dji.cli import main


class CLITests(unittest.TestCase):
    def invoke(self, *arguments):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            main(list(arguments))

    def test_help_lists_all_commands_without_running_analysis(self):
        result = subprocess.run(
            [sys.executable, "-m", "bird_dji", "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("mask", "render", "preview", "batch", "analyze", "overlay"):
            self.assertIn(command, result.stdout + result.stderr)

    def test_command_help_exposes_defaults_and_required_paths(self):
        result = subprocess.run(
            [sys.executable, "-m", "bird_dji", "mask", "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        help_text = result.stdout + result.stderr
        for flag in ("--srt", "--output", "--line_width", "--pose_interval", "--no_self_destruct"):
            self.assertIn(flag, help_text)
        self.assertIn("Default: 2", help_text)

    def test_mask_preserves_short_output_hyphenated_flags_and_literal_fps(self):
        with patch("bird_dji.cli.render_mask") as renderer:
            self.invoke("mask", "--srt", "遥测.srt", "-o", "frames", "--fps", "30",
                        "--width", "320", "--height", "180", "--mask-format", "png",
                        "--reticle", "fixed", "--line-width", "6", "--no-self-destruct",
                        "--overwrite")
        args = renderer.call_args.args
        self.assertEqual(args[:6], (Path("遥测.srt"), Path("frames"), 320, 180, "30", None))
        self.assertEqual(args[10], 6)
        self.assertTrue(args[9])
        self.assertFalse(args[22])
        self.assertEqual(args[-1], "png")

    def test_overlay_uses_existing_mask_without_generating_another(self):
        with patch("bird_dji.cli.overlay") as overlay, patch("bird_dji.cli.render_mask") as mask:
            self.invoke("overlay", "--video", "clip.mp4", "--mask", "alpha.mov",
                        "-o", "combined.mp4", "--duration", "2", "--encoder", "h264_nvenc")
        overlay.assert_called_once_with(Path("clip.mp4"), Path("alpha.mov"),
                                        Path("combined.mp4"), False, 2, "h264_nvenc", 18)
        mask.assert_not_called()

    def test_batch_keeps_positional_directory_and_case_insensitive_pairing(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory)
            video, srt = root / "clip.MP4", root / "CLIP.srt"
            video.touch()
            srt.touch()
            (root / "unpaired.mov").touch()
            with patch("bird_dji.cli.produce") as produce:
                self.invoke("batch", str(root), "--output-dir", str(root / "result"),
                            "--pose", "--pose-interval", "0.5", "--encoder", "h264_nvenc")
            options, actual_video, actual_srt, output = produce.call_args.args
            self.assertEqual((actual_video, actual_srt, output),
                             (video, srt, root / "result/clip_hud.mp4"))
            self.assertTrue(options.pose)
            self.assertEqual(options.pose_interval, .5)
            self.assertEqual(options.encoder, "h264_nvenc")
            produce.assert_called_once()

    def test_render_preserves_fractional_fps_and_detection_defaults(self):
        with patch("bird_dji.cli.probe", return_value={}), patch("bird_dji.cli.produce") as produce:
            self.invoke("render", "--video", "clip.mp4", "--srt", "clip.srt",
                        "--output", "combined.mp4", "--fps", "30000/1001")
        options, video, srt, output = produce.call_args.args
        self.assertEqual(options.fps, "30000/1001")
        self.assertEqual(options.pose_interval, 2)
        self.assertEqual((video, srt, output),
                         (Path("clip.mp4"), Path("clip.srt"), Path("combined.mp4")))

    def test_analysis_preserves_pose_flags_and_numeric_cuda_device(self):
        with patch("bird_dji.analysis.analyze") as analyze:
            self.invoke("analyze", "--video", "clip.mp4", "--srt", "clip.srt",
                        "-o", "analysis.json", "--pose", "--pose-device", "0",
                        "--pose-interval", "0.25", "--duration", "10", "--overwrite")
        self.assertEqual(analyze.call_args.args,
                         (Path("clip.mp4"), Path("clip.srt"), Path("analysis.json")))
        self.assertEqual(analyze.call_args.kwargs["pose_device"], "0")
        self.assertEqual(analyze.call_args.kwargs["pose_model"], Path("models/yolov8n-pose.pt"))
        self.assertEqual(analyze.call_args.kwargs["pose_interval"], .25)
        self.assertTrue(analyze.call_args.kwargs["overwrite"])

    def test_invalid_options_fail_before_media_is_read_or_written(self):
        invalid = [("--mask-format", "jpeg"), ("--reticle", "random"),
                   ("--encoder", "invalid"), ("--opacity", "2"), ("--width", "320"),
                   ("--pose",)]
        with patch("bird_dji.cli.render_mask") as mask, patch("bird_dji.cli.probe") as probe:
            for flags in invalid:
                with self.subTest(flags=flags), self.assertRaises(SystemExit) as error:
                    self.invoke("mask", "--srt", "clip.srt", "-o", "alpha.mov", *flags)
                self.assertIn("错误：", str(error.exception))
        mask.assert_not_called()
        probe.assert_not_called()

    def test_required_paths_fail_before_render(self):
        with patch("bird_dji.cli.produce") as produce:
            for command in ("render", "analyze", "overlay"):
                with self.subTest(command=command), self.assertRaises(SystemExit):
                    self.invoke(command, "--output", "out.mp4")
        produce.assert_not_called()

    def test_misspelled_flag_cannot_create_or_replace_an_output(self):
        with patch("bird_dji.cli.render_mask") as mask:
            with self.assertRaisesRegex(SystemExit, "未知参数"):
                self.invoke("mask", "--srt", "clip.srt", "-o", "valuable.mov",
                            "--overwrite", "--line-wdith", "8")
        mask.assert_not_called()

    def test_preview_exports_real_transparent_png(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory)
            srt, output = root / "clip.srt", root / "preview.png"
            srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n[rel_alt: 2] [h_speed: 3]\n",
                           encoding="utf-8")
            self.invoke("preview", "--srt", str(srt), "-o", str(output), "--width", "320",
                        "--height", "180", "--fps", "30", "--no-self-destruct")
            with Image.open(output) as image:
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.size, (320, 180))
                self.assertEqual(image.getpixel((0, 0))[3], 0)
                self.assertGreater(image.getchannel("A").getextrema()[1], 0)
