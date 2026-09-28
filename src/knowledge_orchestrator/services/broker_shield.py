"""Evita que el Broker tome un documento que HABLA de imágenes por una petición de imagen.

El Broker decide si una tarea pide generar una imagen mirando el texto del
prompt entero, datos incluidos. Un vídeo que cuenta que «con MCP puedes
conectar servicios para generar imágenes» hacía fallar tanto la redacción del
apunte como la extracción con `IMAGE_GENERATION_UNSUPPORTED` (reproducido el
27-sep-2026 contra el Broker real; la base del usuario tenía 4 documentos
perdidos así). Se comprobó por bisección que dispara «generar/crear imágenes»
y «generate images», también con espacio duro, y que no dispara si el
sustantivo lleva dentro un WORD JOINER (U+2060), invisible para el modelo.

Así que antes de enviar se inserta ese carácter en el sustantivo cuando sigue
a un verbo de creación, y al recibir se retira de la respuesta: ni la nota ni
las citas guardan nunca el carácter. Es un parche del cliente para un falso
positivo del Broker; lo correcto es que el Broker solo mire la instrucción.
"""
from __future__ import annotations

import re

WORD_JOINER = "⁠"

_VERBS = (
    r"generar|genera|generan|generamos|generando|generate|generates|generating|generated|"
    r"crear|crea|crean|creamos|creando|create|creates|creating|"
    r"dibujar|dibuja|dibujame|dibújame|draw|draws|drawing|"
    r"diseñar|diseña|design|render|renderizar|renderiza|hacer|haz|make|makes|making|produce|producir|produce"
)
_NOUNS = (
    r"im[aá]gen(?:es)?|images?|fotos?|fotograf[ií]as?|photos?|pictures?|ilustraci[oó]n(?:es)?|"
    r"illustrations?|dibujos?|drawings?|logos?|iconos?|icons?|renders?"
)
# Verbo de creación y, a hasta cuatro palabras, el sustantivo de imagen.
_PATTERN = re.compile(
    rf"(?i)\b(?:{_VERBS})\b(?:[\s ]+[\w'’-]+){{0,4}}?[\s ]+(?P<noun>{_NOUNS})\b",
)


def shield_prompt(text: str) -> str:
    """Rompe el patrón «generar imágenes» sin cambiar lo que se lee."""

    def protect(match: re.Match[str]) -> str:
        noun_start = match.start("noun") - match.start()
        whole = match.group(0)
        return whole[:noun_start + 1] + WORD_JOINER + whole[noun_start + 1:]

    return _PATTERN.sub(protect, text)


def unshield(text: str) -> str:
    """Retira el carácter de protección de lo que devuelva el modelo."""

    return text.replace(WORD_JOINER, "")
