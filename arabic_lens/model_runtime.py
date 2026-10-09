"""Private, hidden local model runtime; never attaches to another application."""
import asyncio
import ctypes
import os
import secrets
import socket
import subprocess
import time
from pathlib import Path
import httpx
from .translation import TranslationError

MODEL_ID = 'translategemma-4b-q4-2026-v1'


def translation_prompt(text):
    return ('<start_of_turn>user\nYou are a professional English (en) to Arabic (ar) translator. '
        'Your goal is to accurately convey the meaning and nuances of the original English text while adhering '
        'to Arabic grammar, vocabulary, and cultural sensitivities.\n'
        'Produce only the Arabic translation, without any additional explanations or commentary. '
        'Use natural Modern Standard Arabic, never a regional dialect. Preserve meaning and do not add facts '
        'or currencies absent from the source. Keep numbers in Western digits 0-9 with their exact values. '
        'Keep English abbreviations verbatim; do not expand them. '
        'Please translate the following English text into Arabic:\n\n\n' + text +
        '<end_of_turn>\n<start_of_turn>model\n')


class _Limits(ctypes.Structure):
    _fields_ = [('user', ctypes.c_int64), ('job', ctypes.c_int64), ('flags', ctypes.c_ulong),
        ('min_working', ctypes.c_size_t), ('max_working', ctypes.c_size_t), ('active', ctypes.c_ulong),
        ('affinity', ctypes.c_size_t), ('priority', ctypes.c_ulong), ('scheduling', ctypes.c_ulong)]


class _JobInfo(ctypes.Structure):
    _fields_ = [('limits', _Limits), ('io', ctypes.c_uint64 * 6), ('process_memory', ctypes.c_size_t),
        ('job_memory', ctypes.c_size_t), ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]


class ModelRuntimeService:
    def __init__(self, gpu_layers=20):
        self.assets = Path(__file__).parent / 'data/translation'
        self.gpu_layers = gpu_layers
        self.process = None
        self.job = None
        self.client = None
        self.lock = asyncio.Lock()
        self.last_used = 0
        self.idle_task = None

    def _own_process(self):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.restype = ctypes.c_void_p
        kernel.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
        kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.job = kernel.CreateJobObjectW(None, None)
        info = _JobInfo()
        info.limits.flags = 0x2000  # KILL_ON_JOB_CLOSE, for this runtime only.
        if not self.job or not kernel.SetInformationJobObject(self.job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError('Runtime ownership unavailable')
        if not kernel.AssignProcessToJobObject(self.job, int(self.process._handle)):
            raise OSError('Runtime ownership unavailable')

    async def _start(self, layers):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        key = secrets.token_urlsafe(32)
        env = os.environ.copy()
        # Do not inherit external runtime/model/HTTP defaults from the desktop.
        env = {k: v for k, v in env.items() if not k.startswith(('LLAMA_', 'GGML_'))}
        env['LLAMA_API_KEY'] = key
        args = [str(self.assets / 'runtime/llama-server.exe'), '-m', str(self.assets / 'translategemma-4b-it-Q4_K_M.gguf'),
            '--host', '127.0.0.1', '--port', str(port), '-c', '2048', '-np', '1', '-t', '4', '-tb', '4',
            '-ngl', str(layers), '--no-webui', '--no-slots', '--no-jinja', '--chat-template', 'chatml',
            '--cache-type-k', 'q8_0', '--cache-type-v', 'q8_0', '--log-disable']
        self.process = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        self._own_process()
        self.client = httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', trust_env=False,
            timeout=60, headers={'Authorization': 'Bearer ' + key})
        start = time.monotonic()
        while time.monotonic() - start < 60:
            if self.process.poll() is not None:
                raise TranslationError('local_unavailable')
            try:
                if (await self.client.get('/health')).status_code == 200:
                    # Compile the backend kernels before the player's first text.
                    await self.client.post('/completion', json={'prompt': translation_prompt('Ready.'),
                        'n_predict': 1, 'temperature': 0, 'cache_prompt': True})
                    return
            except httpx.ConnectError:
                pass
            await asyncio.sleep(.2)
        raise TranslationError('local_unavailable')

    async def ensure_ready(self):
        if self.process and self.process.poll() is None:
            return
        for layers in dict.fromkeys([self.gpu_layers, 0]):
            try:
                await self._start(layers)
                self.last_used = time.monotonic()
                if self.idle_task is None:
                    self.idle_task = asyncio.create_task(self._unload_idle())
                return
            except asyncio.CancelledError:
                await self._stop()
                raise
            except Exception:
                await self._stop()
        raise TranslationError('local_unavailable')

    async def complete(self, text):
        async with self.lock:
            await self.ensure_ready()
            self.last_used = time.monotonic()
            try:
                response = await self.client.post('/completion', json={'prompt': translation_prompt(text),
                    'temperature': 0, 'n_predict': 512, 'cache_prompt': True, 'stop': ['<end_of_turn>']})
                response.raise_for_status()
                data = response.json()
                if data.get('stopped_limit') or data.get('truncated'):
                    raise TranslationError('translation_failed')
                return data['content']
            except asyncio.CancelledError:
                # Cancel obsolete generation, including any request still in its
                # startup phase, rather than leaving a stale queue on the GPU.
                await self._stop()
                raise
            except (httpx.HTTPError, ValueError, KeyError):
                raise TranslationError('translation_failed') from None
            finally:
                self.last_used = time.monotonic()

    async def warm_up(self):
        async with self.lock:
            await self.ensure_ready()

    async def _unload_idle(self):
        while True:
            await asyncio.sleep(30)
            if not self.lock.locked() and time.monotonic() - self.last_used > 180:
                async with self.lock:
                    await self._stop()

    async def _stop(self):
        if self.client:
            await self.client.aclose()
            self.client = None
        if self.job:
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(self.job)
            self.job = None
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
            await asyncio.to_thread(self.process.wait)
            self.process = None

    async def close(self):
        if self.idle_task:
            self.idle_task.cancel()
            await asyncio.gather(self.idle_task, return_exceptions=True)
        await self._stop()
