"""
Descargas de URLs que manda el usuario (links de portales, fotos) sin SSRF.

Un agente puede pegar cualquier link en Findy, el MCP o "agregar fotos"; sin este
filtro el servidor lo descargaba aunque apuntara a la red interna (169.254.x de
metadatos, 10.x, localhost) o a un redirect hacia ella. `SesionSegura` revisa cada
petición (también cada salto de un redirect, que en requests pasa por `send`):
solo http/https, puertos 80/443, sin usuario:clave y un host que resuelva a
direcciones públicas.
"""

import ipaddress
import socket
from typing import Optional
from urllib.parse import urlsplit

import requests


class UrlInsegura(requests.exceptions.InvalidURL):
    """La URL apunta a algo que no es internet público."""


def verificar(url: Optional[str]) -> str:
    """Devuelve la URL si es segura de descargar; si no, lanza `UrlInsegura`."""
    try:
        partes = urlsplit(url or "")
        puerto = partes.port
    except ValueError as e:
        raise UrlInsegura("URL inválida") from e
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise UrlInsegura("Solo se aceptan links http(s)")
    if partes.username or partes.password:
        raise UrlInsegura("URL con credenciales")
    if puerto not in (None, 80, 443):
        raise UrlInsegura("Puerto no permitido")
    try:
        direcciones = {info[4][0] for info in socket.getaddrinfo(partes.hostname, puerto or 443)}
    except socket.gaierror as e:
        raise UrlInsegura("No se pudo resolver el dominio") from e
    for d in direcciones:
        ip = ipaddress.ip_address(d.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise UrlInsegura("La URL apunta a una red interna")
    return url  # type: ignore[return-value]


class SesionSegura(requests.Session):
    """`requests.Session` que valida el destino de cada petición y de cada redirect."""

    max_redirects = 5

    def send(self, request, **kwargs):  # type: ignore[override]
        verificar(request.url)
        return super().send(request, **kwargs)


def get(url: str, **kwargs) -> requests.Response:
    with SesionSegura() as s:
        return s.get(url, **kwargs)
