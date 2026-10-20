"""Genera docs/Manual_de_uso_Knowledge_Orchestrator.pdf a partir de manual.html.

Uso (Python del sistema con PyMuPDF y Pillow; Chrome o Edge instalado):
    python docs/manual/build_pdf.py

Además de imprimir el HTML:
- recorta la barra lateral de las capturas de pantallas concretas (más grande lo que importa);
- ajusta la altura de cada captura que dejaría media página vacía antes de ella;
- repite la cabecera de las tablas largas y no parte las cortas;
- escribe el índice con números de página, cabecera, pie y marcadores del PDF.
El HTML y las imágenes originales no se modifican.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "manual.html"
OUTPUT = HERE.parent / "Manual_de_uso_Knowledge_Orchestrator.pdf"
BROWSERS = (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
FONT = r"C:\Windows\Fonts\segoeui.ttf"
TITLE = "Knowledge Orchestrator · Manual de uso"
# Se corre con el Python del sistema, sin el paquete instalado: la versión se lee del código.
VERSION = re.search(r'__version__ = "([^"]+)"',
                    (HERE.parents[1] / "src" / "knowledge_orchestrator" / "__init__.py").read_text(encoding="utf-8"))[1]
SIDEBAR_PX = 236            # ancho de la barra lateral en las capturas de 1440 px
KEEP_SIDEBAR = {"m01_inicio.png", "s1_01_inicio_primer_arranque.png"}  # se comenta la barra lateral
MM = 72 / 25.4
PAGE_H = 842
MARGIN_TOP, MARGIN_BOTTOM = 20 * MM, 20 * MM
FIGURE_MAX_MM = 118         # altura máxima por defecto de una captura
FIGURE_MIN_MM = 85          # por debajo, mejor pasar a la página siguiente que encoger
CHAPTER_MIN_MM = 55         # un capítulo no empieza en los últimos milímetros de la página
SMALL_TABLE_ROWS = 9        # las tablas con menos filas no se parten

EXTRA_CSS = """
  @page { size: A4; margin: 20mm 17mm 20mm 17mm; }
  html { font-size: 10.2pt; }
  p, li { orphans: 3; widows: 3; }
  h2, h3, h4 { break-after: avoid; page-break-after: avoid; }
  h3 + p, h4 + p { break-before: avoid; }
  .steps > li, .note, .warn, .tip, .bad, .flow { break-inside: avoid; }
  figure { margin: 3mm 0 4.5mm; break-inside: avoid; }
  figure img { width: auto; max-width: 100%; max-height: __MAX__mm; margin: 0 auto; }
  figure.half img { max-width: 70%; }
  figure.small img { max-width: 52%; }
  figure img.ui { border-color: #9aa6b2; }
  thead { display: table-header-group; }
  table.keep { break-inside: avoid; }
  .toc ol { columns: 1; }
  .toc li { display: flex; align-items: baseline; margin: 0 0 2.4mm; font-size: 11pt; }
  .toc li a { flex: 0 1 auto; }
  .toc li .dots { flex: 1 1 auto; border-bottom: 1px dotted #9aa6b2; margin: 0 2mm; transform: translateY(-1.2mm); }
  .toc li .pg { flex: 0 0 9mm; text-align: right; color: #5a6573; font-variant-numeric: tabular-nums; }
  .cover { height: 250mm; }
  .chapter { break-before: auto; page-break-before: auto; margin-top: 11mm; }
  .toc, #que-es { break-before: page; page-break-before: always; margin-top: 0; }
  h2 { font-size: 17pt; padding: 2.2mm 0 2mm; border-bottom: 2.5px solid var(--accent); }
"""


def browser() -> str:
    for path in BROWSERS:
        if Path(path).exists():
            return path
    raise SystemExit("No se encuentra Chrome ni Edge para imprimir el PDF.")


def prepare_images(build: Path) -> None:
    """Copia las imágenes al directorio de trabajo, sin la barra lateral cuando no aporta."""
    (build / "img").mkdir(parents=True)
    for image in (HERE / "img").glob("*.png"):
        target = build / "img" / image.name
        with Image.open(image) as picture:
            if picture.width == 1440 and image.name not in KEEP_SIDEBAR:
                picture.crop((SIDEBAR_PX, 0, picture.width, picture.height)).save(target)
            else:
                shutil.copyfile(image, target)


def transform_tables(html: str) -> str:
    def table(match: re.Match[str]) -> str:
        attrs, body = match.group(1), match.group(2)
        rows = re.findall(r"<tr\b.*?</tr>", body, flags=re.S)
        if rows and "<th" in rows[0]:
            body = body.replace(rows[0], f"<thead>{rows[0]}</thead><tbody>", 1) + "</tbody>"
        if len(rows) <= SMALL_TABLE_ROWS:
            attrs = attrs + ' class="keep"' if "class=" not in attrs else attrs.replace('class="', 'class="keep ')
        return f"<table{attrs}>{body}</table>"

    return re.sub(r"<table([^>]*)>(.*?)</table>", table, html, flags=re.S)


def render(html: str, build: Path, overrides: dict[int, float], pages: dict[str, int],
           breaks: set[str]) -> Path:
    for anchor in breaks:
        html = html.replace(f'<section class="chapter" id="{anchor}">',
                            f'<section class="chapter" id="{anchor}" style="break-before:page;margin-top:0">')
    counter = iter(range(10_000))

    def figure(match: re.Match[str]) -> str:
        index = next(counter)
        tag = match.group(0)
        if index in overrides:
            tag = tag.replace("<img ", f'<img style="max-height:{overrides[index]:.1f}mm" ', 1)
        return tag

    page_html = re.sub(r"<figure\b[^>]*>\s*<img ", figure, html)

    def toc_entry(match: re.Match[str]) -> str:
        anchor, number, label = match.group(1), match.group(2), match.group(3)
        page = pages.get(anchor, "")
        return (f'<li><a href="#{anchor}"><span class="n">{number}</span>{label}</a>'
                f'<span class="dots"></span><span class="pg">{page}</span></li>')

    page_html = re.sub(r'<li><a href="#([^"]+)"><span class="n">(\d+)</span>(.*?)</a></li>', toc_entry, page_html)
    page = build / "manual_print.html"
    page.write_text(page_html, encoding="utf-8")
    pdf = build / "manual.pdf"
    pdf.unlink(missing_ok=True)
    subprocess.run([browser(), "--headless=new", "--disable-gpu", f"--user-data-dir={build / 'profile'}",
                    "--no-pdf-header-footer", "--no-first-run", f"--print-to-pdf={pdf}", page.as_uri()],
                   check=True, capture_output=True, timeout=180)
    return pdf


def headings(doc: fitz.Document) -> list[tuple[int, int, str, float]]:
    """(nivel, página 1-based, texto, altura) de h2 (≥15 pt) y h3 (≈12 pt en color de acento)."""
    found = []
    for number, page in enumerate(doc, start=1):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = line["spans"]
                text = "".join(span["text"] for span in spans).strip()
                if not text or not spans:
                    continue
                size, color = spans[0]["size"], spans[0]["color"]
                if size >= 15 and number > 1:
                    found.append((1, number, text, line["bbox"][1]))
                elif 11.5 <= size < 13 and color == 0x0E8FB0:
                    found.append((2, number, text, line["bbox"][1]))
    return found


def figure_gaps(doc: fitz.Document, current: dict[int, float]) -> tuple[int, float] | None:
    """Primera captura que empieza página dejando hueco aprovechable al final de la anterior."""
    placements = []
    for number, page in enumerate(doc):
        for info in page.get_image_info():
            placements.append((number, fitz.Rect(info["bbox"])))
    placements.sort(key=lambda item: (item[0], item[1].y0))
    for index, (number, rect) in enumerate(placements):
        above = rect.y0 - MARGIN_TOP          # título u otra línea que acompaña a la captura
        if number < 2 or above > 32 * MM:
            continue
        previous = doc[number - 1]
        bottoms = [b[3] for b in previous.get_text("blocks") if b[3] < PAGE_H - MARGIN_BOTTOM + 2]
        bottoms += [fitz.Rect(i["bbox"]).y1 for i in previous.get_image_info()]
        last = max(bottoms, default=MARGIN_TOP)
        free_mm = (PAGE_H - MARGIN_BOTTOM - last - max(above, 0)) / MM - 4.5 - 3 - 9
        height_mm = rect.height / MM
        if FIGURE_MIN_MM <= free_mm < height_mm - 1 and current.get(index, FIGURE_MAX_MM) > free_mm:
            return index, free_mm - 1
    return None


SEGOE = fitz.Font(fontfile=FONT)


def stamp(doc: fitz.Document, marks: list[tuple[int, int, str, float]]) -> None:
    # Un capítulo cuenta para la cabecera desde la página en la que está arriba del todo.
    chapters = [(page if y < MARGIN_TOP + 30 * MM else page + 1, text) for level, page, text, y in marks if level == 1]
    total = doc.page_count
    for number, page in enumerate(doc, start=1):
        if number == 1:
            continue
        chapter = ""
        for start, text in chapters:
            if start <= number:
                chapter = text
        width = page.rect.width
        page.insert_font(fontname="segoe", fontfile=FONT)
        left, right = 17 * MM, width - 17 * MM
        page.insert_text((left, 12 * MM), TITLE, fontname="segoe", fontsize=8, color=(0.45, 0.5, 0.56))
        if chapter and chapter != "Contenido":
            text_width = SEGOE.text_length(chapter, fontsize=8)
            page.insert_text((right - text_width, 12 * MM), chapter, fontname="segoe", fontsize=8,
                             color=(0.45, 0.5, 0.56))
        page.draw_line((left, 13.6 * MM), (right, 13.6 * MM), color=(0.85, 0.87, 0.9), width=0.6)
        page.draw_line((left, PAGE_H - 13.2 * MM), (right, PAGE_H - 13.2 * MM), color=(0.85, 0.87, 0.9), width=0.6)
        label = f"{number} / {total}"
        label_width = SEGOE.text_length(label, fontsize=8.5)
        page.insert_text((right - label_width, PAGE_H - 9 * MM), label, fontname="segoe", fontsize=8.5,
                         color=(0.35, 0.4, 0.46))
        page.insert_text((left, PAGE_H - 9 * MM), f"Versión {VERSION}", fontname="segoe", fontsize=8,
                         color=(0.45, 0.5, 0.56))


def main() -> None:
    html = SOURCE.read_text(encoding="utf-8")
    html = html.replace("</style>", EXTRA_CSS.replace("__MAX__", str(FIGURE_MAX_MM)) + "</style>", 1)
    html = transform_tables(html)
    anchors = re.findall(r'<section class="chapter" id="([^"]+)">\s*<h2>(.*?)</h2>', html)
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp)
        prepare_images(build)
        overrides: dict[int, float] = {}
        breaks: set[str] = set()
        pages: dict[str, int] = {anchor: 88 for anchor, _ in anchors}   # reserva el ancho de dos cifras
        for _ in range(40):
            doc = fitz.open(render(html, build, overrides, pages, breaks))
            gap = figure_gaps(doc, overrides)
            if gap is not None:
                overrides[gap[0]] = gap[1]
            else:
                late = [text for level, _, text, y in headings(doc)
                        if level == 1 and y > PAGE_H - MARGIN_BOTTOM - CHAPTER_MIN_MM * MM]
                anchor = next((a for a, title in anchors if late and re.sub(r"<[^>]+>", "", title) == late[0]), None)
                if anchor is None or anchor in breaks:
                    break
                breaks.add(anchor)
            doc.close()
        marks = headings(doc)
        starts = {text: page for level, page, text, _ in marks if level == 1}
        pages = {anchor: starts.get(re.sub(r"<[^>]+>", "", title), "") for anchor, title in anchors}
        doc.close()
        doc = fitz.open(render(html, build, overrides, pages, breaks))
        marks = headings(doc)
        stamp(doc, marks)
        doc.set_toc([[1, "Portada", 1]] + [[level, text, page] for level, page, text, _ in marks])
        doc.set_metadata({"title": f"Knowledge Orchestrator — Manual de uso {VERSION}", "author": "Knowledge Orchestrator",
                          "subject": "Manual de uso", "keywords": "Knowledge Orchestrator, Obsidian, AI Broker"})
        doc.save(OUTPUT, garbage=4, deflate=True)
        print(f"{OUTPUT} · {doc.page_count} páginas · {len(overrides)} capturas ajustadas · {len(breaks)} capítulos a página nueva")
        doc.close()


if __name__ == "__main__":
    main()
