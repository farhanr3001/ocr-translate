"""Preserve document boundaries and exact visible numeric values."""
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

VALUE = re.compile(r'(?<![\w])(?:[$£€]\s*)?[+-]?\d+(?:[.,]\d+)*(?:%|[xX]\b)?')


def values(text):
    return [match.group() for match in VALUE.finditer(text)]


def display_values(text):
    # LTR isolates keep signs, decimal/group separators and currencies together
    # inside RTL Arabic, without changing stored/copied numeric strings.
    return VALUE.sub(lambda match: '\u2066' + match.group() + '\u2069', text)


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
