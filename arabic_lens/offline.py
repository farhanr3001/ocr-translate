"""Bundled CPU translation: no account, network or local server required."""
import asyncio
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .translation import TranslationError
from .text import clean_translation, protected_acronyms, clean_source_text

MODEL_ID = 'hplt-en-ar-int8-v1'


class OfflineTranslationProvider:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='Local Arabic')
        self.model = self.tokenizer = None
        self.pending = []
        self.dispatcher = None

    def _initialize(self):
        import ctypes
        kernel = ctypes.WinDLL('kernel32')
        kernel.GetCurrentThread.restype = ctypes.c_void_p
        kernel.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        kernel.SetThreadPriority(kernel.GetCurrentThread(), -1)
        if self.model is None:
            import ctranslate2
            import sentencepiece
            root = Path(__file__).parent / 'data/cpu-en-ar'
            self.tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(root / 'sentencepiece.model'))
            self.model = ctranslate2.Translator(str(root / 'model'), device='cpu',
                compute_type='int8', inter_threads=1, intra_threads=2)

    def _translate(self, text, cancelled=None):
        try:
            if cancelled and cancelled.is_set():
                raise asyncio.CancelledError()
            # Give gameplay priority over this one CPU worker. Never change a
            # game's process, priority or graphics device.
            self._initialize()
            text = clean_source_text(text)
            original_text = text
            replacements = {}
            for token in protected_acronyms(text):
                index = len(replacements)
                marker = f'ZXQ{index}ZX'
                while marker in text:
                    index += 1
                    marker = f'ZXQ{index}ZX'
                replacements[marker] = token
                text = re.sub(r'\b' + re.escape(token) + r'\b', marker, text)
            # Bound each input without truncating long dialogue or descriptions.
            chunks, current = [], ''
            for word in text[:6000].split():
                if len(current) + len(word) > 450:
                    chunks.append(current)
                    current = ''
                current += (' ' if current else '') + word
            if current:
                chunks.append(current)
            translated = []
            for chunk in chunks:
                if cancelled and cancelled.is_set():
                    raise asyncio.CancelledError()
                result = self.model.translate_batch([self.tokenizer.encode(chunk, out_type=str)],
                    beam_size=2, max_decoding_length=512)[0]
                translated.append(self.tokenizer.decode(result.hypotheses[0]))
            if cancelled and cancelled.is_set():
                raise asyncio.CancelledError()
            arabic = clean_translation(' '.join(translated))
            for marker, token in replacements.items():
                pattern = r'\b' + r'\s*'.join(re.escape(c) for c in marker) + r'\b'
                arabic, restored = re.subn(pattern, token, arabic, flags=re.IGNORECASE)
                if not restored:
                    # Some fonts/context make the model transliterate markers.
                    # Fall back to translating the surrounding clauses, keeping
                    # the protected letters verbatim rather than guessing them.
                    tokens = list(replacements.values())
                    parts = re.split(r'\b(' + '|'.join(re.escape(t) for t in tokens) + r')\b', original_text)
                    return ' '.join(part if part in tokens or not re.search('[A-Za-z]{2}', part)
                        else self._translate(part.strip(), cancelled) for part in parts if part.strip())
            if not re.search(r'[\u0600-\u06ff]', arabic):
                raise TranslationError('translation_failed')
            return arabic
        except TranslationError:
            raise
        except Exception:
            raise TranslationError('local_unavailable') from None

    def _batch(self, entries):
        """One CPU worker, same beam quality, several independent inputs."""
        self._initialize()
        answers = [None] * len(entries)
        plain = [(i,text) for i,(text,_,cancelled) in enumerate(entries)
                 if not cancelled.is_set() and len(text) <= 450 and not protected_acronyms(text)]
        if plain:
            try:
                results = self.model.translate_batch([self.tokenizer.encode(clean_source_text(text), out_type=str)
                    for _,text in plain], beam_size=2, max_decoding_length=512)
                for (i,_),result in zip(plain,results):
                    arabic = clean_translation(self.tokenizer.decode(result.hypotheses[0]))
                    answers[i] = arabic if re.search(r'[\u0600-\u06ff]',arabic) else TranslationError('translation_failed')
            except Exception:
                # One malformed batch must not discard all the independent texts.
                pass
        for i,(text,_,cancelled) in enumerate(entries):
            if cancelled.is_set():
                continue
            if answers[i] is None:
                try:
                    answers[i] = self._translate(text,cancelled)
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    answers[i] = exc
        return answers

    async def _dispatch(self):
        while self.pending:
            # Coalesce concurrent regions without waiting for an entire screen.
            await asyncio.sleep(.008)
            batch, self.pending = self.pending[:8], self.pending[8:]
            batch = [entry for entry in batch if not entry[1].cancelled()]
            if not batch:
                continue
            try:
                answers = await asyncio.get_running_loop().run_in_executor(self.executor,self._batch,batch)
            except Exception:
                answers = [TranslationError('local_unavailable')] * len(batch)
            for (_,future,_), answer in zip(batch,answers):
                if not future.done():
                    if isinstance(answer,Exception): future.set_exception(answer)
                    elif answer is None: future.cancel()
                    else: future.set_result(answer)

    async def translate(self, text):
        cancelled = threading.Event()
        future = asyncio.get_running_loop().create_future()
        self.pending.append((text,future,cancelled))
        if self.dispatcher is None or self.dispatcher.done():
            self.dispatcher = asyncio.create_task(self._dispatch())
        try:
            return await future
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def close(self):
        if self.dispatcher:
            self.dispatcher.cancel()
            await asyncio.gather(self.dispatcher,return_exceptions=True)
        for _,future,cancelled in self.pending:
            cancelled.set(); future.cancel()
        self.pending.clear()
        self.executor.shutdown(wait=False, cancel_futures=True)


class TranslationProvider:
    """Settings can change without rebuilding the processing pipeline."""
    def __init__(self, settings):
        from .translation import HttpTranslationProvider
        self.settings = settings
        self.local = OfflineTranslationProvider()
        self.remote = HttpTranslationProvider(settings)

    async def translate(self, text):
        provider = self.local if self.settings.provider == 'Built-in offline' else self.remote
        return await provider.translate(text)

    async def close(self):
        await self.local.close()
        await self.remote.close()
