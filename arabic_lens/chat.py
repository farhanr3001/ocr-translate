"""Chat and dialogue text: speaker prefixes, slang, emotes and elongation.

Game dialogue ("Guard: Halt!") and stream chat ("23:33 MrMoonie: dont jp us")
put a name before a colon. The name is an identity, never prose: it is kept
verbatim and only the message is translated. Chat also contains interjection
acronyms (lol, lmao, wtf, smh), emote names (KEKW, monkaS) and nicknames
(jp) that must stay as written, and elongated words (NAHHHHHH) that the model
understands better in their normal spelling.
"""
import re
from functools import lru_cache

from .text import plausible_word

# Chat interjections/acronyms and emote names that are kept verbatim
# anywhere. These are never ordinary English words.
ALWAYS_KEEP = {
    'lol', 'lul', 'lmao', 'lmfao', 'rofl', 'roflmao', 'wtf', 'wth', 'smh', 'omfg', 'idk', 'idc', 'imo', 'imho',
    'tbh', 'ngl', 'brb', 'glhf', 'ggwp', 'ggs', 'xd', 'xdd', 'kekw', 'pogchamp', 'poggers', 'pogu', 'omegalul',
    'lulw', 'pepega', 'monkas', 'monkaw', 'sadge', 'copium', 'hopium', 'pepelaugh', 'ayaya', 'catjam',
    'widepeepohappy', 'frfr', 'iirc', 'afaik', 'tldr', 'istg', 'ikr', 'hbu', 'wbu', 'hmu',
}
# In chat/dialogue lines only: these are also (rarely) ordinary words, so
# outside chat context they are translated normally ("rip the page").
KEEP = ALWAYS_KEEP | {
    'lol', 'lul', 'lmao', 'lmfao', 'rofl', 'roflmao', 'wtf', 'wth', 'smh', 'omg', 'omfg', 'idk', 'idc', 'imo',
    'imho', 'tbh', 'ngl', 'irl', 'afk', 'brb', 'btw', 'fyi', 'gg', 'ggs', 'ggwp', 'wp', 'gl', 'hf', 'glhf', 'ez',
    'xd', 'xdd', 'kek', 'kekw', 'pog', 'poggers', 'pogchamp', 'pogu', 'omegalul', 'lulw', 'kappa', 'pepega',
    'monkas', 'monkaw', 'sadge', 'copium', 'hopium', 'pepelaugh', 'ayaya', 'catjam', 'widepeepohappy', 'ff',
    'jk', 'fr', 'frfr', 'ong', 'nvm', 'iirc', 'afaik', 'tldr', 'ama', 'dm', 'dms', 'pm', 'op', 'rip', 'w', 'l',
    'ratio', 'npc', 'fps', 'rp', 'gta', 'mmr', 'elo', 'dps', 'hp', 'mp', 'xp', 'pvp', 'pve', 'nsfw', 'sus',
    'ty', 'tyvm', 'np', 'yw', 'gn', 'gm', 'hbu', 'wbu', 'ikr', 'icl', 'istg', 'smth', 'ofc', 'ok', 'kk', 'hmu',
}
# Casual spellings with an unambiguous standard form the model translates well.
EXPAND = {
    'u': 'you', 'ur': 'your', 'r': 'are', 'y': 'why', 'pls': 'please', 'plz': 'please', 'thx': 'thanks',
    'thnx': 'thanks', 'tho': 'though', 'cuz': 'because', 'coz': 'because', 'bc': 'because', 'rn': 'right now',
    'ppl': 'people', 'msg': 'message', 'wassup': "what's up", 'wsup': "what's up", 'wssup': "what's up",
    'wsp': "what's up", 'sup': "what's up", 'dont': "don't", 'cant': "can't", 'wont': "won't", 'im': "I'm",
    'ive': "I've", 'didnt': "didn't", 'doesnt': "doesn't", 'isnt': "isn't", 'wasnt': "wasn't", 'aint': "ain't",
    'thats': "that's", 'whats': "what's", 'youre': "you're", 'theyre': "they're", 'ya': 'you', 'yea': 'yeah',
    'yh': 'yeah', 'ye': 'yeah', 'gonna': 'going to', 'wanna': 'want to', 'gotta': 'got to', 'kinda': 'kind of',
    'nah': 'no', 'nope': 'no', 'bruh': 'bro', 'luv': 'love', 'b4': 'before', 'gr8': 'great', '2day': 'today',
}
LABEL_WORDS = {
    'note', 'tip', 'hint', 'warning', 'quest', 'objective', 'goal', 'reward', 'rewards', 'mission', 'task',
    'level', 'score', 'time', 'health', 'status', 'step', 'example', 'question', 'answer', 'result', 'total',
    'error', 'info', 'news', 'update', 'chapter', 'location', 'item', 'items', 'cost', 'price', 'damage',
    'log', 'objectives', 'controls', 'tutorial', 'tips', 'hints', 'settings', 'options', 'map', 'inventory',
    'skills', 'stats', 'quests', 'achievement', 'achievements', 'unlocked', 'new', 'area', 'zone', 'region',
}
TITLE_STARTS = {'the', 'a', 'an', 'my', 'your', 'our', 'main', 'side', 'daily', 'bonus', 'next', 'current'}
TIME = r'(?:\[?\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?\]?)'
# One handle ("MrMoonie", "zylai_01") or a capitalised multi-word name
# ("Jimmy Jon", "Old Man Jenkins", "Jean of the Hills").
NAME = (r"(?:@?[A-Za-z][A-Za-z0-9_\-]{0,20}\d \d{1,6}"  # handle OCR split at its digits: "Happy9 234"
        r"|[A-Z][A-Za-z'\-]{0,15}(?: (?:[A-Z][A-Za-z'\-]{0,15}|of|the|von|van|de|al|el|bin)){1,3}"
        r"|@?[A-Za-z0-9_][A-Za-z0-9_\-]{0,24})")
SPEAKER = re.compile(
    r'^\s*(?P<time>' + TIME + r'\s+)?'
    r'(?P<junk>(?:\S{1,3}\s+){0,3}?)'
    r'(?P<name>' + NAME + r')\s?(?P<colon>[:;]|[•·]?\.(?=\s)|[•·](?=\s))\s+(?P<body>\S.*)$')
NAME_ONLY = re.compile(r'^\s*(?P<time>' + TIME + r'\s+)?(?P<junk>(?:\S{1,3}\s+){0,3}?)'
    r'(?P<name>' + NAME + r')\s*[:;.]?\s*$')
REPLY = re.compile(r'^\s*(?:Replying to|Reply to)\s+@?\S+\s*:\s*', re.IGNORECASE)


def is_name(token):
    """A chat/dialogue speaker, not an English label like "Note"."""
    if ' ' in token.strip():
        # "Jimmy Jon", "Old Man Jenkins", "Captain Price": a capitalised name
        # before a colon. Names are often dictionary words too, so structure
        # decides: titles ("The Lost Ring") and labels ("Main Quest",
        # "Quest Log") are translated instead.
        words = token.split()
        if words[0].casefold() in TITLE_STARTS:
            return False
        return not any(w.casefold() in LABEL_WORDS for w in words)
    bare = token.lstrip('@')
    if not bare or len(bare) > 25 or not re.search('[A-Za-z]', bare):
        return False
    if token.startswith('@') or re.search(r'[0-9_]', bare) or re.search(r'[a-z][A-Z]', bare):
        return True
    if bare.casefold() in LABEL_WORDS:
        return False
    # Real names (Aya, Farhan) and handles (kreuzle). A dictionary word before
    # a colon is a label or prose ("Warning:", "so here:"), not a speaker.
    return not plausible_word(bare)


def split_speaker(text):
    """Return (prefix, body). `prefix` is "Name: " (or "12:30 Name: ")."""
    reply = REPLY.match(text)
    if reply:
        # "Replying to @name: quoted message" -> keep "@name: " as the speaker.
        handle = re.search(r'@?([A-Za-z0-9_][A-Za-z0-9_.\-]{0,24})\s*:', reply.group())
        return ('@' + handle.group(1) + ': ' if handle else ''), text[reply.end():]
    match = SPEAKER.match(text)
    if not match or not is_name(match.group('name')):
        return '', text
    if (' ' in match.group('name') and not re.search(r'\d', match.group('name'))
            and len(match.group('body').split()) < 2):
        return '', text  # "Old Mill: 2" is a label row, not dialogue.
    if match.group('colon') != ':' and not match.group('time'):
        return '', text  # OCR's misread colon is trusted only after a timestamp.
    junk = match.group('junk').split()
    name = match.group('name')
    strong = name.startswith('@') or re.search(r'[0-9_]', name) or re.search(r'[a-z][A-Z]', name)
    if junk and not match.group('time') and not strong and any(plausible_word(t) for t in junk):
        return '', text  # Words before the "name" mean this is prose.
    time = (match.group('time') or '').strip()
    prefix = (time + ' ' if time else '') + match.group('name') + ': '
    return prefix, match.group('body')


def join_speaker_runs(lines):
    """Re-join a speaker and their message that OCR returned as two lines.

    Chat renders the name in a bold colour; Windows OCR often splits it from
    the message on the same row and misreads the colon ('•', '.'). A left run
    that is only "[time] name[:]" followed closely on the same baseline by more
    text becomes one "time name: message" line.
    """
    from .models import TextBlock
    lines = sorted(lines, key=lambda l: (l.rect.y, l.rect.x))
    used, joined = set(), {}
    # First pair every name-only run with the nearest text on its row (an
    # inline emote can lift the message a few pixels above the name).
    for i, left in enumerate(lines):
        match = NAME_ONLY.match(left.text)
        if not (match and (match.group('time') or left.text.rstrip().endswith(':')
                or re.search(r'[0-9_]|[a-z][A-Z]', match.group('name'))) and is_name(match.group('name'))):
            continue
        best = None
        for j, right in enumerate(lines):
            if j in used or j == i or right.rect.x <= left.rect.x:
                continue
            vertical = min(left.rect.bottom, right.rect.bottom) - max(left.rect.y, right.rect.y)
            gap = right.rect.x - left.rect.right
            height = max(left.rect.h, right.rect.h)
            if vertical > min(left.rect.h, right.rect.h) * .5 and -4 <= gap <= height * 3:
                if best is None or gap < best[0]:
                    best = (gap, j)
        if best is None:
            continue
        right = lines[best[1]]
        message = re.sub(r'^\s*[•�.:;·]\s*', '', right.text)
        message = re.sub(r'\s*[•�]\s*$', '', message)
        head = left.text.rstrip().rstrip(':;.').rstrip()
        used.update((i, best[1]))
        joined[i] = TextBlock(head + ': ' + message, left.rect.union(right.rect), left.confidence,
                              False, left.container if left.container == right.container else None)
    return [joined[i] if i in joined else line for i, line in enumerate(lines)
            if i in joined or i not in used]


def is_speaker_line(text):
    return bool(split_speaker(text)[0])


def collapse_elongation(word):
    """NAHHHHHH -> NAH, soooo -> so, goooood -> good (dictionary decides)."""
    if not re.search(r'([A-Za-z])\1\1', word):
        return word
    double = re.sub(r'([A-Za-z])\1{2,}', r'\1\1', word)
    single = re.sub(r'([A-Za-z])\1{2,}', r'\1', word)
    for candidate in (double, single):
        bare = re.sub(r'[^A-Za-z]', '', candidate)
        if plausible_word(bare) or bare.casefold() in KEEP or bare.casefold() in EXPAND:
            return candidate
    return single


@lru_cache(maxsize=4096)
def _keep_token(word):
    bare = word.casefold().strip(".,!?;:'\"()")
    return bare in KEEP


def prepare_chat(body, chat=True):
    """Normalise a message for translation. Returns (text, kept_tokens).

    With `chat` False (ordinary game/document text) only unmistakable chat
    acronyms are kept and elongations collapsed; casual spellings and short
    nicknames are only interpreted inside chat/dialogue lines.

    `kept_tokens` must survive translation verbatim (acronyms, emotes,
    nicknames). An all-caps shout is lowered so it is translated as words
    rather than read as a string of acronyms.
    """
    words = body.split()
    letters = [w for w in words if re.search('[A-Za-z]', w)]
    shouting = len(letters) >= 1 and all(w == w.upper() for w in letters) and len(''.join(letters)) > 3
    kept, out = [], []
    for word in words:
        word = collapse_elongation(word)
        core = word.strip(".,!?;:'\"()")
        lower = core.casefold()
        if not core:
            out.append(word)
            continue
        if shouting and chat and lower not in KEEP:
            word, core = word.lower(), lower
        if lower in (KEEP if chat else ALWAYS_KEEP):
            kept.append(core)
            out.append(word)
            continue
        if not chat:
            out.append(word)
            continue
        if lower in EXPAND and core.islower():
            out.append(word.replace(core, EXPAND[lower]))
            continue
        if (re.fullmatch(r'[A-Za-z]{2,3}', core) and core.islower() and not plausible_word(core)
                and lower not in ('a', 'i')):
            # Short non-words in chat are nicknames/initials ("jp", "xqc").
            kept.append(core)
            out.append(word)
            continue
        out.append(word)
    text = ' '.join(out)
    return text, list(dict.fromkeys(kept))


def has_translatable_words(text):
    """False for lines made only of kept tokens, emotes, links and symbols."""
    for word in text.split():
        core = word.strip(".,!?;:'\"()").casefold()
        if not re.search('[a-z]', core) or core in KEEP:
            continue
        if core.startswith(('!', '#', '@', 'http', 'www.')):
            continue
        return True
    return False
