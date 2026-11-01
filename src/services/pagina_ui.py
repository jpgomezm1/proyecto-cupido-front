"""
Las respuestas del chat de Mi página como programas OpenUI (sin IA): el texto de Findy y
los controles para tocar que propuso (paleta, plantillas, letras, textos, secciones). Los
pinta la librería `mvp-tu360/src/lib/openui/pagina.tsx`; tocar una opción aplica el cambio
en el editor sin otra llamada a la IA. Mismo formato que `findy_ui` (props posicionales).
"""

from typing import Any, Dict, List

from src.services.findy_ui import _llamada, _programa


def programa(respuesta: str, controles: List[Dict[str, Any]]) -> str:
    bloques = [_llamada("Texto", respuesta)]
    for c in controles:
        t = c["tipo"]
        if t == "paleta":
            bloques.append(_llamada("Paleta", c["titulo"], c["opciones"]))
        elif t == "plantillas":
            bloques.append(_llamada("Plantillas", c["titulo"], c["opciones"]))
        elif t == "letras":
            bloques.append(_llamada("Letras", c["titulo"], c["opciones"]))
        elif t == "textos":
            bloques.append(_llamada("Textos", c["titulo"], c["opciones"], c["destino"]))
        elif t == "secciones":
            bloques.append(_llamada("Secciones", c["titulo"], c["opciones"]))
    return _programa(bloques)
