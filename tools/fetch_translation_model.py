"""Fetch pinned model/runtime assets, verifying upstream SHA-256 digests."""
import hashlib
import json
import time
import zipfile
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'arabic_lens/data/translation'
DEST.mkdir(parents=True, exist_ok=True)
FILES = [
    ('translategemma-4b-it-Q4_K_M.gguf',
     'https://huggingface.co/42ailab/TranslateGemma-4B-GGUF/resolve/main/translategemma-4b-it-Q4_K_M.gguf',
     '7f7357c14abd9da4eb200b38b05da502cd6e10d7e1d403fbc9f78c19f3209b72'),
    ('llama-b11146-bin-win-vulkan-x64.zip',
     'https://github.com/ggml-org/llama.cpp/releases/download/b11146/llama-b11146-bin-win-vulkan-x64.zip',
     '55a378aa095b466979d85075234f66d7655c7a7483222af0c006c0e55b4d7bd6'),
]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


for name, url, expected in FILES:
    path = DEST / name if name.endswith('.gguf') else ROOT / 'artifacts' / name
    if not path.exists() or digest(path) != expected:
        temp = path.with_suffix(path.suffix + '.download')
        h = hashlib.sha256()
        received, announced = 0, 0
        with httpx.stream('GET', url + '?download=true&t=' + str(int(time.time())),
                          follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with temp.open('wb') as f:
                for chunk in response.iter_bytes(4 * 1024 * 1024):
                    f.write(chunk)
                    h.update(chunk)
                    received += len(chunk)
                    if received - announced > 256 * 1024 * 1024:
                        print(f'{name}: {received / 1e9:.2f} GB downloaded', flush=True)
                        announced = received
        if h.hexdigest() != expected:
            raise ValueError('Download checksum mismatch: ' + name)
        temp.replace(path)
    print(f'Verified {name}: {path.stat().st_size:,} bytes', flush=True)
    if name.endswith('.zip'):
        runtime = DEST / 'runtime'
        runtime.mkdir(exist_ok=True)
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                target = runtime / Path(entry.filename).name
                if target.suffix.lower() in ('.exe', '.dll') or 'license' in target.name.lower():
                    target.write_bytes(archive.read(entry))
(DEST / 'sources.json').write_text(json.dumps(FILES, indent=2), encoding='utf-8')
