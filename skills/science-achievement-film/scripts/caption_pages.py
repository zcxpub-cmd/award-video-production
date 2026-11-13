"""Pure subtitle pagination; no models, prompts, I/O, or speech-alignment claims.

Adapted from Yingxu's local caption pagination. Preserve authored punctuation;
page widths are approximate and timing within each cue is explicitly estimated.
"""
import math
import re
import unicodedata

NO_START = frozenset('，。；、：！？）》】」』”’）,.;:!?%')
NO_END = frozenset('（《【「『“‘(')
PAUSES = frozenset('，。；、：！？,.;:!?')
WORDS = re.compile(r'[A-Za-z0-9]+(?:[.\-+][A-Za-z0-9]+)*')
CLAUSES = re.compile(r'(?=而且|并且|通过|从而|其中|因此|为了|由于|以及|同时|如何|为什么)')


def columns(text):
    return sum(1 if unicodedata.east_asian_width(c) in 'FWA' else .55 for c in text)


def paginate(text, maximum):
    text = ' '.join(text.split())
    protected = {i for m in WORDS.finditer(text) for i in range(m.start()+1,m.end())}
    boundaries = {m.start() for m in CLAUSES.finditer(text)}
    pages = []
    start = 0
    while start < len(text):
        limit = start
        while limit < len(text) and columns(text[start:limit+1]) <= maximum:
            limit += 1
        valid = [i for i in range(start+1,limit+1) if i not in protected
                 and text[i-1] not in NO_END and (i == len(text) or text[i] not in NO_START)]
        if not valid:
            raise ValueError('A subtitle term exceeds max_columns; increase the width or edit the cue.')
        pauses = [i for i in valid if text[i-1] in PAUSES and columns(text[start:i]) >= maximum*.4]
        words = [i for i in valid if (i in boundaries or text[i-1].isspace()) and columns(text[start:i]) >= maximum*.4]
        end = len(text) if limit == len(text) else (pauses or words or valid)[-1]
        page = text[start:end].strip()
        if page:
            pages.append(page)
        start = end
    return pages


def timed_pages(text, start, end, maximum):
    pages = paginate(text, maximum)
    # ASS stores centiseconds, so every page must survive its timestamp rounding.
    first, last = math.floor(start*100+.5), math.floor(end*100+.5)
    if last-first < len(pages):
        raise ValueError('Subtitle interval is too short for single-line pages; edit timing first.')
    weights = [columns(page) for page in pages]
    remaining = sum(weights)
    cursor = first
    result = []
    for i,(page,weight) in enumerate(zip(pages,weights)):
        length = min(last-cursor-(len(pages)-i-1),max(1,round((last-cursor)*weight/remaining)))
        right = cursor+length
        result.append((start if i==0 else cursor/100,end if i==len(pages)-1 else right/100,page))
        cursor = right
        remaining -= weight
    return result
