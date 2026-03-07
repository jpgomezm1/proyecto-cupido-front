#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Professional PDF Generator for Property Proposals
Canvas-based rendering with AI-enhanced copywriting
"""

import os
import re
import json
import requests
from io import BytesIO
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import Paragraph


# ─── Page dimensions ───
W, H = letter  # 612 x 792
MARGIN = 50
CONTENT_W = W - 2 * MARGIN  # 512

# ─── Color palette ───
ACCENT = HexColor('#2AE38C')
ACCENT_DARK = HexColor('#1FB872')
DARK = HexColor('#0a0a0a')
DARK_CARD = HexColor('#141414')
WHITE = HexColor('#FFFFFF')
TEXT_DARK = HexColor('#1a1a1a')
TEXT_BODY = HexColor('#444444')
TEXT_MUTED = HexColor('#888888')
TEXT_SUBTLE = HexColor('#aaaaaa')
COVER_TEXT = HexColor('#cccccc')
LIGHT_BG = HexColor('#f5f5f5')
BORDER = HexColor('#e5e5e5')

FYNDER_LOGO_URL = "https://storage.googleapis.com/cluvi/FYNDER/logo_blanco_fynder_final.png"
FINDY_AVATAR_URL = "https://storage.googleapis.com/cluvi/FYNDER/emoji_fynder.png"

MONTHS_ES = {
    1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
    5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
    9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
}

AI_MODEL = "claude-haiku-4-5-20251001"


# ─── Utilities ───

def fmt_short(price):
    """$550 M"""
    if not price:
        return "Consultar"
    try:
        p = int(price)
        if p >= 1_000_000_000:
            return f"${p / 1_000_000_000:,.1f} Mil M"
        if p >= 1_000_000:
            return f"${p / 1_000_000:,.0f} M"
        return f"${p:,.0f}"
    except (ValueError, TypeError):
        return "Consultar"


def fmt_full(price):
    """$550,000,000"""
    if not price:
        return "Consultar"
    try:
        return f"${int(price):,.0f}"
    except (ValueError, TypeError):
        return "Consultar"


def _fetch_image(url):
    """Fetch image from URL, return ImageReader or None"""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=6)
        resp.raise_for_status()
        return ImageReader(BytesIO(resp.content))
    except Exception:
        return None


def _enhance_with_ai(properties):
    """
    Use Claude Haiku to generate professional titles and descriptions.
    Returns dict mapping property id -> {titulo, descripcion}.
    Falls back gracefully on any error.
    """
    api_key = os.getenv('ANTHROPIC_API_KEY', '')
    if not api_key:
        return {}

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except Exception:
        return {}

    props_data = []
    for p in properties:
        props_data.append({
            "id": p['id'],
            "titulo_original": str(p.get('titulo', '')),
            "tipo": str(p.get('tipo_propiedad', '') or ''),
            "ciudad": str(p.get('ciudad', '') or ''),
            "zona": str(p.get('zona', '') or ''),
            "precio": fmt_full(p.get('precio')),
            "area_m2": str(p.get('area_construida', '') or ''),
            "habitaciones": str(p.get('habitaciones', '') or ''),
            "banos": str(p.get('banos', '') or ''),
            "estrato": str(p.get('estrato', '') or ''),
            "parqueaderos": str(p.get('parqueaderos', '') or ''),
            "administracion": fmt_full(p.get('administracion')) if p.get('administracion') else '',
        })

    system_prompt = """Eres un experto en copywriting inmobiliario colombiano. Tu trabajo es crear títulos y descripciones profesionales que motiven la compra de propiedades.

Reglas para el TÍTULO:
- Elegante, corto (máximo 55 caracteres), en formato título (no TODO MAYÚSCULAS).
- Debe resaltar lo mejor del inmueble o la zona.

Reglas para la DESCRIPCIÓN:
- Escribe 2 párrafos completos (separados por doble salto de línea).
- Primer párrafo: describe el inmueble — distribución, estilo, acabados, iluminación, espacios. Menciona datos concretos como la zona, tipo de cocina, balcón, vista, etc.
- Segundo párrafo: describe el entorno, amenidades del conjunto, seguridad, conectividad, transporte, vida de barrio.
- Extensión total: entre 400 y 600 caracteres. NO hagas descripciones cortas ni genéricas.
- Usa lenguaje persuasivo y profesional, como un brochure de alto nivel.
- SÍ puedes mencionar el tipo de propiedad, la zona y el estrato — aportan contexto.
- NO repitas el precio exacto ni los números de habitaciones/baños/m² — esos ya aparecen en la ficha técnica.
- NO uses comillas, emojis ni caracteres especiales.

Responde SOLO con el JSON, sin markdown ni explicaciones."""

    user_msg = f"""Genera título y descripción profesional para cada propiedad:

{json.dumps(props_data, ensure_ascii=False, indent=2)}

Responde con un JSON array exacto:
[{{"id": <id>, "titulo": "...", "descripcion": "..."}}, ...]"""

    try:
        response = client.messages.create(
            model=AI_MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}]
        )

        text = response.content[0].text.strip()
        # Strip markdown fences if present
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        enhanced = json.loads(text)
        return {item['id']: item for item in enhanced}
    except Exception as e:
        print(f"⚠️ AI enhancement failed (falling back to originals): {e}")
        return {}


def _fallback_title(prop):
    """Clean up a title without AI"""
    titulo = prop.get('titulo', 'Propiedad')
    # Title case if all caps
    if titulo == titulo.upper() and len(titulo) > 5:
        titulo = titulo.title()
    return titulo


# ─── Main Generator ───

class PropertyPDFGenerator:

    def __init__(self, properties, agent_info, share_id):
        self.properties = properties
        self.agent = agent_info or {}
        self.share_id = share_id
        self._images = {}
        self._enhanced = {}

    # ── Image prefetch ──

    def _prefetch_images(self):
        urls = {}
        for prop in self.properties:
            url = prop.get('imagen_principal')
            if url:
                urls[prop['id']] = url
        urls['_logo'] = FYNDER_LOGO_URL
        urls['_findy'] = FINDY_AVATAR_URL

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {k: pool.submit(_fetch_image, u) for k, u in urls.items()}
            for k, f in futures.items():
                try:
                    self._images[k] = f.result()
                except Exception:
                    self._images[k] = None

    def _get_title(self, prop):
        """Get AI-enhanced title or fallback"""
        enhanced = self._enhanced.get(prop['id'])
        if enhanced and enhanced.get('titulo'):
            return enhanced['titulo']
        return _fallback_title(prop)

    def _get_description(self, prop):
        """Get AI-enhanced description or empty"""
        enhanced = self._enhanced.get(prop['id'])
        if enhanced and enhanced.get('descripcion'):
            return enhanced['descripcion']
        return ''

    # ── Main entry ──

    def generate(self):
        self._prefetch_images()
        self._enhanced = _enhance_with_ai(self.properties)

        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)

        self._draw_cover(c)
        c.showPage()

        for i, prop in enumerate(self.properties):
            self._draw_property(c, prop, i + 1)
            c.showPage()

        if len(self.properties) > 1:
            self._draw_comparison(c)
            c.showPage()

        c.save()
        buf.seek(0)
        return buf

    # ════════════════════════════════════════════════════════
    #  COVER PAGE
    # ════════════════════════════════════════════════════════

    def _draw_cover(self, c):
        # Full dark background
        c.setFillColor(DARK)
        c.rect(0, 0, W, H, fill=1, stroke=0)

        # ── Logo ──
        logo = self._images.get('_logo')
        if logo:
            c.drawImage(logo, (W - 110) / 2, 694, 110, 32, mask='auto')
        else:
            c.setFont('Helvetica-Bold', 24)
            c.setFillColor(WHITE)
            c.drawCentredString(W / 2, 700, 'FYNDER')

        # ── Accent line ──
        c.setStrokeColor(ACCENT)
        c.setLineWidth(2)
        c.line(W / 2 - 45, 678, W / 2 + 45, 678)

        # ── Title ──
        c.setFont('Helvetica-Bold', 38)
        c.setFillColor(WHITE)
        c.drawCentredString(W / 2, 618, 'PROPUESTA')
        c.setFillColor(ACCENT)
        c.drawCentredString(W / 2, 575, 'INMOBILIARIA')

        # ── Subtitle ──
        n = len(self.properties)
        sub = f"{n} propiedad{'es' if n != 1 else ''} seleccionada{'s' if n != 1 else ''} para ti"
        c.setFont('Helvetica', 13)
        c.setFillColor(COVER_TEXT)
        c.drawCentredString(W / 2, 542, sub)

        # Date
        now = datetime.now()
        date_str = f"{now.day} de {MONTHS_ES.get(now.month, '')} de {now.year}"
        c.setFont('Helvetica', 11)
        c.setFillColor(TEXT_MUTED)
        c.drawCentredString(W / 2, 522, date_str)

        # ── Agent card ──
        agent_name = self.agent.get('name', 'Fynder')
        agent_phone = self.agent.get('phone', '')

        card_w = 310
        card_h = 85
        card_x = (W - card_w) / 2
        card_y = 395

        # Card bg
        c.setFillColor(DARK_CARD)
        c.roundRect(card_x, card_y, card_w, card_h, 10, fill=1, stroke=0)

        # Left accent bar
        c.setFillColor(ACCENT)
        c.roundRect(card_x, card_y, 5, card_h, 2, fill=1, stroke=0)

        # Card content
        ix = card_x + 28

        c.setFont('Helvetica-Bold', 8)
        c.setFillColor(ACCENT)
        c.drawString(ix, card_y + card_h - 24, 'TU AGENTE INMOBILIARIO')

        c.setFont('Helvetica-Bold', 19)
        c.setFillColor(WHITE)
        c.drawString(ix, card_y + card_h - 50, agent_name)

        if agent_phone:
            c.setFont('Helvetica', 11)
            c.setFillColor(TEXT_SUBTLE)
            c.drawString(ix, card_y + card_h - 72, agent_phone)

        # ── Property list ──
        y = 350
        c.setFont('Helvetica-Bold', 9)
        c.setFillColor(ACCENT)
        c.drawString(MARGIN + 50, y, 'PROPIEDADES INCLUIDAS')

        # Thin line
        y -= 8
        c.setStrokeColor(HexColor('#333333'))
        c.setLineWidth(0.5)
        c.line(MARGIN + 50, y, W - MARGIN - 50, y)

        y -= 22
        for i, prop in enumerate(self.properties):
            if y < 80:
                break
            titulo = self._get_title(prop)
            if len(titulo) > 42:
                titulo = titulo[:40] + '..'
            precio = fmt_short(prop.get('precio'))

            # Number
            c.setFont('Helvetica-Bold', 11)
            c.setFillColor(ACCENT)
            c.drawRightString(MARGIN + 68, y, f"{i + 1}.")

            # Title
            c.setFont('Helvetica', 10)
            c.setFillColor(COVER_TEXT)
            c.drawString(MARGIN + 76, y, titulo)

            # Price
            c.setFont('Helvetica-Bold', 10)
            c.setFillColor(ACCENT)
            c.drawRightString(W - MARGIN - 50, y, precio)

            y -= 20

        # ── Footer with Findy ──
        self._draw_findy_footer(c, dark=True)

    # ════════════════════════════════════════════════════════
    #  PROPERTY PAGE
    # ════════════════════════════════════════════════════════

    def _draw_property(self, c, prop, rank):
        total = len(self.properties)

        # ── Page indicator (top right) ──
        c.setFont('Helvetica', 9)
        c.setFillColor(TEXT_MUTED)
        c.drawRightString(W - MARGIN, H - 35, f"{rank} / {total}")

        # ── Image area ──
        img_x = MARGIN
        img_y = 478
        img_w = CONTENT_W
        img_h = 275

        reader = self._images.get(prop['id'])
        if reader:
            # Cover-fit with clipping
            c.saveState()
            p = c.beginPath()
            p.rect(img_x, img_y, img_w, img_h)
            c.clipPath(p, stroke=0)

            src_w, src_h = reader.getSize()
            src_a = src_w / max(src_h, 1)
            tgt_a = img_w / img_h

            if src_a > tgt_a:
                dh = img_h
                dw = dh * src_a
                dx = img_x - (dw - img_w) / 2
                dy = img_y
            else:
                dw = img_w
                dh = dw / max(src_a, 0.1)
                dx = img_x
                dy = img_y - (dh - img_h) / 2

            c.drawImage(reader, dx, dy, dw, dh, mask='auto')
            c.restoreState()

            # Thin border around image
            c.setStrokeColor(BORDER)
            c.setLineWidth(0.5)
            c.rect(img_x, img_y, img_w, img_h, fill=0, stroke=1)
        else:
            # Placeholder
            c.setFillColor(LIGHT_BG)
            c.roundRect(img_x, img_y, img_w, img_h, 8, fill=1, stroke=0)
            c.setFont('Helvetica', 12)
            c.setFillColor(TEXT_MUTED)
            c.drawCentredString(img_x + img_w / 2, img_y + img_h / 2 - 4, 'Sin imagen disponible')

        # ── Rank badge (on image) ──
        bx = img_x + 16
        by = img_y + img_h - 46
        c.setFillColor(ACCENT)
        c.circle(bx + 15, by + 15, 17, fill=1, stroke=0)
        c.setFont('Helvetica-Bold', 15)
        c.setFillColor(DARK)
        c.drawCentredString(bx + 15, by + 10, str(rank))

        # ── Title (AI-enhanced) ──
        y = 450
        titulo = self._get_title(prop)
        if len(titulo) > 55:
            style = ParagraphStyle('t', fontName='Helvetica-Bold', fontSize=16,
                                   textColor=TEXT_DARK, leading=20)
            safe = titulo.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            para = Paragraph(safe, style)
            pw, ph = para.wrapOn(c, CONTENT_W, 60)
            para.drawOn(c, MARGIN, y - ph + 16)
            y -= ph + 4
        else:
            c.setFont('Helvetica-Bold', 16)
            c.setFillColor(TEXT_DARK)
            c.drawString(MARGIN, y, titulo)
            y -= 4

        # ── Location ──
        y -= 18
        ciudad = prop.get('ciudad', '')
        zona = prop.get('zona', '')
        loc = f"{zona}, {ciudad}" if zona else ciudad
        if loc:
            c.setFont('Helvetica', 11)
            c.setFillColor(TEXT_MUTED)
            c.drawString(MARGIN, y, loc)
            y -= 8

        # ── Price ──
        y -= 22
        c.setFont('Helvetica-Bold', 26)
        c.setFillColor(ACCENT)
        c.drawString(MARGIN, y, fmt_full(prop.get('precio')))

        # ── Accent divider ──
        y -= 16
        c.setStrokeColor(ACCENT)
        c.setLineWidth(3)
        c.line(MARGIN, y, MARGIN + 55, y)

        # ── Specs bar ──
        y -= 14
        bar_h = 52
        bar_y = y - bar_h

        c.setFillColor(LIGHT_BG)
        c.roundRect(MARGIN, bar_y, CONTENT_W, bar_h, 8, fill=1, stroke=0)

        specs = [
            (str(prop.get('area_construida', '-')), 'm\u00b2'),
            (str(prop.get('habitaciones', '-')), 'Hab.'),
            (str(prop.get('banos', '-')), 'Ba\u00f1os'),
            (str(prop.get('parqueaderos', 0) or 0), 'Parq.'),
        ]
        col_w = CONTENT_W / 4
        for i, (val, label) in enumerate(specs):
            cx = MARGIN + col_w * i + col_w / 2
            c.setFont('Helvetica-Bold', 19)
            c.setFillColor(TEXT_DARK)
            c.drawCentredString(cx, bar_y + 28, val)
            c.setFont('Helvetica', 9)
            c.setFillColor(TEXT_MUTED)
            c.drawCentredString(cx, bar_y + 10, label)
            if i < 3:
                sx = MARGIN + col_w * (i + 1)
                c.setStrokeColor(BORDER)
                c.setLineWidth(0.5)
                c.line(sx, bar_y + 8, sx, bar_y + bar_h - 8)

        y = bar_y - 14

        # ── Details (type, stratum, admin) ──
        parts = []
        tipo = prop.get('tipo_propiedad')
        if tipo:
            parts.append(tipo)
        estrato = prop.get('estrato')
        if estrato:
            parts.append(f"Estrato {estrato}")
        admin = prop.get('administracion')
        if admin:
            parts.append(f"Admin {fmt_full(admin)}")
        if parts:
            c.setFont('Helvetica', 10)
            c.setFillColor(TEXT_BODY)
            c.drawString(MARGIN, y, '   \u00b7   '.join(parts))
            y -= 22

        # ── Description (AI-enhanced) ──
        desc = self._get_description(prop)
        if desc:
            y -= 6
            # Convert newlines to <br/> for paragraph rendering
            desc_safe = desc.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            desc_safe = desc_safe.replace('\n\n', '<br/><br/>').replace('\n', '<br/>')
            style = ParagraphStyle('d', fontSize=10, leading=14, textColor=TEXT_BODY)
            para = Paragraph(desc_safe, style)
            available_h = y - 70  # Leave room for footer
            pw, ph = para.wrapOn(c, CONTENT_W, available_h)
            para.drawOn(c, MARGIN, y - ph)

        # ── Footer ──
        self._draw_page_footer(c)

    # ════════════════════════════════════════════════════════
    #  COMPARISON PAGE
    # ════════════════════════════════════════════════════════

    def _draw_comparison(self, c):
        # ── Title ──
        c.setFont('Helvetica-Bold', 22)
        c.setFillColor(TEXT_DARK)
        c.drawCentredString(W / 2, H - 65, 'Comparación de Propiedades')

        # Accent line
        c.setStrokeColor(ACCENT)
        c.setLineWidth(2.5)
        c.line(W / 2 - 55, H - 76, W / 2 + 55, H - 76)

        # ── Table layout ──
        y_start = H - 110
        row_h = 38

        cols = [
            ('#',         28,  'center'),
            ('Propiedad', 175, 'left'),
            ('Precio',    80,  'left'),
            ('m\u00b2',   45,  'center'),
            ('Hab.',      40,  'center'),
            ('Baños',     40,  'center'),
            ('Ubicación', 104, 'left'),
        ]

        # ── Header row ──
        y = y_start
        c.setFillColor(DARK)
        c.roundRect(MARGIN, y - row_h, CONTENT_W, row_h, 6, fill=1, stroke=0)

        x = MARGIN
        for header, w, align in cols:
            c.setFont('Helvetica-Bold', 9)
            c.setFillColor(WHITE)
            if align == 'center':
                c.drawCentredString(x + w / 2, y - row_h + 14, header)
            else:
                c.drawString(x + 10, y - row_h + 14, header)
            x += w

        y -= row_h

        # ── Data rows ──
        for idx, prop in enumerate(self.properties):
            bg = LIGHT_BG if idx % 2 == 0 else WHITE
            c.setFillColor(bg)
            c.rect(MARGIN, y - row_h, CONTENT_W, row_h, fill=1, stroke=0)

            c.setStrokeColor(BORDER)
            c.setLineWidth(0.5)
            c.line(MARGIN, y - row_h, MARGIN + CONTENT_W, y - row_h)

            titulo = self._get_title(prop)
            if len(titulo) > 32:
                titulo = titulo[:30] + '..'
            zona = prop.get('zona', '')
            ciudad = prop.get('ciudad', '')
            loc = f"{zona}, {ciudad}" if zona else ciudad
            if len(loc) > 18:
                loc = loc[:16] + '..'

            values = [
                str(idx + 1),
                titulo,
                fmt_short(prop.get('precio')),
                str(prop.get('area_construida', '-')),
                str(prop.get('habitaciones', '-')),
                str(prop.get('banos', '-')),
                loc,
            ]

            x = MARGIN
            for i, ((_, w, align), val) in enumerate(zip(cols, values)):
                if i == 0:
                    c.setFont('Helvetica-Bold', 9)
                    c.setFillColor(TEXT_DARK)
                elif i == 2:
                    c.setFont('Helvetica-Bold', 9)
                    c.setFillColor(ACCENT_DARK)
                else:
                    c.setFont('Helvetica', 9)
                    c.setFillColor(TEXT_BODY)

                if align == 'center':
                    c.drawCentredString(x + w / 2, y - row_h + 14, val)
                else:
                    c.drawString(x + 10, y - row_h + 14, val)
                x += w

            y -= row_h

        # ── Agent contact (no wa.me) ──
        y -= 30
        agent_name = self.agent.get('name', 'Fynder')
        agent_phone = self.agent.get('phone', '')

        contact = f"Contacto:  {agent_name}"
        if agent_phone:
            contact += f"   \u00b7   {agent_phone}"

        c.setFont('Helvetica', 10)
        c.setFillColor(TEXT_MUTED)
        c.drawCentredString(W / 2, y, contact)

        # Footer with Findy
        self._draw_findy_footer(c, dark=False)

    # ════════════════════════════════════════════════════════
    #  FOOTERS
    # ════════════════════════════════════════════════════════

    def _draw_page_footer(self, c):
        """Agent contact footer for property pages"""
        y = 48

        # Accent line
        c.setStrokeColor(ACCENT)
        c.setLineWidth(1.5)
        c.line(MARGIN, y + 14, W - MARGIN, y + 14)

        agent_name = self.agent.get('name', 'Fynder')
        agent_phone = self.agent.get('phone', '')

        right_text = agent_name
        if agent_phone:
            right_text += f'  \u00b7  {agent_phone}'

        c.setFont('Helvetica', 9)
        c.setFillColor(TEXT_MUTED)
        c.drawRightString(W - MARGIN, y, right_text)

        # Findy avatar + fynder.co
        findy = self._images.get('_findy')
        if findy:
            c.drawImage(findy, MARGIN, y - 4, 18, 18, mask='auto')
            c.setFont('Helvetica', 7)
            c.setFillColor(TEXT_SUBTLE)
            c.drawString(MARGIN + 22, y, 'fynder.co')
        else:
            c.setFont('Helvetica', 7)
            c.setFillColor(TEXT_SUBTLE)
            c.drawString(MARGIN, y, 'fynder.co')

    def _draw_findy_footer(self, c, dark=False):
        """Footer with Findy avatar for cover and comparison pages"""
        y = 36
        text_color = HexColor('#444444') if dark else TEXT_SUBTLE

        findy = self._images.get('_findy')
        label = 'Propuesta generada con Fynder'
        c.setFont('Helvetica', 8)

        if findy:
            # Calculate centered position: [findy icon] [text]
            text_w = c.stringWidth(label, 'Helvetica', 8)
            total_w = 20 + 4 + text_w  # icon + gap + text
            start_x = (W - total_w) / 2
            c.drawImage(findy, start_x, y - 3, 16, 16, mask='auto')
            c.setFillColor(text_color)
            c.drawString(start_x + 20, y, label)
        else:
            c.setFillColor(text_color)
            c.drawCentredString(W / 2, y, label)
