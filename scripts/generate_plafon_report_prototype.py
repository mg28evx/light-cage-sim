#!/usr/bin/env python3
"""Generate a metrologically structured visual prototype for the PLAFON report.

The prototype only uses values present in ``plafon.pdf``. Missing evidence is
shown explicitly as pending so the document cannot be mistaken for an
accredited or final test report.
"""

from __future__ import annotations

import math
from pathlib import Path

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "propuesta_formato_plafon.pdf"
SOURCE_PAGE = ROOT / "tmp" / "pdfs" / "plafon" / "page-1.jpg"

W, H = A4
M = 38

INK = HexColor("#14212B")
NAVY = HexColor("#123B5D")
TEAL = HexColor("#00A6A6")
AMBER = HexColor("#F2B134")
RED = HexColor("#D84A4A")
BLUE = HexColor("#3159A7")
GREEN = HexColor("#4D8B67")
MUTED = HexColor("#61717E")
LINE = HexColor("#D9E1E6")
PALE = HexColor("#F4F7F8")
PALE_BLUE = HexColor("#EDF4F8")
PALE_AMBER = HexColor("#FFF6E4")


def fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def set_font(c: canvas.Canvas, size: float, bold: bool = False, color=INK) -> None:
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.setFillColor(color)


def text(c: canvas.Canvas, x: float, y: float, value: str, size=9, bold=False, color=INK) -> None:
    set_font(c, size, bold, color)
    c.drawString(x, y, value)


def text_right(c: canvas.Canvas, x: float, y: float, value: str, size=9, bold=False, color=INK) -> None:
    set_font(c, size, bold, color)
    c.drawRightString(x, y, value)


def wrap(c: canvas.Canvas, x: float, y: float, value: str, width: float, size=9,
         leading=12, bold=False, color=INK, max_lines: int | None = None) -> float:
    words = value.split()
    lines: list[str] = []
    line = ""
    font = "Helvetica-Bold" if bold else "Helvetica"
    for word in words:
        test = f"{line} {word}".strip()
        if stringWidth(test, font, size) <= width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    if max_lines is not None:
        lines = lines[:max_lines]
    set_font(c, size, bold, color)
    for item in lines:
        c.drawString(x, y, item)
        y -= leading
    return y


def header(c: canvas.Canvas, section: str, page: int) -> None:
    c.setFillColor(NAVY)
    c.rect(0, H - 52, W, 52, fill=1, stroke=0)
    text(c, M, H - 30, "EVOLUX", 18, True, white)
    c.setFillColor(AMBER)
    c.circle(M + 85, H - 26, 5, fill=1, stroke=0)
    text(c, M + 105, H - 25, section.upper(), 8.5, True, white)
    text_right(c, W - M, H - 25, "VFR-260713-0683-MS", 8.5, False, white)

    c.setStrokeColor(LINE)
    c.line(M, 27, W - M, 27)
    text(c, M, 15, "PROTOTIPO DOCUMENTAL - NO ES INFORME ACREDITADO", 6.8, True, MUTED)
    text_right(c, W - M, 15, f"PLAFON 60 cm 4000 K  |  {page:02d}/06", 6.8, False, MUTED)

    c.saveState()
    c.translate(W / 2, H / 2)
    c.rotate(32)
    set_font(c, 46, True, Color(0.08, 0.23, 0.36, alpha=0.035))
    c.drawCentredString(0, 0, "PROTOTIPO")
    c.restoreState()


def section_title(c: canvas.Canvas, y: float, kicker: str, title_value: str,
                  subtitle: str | None = None) -> float:
    text(c, M, y, kicker.upper(), 7.8, True, TEAL)
    text(c, M, y - 23, title_value, 20, True, NAVY)
    y -= 43
    if subtitle:
        y = wrap(c, M, y, subtitle, W - 2 * M, 8.8, 12, False, MUTED)
        y -= 4
    return y


def rounded_box(c: canvas.Canvas, x: float, y: float, w: float, h: float,
                fill=PALE, stroke=LINE, radius=8) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(0.7)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def metric_card(c: canvas.Canvas, x: float, y: float, w: float, h: float,
                label: str, value: str, detail: str, color=TEAL) -> None:
    rounded_box(c, x, y, w, h, white, LINE)
    c.setFillColor(color)
    c.roundRect(x, y, 5, h, 2.5, fill=1, stroke=0)
    text(c, x + 15, y + h - 18, label.upper(), 6.8, True, MUTED)
    text(c, x + 15, y + h - 43, value, 18, True, INK)
    text(c, x + 15, y + 12, detail, 7, False, MUTED)


def status_chip(c: canvas.Canvas, x: float, y: float, label: str, ok: bool) -> float:
    fill = HexColor("#E8F6F1") if ok else PALE_AMBER
    color = GREEN if ok else HexColor("#9A6413")
    width = stringWidth(label, "Helvetica-Bold", 7) + 22
    c.setFillColor(fill)
    c.roundRect(x, y, width, 17, 8.5, fill=1, stroke=0)
    c.setFillColor(color)
    c.circle(x + 9, y + 8.5, 2.5, fill=1, stroke=0)
    text(c, x + 15, y + 5.5, label, 7, True, color)
    return width


def kv(c: canvas.Canvas, x: float, y: float, label: str, value: str,
       width: float, pending=False) -> float:
    text(c, x, y, label.upper(), 6.7, True, MUTED)
    color = HexColor("#9A6413") if pending else INK
    text(c, x, y - 15, value, 9, bool(pending), color)
    c.setStrokeColor(LINE)
    c.line(x, y - 24, x + width, y - 24)
    return y - 38


def draw_polar(c: canvas.Canvas, cx: float, cy: float, radius: float) -> None:
    c.saveState()
    c.setStrokeColor(HexColor("#C9D3D9"))
    c.setLineWidth(0.45)
    for frac in (0.25, 0.5, 0.75, 1.0):
        c.circle(cx, cy, radius * frac, fill=0, stroke=1)
    for angle in range(0, 360, 15):
        a = math.radians(angle)
        c.line(cx, cy, cx + radius * math.sin(a), cy + radius * math.cos(a))

    gammas = list(range(0, 100, 5))
    plane0 = [1162, 1161, 1146, 1118, 1082, 1036, 975, 886, 748, 607,
              457, 340, 260, 180, 139, 109, 75, 37, 2, 0]
    plane90 = [1162, 1154, 1139, 1111, 1073, 1026, 966, 878, 738, 572,
               429, 322, 244, 184, 138, 99, 64, 29, 1, 0]

    def shape(values: list[int], color) -> None:
        p = c.beginPath()
        points: list[tuple[float, float]] = []
        for sign in (-1, 1):
            seq = list(zip(gammas, values))
            if sign == 1:
                seq.reverse()
            for gamma, intensity in seq:
                a = math.radians(sign * gamma)
                r = radius * intensity / 1164
                points.append((cx + r * math.sin(a), cy - r * math.cos(a)))
        p.moveTo(*points[0])
        for point in points[1:]:
            p.lineTo(*point)
        p.close()
        c.setStrokeColor(color)
        c.setLineWidth(1.4)
        c.setFillColor(Color(color.red, color.green, color.blue, alpha=0.06))
        c.drawPath(p, fill=1, stroke=1)

    shape(plane0, RED)
    shape(plane90, BLUE)
    text(c, cx - radius, cy - radius - 17, "C0-C180", 7, True, RED)
    text(c, cx - radius + 68, cy - radius - 17, "C90-C270", 7, True, BLUE)
    c.restoreState()


def draw_linear_distribution(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    angles = list(range(-95, 100, 5))
    half = [1162, 1161, 1146, 1118, 1082, 1036, 975, 886, 748, 607,
            457, 340, 260, 180, 139, 109, 75, 37, 2, 0]
    vals = list(reversed(half[1:])) + half
    c.setFillColor(PALE_BLUE)
    c.rect(x, y, w, h, fill=1, stroke=0)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    for frac in (0, 0.25, 0.5, 0.75, 1):
        yy = y + frac * h
        c.line(x, yy, x + w, yy)
    p = c.beginPath()
    for i, (angle, value) in enumerate(zip(angles, vals)):
        px = x + (angle + 95) / 190 * w
        py = y + value / 1164 * h
        if i == 0:
            p.moveTo(px, py)
        else:
            p.lineTo(px, py)
    c.setStrokeColor(NAVY)
    c.setLineWidth(1.8)
    c.drawPath(p, fill=0, stroke=1)
    for angle in (-90, -45, 0, 45, 90):
        px = x + (angle + 95) / 190 * w
        text(c, px - 7, y - 12, f"{angle}°", 6.5, False, MUTED)


def draw_cri_bars(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    values = [93.6, 95.9, 96.5, 93.6, 92.8, 93.2, 94.1, 85.6, 63.5,
              89.2, 93.9, 73.2, 94.5, 97.7, 90.6]
    gap = 3
    bw = (w - gap * (len(values) - 1)) / len(values)
    c.setStrokeColor(LINE)
    for tick in (60, 80, 100):
        yy = y + tick / 100 * h
        c.line(x, yy, x + w, yy)
        text(c, x - 20, yy - 2, str(tick), 6.5, False, MUTED)
    for i, value in enumerate(values):
        bx = x + i * (bw + gap)
        color = RED if i == 8 else TEAL if value >= 90 else AMBER
        c.setFillColor(color)
        c.roundRect(bx, y, bw, h * value / 100, 2, fill=1, stroke=0)
        text(c, bx + 1, y - 11, f"R{i + 1}", 5.7, False, MUTED)
        text(c, bx, y + h * value / 100 + 4, str(round(value)), 5.5, True, INK)


def draw_spectrum_crop(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    if not SOURCE_PAGE.exists():
        rounded_box(c, x, y, w, h, PALE, LINE)
        text(c, x + 15, y + h / 2, "Espectro original no disponible", 8, False, MUTED)
        return
    # The plot occupies x=42..872 and y=716..1109 in the 992x1403 rendered page.
    sx0, sy0, sx1, sy1 = 42, 716, 872, 1109
    source_w, source_h = 992, 1403
    scale = w / (sx1 - sx0)
    draw_w, draw_h = source_w * scale, source_h * scale
    draw_x = x - sx0 * scale
    # ReportLab image origin is bottom-left; convert screenshot top-origin crop.
    crop_bottom = source_h - sy1
    draw_y = y - crop_bottom * scale
    c.saveState()
    path = c.beginPath()
    path.rect(x, y, w, h)
    c.clipPath(path, stroke=0, fill=0)
    c.drawImage(str(SOURCE_PAGE), draw_x, draw_y, draw_w, draw_h,
                preserveAspectRatio=False, mask="auto")
    c.restoreState()
    c.setStrokeColor(LINE)
    c.rect(x, y, w, h, fill=0, stroke=1)


def draw_stability(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    c.setFillColor(PALE)
    c.rect(x, y, w, h, fill=1, stroke=0)
    c.setStrokeColor(LINE)
    for frac in (0, 0.25, 0.5, 0.75, 1):
        c.line(x, y + frac * h, x + w, y + frac * h)
    # Only the initial/final values are numerically available in the source PDF.
    # A straight segment avoids inventing intermediate samples from the visual plot.
    values = [100.0, 99.9]
    p = c.beginPath()
    for i, value in enumerate(values):
        px = x + i / (len(values) - 1) * w
        py = y + (value - 99.0) * h
        if i == 0:
            p.moveTo(px, py)
        else:
            p.lineTo(px, py)
    c.setStrokeColor(TEAL)
    c.setLineWidth(2)
    c.drawPath(p, fill=0, stroke=1)
    text(c, x, y - 13, "0 min", 6.5, False, MUTED)
    text_right(c, x + w, y - 13, "15 min 1 s", 6.5, False, MUTED)


def page_one(c: canvas.Canvas) -> None:
    header(c, "Resumen ejecutivo", 1)
    y = H - 83
    y = section_title(
        c, y, "Informe de caracterización", "PLAFON 60 cm 4000 K",
        "Lectura ejecutiva de desempeño, acompañada por trazabilidad de medición y anexos técnicos auditables.",
    )

    chip_x = M
    chip_x += status_chip(c, chip_x, y - 4, "MEDICION COMPLETA", True) + 8
    status_chip(c, chip_x, y - 4, "INCERTIDUMBRE PENDIENTE", False)

    y -= 96
    gap = 10
    card_w = (W - 2 * M - 2 * gap) / 3
    card_h = 82
    cards = [
        ("Flujo luminoso", "2.553 lm", "0% arriba / 100% abajo", TEAL),
        ("Eficacia luminosa", "54 lm/W", "47,5 W de entrada", AMBER),
        ("Intensidad máxima", "1.164 cd", "Apertura FWHM 90,85°", NAVY),
        ("Color", "3.950 K", "Objetivo nominal 4.000 K", TEAL),
        ("Reproducción", "CRI 93,2", "R9 63,5 | Rf 91,0", RED),
        ("Consistencia", "SDCM 1,1", "Duv -0,0002 | Rg 98,9", GREEN),
    ]
    for row in range(2):
        for col in range(3):
            idx = row * 3 + col
            x = M + col * (card_w + gap)
            yy = y - row * (card_h + gap)
            metric_card(c, x, yy, card_w, card_h, *cards[idx])

    y -= card_h + gap + card_h + 31
    rounded_box(c, M, y - 93, W - 2 * M, 93, PALE_BLUE, PALE_BLUE)
    text(c, M + 16, y - 20, "LECTURA TECNICA", 7, True, NAVY)
    wrap(
        c, M + 16, y - 39,
        "El plafón entrega una distribución directa amplia y prácticamente simétrica. La cromaticidad está muy próxima al objetivo nominal y la reproducción global es alta; el R9 es el indicador cromático más débil y debe mantenerse visible en la primera lectura, no oculto en el anexo.",
        W - 2 * M - 32, 9, 13, False, INK,
    )

    y -= 117
    rounded_box(c, M, y - 72, W - 2 * M, 72, PALE_AMBER, HexColor("#F1D39A"))
    text(c, M + 16, y - 19, "CONTROL DE VALIDEZ", 7, True, HexColor("#81530E"))
    wrap(
        c, M + 16, y - 37,
        "Antes de emitir una versión final deben integrarse la identificación de muestra, el responsable del ensayo, las condiciones ambientales, las normas y cláusulas aplicadas, la incertidumbre expandida y la aprobación firmada.",
        W - 2 * M - 32, 8.5, 12, False, HexColor("#6D5225"),
    )


def page_two(c: canvas.Canvas) -> None:
    header(c, "Trazabilidad y método", 2)
    y = section_title(
        c, H - 83, "Evidencia metrológica", "Qué se midió y bajo qué condiciones",
        "La estructura separa información declarada por el cliente, condiciones observadas y resultados calculados.",
    )

    col_w = (W - 2 * M - 18) / 2
    left, right = M, M + col_w + 18
    yy_l = y - 10
    yy_l = kv(c, left, yy_l, "Producto", "PLAFON 60 cm 4000 K", col_w)
    yy_l = kv(c, left, yy_l, "ID de medición", "VFR-260713-0683-MS", col_w)
    yy_l = kv(c, left, yy_l, "Fecha y hora", "13-07-2026 16:15:02", col_w)
    yy_l = kv(c, left, yy_l, "Identificación de muestra", "PENDIENTE", col_w, True)
    yy_l = kv(c, left, yy_l, "Solicitante / dirección", "PENDIENTE", col_w, True)
    yy_l = kv(c, left, yy_l, "Operador responsable", "PENDIENTE", col_w, True)

    yy_r = y - 10
    yy_r = kv(c, right, yy_r, "Sistema", "LabSpion - Tipo C horizontal", col_w)
    yy_r = kv(c, right, yy_r, "Sensor", "LabSensor Model2 - S/N 0338559446", col_w)
    yy_r = kv(c, right, yy_r, "Calibración sensor", "07-08-2025", col_w)
    yy_r = kv(c, right, yy_r, "Espectrómetro", "Ibsen Freedom VIS (Custom Viso)", col_w)
    yy_r = kv(c, right, yy_r, "Norma / cláusula", "PENDIENTE", col_w, True)
    yy_r = kv(c, right, yy_r, "Incertidumbre expandida", "PENDIENTE", col_w, True)

    y = min(yy_l, yy_r) - 4
    text(c, M, y, "CONDICIONES DE MEDICION", 8, True, NAVY)
    y -= 18
    entries = [
        ("Planos C", "12 / 30°"), ("Resolución gamma", "5°"),
        ("Distancia", "4,09 m"), ("Alimentación", "220 V / 50 Hz"),
        ("Estabilización", "15 min 1 s"), ("Variación", "2,0% (criterio)"),
        ("Temperatura", "PENDIENTE"), ("Humedad", "PENDIENTE"),
    ]
    box_w = (W - 2 * M - 3 * 8) / 4
    for i, (label, value) in enumerate(entries):
        row, col = divmod(i, 4)
        x = M + col * (box_w + 8)
        yy = y - row * 58
        rounded_box(c, x, yy - 45, box_w, 45, PALE if "PENDIENTE" not in value else PALE_AMBER, LINE)
        text(c, x + 10, yy - 15, label.upper(), 6.2, True, MUTED)
        text(c, x + 10, yy - 33, value, 8.4, "PENDIENTE" in value,
             HexColor("#9A6413") if "PENDIENTE" in value else INK)

    y -= 134
    text(c, M, y, "CADENA DE EVIDENCIA", 8, True, NAVY)
    y -= 24
    stages = [
        ("01", "Muestra", "Identidad y estado de recepción", False),
        ("02", "Método", "Norma, geometría y resolución", False),
        ("03", "Medición", "Datos primarios y estabilización", True),
        ("04", "Cálculo", "Indicadores, unidades y redondeo", True),
        ("05", "Revisión", "Incertidumbre y aprobación", False),
    ]
    stage_gap = 7
    stage_w = (W - 2 * M - 4 * stage_gap) / 5
    for i, (num, label, desc, ok) in enumerate(stages):
        x = M + i * (stage_w + stage_gap)
        rounded_box(c, x, y - 94, stage_w, 94, white, LINE)
        c.setFillColor(TEAL if ok else AMBER)
        c.circle(x + 16, y - 18, 9, fill=1, stroke=0)
        text(c, x + 10, y - 21, num, 6.5, True, white)
        text(c, x + 10, y - 43, label, 8, True, INK)
        wrap(c, x + 10, y - 58, desc, stage_w - 20, 6.6, 9, False, MUTED, 3)


def page_three(c: canvas.Canvas) -> None:
    header(c, "Fotometría", 3)
    y = section_title(
        c, H - 83, "Distribución luminosa", "Forma, apertura y alcance del haz",
        "Los gráficos son la lectura principal; la matriz completa permanece en el anexo para auditoría.",
    )

    rounded_box(c, M, 415, 314, 292, white, LINE)
    text(c, M + 16, 684, "DIAGRAMA POLAR RELATIVO", 7.5, True, NAVY)
    draw_polar(c, M + 157, 542, 108)

    rx = M + 328
    rounded_box(c, rx, 415, W - M - rx, 292, PALE_BLUE, PALE_BLUE)
    text(c, rx + 16, 684, "RESULTADOS PRINCIPALES", 7.5, True, NAVY)
    result_rows = [
        ("Flujo total", "2.553 lm"), ("Distribución", "0% / 100%"),
        ("Intensidad máxima", "1.164 cd"), ("FWHM", "90,85°"),
        ("Cono de 90°", "66,7%"), ("Cono de 120°", "86,9%"),
        ("Corte 2,5%", "171,3°"), ("Campo 10%", "146,7°"),
    ]
    yy = 653
    for label, value in result_rows:
        text(c, rx + 16, yy, label, 7.4, False, MUTED)
        text_right(c, W - M - 16, yy, value, 8.5, True, INK)
        yy -= 26

    text(c, M, 387, "DISTRIBUCION LINEAL - INTENSIDAD VS. ANGULO GAMMA", 7.5, True, NAVY)
    draw_linear_distribution(c, M, 245, W - 2 * M, 122)

    text(c, M, 210, "ILUMINANCIA EN EL EJE Y DIAMETRO DEL HAZ", 7.5, True, NAVY)
    distances = [1, 2, 3, 4, 5]
    lux = [1162, 291, 129, 73, 46]
    widths = [2.0, 4.1, 6.1, 10.1, 10.1]
    cell_w = (W - 2 * M) / 5
    for i, (d, l, bw) in enumerate(zip(distances, lux, widths)):
        x = M + i * cell_w
        c.setFillColor(PALE_AMBER if i >= 3 else (PALE if i % 2 == 0 else PALE_BLUE))
        c.rect(x, 101, cell_w, 90, fill=1, stroke=0)
        text(c, x + 12, 171, f"{d} m", 8, True, NAVY)
        text(c, x + 12, 144, f"{l} lx", 13, True, INK)
        text(c, x + 12, 119, f"haz {fmt(bw)} m", 7.2, False, MUTED)
    text(c, M, 77, "Valores transcritos del informe fuente. Los anchos a 4 m y 5 m requieren control por inconsistencia geométrica.", 7, False, MUTED)


def page_four(c: canvas.Canvas) -> None:
    header(c, "Colorimetría", 4)
    y = section_title(
        c, H - 83, "Calidad espectral", "Color objetivo, fidelidad y saturación",
        "La página distingue el promedio CRI del rendimiento por muestra, con R9 resaltado como variable crítica.",
    )

    metrics = [
        ("CCT medida", "3.950 K", "objetivo 4.000 K"),
        ("CRI Ra", "93,2", "promedio R1-R8"),
        ("TM-30", "Rf 91,0", "Rg 98,9"),
        ("Consistencia", "SDCM 1,1", "Duv -0,0002"),
    ]
    mw = (W - 2 * M - 3 * 8) / 4
    for i, (label, value, detail) in enumerate(metrics):
        metric_card(c, M + i * (mw + 8), 612, mw, 72, label, value, detail,
                    RED if i == 1 else TEAL)

    text(c, M, 584, "DISTRIBUCION ESPECTRAL ORIGINAL", 7.5, True, NAVY)
    draw_spectrum_crop(c, M, 397, W - 2 * M, 168)
    text(c, M, 382, "Recorte del gráfico vectorial contenido en el informe fuente; requiere exportación de datos espectrales para análisis numérico.", 6.5, False, MUTED)

    text(c, M, 351, "REPRODUCCION CROMATICA POR MUESTRA CIE", 7.5, True, NAVY)
    draw_cri_bars(c, M + 22, 198, W - 2 * M - 22, 125)

    rounded_box(c, M, 75, W - 2 * M, 83, PALE_AMBER, HexColor("#F1D39A"))
    text(c, M + 16, 137, "INDICADOR A VIGILAR: R9", 7, True, HexColor("#81530E"))
    wrap(c, M + 16, 119,
         "R9 = 63,5 es sustancialmente menor que CRI Ra = 93,2. El formato propuesto lo conserva en la lectura ejecutiva porque el promedio CRI puede ocultar un rendimiento rojo comparativamente bajo.",
         W - 2 * M - 32, 8.3, 12, False, HexColor("#6D5225"))


def page_five(c: canvas.Canvas) -> None:
    header(c, "Electricidad y estabilidad", 5)
    y = section_title(
        c, H - 83, "Consumo y control temporal", "Entrada eléctrica y estabilización",
        "Los indicadores de potencia se presentan con contexto de calidad de red y la estabilidad se muestra como serie temporal.",
    )

    left_w = 260
    rounded_box(c, M, 456, left_w, 235, white, LINE)
    text(c, M + 16, 668, "ENTRADA ELECTRICA", 7.5, True, NAVY)
    rows = [
        ("Potencia activa", "47,5 W"), ("Tensión RMS", "220 V"),
        ("Corriente RMS", "0,221 A"), ("Potencia aparente", "48,52 VA"),
        ("Factor de potencia", "0,98"), ("Factor desplazamiento", "0,98"),
        ("THD corriente", "7,65%"), ("THD tensión", "0,54%"),
    ]
    yy = 641
    for label, value in rows:
        text(c, M + 16, yy, label, 7.7, False, MUTED)
        text_right(c, M + left_w - 16, yy, value, 8.7, True, INK)
        yy -= 24

    rx = M + left_w + 14
    rounded_box(c, rx, 456, W - M - rx, 235, PALE_BLUE, PALE_BLUE)
    text(c, rx + 16, 668, "INDICADORES DERIVADOS", 7.5, True, NAVY)
    metric_card(c, rx + 16, 568, W - M - rx - 32, 76, "Eficacia luminosa", "54 lm/W", "flujo / potencia activa", AMBER)
    metric_card(c, rx + 16, 477, W - M - rx - 32, 76, "Eficiencia de potencia radiada", "18,1%", "valor informado por el sistema", TEAL)

    text(c, M, 424, "CURVA DE ESTABILIZACION", 7.5, True, NAVY)
    draw_stability(c, M, 239, W - 2 * M, 158)
    text(c, M, 213, "Flujo inicial 2.554 lm", 7.4, False, MUTED)
    text(c, M + 165, 213, "Flujo final 2.553 lm", 7.4, False, MUTED)
    text_right(c, W - M, 213, "Variación informada -0,1%", 7.4, True, TEAL)
    text(c, M, 195, "Segmento entre extremos; el PDF fuente no expone las muestras temporales numéricas.", 6.5, False, MUTED)

    rounded_box(c, M, 75, W - 2 * M, 105, PALE_BLUE, PALE_BLUE)
    text(c, M + 16, 157, "CRITERIO DE ACEPTACION", 7, True, NAVY)
    wrap(c, M + 16, 139,
         "El documento fuente indica estabilización en 15 min 1 s y un criterio de variación de 2,0%. La versión final debe vincular este criterio con una norma o procedimiento interno identificado, además de declarar temperatura y humedad ambientales.",
         W - 2 * M - 32, 8.4, 12, False, INK)


def page_six(c: canvas.Canvas) -> None:
    header(c, "Anexo técnico", 6)
    y = section_title(
        c, H - 83, "Datos auditables", "Matriz angular y cierre documental",
        "El anexo conserva suficiente granularidad para verificación sin sobrecargar la lectura ejecutiva.",
    )

    text(c, M, y - 3, "INTENSIDADES POR PLANO C (cd)", 7.5, True, NAVY)
    y -= 24
    gammas = list(range(0, 100, 5))
    p0 = [1162,1161,1146,1118,1082,1036,975,886,748,607,457,340,260,180,139,109,75,37,2,0]
    p90 = [1162,1154,1139,1111,1073,1026,966,878,738,572,429,322,244,184,138,99,64,29,1,0]
    p180 = [1162,1160,1147,1121,1083,1035,975,886,751,601,476,344,257,195,140,108,66,33,1,0]
    p270 = [1162,1156,1143,1118,1082,1038,980,889,753,601,460,344,261,195,144,108,73,37,2,0]
    cols = ["gamma", "C0", "C90", "C180", "C270"]
    col_widths = [72, 92, 92, 92, 92]
    x_positions = [M]
    for cw in col_widths[:-1]:
        x_positions.append(x_positions[-1] + cw)
    c.setFillColor(NAVY)
    c.rect(M, y - 21, sum(col_widths), 21, fill=1, stroke=0)
    for x, label in zip(x_positions, cols):
        text(c, x + 8, y - 14, label, 7, True, white)
    y -= 21
    row_h = 18
    for i, gamma in enumerate(gammas):
        c.setFillColor(PALE if i % 2 == 0 else white)
        c.rect(M, y - row_h, sum(col_widths), row_h, fill=1, stroke=0)
        values = [f"{gamma}°", str(p0[i]), str(p90[i]), str(p180[i]), str(p270[i])]
        for x, value in zip(x_positions, values):
            text(c, x + 8, y - 12.5, value, 7, False, INK)
        y -= row_h

    y -= 22
    text(c, M, y, "CIERRE Y APROBACION", 7.5, True, NAVY)
    y -= 19
    boxes = [
        ("Revisión técnica", "PENDIENTE"),
        ("Incertidumbre", "PENDIENTE"),
        ("Firma responsable", "PENDIENTE"),
    ]
    bw = (W - 2 * M - 2 * 10) / 3
    for i, (label, value) in enumerate(boxes):
        x = M + i * (bw + 10)
        rounded_box(c, x, y - 73, bw, 73, PALE_AMBER, HexColor("#F1D39A"))
        text(c, x + 12, y - 20, label.upper(), 6.5, True, HexColor("#81530E"))
        text(c, x + 12, y - 48, value, 10, True, HexColor("#9A6413"))

    text(c, M, 42, "Fuente: plafon.pdf, emitido 13-07-2026. Cifras reproducidas sin reinterpretar el método de ensayo.", 6.6, False, MUTED)


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=A4, pageCompression=1)
    c.setTitle("Propuesta de formato metrológico - PLAFON 60 cm 4000 K")
    c.setAuthor("EVOLUX / prototipo generado para revisión")
    for page in (page_one, page_two, page_three, page_four, page_five, page_six):
        page(c)
        c.showPage()
    c.save()
    return OUTPUT


if __name__ == "__main__":
    print(build())
