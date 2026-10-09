"""Translate every detected fixture block with the real built-in CPU service."""
import asyncio,json,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from arabic_lens.offline import OfflineTranslationProvider
from arabic_lens.translation import TranslationService
from arabic_lens.storage import TranslationStore
from arabic_lens.config import Settings

async def main():
    root=Path('artifacts/desktop-clean-coverage')
    data=json.loads((root/'coverage.json').read_text(encoding='utf8'))['fullscreen']['blocks']
    provider=OfflineTranslationProvider()
    store=TranslationStore(root/'fixture-translations.db',Settings(cache_enabled=False))
    try:
        service=TranslationService(provider,store)
        start=time.perf_counter()
        results=await asyncio.gather(*(service.translate(b['text']) for b in data),return_exceptions=True)
        output=[{'english':b['text'],'rect':b['rect'],'arabic':r[0] if not isinstance(r,BaseException) else '',
                 'error':str(r) if isinstance(r,BaseException) else ''} for b,r in zip(data,results)]
        report={'seconds':time.perf_counter()-start,'processed':sum(not item['error'] for item in output),
                'preserved_identifiers':sum(item['english']==item['arabic'] for item in output),'total':len(output),'results':output}
        (root/'translation-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({k:v for k,v in report.items() if k!='results'}))
        return 1 if any(item['error'] for item in output) else 0
    finally:
        await provider.close();store.close()

if __name__=='__main__':raise SystemExit(asyncio.run(main()))
