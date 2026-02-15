#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF Generator for Property Proposals
Generates professional PDF comparing shared property selections
"""

import requests
from io import BytesIO
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch, cm
from reportlab.lib.colors import HexColor, white, black, lightgrey, Color
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table,
    TableStyle, PageBreak, KeepTogether, Flowable
)


# Brand colors
ACCENT = HexColor('#2AE38C')
DARK_BG = HexColor('#0a0a0a')
DARK_CARD = HexColor('#1a1a1a')
TEXT_PRIMARY = HexColor('#222222')
TEXT_SECONDARY = HexColor('#666666')
LIGHT_BG = HexColor('#f5f5f5')
WHITE = white

FYNDER_LOGO_URL = "https://storage.googleapis.com/cluvi/FYNDER/logo_blanco_fynder_final.png"


class ColoredBlock(Flowable):
    """A colored rectangle block used as background"""
    def __init__(self, width, height, color):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.color = color

    def draw(self):
        self.canv.setFillColor(self.color)
        self.canv.rect(0, 0, self.width, self.height, fill=1, stroke=0)


def format_cop(price):
    """Format price as Colombian Pesos"""
    if not price:
        return "Consultar"
    try:
        price = int(price)
        if price >= 1_000_000_000:
            return f"${price / 1_000_000_000:,.1f} Mil M"
        elif price >= 1_000_000:
            return f"${price / 1_000_000:,.0f} M"
        else:
            return f"${price:,.0f}"
    except (ValueError, TypeError):
        return "Consultar"


def format_cop_full(price):
    """Format price with full number"""
    if not price:
        return "Consultar"
    try:
        return f"${int(price):,.0f} COP"
    except (ValueError, TypeError):
        return "Consultar"


def _fetch_single_image(url, max_width=420, max_height=260):
    """Fetch a single image from URL and return ReportLab Image or None"""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=5, stream=True)
        resp.raise_for_status()
        img_data = BytesIO(resp.content)
        img = RLImage(img_data)
        iw = img.imageWidth
        ih = img.imageHeight
        if iw <= 0 or ih <= 0:
            return None
        aspect = iw / ih
        w = min(iw, max_width)
        h = w / aspect
        if h > max_height:
            h = max_height
            w = h * aspect
        img.drawWidth = w
        img.drawHeight = h
        return img
    except Exception:
        return None


class PropertyPDFGenerator:
    """Generates professional PDF proposals for shared property selections"""

    def __init__(self, properties, agent_info, share_id):
        """
        Args:
            properties: list of property dicts from DB
            agent_info: dict with name, phone, email (can be None)
            share_id: string identifier
        """
        self.properties = properties
        self.agent = agent_info or {}
        self.share_id = share_id
        self.page_width, self.page_height = letter
        self.styles = self._create_styles()
        self._image_cache = {}

    def _create_styles(self):
        """Create custom paragraph styles"""
        styles = getSampleStyleSheet()

        styles.add(ParagraphStyle(
            'CoverTitle',
            parent=styles['Title'],
            fontSize=28,
            textColor=TEXT_PRIMARY,
            spaceAfter=6,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold',
        ))

        styles.add(ParagraphStyle(
            'CoverSubtitle',
            parent=styles['Normal'],
            fontSize=14,
            textColor=TEXT_SECONDARY,
            spaceAfter=4,
            alignment=TA_CENTER,
        ))

        styles.add(ParagraphStyle(
            'PropTitle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=TEXT_PRIMARY,
            spaceAfter=4,
            fontName='Helvetica-Bold',
        ))

        styles.add(ParagraphStyle(
            'PropPrice',
            parent=styles['Normal'],
            fontSize=22,
            textColor=ACCENT,
            spaceAfter=8,
            fontName='Helvetica-Bold',
        ))

        styles.add(ParagraphStyle(
            'PropLocation',
            parent=styles['Normal'],
            fontSize=12,
            textColor=TEXT_SECONDARY,
            spaceAfter=8,
        ))

        styles.add(ParagraphStyle(
            'PropDescription',
            parent=styles['Normal'],
            fontSize=10,
            textColor=TEXT_SECONDARY,
            spaceAfter=6,
            leading=14,
        ))

        styles.add(ParagraphStyle(
            'AgentName',
            parent=styles['Normal'],
            fontSize=16,
            textColor=TEXT_PRIMARY,
            fontName='Helvetica-Bold',
            spaceAfter=4,
        ))

        styles.add(ParagraphStyle(
            'AgentDetail',
            parent=styles['Normal'],
            fontSize=11,
            textColor=TEXT_SECONDARY,
            spaceAfter=2,
        ))

        styles.add(ParagraphStyle(
            'SectionTitle',
            parent=styles['Heading2'],
            fontSize=16,
            textColor=TEXT_PRIMARY,
            fontName='Helvetica-Bold',
            spaceAfter=12,
            spaceBefore=4,
        ))

        styles.add(ParagraphStyle(
            'FooterText',
            parent=styles['Normal'],
            fontSize=8,
            textColor=TEXT_SECONDARY,
            alignment=TA_CENTER,
        ))

        styles.add(ParagraphStyle(
            'SpecLabel',
            parent=styles['Normal'],
            fontSize=9,
            textColor=TEXT_SECONDARY,
            alignment=TA_CENTER,
        ))

        styles.add(ParagraphStyle(
            'SpecValue',
            parent=styles['Normal'],
            fontSize=16,
            textColor=TEXT_PRIMARY,
            fontName='Helvetica-Bold',
            alignment=TA_CENTER,
        ))

        return styles

    def _prefetch_images(self):
        """Prefetch all property images concurrently"""
        urls = []
        for prop in self.properties:
            url = prop.get('imagen_principal')
            if url:
                urls.append(url)

        # Also fetch logo
        urls.append(FYNDER_LOGO_URL)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {}
            for url in urls:
                futures[url] = executor.submit(_fetch_single_image, url)

            for url, future in futures.items():
                try:
                    self._image_cache[url] = future.result()
                except Exception:
                    self._image_cache[url] = None

    def _get_image(self, url, max_width=420, max_height=260):
        """Get image from cache or fetch"""
        if url in self._image_cache:
            return self._image_cache[url]
        return _fetch_single_image(url, max_width, max_height)

    def generate(self):
        """Generate PDF and return BytesIO buffer"""
        self._prefetch_images()

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=0.6 * inch,
            bottomMargin=0.6 * inch,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
        )

        story = []

        # Cover page
        story.extend(self._build_cover_page())

        # Property pages
        for i, prop in enumerate(self.properties):
            story.append(PageBreak())
            story.extend(self._build_property_page(prop, i + 1))

        # Comparison table (only if >1 property)
        if len(self.properties) > 1:
            story.append(PageBreak())
            story.extend(self._build_comparison_table())

        doc.build(story)
        buffer.seek(0)
        return buffer

    def _build_cover_page(self):
        """Build the cover page with logo, title, and agent contact"""
        elements = []
        usable_width = self.page_width - 1.5 * inch

        # Dark header bar with Fynder logo
        logo_img = self._get_image(FYNDER_LOGO_URL, max_width=140, max_height=40)
        if logo_img:
            logo_img.drawWidth = 120
            logo_img.drawHeight = 35
            header_content = logo_img
        else:
            header_content = Paragraph(
                '<font color="white"><b>FYNDER</b></font>',
                ParagraphStyle('LogoFallback', fontSize=20, textColor=white,
                               alignment=TA_CENTER, fontName='Helvetica-Bold')
            )

        header_table = Table(
            [[header_content]],
            colWidths=[usable_width],
            rowHeights=[60]
        )
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), DARK_BG),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 20),
            ('RIGHTPADDING', (0, 0), (-1, -1), 20),
            ('ROUNDEDCORNERS', [8, 8, 8, 8]),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 50))

        # Title
        elements.append(Paragraph("Propuesta de Propiedades", self.styles['CoverTitle']))
        elements.append(Spacer(1, 8))

        # Subtitle
        count = len(self.properties)
        elements.append(Paragraph(
            f"{count} propiedad{'es' if count != 1 else ''} seleccionada{'s' if count != 1 else ''} para ti",
            self.styles['CoverSubtitle']
        ))
        elements.append(Spacer(1, 6))

        # Date
        date_str = datetime.now().strftime('%d de %B de %Y').replace(
            'January', 'enero').replace('February', 'febrero').replace(
            'March', 'marzo').replace('April', 'abril').replace(
            'May', 'mayo').replace('June', 'junio').replace(
            'July', 'julio').replace('August', 'agosto').replace(
            'September', 'septiembre').replace('October', 'octubre').replace(
            'November', 'noviembre').replace('December', 'diciembre')
        elements.append(Paragraph(date_str, self.styles['CoverSubtitle']))
        elements.append(Spacer(1, 50))

        # Agent contact card
        agent_name = self.agent.get('name', 'Fynder')
        agent_phone = self.agent.get('phone', '')
        agent_email = self.agent.get('email', '')

        contact_rows = []
        contact_rows.append([Paragraph(
            '<font color="#2AE38C"><b>Tu Agente Inmobiliario</b></font>',
            ParagraphStyle('CardHeader', fontSize=10, textColor=ACCENT,
                           fontName='Helvetica-Bold', spaceAfter=4)
        )])
        contact_rows.append([Paragraph(agent_name, self.styles['AgentName'])])

        if agent_phone:
            phone_display = agent_phone
            whatsapp_num = agent_phone.replace('+', '')
            contact_rows.append([Paragraph(
                f'Tel: {phone_display}',
                self.styles['AgentDetail']
            )])
            contact_rows.append([Paragraph(
                f'WhatsApp: wa.me/{whatsapp_num}',
                self.styles['AgentDetail']
            )])

        if agent_email:
            contact_rows.append([Paragraph(
                f'Email: {agent_email}',
                self.styles['AgentDetail']
            )])

        card_width = 320
        contact_table = Table(contact_rows, colWidths=[card_width - 40])
        contact_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
            ('TOPPADDING', (0, 0), (-1, 0), 16),
            ('BOTTOMPADDING', (0, -1), (-1, -1), 16),
            ('LEFTPADDING', (0, 0), (-1, -1), 20),
            ('RIGHTPADDING', (0, 0), (-1, -1), 20),
            ('TOPPADDING', (0, 1), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -2), 2),
            ('ROUNDEDCORNERS', [6, 6, 6, 6]),
        ]))

        # Center the card
        wrapper = Table([[contact_table]], colWidths=[usable_width])
        wrapper.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(wrapper)

        elements.append(Spacer(1, 80))

        # Property summary list
        if self.properties:
            elements.append(Paragraph("Propiedades incluidas:", self.styles['SectionTitle']))
            for i, prop in enumerate(self.properties):
                titulo = prop.get('titulo', 'Sin titulo')[:60]
                precio = format_cop(prop.get('precio'))
                ciudad = prop.get('ciudad', '')
                zona = prop.get('zona', '')
                location = f"{zona}, {ciudad}" if zona else ciudad
                elements.append(Paragraph(
                    f'<b>{i + 1}.</b>  {titulo}  —  <font color="#2AE38C"><b>{precio}</b></font>  ({location})',
                    ParagraphStyle('SummaryItem', fontSize=10, textColor=TEXT_PRIMARY,
                                   spaceAfter=4, leading=14)
                ))

        # Footer
        elements.append(Spacer(1, 40))
        elements.append(Paragraph("Propuesta generada por Fynder", self.styles['FooterText']))

        return elements

    def _build_property_page(self, prop, rank):
        """Build a single property detail page"""
        elements = []
        usable_width = self.page_width - 1.5 * inch

        # Rank badge + page info
        total = len(self.properties)
        header_text = f'<font color="#2AE38C"><b>#{rank}</b></font> <font color="#999999">de {total}</font>'
        elements.append(Paragraph(header_text, ParagraphStyle(
            'RankHeader', fontSize=12, textColor=TEXT_PRIMARY, spaceAfter=12
        )))

        # Property image
        img_url = prop.get('imagen_principal')
        if img_url:
            img = self._get_image(img_url, max_width=usable_width, max_height=280)
            if img:
                # Center image
                img_table = Table([[img]], colWidths=[usable_width])
                img_table.setStyle(TableStyle([
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 0),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ]))
                elements.append(img_table)
                elements.append(Spacer(1, 16))
            else:
                elements.append(self._image_placeholder(usable_width))
                elements.append(Spacer(1, 16))
        else:
            elements.append(self._image_placeholder(usable_width))
            elements.append(Spacer(1, 16))

        # Title
        titulo = prop.get('titulo', 'Sin titulo')
        elements.append(Paragraph(titulo, self.styles['PropTitle']))

        # Location
        ciudad = prop.get('ciudad', '')
        zona = prop.get('zona', '')
        location = f"{zona}, {ciudad}" if zona else ciudad
        if location:
            elements.append(Paragraph(f"📍 {location}", self.styles['PropLocation']))

        # Price
        precio_full = format_cop_full(prop.get('precio'))
        elements.append(Paragraph(precio_full, self.styles['PropPrice']))

        # Specs grid
        area = prop.get('area_construida', '-')
        hab = prop.get('habitaciones', '-')
        banos = prop.get('banos', '-')
        parq = prop.get('parqueaderos', 0) or 0

        spec_data = [
            [
                Paragraph(f'<b>{area}</b>', self.styles['SpecValue']),
                Paragraph(f'<b>{hab}</b>', self.styles['SpecValue']),
                Paragraph(f'<b>{banos}</b>', self.styles['SpecValue']),
                Paragraph(f'<b>{parq}</b>', self.styles['SpecValue']),
            ],
            [
                Paragraph('m\u00b2', self.styles['SpecLabel']),
                Paragraph('Hab.', self.styles['SpecLabel']),
                Paragraph('Ba\u00f1os', self.styles['SpecLabel']),
                Paragraph('Parq.', self.styles['SpecLabel']),
            ]
        ]

        col_w = usable_width / 4
        spec_table = Table(spec_data, colWidths=[col_w] * 4, rowHeights=[30, 18])
        spec_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, -1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e0e0e0')),
            ('ROUNDEDCORNERS', [4, 4, 4, 4]),
        ]))
        elements.append(spec_table)
        elements.append(Spacer(1, 12))

        # Property type, stratum, admin fee
        details = []
        tipo = prop.get('tipo_propiedad')
        if tipo:
            details.append(f"<b>Tipo:</b> {tipo}")
        estrato = prop.get('estrato')
        if estrato:
            details.append(f"<b>Estrato:</b> {estrato}")
        admin = prop.get('administracion')
        if admin:
            details.append(f"<b>Admin:</b> {format_cop_full(admin)}")

        if details:
            elements.append(Paragraph(
                "  |  ".join(details),
                ParagraphStyle('PropDetails', fontSize=10, textColor=TEXT_SECONDARY,
                               spaceAfter=12)
            ))

        # Description
        desc = prop.get('descripcion', '')
        if desc:
            # Truncate to 500 chars
            if len(desc) > 500:
                desc = desc[:500].rsplit(' ', 1)[0] + '...'
            # Clean up for PDF
            desc = desc.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            elements.append(Paragraph("Descripcion", self.styles['SectionTitle']))
            elements.append(Paragraph(desc, self.styles['PropDescription']))

        # Agent contact footer
        elements.append(Spacer(1, 20))
        agent_name = self.agent.get('name', 'Fynder')
        agent_phone = self.agent.get('phone', '')
        if agent_phone:
            elements.append(Paragraph(
                f'<font color="#999999">Contacto:</font> <b>{agent_name}</b> — {agent_phone}',
                ParagraphStyle('PropFooter', fontSize=9, textColor=TEXT_SECONDARY,
                               alignment=TA_RIGHT)
            ))

        return elements

    def _build_comparison_table(self):
        """Build comparison table page"""
        elements = []
        usable_width = self.page_width - 1.5 * inch

        elements.append(Paragraph("Comparacion de Propiedades", self.styles['CoverTitle']))
        elements.append(Spacer(1, 20))

        # Table header
        header = ['#', 'Propiedad', 'Precio', 'm\u00b2', 'Hab', 'Ba\u00f1os', 'Ubicacion']

        rows = [header]
        for i, prop in enumerate(self.properties):
            titulo = prop.get('titulo', 'Sin titulo')
            if len(titulo) > 30:
                titulo = titulo[:28] + '..'
            rows.append([
                str(i + 1),
                titulo,
                format_cop(prop.get('precio')),
                str(prop.get('area_construida', '-')),
                str(prop.get('habitaciones', '-')),
                str(prop.get('banos', '-')),
                f"{prop.get('zona', '')}, {prop.get('ciudad', '')}".strip(', ')[:25],
            ])

        # Column widths
        col_widths = [25, 130, 70, 35, 30, 38, usable_width - 328]

        table = Table(rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), DARK_BG),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            # Body
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('TEXTCOLOR', (0, 1), (-1, -1), TEXT_PRIMARY),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            # Alternating row colors
            *[('BACKGROUND', (0, i), (-1, i), LIGHT_BG)
              for i in range(2, len(rows), 2)],
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e0e0e0')),
            # Alignment
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (3, 0), (5, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            # Price column in green
            ('TEXTCOLOR', (2, 1), (2, -1), ACCENT),
            ('FONTNAME', (2, 1), (2, -1), 'Helvetica-Bold'),
        ]))

        elements.append(table)
        elements.append(Spacer(1, 30))

        # Agent contact at bottom
        agent_name = self.agent.get('name', 'Fynder')
        agent_phone = self.agent.get('phone', '')
        agent_email = self.agent.get('email', '')

        contact_parts = [f'<b>{agent_name}</b>']
        if agent_phone:
            contact_parts.append(agent_phone)
        if agent_email:
            contact_parts.append(agent_email)

        elements.append(Paragraph(
            f'Contacto: {" | ".join(contact_parts)}',
            ParagraphStyle('TableFooter', fontSize=10, textColor=TEXT_SECONDARY,
                           alignment=TA_CENTER, spaceAfter=8)
        ))

        elements.append(Spacer(1, 20))
        elements.append(Paragraph("Propuesta generada por Fynder", self.styles['FooterText']))

        return elements

    def _image_placeholder(self, width, height=180):
        """Create a gray placeholder for missing images"""
        placeholder = Table(
            [[Paragraph(
                '<font color="#999999">Sin imagen disponible</font>',
                ParagraphStyle('Placeholder', fontSize=12, textColor=TEXT_SECONDARY,
                               alignment=TA_CENTER)
            )]],
            colWidths=[width],
            rowHeights=[height]
        )
        placeholder.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ROUNDEDCORNERS', [6, 6, 6, 6]),
        ]))
        return placeholder
