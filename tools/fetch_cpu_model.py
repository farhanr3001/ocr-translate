"""Build a small, licensed CPU-only English→Arabic model from official assets."""
import hashlib
import json
from pathlib import Path
import requests
import sentencepiece as spm
from ctranslate2.converters import MarianConverter

ROOT = Path(__file__).resolve().parents[1]
REVISION = '66fc22dc4ee77aeb1cfd186cfdb6bd658bba36bd'
REPO = 'HPLT/translate-en-ar-v1.0-hplt_opus'
download = ROOT / 'artifacts/models/hplt-en-ar'
target = ROOT / 'arabic_lens/data/cpu-en-ar'
download.mkdir(parents=True, exist_ok=True)
target.mkdir(parents=True, exist_ok=True)
sources = []
for name in ['model.npz.best-chrf.npz', 'model.en-ar.spm', 'README.md']:
    path = download / name
    url = f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}'
    if not path.exists():
        with requests.get(url, stream=True, timeout=90) as response:
            response.raise_for_status()
            with path.with_suffix(path.suffix + '.part').open('wb') as output:
                for block in response.iter_content(1024 * 1024):
                    output.write(block)
        path.with_suffix(path.suffix + '.part').replace(path)
    sources.append(dict(file=name, url=url, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size))
    print(name, path.stat().st_size, flush=True)
tokenizer = spm.SentencePieceProcessor(model_file=str(download / 'model.en-ar.spm'))
vocab = download / 'vocab.yml'
vocab.write_text('\n'.join("'" + tokenizer.id_to_piece(i).replace("'", "''") + "': " + str(i)
    for i in range(tokenizer.get_piece_size())), encoding='utf-8')
MarianConverter(str(download / 'model.npz.best-chrf.npz'), [str(vocab)]).convert(
    str(target / 'model'), quantization='int8', force=True)
(target / 'sentencepiece.model').write_bytes((download / 'model.en-ar.spm').read_bytes())
(target / 'MODEL_CARD.md').write_bytes((download / 'README.md').read_bytes())
(target / 'sources.json').write_text(json.dumps(dict(id='hplt-en-ar-int8-v1', repository=REPO,
    revision=REVISION, license='CC-BY-4.0', conversion='CTranslate2 int8, CPU', files=sources), indent=2), encoding='utf-8')
print('Converted bytes:', sum(p.stat().st_size for p in target.rglob('*') if p.is_file()))
