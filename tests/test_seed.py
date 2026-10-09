from pathlib import Path
from arabic_lens.config import Settings
from arabic_lens.storage import TranslationStore
from arabic_lens.text import TextFilterService, watch_context
from arabic_lens.models import TextBlock, Rect

PACK = Path(__file__).resolve().parents[1] / 'arabic_lens/data/dressmaker.json'


def test_seed_restart_clear_and_existing_translation(tmp_path):
    path = tmp_path / 'cache.db'
    store = TranslationStore(path, Settings())
    store.put('Finish Dress', 'ترجمة المستخدم')
    assert store.seed_pack(PACK) > 30
    assert store.get('FINISH DRESS.') == 'ترجمة المستخدم'
    assert store.get('Approx. 3.85m fabric required') == 'يلزم نحو 3.85 متر من القماش'
    assert store.get('Approx. 4.85m fabric required') is None
    assert store.get('Singte Tiered Skirt') == store.get('Single Tiered Skirt')
    store.close()
    store = TranslationStore(path, Settings())
    assert store.seed_pack(PACK) == 0
    assert store.get('You may add accessories, or click below when the dress is finished.')
    store.clear('cache')
    assert store.seed_pack(PACK) == 0
    assert store.get('Finish Dress') is None
    assert store.seed_pack(PACK, force=True) > 30
    store.close()


def test_disabled_cache_does_not_seed(tmp_path):
    settings = Settings(cache_enabled=False)
    store = TranslationStore(tmp_path / 'cache.db', settings)
    assert store.seed_pack(PACK) == 0
    assert store.db.execute('SELECT count(*) FROM cache').fetchone()[0] == 0
    store.close()


def test_corrupt_ocr_and_dialogue_context():
    f = TextFilterService(Settings())
    r = Rect(0, 0, 600, 40)
    assert f.reason(TextBlock('Qualit El nt Giamour Of rack are RrjutingQue', r))
    assert not f.reason(TextBlock('Ask Zephyrax and Morvella to bring the fabric to my cottage.', r))
    dialogue = TextBlock('You may add accessories, or click below when the dress is finished.', r)
    assert watch_context([TextBlock('SEWING COMPLETE', r), dialogue, TextBlock('Finish Dress', r)]) == [dialogue]


def test_seeded_translation_never_calls_provider(tmp_path):
    import asyncio
    from arabic_lens.translation import TranslationService
    class UnavailableProvider:
        async def translate(self, source):
            raise AssertionError('Seeded text must not call the network provider')
    store = TranslationStore(tmp_path / 'cache.db', Settings())
    store.seed_pack(PACK)
    translation, cached = asyncio.run(TranslationService(UnavailableProvider(), store).translate(
        'You may add accessories, or click below when the dress is finished.'))
    assert cached and 'الفستان' in translation
    store.close()
