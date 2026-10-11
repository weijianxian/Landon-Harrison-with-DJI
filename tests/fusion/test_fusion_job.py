import json
import shutil
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bird_dji.fusion_job import prepare, run_job, resolve_device


class FusionJobTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root/'插件目录'
        (self.bundle/'models').mkdir(parents=True)
        (self.bundle/'models/yolov8n-pose.pt').write_bytes(b'model fixture')
        video = self.root/'无人机.mp4'
        video.write_bytes(b'video fixture')
        video.with_suffix('.SRT').write_text('subtitle',encoding='utf-8')
        self.job = dict(video=str(video),bundle_dir=str(self.bundle),cache_dir=str(self.root/'cache'),device='cpu')
        self.job_file = self.root/'job.json'

    def write_job(self):
        self.job_file.write_text(json.dumps(self.job,ensure_ascii=False),encoding='utf-8')

    def test_bundle_model_pairing_and_analysis_rate_change_cache_identity(self):
        video,srt,output,options = prepare(self.job)
        self.assertEqual(srt,video.with_suffix('.SRT'))
        self.assertEqual(options['pose_model'],self.bundle/'models/yolov8n-pose.pt')
        self.assertEqual(options['pose_interval'],2)
        self.job['detection_rate'] = 2
        _,_,faster,faster_options = prepare(self.job)
        self.assertEqual(faster_options['pose_interval'],.5)
        self.assertNotEqual(output,faster)
        self.job['result_rate'] = .5
        self.assertEqual(prepare(self.job)[2],faster)
        self.job['detection_rate'] = float('nan')
        with self.assertRaisesRegex(ValueError,'detection_rate'):
            prepare(self.job)

    def test_reuse_and_failed_forced_analysis_preserve_usable_cache(self):
        output = prepare(self.job)[2]
        previous = json.dumps(dict(schema='bird-dji.fusion.v1',frame_count=1))
        output.write_text(previous,encoding='utf-8')
        self.write_job()
        with patch('bird_dji.fusion_job.analyze') as analyzer:
            self.assertTrue(run_job(self.job_file))
            analyzer.assert_not_called()
        result = Path(str(self.job_file)+'.result')
        self.assertEqual(result.read_text(encoding='utf-8').splitlines()[:2],['OK',str(output)])
        self.job['force'] = True
        self.write_job()
        with patch('bird_dji.fusion_job.analyze',side_effect=ValueError('broken detector')):
            self.assertFalse(run_job(self.job_file))
        self.assertEqual(output.read_text(encoding='utf-8'),previous)
        self.assertFalse(output.with_suffix('.lock').exists())
        self.assertIn('ERROR\n\nbroken detector',result.read_text(encoding='utf-8'))

    def test_disabled_pose_needs_no_model_and_existing_lock_is_preserved(self):
        self.job.update(pose_enabled=False,model='missing.pt')
        self.assertIsNone(prepare(self.job)[3]['pose_model'])
        output = prepare(self.job)[2]
        lock = output.with_suffix('.lock')
        lock.write_text('other active job',encoding='utf-8')
        self.write_job()
        with patch('bird_dji.fusion_job.analyze') as analyzer:
            self.assertFalse(run_job(self.job_file))
            analyzer.assert_not_called()
        self.assertEqual(lock.read_text(encoding='utf-8'),'other active job')

    def test_auto_device_selects_available_cuda_and_falls_back_to_cpu(self):
        for available,expected in ((True,'0'),(False,'cpu')):
            with patch.dict('sys.modules',torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:available))):
                self.assertEqual(resolve_device(),expected)
        self.assertEqual(resolve_device('auto',False),'cpu')
        self.assertEqual(resolve_device('1'),'1')

    def test_hidden_bootstrap_returns_worker_error_and_captures_log(self):
        launcher = self.bundle/'launch-analysis.py'
        shutil.copyfile(Path(__file__).resolve().parents[2]/'fusion/launch-analysis.py',launcher)
        self.job['video'] = str(self.root/'missing-video.mp4')
        self.write_job()
        process = subprocess.run([sys.executable,'-I',str(launcher),'--job',str(self.job_file)],
                                 capture_output=True,text=True)
        self.assertEqual(process.returncode,1)
        self.assertEqual(process.stdout,'')
        self.assertEqual(process.stderr,'')
        result = Path(str(self.job_file)+'.result').read_text(encoding='utf-8')
        self.assertTrue(result.startswith('ERROR\n\n'))
        self.assertIn('missing-video.mp4',result)
        self.assertTrue(Path(str(self.job_file)+'.log').is_file())
