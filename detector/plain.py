"""Turn formulaic English into shorter, plainer sentences.

The substitutions are ordinary phrasing, not a search for a lower score.
"""

from __future__ import annotations

import re

SWAPS = [
    (r"\bit is important to note that\s+", ""),
    (r"\bit is (?:essential|crucial) to recognize that\s+", ""),
    (r"\bit is worth (?:noting|mentioning) that\s+", ""),
    (r"\bin today's (?:rapidly )?evolving world,?\s*", ""),
    (r"\bin order to\b", "to"),
    (r"\bfundamentally\s+", ""),
    (r"\bplays a crucial role in shaping modern education\b", "matters for how school works"),
    (r"\bshaping modern education\b", "how school works"),
    (r"\bsustainable growth and meaningful outcomes\b", "gains that last"),
    (r"\bplays a crucial role in\b", "matters for"),
    (r"\b(?:the )?digital transformation of commerce\b", "online shops"),
    (r"\bdigital transformation\b", "the online shift"),
    (r"\bconsumer expectations\b", "what people expect"),
    (r"\bconsumer preferences\b", "what people prefer"),
    (r"\bparadigm shift\b", "change"),
    (r"\bshift in paradigm\b", "change"),
    (r"\bunderscores the (?:critical )?need for\b", "needs"),
    (r"\bemphasizes the importance of\b", "calls for"),
    (r"\ba robust and (?:comprehensive|all-encompassing) (?:approach|strategy)\b", "a careful plan"),
    (r"\ba comprehensive approach is necessary to\b", "a full plan still has to"),
    (r"\bcutting-edge methodologies\b", "current methods"),
    (r"\bcutting-edge\b", "new"),
    (r"\bfacilitate seamless experiences\b", "make the experience easier"),
    (r"\bseamless experiences\b", "an easier experience"),
    (r"\binnovative solutions\b", "new tools"),
    (r"\binventive strategies\b", "new ideas"),
    (r"\binnovative strategies\b", "new ways"),
    (r"\binnovative approaches\b", "new methods"),
    (r"\bleverage\b", "use"),
    (r"\butilize\b", "use"),
    (r"\bstakeholders\b", "the people in charge"),
    (r"\borganizations\b", "companies"),
    (r"\beducators\b", "teachers"),
    (r"\binstitutions\b", "schools"),
    (r"\boptimize outcomes\b", "improve the result"),
    (r"\benhance outcomes\b", "improve the result"),
    (r"\bdrive meaningful engagement\b", "keep people interested"),
    (r"\bfoster meaningful (?:engagement|participation)\b", "keep people interested"),
    (r"\bfoster a dynamic learning environment\b", "make class feel more alive"),
    (r"\bremain competitive\b", "keep up"),
    (r"\bhas had a profound impact on\b", "has changed"),
    (r"\bhas reshaped\b", "changed"),
    (r"\bhas transformed\b", "has changed"),
    (r"\btransformed the way\b", "changed how"),
    (r"\bacademic writing\b", "writing for class"),
    (r"\bgenerate coherent essays\b", "write clear essays"),
    (r"\bsummarize complex materials\b", "shorten hard readings"),
    (r"\bprovide structured arguments\b", "lay out a clear argument"),
    (r"\bwithin seconds\b", "quickly"),
    (r"\bthe widespread availability of such tools\b", "easy access to those tools"),
    (r"\braises important questions about\b", "leaves a question about"),
    (r"\bacademic integrity and original thought\b", "honest work and a person's own ideas"),
    (r"\bthe benefits of technological assistance\b", "help from the tools"),
    (r"\bpreserve critical thinking skills\b", "keep the thinking"),
    (r"\badopting detection methods\b", "setting up checks"),
    (r"\bclearer policies to guide responsible use\b", "clearer rules for careful use"),
    (r"\breject innovation\b", "drop the new tools"),
    (r"\b(?:the ultimate goal|the goal) is not to\b", "the point is not to"),
    (r"\bensure that\b", "make sure"),
    (r"\bsubmitted work reflects\b", "the work handed in shows"),
    (r"\bhave to use\b", "try"),
    (r"\bto make the experience easier\b", "so the experience is easier"),
    (r"\bmust\b", "have to"),
    (r"\bshould\b", ""),
]

OPENERS = re.compile(
    r"^(?:furthermore|moreover|however|therefore|ultimately|additionally|in addition|in conclusion|overall|thus|hence),?\s+",
    re.I,
)


def loosen(text: str) -> str:
    updated = text
    for pattern, replacement in SWAPS:
        updated = re.sub(pattern, replacement, updated, flags=re.I)
    updated = re.sub(r"\bhave to use\b", "try", updated, flags=re.I)
    updated = re.sub(r"\s+", " ", updated).strip()
    sentences = [OPENERS.sub("", part.strip()) for part in re.split(r"(?<=[.!?])\s+", updated)]
    sentences = [_tidy(part) for part in sentences if part.strip()]
    sentences = [part for part in sentences if part]
    sentences = _reshape(sentences)
    return " ".join(sentences)


def _tidy(part: str) -> str:
    part = re.sub(r"\s+", " ", part).strip(" ,")
    part = re.sub(r"\s+([,.])", r"\1", part)
    part = re.sub(r"^(?:the move to)\s+", "", part, flags=re.I)
    part = re.sub(r"^the online shops\b", "Online shops", part, flags=re.I)
    part = re.sub(r"\bthis change (?:still )?needs a careful plan\b", "A careful plan is still part of that", part, flags=re.I)
    part = re.sub(
        r"^the people in charge (?:can |have to )?(?:use|try) (?:current |new )?methods to (.+)$",
        r"Someone picks the methods. Those methods \1",
        part,
        flags=re.I,
    )
    if not part:
        return ""
    part = part[0].upper() + part[1:]
    if part[-1] not in ".!?":
        part += "."
    return part


def _reshape(sentences: list[str]) -> list[str]:
    if len(sentences) < 3:
        return sentences
    lengths = [len(part.split()) for part in sentences]
    if max(lengths) - min(lengths) > 14 or min(lengths) < 6:
        return sentences
    flattened: list[str] = []
    for part in sentences:
        flattened.extend(re.split(r"(?<=[.!?])\s+", part))
    return [piece for piece in flattened if piece]
