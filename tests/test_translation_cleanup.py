import asyncio
from arabic_lens.config import Settings
from arabic_lens.offline import OfflineTranslationProvider
from arabic_lens.storage import TranslationStore
from arabic_lens.text import clean_translation, clean_source_text, protected_acronyms
from arabic_lens.translation import TranslationService


def test_plain_text_quotes_symbols_and_digits():
    assert clean_translation('قال &quot;مرحبا&quot; &amp; وداعا ٣٫٨٥') == 'قال "مرحبا" & وداعا 3.85'
    assert clean_translation('&amp;quot;مرحبا&amp;quot;') == '"مرحبا"'
    assert clean_translation('س < ص &gt; ع') == 'س < ص > ع'
    assert clean_source_text('Sunday.„ this might be good.') == 'Sunday... this might be good.'
    assert clean_source_text('He said "good".') == 'He said "good".'
    assert protected_acronyms('SEWING COMPLETE') == []
    assert protected_acronyms('You need to find MY dress.') == []


def test_legacy_cache_and_new_provider_results_decode_entities(tmp_path):
    store = TranslationStore(tmp_path / 'cache.db', Settings())
    store.db.execute('INSERT INTO cache VALUES(?,?,0,?)', ('a quote', '&quot;نص قديم&quot;', store.namespace()))
    store.db.commit()
    assert store.get('A quote') == '"نص قديم"'
    assert store.get('A quote') == '"نص قديم"'  # Memory path too.
    store.put('For NFL Sunday', 'من أجل جبهة التحرير الوطنية')
    assert store.get('For NFL Sunday') is None  # Don't reuse the incorrect expansion.
    class Provider:
        async def translate(self, text):
            return '&quot;ترجمة جديدة&quot;'
    result, cached = asyncio.run(TranslationService(Provider(), store).translate('New text'))
    assert result == '"ترجمة جديدة"' and not cached
    assert store.get('New text') == result
    store.close()


def test_real_tweet_translation_has_no_html_or_invented_acronym_expansion():
    async def scenario():
        provider = OfflineTranslationProvider()
        try:
            result = await provider.translate('was already at Costco so why not flourish with some Costco pizza for NFL Sunday.„ this might be the best deal in America $10')
            assert 'NFL' in result and '10' in result
            assert '&quot' not in result and 'ZXQ' not in result
            assert 'جبهة التحرير' not in result
        finally:
            await provider.close()
    asyncio.run(scenario())
