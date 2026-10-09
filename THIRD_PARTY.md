Arabic Lens uses PySide6/Qt (LGPLv3), Python (PSF license), NumPy (BSD), Pillow (MIT-CMU),
OpenCV (Apache 2.0), HTTPX (BSD), PyWinRT (MIT), and the PyInstaller bootloader
(GPL with distribution exception). Their distribution metadata/licenses are included where supplied by the packager.

PySide6 is dynamically linked. Its DLLs remain replaceable in the portable `_internal` folder.
Fonts and English OCR come from Windows. Offline translation uses the HPLT
English–Arabic Transformer-base model trained on OPUS and HPLT data by researchers
from the University of Edinburgh and Charles University in Prague, supported by
the HPLT consortium (EU grant 101070350 and UKRI grant 10052546).
Model: https://huggingface.co/HPLT/translate-en-ar-v1.0-hplt_opus
Revision: 66fc22dc4ee77aeb1cfd186cfdb6bd658bba36bd
License: Creative Commons Attribution 4.0 International (CC-BY-4.0).
https://creativecommons.org/licenses/by/4.0/
Arabic Lens converts the original Marian weights to CTranslate2 int8 for CPU
inference; no training or fine-tuning has been performed. Original model card,
source hashes, conversion details and license text are bundled under
`arabic_lens/data/cpu-en-ar`. CTranslate2 is MIT; SentencePiece is Apache 2.0.
The retired Argos model and experimental TranslateGemma/Vulkan assets are excluded
from the portable application. They may remain in the development workspace.

Before public distribution, review bundled notices and license obligations, provide Qt/PySide
source availability as required, and sign the executable/installer with your own certificate.
# OCR vocabulary

The English plausibility vocabulary is derived from [CMUdict](https://github.com/cmusphinx/cmudict), maintained by the Carnegie Mellon University Speech Group. Its BSD license is included in `arabic_lens/data/CMUDICT-LICENSE.txt`. It is used only to reject heavily corrupted recognition, not to change OCR words or translate text.
