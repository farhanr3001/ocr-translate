"""Preserve document boundaries and exact visible numeric values."""
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

VALUE = re.compile(r'(?<![\w])(?:[$£€]\s*)?[+-]?\d+(?:[.,]\d+)*(?:%|[xX]\b)?')


def values(text):
    return [match.group() for match in VALUE.finditer(text)]


CLOCK = re.compile(r'(?<![\w:])\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AaPp][Mm])?(?![\w:])')
SPEAKER_PREFIX = re.compile(r"^(?:\[?\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AaPp][Mm])?\]?\s+)?(?:[A-Z][A-Za-z'\-]{0,15}(?: [A-Za-z][A-Za-z'\-]{0,15}){1,3}|@?[A-Za-z0-9_][A-Za-z0-9_\-]{0,24}): ")


def _isolate(text):
    return '\u2066' + text + '\u2069'


def display_values(text):
    # LTR isolates keep signs, decimal/group separators and currencies together
    # inside RTL Arabic, without changing stored/copied numeric strings.
    # A clock time is one unit: isolating "23" and "33" separately let RTL
    # ordering show 23:33 as 33:23. A kept chat/dialogue speaker prefix
    # ("23:33 Farhan: ") keeps its time and name as separate LTR units while
    # the colon stays in the Arabic flow: read from the right it is
    # "23:33  Farhan  :  message", not "Farhan:" stuck at the outer edge.
    prefix = ''
    match = SPEAKER_PREFIX.match(text)
    if match:
        head = match.group().rstrip()[:-1].strip()
        pieces = []
        clock = re.match(r'\[?(\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AaPp][Mm])?)\]?\s+', head)
        if clock:
            pieces.append(_isolate(clock.group(1)))
            head = head[clock.end():]
        pieces.append(_isolate(head))
        prefix = ' '.join(pieces) + ': '
        text = text[match.end():]
    parts, last = [], 0
    for clock in CLOCK.finditer(text):
        parts.append(VALUE.sub(lambda m: _isolate(m.group()), text[last:clock.start()]))
        parts.append(_isolate(clock.group()))
        last = clock.end()
    parts.append(VALUE.sub(lambda m: _isolate(m.group()), text[last:]))
    return prefix + ''.join(parts)


def preserves_values(source, translated):
    return Counter(values(source)) == Counter(values(translated))


def preserves_layout(source, translated):
    return source.count('\n') == translated.count('\n')


def numeric_key(value):
    number = re.sub(r'[^\d.,+-]', '', value)
    if ',' in number:
        parts = number.split(',')
        number = ''.join(parts) if all(len(p.split('.')[0]) == 3 for p in parts[1:]) else number.replace(',', '.')
    try:
        return Decimal(number)
    except InvalidOperation:
        return number


def restore_values(source, translated):
    originals = defaultdict(list)
    for value in values(source):
        originals[numeric_key(value)].append(value)
    targets = list(VALUE.finditer(translated))
    if sum(map(len, originals.values())) != len(targets):
        return None
    replacements = []
    for target in targets:
        key = numeric_key(target.group())
        if not originals[key]:
            return None
        replacements.append((target, originals[key].pop(0)))
    for target, original in reversed(replacements):
        translated = translated[:target.start()] + original + translated[target.end():]
    return translated
