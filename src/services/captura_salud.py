"""
Alarma de la captura de inventario: si dejan de entrar inmuebles de los grupos, avisa.

Entre el 8-ago y el 12-oct-2026 no entró ni un inmueble y nadie se enteró. El worker
llama `revisar()` cada hora: de lunes a sábado, de 8 a. m. a 8 p. m. (Bogotá), si la
última captura tiene más de `CAPTURA_ALERTA_HORAS` (6), manda el error a Sentry y un
correo al buzón de soporte. Repite como mucho cada 12 h mientras siga caída.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from src.services.db import get_db, scalar

BOGOTA = timezone(timedelta(hours=-5))
_ultimo_aviso: Optional[datetime] = None


def ultima_captura(cur) -> Optional[datetime]:
    # fecha_evento es timestamp sin zona, en UTC.
    v = scalar(cur, "SELECT MAX(fecha_evento) FROM eventos_log WHERE tipo_evento = 'Propiedad_Captada'")
    return v.replace(tzinfo=timezone.utc) if v else None


def revisar(ahora: Optional[datetime] = None) -> Dict[str, Any]:
    global _ultimo_aviso
    ahora = ahora or datetime.now(timezone.utc)
    umbral = float(os.getenv("CAPTURA_ALERTA_HORAS", "6"))
    with get_db() as db:
        ultima = ultima_captura(db.cursor)
    horas = (ahora - ultima).total_seconds() / 3600 if ultima else None
    local = ahora.astimezone(BOGOTA)
    en_horario = local.weekday() < 6 and 8 <= local.hour < 20
    caida = en_horario and (horas is None or horas >= umbral)
    out = {"ultima_captura": ultima.isoformat() if ultima else None,
           "horas": round(horas, 1) if horas is not None else None, "caida": caida}
    if not caida or (_ultimo_aviso and ahora - _ultimo_aviso < timedelta(hours=12)):
        return out
    _ultimo_aviso = ahora
    _avisar(horas, ultima)
    out["avisado"] = True
    return out


def _avisar(horas: Optional[float], ultima: Optional[datetime]) -> None:
    hace = f"{horas:.0f} horas" if horas is not None else "nunca"
    cuando = ultima.astimezone(BOGOTA).strftime("%d-%b %H:%M") if ultima else "—"
    texto = (f"No entra inventario de los grupos hace {hace} (última captura: {cuando}, hora de Bogotá). "
             "Revisa la instancia de UltraMSG (que siga conectada y en los grupos), el webhook y el worker.")
    print(f"[CAPTURA] ALERTA {texto}")
    try:
        import sentry_sdk
        sentry_sdk.capture_message(f"Captura detenida: {hace} sin inmuebles", level="error")
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.services import correo_service as cs
        cs.enviar(cs.buzon_soporte(), f"Fynder: la captura lleva {hace} sin inmuebles",
                  f"<p>{texto}</p>", texto, "alerta_captura", esperar=True)
    except Exception as e:  # noqa: BLE001
        print(f"[CAPTURA] No pude mandar el correo: {e}")
