import json
import socket
import subprocess
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
assets = ROOT / 'arabic_lens/data/translation'
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
log = (ROOT / 'artifacts/translategemma-benchmark.log').open('w', encoding='utf-8')
process = subprocess.Popen([str(assets / 'runtime/llama-server.exe'), '-m', str(assets / 'translategemma-4b-it-Q4_K_M.gguf'),
    '--host', '127.0.0.1', '--port', str(port), '-c', '2048', '-np', '1', '-t', '4', '-tb', '4',
    '-ngl', '20', '--no-webui', '--no-slots', '--no-jinja', '--chat-template', 'chatml',
    '--cache-type-k', 'q8_0', '--cache-type-v', 'q8_0'],
    stdout=subprocess.DEVNULL, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
url = f'http://127.0.0.1:{port}'
texts = [
    'was already at Costco so why not flourish with some Costco pizza for NFL Sunday... this might be the best deal in America $10',
    "I'm hosting a garden party at the family cottage, but most of my dresses have paint stains. Can you make me something cute and full of life? My budget is 800.",
    'You need to find the key before sunset.',
    'You do not have enough money.',
    'Press the API button to display your CPU and GPU usage.',
    'SEWING COMPLETE', 'Approx. 3.85m fabric required',
]


def prompt(text):
    return ('<start_of_turn>user\nYou are a professional English (en) to Arabic (ar) translator. '
        'Your goal is to accurately convey the meaning and nuances of the original English text while adhering '
        'to Arabic grammar, vocabulary, and cultural sensitivities.\n'
        'Produce only the Arabic translation, without any additional explanations or commentary. '
        'Use natural Modern Standard Arabic. Keep numbers in Western digits 0-9 with their exact values, '
        'and keep abbreviations such as NFL, CPU and HP in their original letters. '
        'Please translate the following English text into Arabic:\n\n\n' + text +
        '<end_of_turn>\n<start_of_turn>model\n')


try:
    start = time.perf_counter()
    with httpx.Client(timeout=60, trust_env=False) as client:
        while time.perf_counter() - start < 60:
            if process.poll() is not None:
                raise RuntimeError('Model runtime exited; check benchmark log')
            try:
                if client.get(url + '/health').status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            time.sleep(.2)
        print('Load seconds:', round(time.perf_counter() - start, 2), flush=True)
        report = []
        for text in texts:
            start = time.perf_counter()
            response = client.post(url + '/completion', json={'prompt': prompt(text), 'temperature': 0,
                'n_predict': 512, 'cache_prompt': True, 'stop': ['<end_of_turn>']})
            response.raise_for_status()
            result = response.json()
            entry = dict(english=text, arabic=result['content'], seconds=round(time.perf_counter() - start, 2),
                timings=result.get('timings', {}))
            report.append(entry)
            print(json.dumps(entry, ensure_ascii=True), flush=True)
        (ROOT / 'artifacts/translategemma-benchmark.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
finally:
    process.terminate()
    try:
        process.wait(5)
    except subprocess.TimeoutExpired:
        process.kill()
    log.close()
