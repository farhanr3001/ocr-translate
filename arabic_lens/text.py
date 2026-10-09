import re
import html
import unicodedata
from pathlib import Path
from functools import lru_cache
from .models import TextBlock, Rect


def normalize(text):
    text = clean_source_text(text)
    text = unicodedata.normalize("NFKC", text).translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"}))
    text = re.sub(r"\s+", " ", text).strip().casefold()
    # Periods at the end are equivalent, but retain questions/exclamations and internal punctuation.
    return text.rstrip(".").strip()


def western_digits(text):
    return text.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')).replace('٫', '.')


def clean_translation(text):
    # Translation corpora/services sometimes return HTML-encoded punctuation.
    # Decode as plain text; never interpret markup or remove literal < > signs.
    for _ in range(2):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return western_digits(text).strip()


def clean_source_text(text):
    # Windows OCR can merge the last two dots of a small ellipsis into „.
    # Correct only this invalid English punctuation pair, not actual quotes.
    text = text.replace('.„', '...')
    text = re.sub(r'^\s*\ufffd\s*', '• ', text)
    # Only numeric multiplier contexts: never rewrite letters in names/prose.
    text = re.sub(r'\(([\dOolI|,]+)[xX]\)', lambda m: '(' + m[1].translate(str.maketrans('OoIl|', '00111')) + 'x)', text)
    return text


def protected_acronyms(text):
    if not re.search('[a-z]', text):
        return []  # All-caps headings still need normal Arabic translation.
    common = {'NFL', 'CPU', 'GPU', 'UI', 'API', 'RPG', 'MMO', 'XP', 'HP', 'DPS',
        'FPS', 'SDK', 'BIOS', 'HTML', 'HTTP', 'USB', 'VR', 'PC', 'FAQ', 'ID'}
    return list(dict.fromkeys(token for token in re.findall(r'\b[A-Z]{2,6}(?:\d{1,3})?\b', text)
        if token in common or not plausible_word(token)))


def preserves_acronyms(source, translated):
    return all(token in translated for token in protected_acronyms(source))


def label_key(text):
    return re.sub(r"[^a-z0-9 ]", "", normalize(text)).strip()


class TextFilterService:
    def __init__(self, settings):
        self.settings = settings

    def reason(self, block: TextBlock, manual=False):
        text = block.text.strip()
        letters = re.findall(r"[A-Za-z]", text)
        if block.confidence is not None and block.confidence < 0.5:
            return "low confidence"
        lexical = re.sub(r'[$£€]?\d+(?:[.,]\d+)*(?:%|x)?', '', text)
        if not letters or len(letters) / max(1, len(re.sub(r"\s", "", lexical))) < 0.5:
            return "not English / noisy text"
        words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)
        if re.fullmatch(r'\s*\d[\d.,]*\s*[kmb]\s*',text,re.IGNORECASE):
            return 'numeric value'
        if len(words) == 1 and len(words[0]) == 1 and words[0].casefold() not in ('a','i'):
            return 'single glyph / icon'
        if any(len(w) > 32 for w in words):
            return "noisy text"
        if not manual:
            # A game or social post can contain several invented names, item
            # names, and acronyms. Dictionary coverage is not an OCR confidence
            # score; rejecting such a sentence drops legitimate English text.
            # Combine it only with an OCR-specific corruption clue such as a
            # stray two-letter fragment or a midword capital in a long token.
            if len(words) >= 5:
                unknown = [word for word in words if not plausible_word(word)]
                fragments = any(len(word) <= 2 for word in unknown)
                damaged_case = any(re.search(r'[a-z][A-Z]', word) for word in unknown)
                if len(unknown) >= 3 and len(unknown) / len(words) > .4 and (fragments or damaged_case):
                    return 'low English plausibility'
            if self.settings.filter_ui:
                if self.is_ui_label(text):
                    return "simple UI label"
            if len(words) == 1 and len(words[0]) <= 2 and not plausible_word(words[0]):
                return "noisy text"
        return ""

    def is_ui_label(self, text):
        key = label_key(text)
        ignored = {label_key(t) for t in self.settings.ignored}
        return bool(key) and key in ignored


@lru_cache(maxsize=1)
def english_vocabulary():
    return frozenset((Path(__file__).parent / 'data/english_words.txt').read_text(encoding='utf-8').splitlines())


def plausible_word(word):
    word = word.casefold()
    vocabulary = english_vocabulary()
    compounds = {'daywear', 'workwear', 'fae'}
    return word in compounds or word in vocabulary or word.rstrip("s") in vocabulary or (word.endswith("'s") and word[:-2] in vocabulary)


def watch_context(blocks):
    """Prefer dialogue/instructions over neighbouring labels in a large crop."""
    connectors = {'the', 'you', 'your', 'i', 'my', 'can', 'may', 'when', 'is', 'are', 'to', 'of', 'with', 'but', 'and', 'for', 'a', 'an'}
    sentences = []
    for block in blocks:
        words = re.findall(r"[a-z]+", block.text.casefold())
        if len(words) >= 8 and sum(w in connectors for w in words) >= 3:
            sentences.append((len(words), block))
    if sentences:
        return [max(sentences, key=lambda pair: pair[0])[1]]
    unique = {}
    for block in blocks:
        unique.setdefault(normalize(block.text), block)
    return list(unique.values())


def group_lines(lines):
    """Join vertically adjacent lines in the same column, never individual words."""
    blocks = []
    for line in sorted(lines, key=lambda b: (b.rect.y, b.rect.x)):
        best = None
        for block in reversed(blocks):
            if is_list_item(line.text) or is_list_item(block.text):
                # Each bullet/numbered item is a separate translation anchor.
                # An indented continuation can still belong to that item.
                if is_list_item(line.text) or line.rect.x <= block.rect.x + 5:
                    continue
            if block.text.rstrip().endswith(':'):
                continue
            continuation = (not line.container and not block.container
                and not re.search(r'[.!?:]$', block.text.rstrip())
                and bool(re.match(r'[a-z]',line.text))
                and (len(block.text.split()) >= 4 or len(line.text.split()) >= 3))
            if (line.standalone or block.standalone) and not continuation:
                continue
            if line.container != block.container:
                continue
            if block.text.isupper() and len(block.text.split()) <= 3 and not line.text.isupper():
                continue  # Separate compact headings/nameplates from dialogue.
            a, b = block.rect, line.rect
            previous_height = getattr(block, '_line_height', a.h)
            if max(previous_height, b.h) > min(previous_height, b.h) * (1.9 if continuation else 1.4):
                continue
            horizontal = max(0, min(a.right, b.right) - max(a.x, b.x)) / max(1, min(a.w, b.w))
            gap = b.y - a.bottom
            if -4 <= gap <= max(6, max(previous_height,b.h) * .7) and horizontal > .3:
                best = block
                break
        if best:
            best.standalone = False
            best.text += " " + line.text
            best.rect = best.rect.union(line.rect)
            best._line_height = line.rect.h
            if best.confidence is not None and line.confidence is not None:
                best.confidence = min(best.confidence, line.confidence)
        else:
            blocks.append(TextBlock(line.text, line.rect, line.confidence, line.standalone, line.container))
    return blocks


def is_list_item(text):
    return bool(re.match(r'^\s*(?:[•●▪·*\-–\ufffd]\s*|\d+[.)]\s+|[^.!?]{1,45}:\s*[$£€]?\d)', text))


def align_list_columns(blocks):
    """RTL bullets share one right edge while retaining separate row anchors."""
    runs, run = [], []
    for block in blocks:
        if is_list_item(block.text) and (not run or (block.container == run[-1].container and abs(block.rect.x - run[-1].rect.x) < 12 and 0 <= block.rect.y - run[-1].rect.bottom <= max(12, block.rect.h))):
            run.append(block)
        else:
            if run: runs.append(run)
            run = [block] if is_list_item(block.text) else []
    if run: runs.append(run)
    for run in runs:
        if len(run) < 2:
            continue
        right = max(block.rect.right for block in run)
        for block in run:
            widened = Rect(block.rect.x, block.rect.y, right - block.rect.x, block.rect.h)
            if not any(other not in run and other.rect.overlap(widened) > .1 for other in blocks):
                block.rect = widened
    return blocks


def belongs_to_region(block, region):
    if block.rect.overlap(region) > .6:
        return True
    horizontal = max(0, min(block.rect.right, region.right) - max(block.rect.x, region.x))
    if block.standalone and len(block.text.split()) <= 3 and horizontal > block.rect.w * .6:
        # A text grid's final row can lie just beyond the morphology candidate.
        # Keep independent labels from the bounded context crop, not a union.
        if -32 <= block.rect.y - region.bottom <= 48 or 0 <= region.y - block.rect.bottom <= 48:
            return True
    # Nearby headings are useful even when the detector finds only their body.
    return len(block.text.split()) <= 3 and 0 <= region.y - block.rect.bottom < 64 and horizontal > min(block.rect.w, region.w) * .5
