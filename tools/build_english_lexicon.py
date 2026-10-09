"""Build a compact OCR plausibility vocabulary from the BSD-licensed CMUdict."""
import re
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'arabic_lens/data'
url = 'https://raw.githubusercontent.com/cmusphinx/cmudict/master/'
dictionary = urllib.request.urlopen(url + 'cmudict.dict', timeout=30).read().decode('utf-8')
words = {re.sub(r'\(\d+\)$', '', line.split()[0]).casefold()
    for line in dictionary.splitlines() if line and not line.startswith(';;;')}
words = {w for w in words if re.fullmatch(r"[a-z]+(?:'[a-z]+)?", w)}
root.joinpath('english_words.txt').write_text('\n'.join(sorted(words)), encoding='utf-8')
root.joinpath('CMUDICT-LICENSE.txt').write_bytes(urllib.request.urlopen(url + 'LICENSE', timeout=30).read())
print(f'{len(words)} vocabulary entries')
