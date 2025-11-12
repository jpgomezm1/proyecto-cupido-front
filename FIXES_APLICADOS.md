# 🔧 Correcciones Aplicadas al Bot de WhatsApp

## ⚠️ Problema Identificado

**Situación:** El mensaje "Oli" enviado en un grupo de WhatsApp activó una búsqueda de propiedades y devolvió 20 resultados.

**Causas identificadas:**
1. ✅ Mensajes de grupos estaban siendo procesados
2. ✅ Eventos múltiples (message_create, message_ack) estaban siendo procesados
3. ✅ Mensajes propios estaban siendo procesados repetidamente
4. ✅ Mensajes cortos sin sentido activaban búsquedas

---

## ✅ Soluciones Implementadas

### 1. Filtrado de Eventos (`whatsapp_bot.py` líneas 418-421)

**Problema:** Eventos como `message_create`, `message_ack` estaban siendo procesados.

**Solución:**
```python
# Ignorar eventos que no son mensajes nuevos
if event_type not in ['message_received', '']:
    print(f"⚠️  Ignorando evento tipo: {event_type}")
    return {'status': 'ignored', 'reason': 'not_message_received'}
```

**Resultado:** Solo se procesan eventos `message_received` (mensajes entrantes reales).

---

### 2. Filtrado de Mensajes Propios (`whatsapp_bot.py` líneas 423-426)

**Problema:** Los mensajes enviados por el bot eran procesados múltiples veces.

**Solución:**
```python
# Ignorar mensajes propios (fromMe)
if message_data.get('fromMe') or message_data.get('self'):
    print(f"⚠️  Ignorando mensaje propio")
    return {'status': 'ignored', 'reason': 'own_message'}
```

**Resultado:** Los mensajes del bot mismo ya no se procesan.

---

### 3. Filtrado de Mensajes de Grupos (`whatsapp_bot.py` líneas 428-431)

**Problema:** Mensajes en grupos de WhatsApp estaban siendo procesados.

**Solución:**
```python
# Ignorar mensajes de grupos (termina en @g.us)
if '@g.us' in sender or '@g.us' in to:
    print(f"⚠️  Ignorando mensaje de grupo")
    return {'status': 'ignored', 'reason': 'group_message'}
```

**Resultado:** Solo se procesan mensajes de conversaciones individuales (1 a 1).

---

### 4. Validación de Longitud Mínima (`whatsapp_bot.py` líneas 496-505)

**Problema:** Mensajes cortos como "Oli", "ok", "jaja" activaban búsquedas.

**Solución:**
```python
# Validar longitud mínima para búsqueda (evitar "Oli", "ok", etc.)
if len(message_body.strip()) < 10:
    help_msg = "🤔 Mensaje muy corto para realizar una búsqueda.\n\n"
    help_msg += "📝 *Para buscar propiedades*, describe lo que necesitas.\n\n"
    help_msg += "💡 *Ejemplo:*\n"
    help_msg += "_Busco apto en Laureles, 2 habitaciones, hasta 500 millones_\n\n"
    help_msg += "O escribe *ayuda* para ver más ejemplos."

    self.send_message(sender, help_msg)
    return {'status': 'query_too_short'}
```

**Resultado:** Mensajes con menos de 10 caracteres no activan búsquedas.

---

### 5. Validación de Palabras Clave (`whatsapp_bot.py` líneas 507-532)

**Problema:** Cualquier mensaje largo activaba búsqueda, aunque no tuviera relación con propiedades.

**Solución:**
```python
# Validar que contenga palabras clave relacionadas con búsqueda de propiedades
search_keywords = [
    'busco', 'buscar', 'quiero', 'necesito', 'me interesa',
    'apto', 'apartamento', 'casa', 'penthouse', 'duplex',
    'habitacion', 'habitaciones', 'alcoba', 'alcobas', 'cuarto',
    'precio', 'presupuesto', 'millones', 'millon', 'valor',
    'laureles', 'poblado', 'envigado', 'belen', 'sabaneta',
    'parqueadero', 'balcon', 'terraza', 'piscina', 'gimnasio',
    'venta', 'comprar', 'adquirir', 'propiedad', 'inmueble'
]

has_keyword = any(keyword in message_lower for keyword in search_keywords)

if not has_keyword:
    help_msg = "🤔 No entendí tu búsqueda.\n\n"
    help_msg += "📝 *Para buscar propiedades*, describe:\n"
    help_msg += "• Ubicación (Ej: Laureles, Poblado)\n"
    help_msg += "• Tipo (Apartamento, Casa)\n"
    help_msg += "• Habitaciones\n"
    help_msg += "• Presupuesto\n\n"
    help_msg += "💡 *Ejemplo:*\n"
    help_msg += "_Busco apto en Laureles, 2 habitaciones, hasta 500 millones_\n\n"
    help_msg += "O escribe *ayuda* para ver más información."

    self.send_message(sender, help_msg)
    return {'status': 'no_search_keywords'}
```

**Resultado:** Solo se activan búsquedas cuando el mensaje contiene palabras relacionadas con propiedades.

---

## 🧪 Cómo Probar las Correcciones

### 1. Reiniciar el servidor webhook

```powershell
# Detener el servidor actual (Ctrl + C)
# Iniciar de nuevo:
python webhook_server.py
```

### 2. Probar casos que ANTES fallaban

#### ❌ Mensaje en grupo (DEBE ser ignorado)
- Envía cualquier mensaje en un grupo donde esté el bot
- **Resultado esperado:** El bot ignora el mensaje completamente

#### ❌ Mensaje corto sin sentido (DEBE ser rechazado)
- Envía: "Oli"
- **Resultado esperado:** Bot responde con ayuda, no realiza búsqueda

#### ❌ Mensaje largo sin palabras clave (DEBE ser rechazado)
- Envía: "Qué tal amigo cómo estás hoy en la tarde"
- **Resultado esperado:** Bot responde que no entendió, solicita búsqueda válida

### 3. Probar casos que DEBEN funcionar

#### ✅ Búsqueda legítima
- Envía: "Busco apto en Laureles 2 habitaciones"
- **Resultado esperado:** Bot realiza búsqueda y devuelve propiedades

#### ✅ Comandos especiales
- Envía: "hola"
- **Resultado esperado:** Mensaje de bienvenida

- Envía: "ayuda"
- **Resultado esperado:** Mensaje de ayuda

#### ✅ Selección de propiedades
- Después de recibir resultados, envía: "1 y 3"
- **Resultado esperado:** Bot confirma selección

---

## 📊 Logs para Debug

Ahora los logs muestran más información:

```
📩 Mensaje recibido de: +573001234567
📝 Contenido: Oli...
📋 Tipo: chat
📋 Evento: message_received
⚠️  Mensaje muy corto para búsqueda
```

```
📩 Mensaje recibido de: 573001234567@g.us
⚠️  Ignorando mensaje de grupo
```

---

## 🎯 Resumen de Cambios

| # | Problema | Solución | Estado |
|---|----------|----------|--------|
| 1 | Eventos múltiples procesados | Filtrar solo `message_received` | ✅ Corregido |
| 2 | Mensajes propios procesados | Detectar `fromMe` y ignorar | ✅ Corregido |
| 3 | Mensajes de grupos procesados | Detectar `@g.us` y ignorar | ✅ Corregido |
| 4 | Mensajes cortos activan búsqueda | Validar longitud mínima (10 chars) | ✅ Corregido |
| 5 | Mensajes sin sentido activan búsqueda | Validar palabras clave | ✅ Corregido |

---

## 🚀 Siguiente Paso

**Todas las correcciones han sido aplicadas.**

Para probar:
1. Reinicia el servidor webhook
2. Prueba enviar "Oli" desde un chat individual
3. Verifica que el bot responde con ayuda (no realiza búsqueda)
4. Prueba enviar mensaje en grupo
5. Verifica que el bot lo ignora completamente

**Una vez confirmado que funciona correctamente, estarás listo para la siguiente parte del flujo.**
