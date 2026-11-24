"""Local Flask server for the AgroMask GIS conversion workbench."""

import argparse
import json
import math
import os
import re
import tempfile
import webbrowser
from pathlib import Path
from threading import Lock, Timer
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.mpl-cache'))

from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from pyproj.exceptions import ProjError
from rasterio.errors import RasterioError
from werkzeug.serving import make_server

from generate_demo import run_demo
from pipeline import convert
from products import DOWNLOADS, PREVIEWS

DEMO = ROOT / 'demo_results'
RUNS = ROOT / 'runs'
FILE_NAMES = {*DOWNLOADS, *PREVIEWS}
app = Flask(__name__)
app.config.update(MAX_CONTENT_LENGTH=192 * 1024 * 1024, MAX_FORM_PARTS=1508)
app.json.sort_keys = False
processing = Lock()


def package(meta, job):
    return {**meta, 'job': job, 'downloads': DOWNLOADS}


@app.get('/')
def index():
    return render_template('index.html')


@app.get('/api/demo')
def demo():
    return jsonify(package(json.loads((DEMO / 'summary.json').read_text(encoding='utf-8')), 'demo'))


@app.errorhandler(413)
def too_large(_):
    return jsonify(error='上传超过限制。每批最多 192 MB、1,500 个文件。请分批处理。'), 413


@app.post('/api/convert')
def process():
    try:
        threshold = float(request.form.get('threshold', '10'))
        background = int(request.form.get('background', '0'))
        if not math.isfinite(threshold) or not 0 <= threshold <= 1e12 or not 0 <= background <= 65535:
            raise ValueError
    except ValueError:
        return jsonify(error='面积阈值须在 0 至 10¹² m² 之间，背景类别须为 0 至 65535 的整数。'), 400
    mode = request.form.get('mode', 'upload')
    if mode not in {'demo', 'upload'}:
        return jsonify(error='未知的数据来源。'), 400
    uploads = request.files.getlist('files') if mode == 'upload' else []
    if mode == 'upload' and not 1 <= len(uploads) <= 1500:
        return jsonify(error='请选择包含参考影像与掩膜的文件夹，本批最多 1,500 个文件。'), 400
    if not processing.acquire(blocking=False):
        return jsonify(error='已有转换正在运行，请稍后重试。'), 409
    job = uuid4().hex
    try:
        RUNS.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=RUNS, prefix='.building-') as directory:
            output = Path(directory) / 'result'
            output.mkdir()
            if mode == 'demo':
                meta = run_demo(ROOT / 'demo_data', output, threshold, background)
            else:
                meta = convert([(item.filename or '', item.stream) for item in uploads], output, threshold, background)
            output.rename(RUNS / job)
    except (ValueError, RasterioError, ProjError) as exc:
        return jsonify(error=f'转换失败。{exc}'), 400
    except OSError:
        app.logger.exception('Conversion I/O failed')
        return jsonify(error='读取或保存文件失败，请查看启动窗口中的错误信息并检查磁盘空间。'), 500
    finally:
        processing.release()
    return jsonify(package(meta, job))


@app.get('/files/<job>/<name>')
def result_file(job, name):
    if name not in FILE_NAMES or (job != 'demo' and re.fullmatch('[0-9a-f]{32}', job) is None):
        abort(404)
    directory = DEMO if job == 'demo' else RUNS / job
    return send_from_directory(directory, name, as_attachment=name in DOWNLOADS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    try:
        server = make_server('127.0.0.1', args.port, app, threaded=True)
    except SystemExit:
        server = make_server('127.0.0.1', 0, app, threaded=True)
    url = f'http://127.0.0.1:{server.server_port}/'
    print(f'AgroMask GIS: {url}\nKeep this window open. Press Ctrl+C to stop.', flush=True)
    if not args.no_browser:
        browser = Timer(.45, webbrowser.open, args=(url,))
        browser.daemon = True
        browser.start()
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
