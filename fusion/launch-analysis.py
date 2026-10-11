"""Hidden worker bootstrap; report even import/dependency failures to Fusion."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import os
from pathlib import Path
import runpy
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job',type=Path,required=True)
    job = parser.parse_args().job.resolve()
    bundle = Path(__file__).resolve().parent
    os.chdir(bundle)
    os.environ['PATH'] = str(bundle/'bin')+os.pathsep+os.environ.get('PATH','')
    os.environ['YOLO_CONFIG_DIR'] = str(bundle/'.ultralytics')
    result = Path(str(job)+'.result')
    with Path(str(job)+'.log').open('w',encoding='utf-8',buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
        try:
            sys.argv = ['bird_dji.fusion_job','--job',str(job)]
            runpy.run_module('bird_dji.fusion_job',run_name='__main__')
        except SystemExit as error:
            if error.code and not result.exists():
                result.write_text(f'ERROR\n\n分析器退出：{error.code}\n',encoding='utf-8')
            return error.code or 0
        except Exception as error:
            import traceback
            traceback.print_exc()
            message = str(error).replace('\n',' ').replace('\r',' ')
            result.write_text(f'ERROR\n\n{message}\n',encoding='utf-8')
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
