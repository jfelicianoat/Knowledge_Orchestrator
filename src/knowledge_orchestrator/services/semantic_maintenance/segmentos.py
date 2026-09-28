"""Segmentos numerados de la nota y de la fuente, y respaldo de cada afirmación.

Dos lecciones medidas contra el Broker real dieron forma a este módulo:

1. Ningún modelo sabe contar caracteres (0.3.3) y tampoco copia: parafrasea.
   `lfm2:24b` devolvió 10 afirmaciones correctas y ninguna cita literal. Pedirle
   texto era pedirle lo único que no hace bien. Lo que sí hace bien es copiar un
   identificador corto. Así que la aplicación trocea la nota y la fuente en
   segmentos numerados (N1, N2… y S1, S2…) y el modelo solo elige números.
   El texto de la afirmación es siempre el de la nota, nunca redacción suya.

2. Una cita exacta de la nota prueba que la afirmación está en el resumen que
   escribió otra IA, no que la fuente la diga (auditoría H07: «La Luna está
   hecha de queso» quedaba como conocimiento vigente). El respaldo se busca en
   la captura original, y lo comprueba la aplicación, no el modelo.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

#: Solo se proponen al modelo frases con contenido; un «Sí.» no es afirmable.
MIN_SEGMENT_CHARS = 12
#: Por encima de esto una línea se parte en frases.
MAX_NOTE_SEGMENT_CHARS = 320
#: Tamaño objetivo de cada segmento de la fuente: unas dos o tres líneas de
#: subtítulos, suficiente para contener una idea sin disparar el prompt.
SOURCE_SEGMENT_CHARS = 360
#: Techo de fuente que viaja en el prompt. Una transcripción de dos horas no
#: cabe en la ventana de un modelo local; se envían los tramos más afines a
#: la nota, en su orden original.
MAX_SOURCE_PROMPT_CHARS = 36_000
#: Proporción mínima (ponderada por rareza) de las raíces con contenido de la
#: afirmación que tienen que aparecer en el tramo de la fuente, y mínimo de
#: raíces distintas coincidentes. Medido sobre respuestas reales: con 0.5 sin
#: ponderar y ventanas de tres tramos, «los beneficios se reparten» casaba con
#: «publico vídeos a diario… inversiones» por las palabras del tema.
MIN_COVERAGE = 0.5
MIN_MATCHED_STEMS = 2
#: Longitud de la raíz: iguala flexiones («reparten»/«reparto»,
#: «trimestral»/«trimestralmente») sin mezclar palabras distintas.
STEM_LENGTH = 6
#: Secciones del formato de apuntes que no contienen afirmaciones sobre la
#: fuente: la cobertura habla del propio apunte y el checklist son tareas.
NON_CLAIM_SECTIONS = ("cobertura", "checklist", "preguntas de repaso")

_TIMESTAMP = re.compile(r"^\s*\[\d{1,2}:\d{2}(?::\d{2})?\]\s*")
_LIST_MARKER = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|>\s*)+")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_WORD = re.compile(r"[\w]+", re.UNICODE)
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9&]{1,}\b")
_STOPWORDS = frozenset("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun aunque bien cada casi como con
contra cual cuales cuando cuanto de del desde donde dos el ella ellas ello ellos en entre era eran es
esa esas ese eso esos esta estaba estado estan estar estas este esto estos fue fueron ha habia han
hasta hay hace hacen hacer la las le les lo los mas me mi mis mucho muy nada ni no nos nosotros o os
otra otras otro otros para pero poco por porque puede pueden que quien se sea ser si sin sino sobre
solo son su sus tambien tan tanto te tiene tienen todo todos tu tus un una unas uno unos usted ya yo
the and for with that this from are was were been have has into your you our their they them than then
what when which will would there here about also just more most some such only over very can could
""".split())


@dataclass(frozen=True, slots=True)
class Segment:
    """Un tramo del documento con su identificador y sus offsets reales."""

    segment_id: str
    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class SourceMatch:
    """Tramo de la fuente original que respalda una afirmación."""

    start: int
    end: int
    quote: str
    method: str  # LEXICAL | MODEL_LINK
    score: float


def _plain(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def content_words(value: str) -> set[str]:
    """Raíces de las palabras que llevan significado: sin tildes, mayúsculas ni palabras vacías."""

    return {
        word[:STEM_LENGTH] for word in _WORD.findall(_plain(value))
        if not word.isdigit() and len(word) >= 4 and word not in _STOPWORDS
    }


def numbers_in(value: str) -> set[str]:
    """Cifras normalizadas: «2,5» y «2.5» son la misma; «1.0» y «2.0» no."""

    return {re.sub(r"[.,]0+$", "", number.replace(",", ".")) for number in _NUMBER.findall(value)}


def _strip_markup(text: str) -> str:
    return text.replace("**", "").replace("__", "").replace("`", "")


def note_segments(document: str, *, body_start: int, body_end: int | None = None) -> list[Segment]:
    """Frases afirmables del cuerpo de la nota, con sus offsets en el documento.

    Se descartan títulos, separadores, tablas y bloques de código. El marcador
    de lista queda fuera del tramo para que la cita sea solo la frase.
    """

    end_of_body = len(document) if body_end is None else body_end
    segments: list[Segment] = []
    in_code = False
    skipping_section = False
    position = body_start
    for line in document[body_start:end_of_body].splitlines(keepends=True):
        line_start = position
        position += len(line)
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if stripped.startswith("#"):
            heading = _plain(stripped.lstrip("#").strip())
            skipping_section = any(heading.startswith(name) for name in NON_CLAIM_SECTIONS)
            continue
        if in_code or skipping_section or not stripped or stripped.startswith(("|", "---", "***", "<!--")):
            continue
        marker = _LIST_MARKER.match(line)
        offset = marker.end() if marker else len(line) - len(line.lstrip())
        content = line[offset:].rstrip("\r\n").rstrip()
        pieces = [content] if len(content) <= MAX_NOTE_SEGMENT_CHARS else _SENTENCE_END.split(content)
        cursor = line_start + offset
        for piece in pieces:
            located = document.find(piece, cursor, position)
            if located == -1:
                continue
            cursor = located + len(piece)
            if len(piece.strip()) < MIN_SEGMENT_CHARS or not _is_statement(piece):
                continue
            segments.append(Segment(f"N{len(segments) + 1}", located, located + len(piece), piece))
    return segments


def _is_statement(text: str) -> bool:
    """Descarta lo que no afirma nada: etiquetas («Requisitos:»), preguntas y casillas."""

    plain = _strip_markup(text).strip()
    if plain.endswith((":", "?", "¿")) or plain.startswith(("[ ]", "[x]", "[X]", "¿")):
        return False
    words = content_words(plain)
    # «Activo: SPY (S&P 500 ETF)» afirma algo aunque solo tenga una palabra larga.
    return len(words) >= 2 or (bool(words) and (bool(numbers_in(plain)) or bool(_ACRONYM.search(plain))))


def source_segments(transcript: str) -> list[Segment]:
    """Tramos consecutivos de la fuente original, sin partir líneas.

    El texto que se enseña al modelo va sin marcas de tiempo; los offsets
    apuntan al texto original, que es lo que se conserva como evidencia.
    """

    segments: list[Segment] = []
    start: int | None = None
    end = 0
    texts: list[str] = []
    position = 0
    for line in transcript.splitlines(keepends=True):
        line_start = position
        position += len(line)
        stamp = _TIMESTAMP.match(line)
        text_start = line_start + (stamp.end() if stamp else 0)
        text = transcript[text_start:position].strip()
        if not text:
            continue
        if start is None:
            start = text_start
        texts.append(text)
        end = line_start + len(line.rstrip("\r\n"))
        if sum(len(item) + 1 for item in texts) >= SOURCE_SEGMENT_CHARS:
            segments.append(Segment(f"S{len(segments) + 1}", start, end, " ".join(texts)))
            start, texts = None, []
    if start is not None and texts:
        segments.append(Segment(f"S{len(segments) + 1}", start, end, " ".join(texts)))
    return segments


def select_source_for_prompt(sources: Sequence[Segment], notes: Sequence[Segment],
                             *, limit: int = MAX_SOURCE_PROMPT_CHARS) -> list[Segment]:
    """Los tramos de la fuente que caben en el prompt, priorizando los afines a la nota."""

    if sum(len(segment.text) for segment in sources) <= limit:
        return list(sources)
    vocabulary = set().union(*(content_words(segment.text) for segment in notes)) if notes else set()
    ranked = sorted(
        range(len(sources)),
        key=lambda index: len(content_words(sources[index].text) & vocabulary),
        reverse=True,
    )
    chosen: set[int] = set()
    used = 0
    for index in ranked:
        size = len(sources[index].text)
        if used + size > limit:
            continue
        chosen.add(index)
        used += size
    return [sources[index] for index in sorted(chosen)]


def _windows(count: int, indexes: Iterable[int] | None = None) -> Iterable[tuple[int, int]]:
    """Ventanas de uno o dos tramos seguidos: una idea puede cruzar un corte, no tres."""

    allowed = range(count) if indexes is None else sorted(set(indexes))
    for first in allowed:
        for width in (1, 2):
            last = first + width - 1
            if last < count:
                yield first, last


_LABEL = re.compile(r"^\s*(?:\*\*|__)?([^:*_]{1,40}?)(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*(?P<rest>.+)$", re.S)


def _without_label(statement: str) -> str:
    """«**Frecuencia:** Reparto trimestral.» afirma lo que va tras la etiqueta.

    La etiqueta es estructura del apunte, no contenido de la fuente; contarla
    hundía la cobertura de frases que la fuente sí dice (medido en real).
    """

    match = _LABEL.match(_strip_markup(statement))
    if match and len(match.group(1).split()) <= 4 and len(content_words(match.group("rest"))) >= 2:
        return match.group("rest")
    return statement


def find_support(
    statement: str,
    transcript: str,
    sources: Sequence[Segment],
    *,
    hinted: Sequence[str] = (),
) -> tuple[str, list[SourceMatch]]:
    """Grado de respaldo de una afirmación en la fuente original.

    - `SOURCE`: la aplicación encontró un tramo que contiene al menos la mitad
      de sus palabras con contenido y todas sus cifras.
    - `MODEL_LINKED`: el modelo señaló tramos existentes, pero no se pudo
      verificar (típico con una fuente en otro idioma). Se guardan para que una
      persona lo compruebe; no bastan para proponer cambios.
    - `SUMMARY_ONLY`: nada lo respalda; solo consta en el resumen generado.
    """

    by_id = {segment.segment_id: index for index, segment in enumerate(sources)}
    hinted_indexes = [by_id[item] for item in hinted if item in by_id]
    claim_text = _without_label(statement)
    wanted, required_numbers = content_words(claim_text), numbers_in(claim_text)
    words = [content_words(segment.text) for segment in sources]
    numbers = [numbers_in(segment.text) for segment in sources]
    # Rareza de cada raíz en ESTA fuente: en un vídeo de ETFs, «dividendo» sale
    # en todos los tramos y no prueba nada; «trimestral» sí.
    frequency: dict[str, int] = {}
    for stems in words:
        for stem in stems:
            frequency[stem] = frequency.get(stem, 0) + 1
    total = max(1, len(sources))

    def weight(stem: str) -> float:
        return math.log((total + 1) / (frequency.get(stem, 0) + 1)) + 1.0

    wanted_weight = sum(weight(stem) for stem in wanted)
    best: tuple[float, int, int] | None = None
    # Primero donde dijo el modelo; si ahí no está, en toda la fuente.
    for scope in ([hinted_indexes] if hinted_indexes else []) + [None]:
        for first, last in _windows(len(sources), scope):
            if required_numbers and not required_numbers <= set().union(*numbers[first:last + 1]):
                continue  # una cifra distinta es otra afirmación, aunque compartan palabras
            matched = wanted & set().union(*words[first:last + 1])
            if len(matched) < min(MIN_MATCHED_STEMS, len(wanted)) or not wanted_weight:
                continue
            score = sum(weight(stem) for stem in matched) / wanted_weight
            # A igualdad de cobertura gana el tramo más corto: cita más precisa.
            if best is None or score > best[0] + 1e-9 or (
                abs(score - best[0]) < 1e-9 and last - first < best[2] - best[1]
            ):
                best = (score, first, last)
        if best is not None and best[0] >= MIN_COVERAGE:
            break
    if best is not None and best[0] >= MIN_COVERAGE:
        score, first, last = best
        start, end = sources[first].start, sources[last].end
        return "SOURCE", [SourceMatch(start, end, transcript[start:end], "LEXICAL", round(score, 3))]
    if hinted_indexes:
        return "MODEL_LINKED", [
            SourceMatch(sources[index].start, sources[index].end,
                        transcript[sources[index].start:sources[index].end], "MODEL_LINK", 0.0)
            for index in sorted(set(hinted_indexes))[:3]
        ]
    return "SUMMARY_ONLY", []


def segmentation_fingerprint(notes: Sequence[Segment], sources: Sequence[Segment]) -> str:
    """Huella de la numeración N#/S# que vio el modelo.

    Los identificadores se recalculan al leer la respuesta; si la segmentación
    cambiara entre el envío y la respuesta (una actualización de la aplicación
    con trabajos en vuelo), N12 señalaría otra frase. Con la huella en la
    petición, ese caso se detecta y se pide reintentar en vez de mezclar.
    """

    import hashlib
    import json

    layout = [[item.segment_id, item.start, item.end] for item in (*notes, *sources)]
    return hashlib.sha256(json.dumps(layout).encode("utf-8")).hexdigest()[:16]
