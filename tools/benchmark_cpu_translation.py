"""Measure actual uncached translation and cache cost; no network or GPU calls."""
import asyncio
import ctypes
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arabic_lens.config import Settings
from arabic_lens.offline import OfflineTranslationProvider, MODEL_ID
from arabic_lens.storage import TranslationStore
from arabic_lens.translation import TranslationService


class Memory(ctypes.Structure):
    _fields_ = [('cb', ctypes.c_ulong), ('faults', ctypes.c_ulong)] + [(n, ctypes.c_size_t) for n in
        ['peak_working', 'working', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile']]


def memory():
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL('psapi')
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    info = Memory()
    info.cb = ctypes.sizeof(info)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(info), info.cb):
        raise OSError('Memory measurement failed')
    return info.working


async def main():
    provider = OfflineTranslationProvider()
    report = {'model': MODEL_ID, 'device': 'cpu', 'cpu_threads': 2, 'memory_before_bytes': memory(), 'translations': []}
    texts = ['You need to find the key before sunset.', 'You do not have enough money.',
        'Please save your changes before closing this window.', 'My budget is 800.',
        'You received 25 XP and 10 gold.', 'This fabric is perfect for a summer dress!',
        'Continue through the tunnel until you reach the village.',
        "I'm hosting a garden party at the family cottage, but most of my dresses have paint stains. Can you make me something cute and full of life? My budget is 800.",
        'was already at Costco so why not flourish with some Costco pizza for NFL Sunday... this might be the best deal in America $10']
    try:
        for source in texts:
            started, cpu = time.perf_counter(), time.process_time()
            result = await provider.translate(source)
            report['translations'].append(dict(source=source, arabic=result, wall_ms=round((time.perf_counter() - started)*1000, 2), cpu_ms=round((time.process_time()-cpu)*1000, 2)))
        report['memory_loaded_bytes'] = memory()
        store = TranslationStore(':memory:', Settings())
        service = TranslationService(provider, store)
        store.put(texts[0], report['translations'][0]['arabic'])
        started = time.perf_counter()
        for _ in range(1000):
            _, cached = await service.translate(texts[0])
            assert cached
        report['cache_hit_mean_ms'] = (time.perf_counter()-started)
        store.close()
    finally:
        await provider.close()
    Path('artifacts/cpu-translation-benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))


asyncio.run(main())
