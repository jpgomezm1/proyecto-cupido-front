# 📡 Ejemplos de Uso - API del Bot WhatsApp TU360

## 🔧 Configuración base

Todos los ejemplos asumen que el servidor está corriendo en `http://localhost:5000`

Si estás usando ngrok u otro túnel, reemplaza `localhost:5000` por tu URL pública.

## 📋 1. Health Check

Verificar que el servidor está corriendo:

```bash
curl http://localhost:5000/health
```

**Respuesta esperada:**
```json
{
  "status": "healthy",
  "timestamp": "2025-10-31T16:30:00.123456",
  "bot_initialized": true
}
```

## 📤 2. Enviar mensaje simple

```bash
curl -X POST http://localhost:5000/send \
  -H "Content-Type: application/json" \
  -d '{
    "to": "+573001234567",
    "message": "¡Hola! Este es un mensaje de prueba desde la API."
  }'
```

**Respuesta esperada:**
```json
{
  "status": "success",
  "result": {
    "sent": "true",
    "message": "ok",
    "id": "message_id_123"
  }
}
```

## 🔍 3. Búsqueda simple

```bash
curl -X POST http://localhost:5000/search \
  -H "Content-Type: application/json" \
  -d '{
    "to": "+573001234567",
    "query": "Busco apto en Laureles, 2 habitaciones, hasta 500 millones"
  }'
```

**Respuesta esperada:**
```json
{
  "status": "success",
  "sent": true
}
```

El usuario recibirá por WhatsApp:
1. Mensaje con criterios extraídos
2. 5 mensajes con las propiedades encontradas
3. Mensaje final con resumen

## 🏠 4. Búsqueda con múltiples criterios

```bash
curl -X POST http://localhost:5000/search \
  -H "Content-Type: application/json" \
  -d '{
    "to": "+573001234567",
    "query": "Busco apartamento nuevo en Poblado o Laureles. Presupuesto hasta 800 millones. 2 o 3 habitaciones. Con balcón, parqueadero y gimnasio en la unidad. Área mínimo 80 m2."
  }'
```

## 🏡 5. Búsqueda de casa

```bash
curl -X POST http://localhost:5000/search \
  -H "Content-Type: application/json" \
  -d '{
    "to": "+573001234567",
    "query": "Casa en Envigado, 3 o 4 alcobas, con jardín y parqueadero para 2 carros, hasta 1.2 billones"
  }'
```

## 🧪 6. Test webhook (simulación)

Simular que un usuario envió un mensaje:

```bash
curl -X POST http://localhost:5000/test \
  -H "Content-Type: application/json" \
  -d '{
    "from": "+573001234567",
    "body": "Busco apartamento en El Poblado",
    "type": "chat",
    "id": "test_message_123"
  }'
```

**Respuesta esperada:**
```json
{
  "status": "success",
  "test": true,
  "response": {
    "status": "success",
    "sender": "+573001234567",
    "query": "Busco apartamento en El Poblado"
  }
}
```

## 🎯 7. Comandos especiales

### Comando "hola"

```bash
curl -X POST http://localhost:5000/test \
  -H "Content-Type: application/json" \
  -d '{
    "from": "+573001234567",
    "body": "hola",
    "type": "chat"
  }'
```

El bot enviará mensaje de bienvenida.

### Comando "ayuda"

```bash
curl -X POST http://localhost:5000/test \
  -H "Content-Type: application/json" \
  -d '{
    "from": "+573001234567",
    "body": "ayuda",
    "type": "chat"
  }'
```

El bot enviará instrucciones de uso.

## 📊 8. Queries de ejemplo reales

### Estudiante con presupuesto ajustado

```bash
curl -X POST http://localhost:5000/search \
  -H "Content-Type: application/json" \
  -d '{
    "to": "+573001234567",
    "query": "Busco para estudiante, cerca a universidades, 1 habitación, máximo 250 millones, Laureles, Estadio o La América"
  }'
```

### Cliente VIP con alto presupuesto

```bash
curl -X POST http://localhost:5000/search \
  -H "Content-Type: application/json" \
  -d '{
    "to": "+573001234567",
    "query": "Busco penthouse de lujo en El Poblado, mínimo 3 habitaciones, con balcón grande, gimnasio y piscina, acabados premium, presupuesto hasta 2 billones"
  }'
```

### Persona mayor (primer piso)

```bash
curl -X POST http://localhost:5000/search \
  -H "Content-Type: application/json" \
  -d '{
    "to": "+573001234567",
    "query": "Busco apto en Ciudad del Río o Laureles, persona mayor primer piso, 2 o 3 habitaciones, con portería, presupuesto 1000 millones"
  }'
```

### Inversión para arrendar

```bash
curl -X POST http://localhost:5000/search \
  -H "Content-Type: application/json" \
  -d '{
    "to": "+573001234567",
    "query": "Busco apto para invertir y arrendar, Belén, La América o Robledo, 2 habitaciones, buena zona, entre 300 y 500 millones, buenos acabados"
  }'
```

## 🔄 9. Webhook real (UltraMSG)

Cuando UltraMSG recibe un mensaje, envía un webhook a tu servidor con este formato:

```json
{
  "id": "message_id_12345",
  "from": "573001234567@c.us",
  "to": "instance_phone@c.us",
  "body": "Busco apto en Laureles",
  "type": "chat",
  "time": "1698765432",
  "participant": null,
  "caption": null,
  "filename": null
}
```

Tu servidor en `/webhook` procesará automáticamente este mensaje.

## 🐍 10. Ejemplos en Python

### Enviar mensaje

```python
import requests

url = "http://localhost:5000/send"
data = {
    "to": "+573001234567",
    "message": "Hola desde Python"
}

response = requests.post(url, json=data)
print(response.json())
```

### Búsqueda

```python
import requests

url = "http://localhost:5000/search"
data = {
    "to": "+573001234567",
    "query": "Busco apto en Laureles, 2 habitaciones, hasta 500 millones"
}

response = requests.post(url, json=data)
print(response.json())
```

### Usar el bot directamente

```python
from whatsapp_bot import WhatsAppBot

bot = WhatsAppBot()

# Enviar mensaje
bot.send_message("+573001234567", "Hola desde Python directo")

# Búsqueda completa
bot.send_search_results(
    "+573001234567",
    "Busco apto en Laureles, 2 habitaciones, hasta 500 millones"
)
```

## 📱 11. Usar PropertySearchAgent directamente

Si solo quieres buscar propiedades sin enviar por WhatsApp:

```python
from busqueda_propiedades import PropertySearchAgent

agent = PropertySearchAgent()

# Realizar búsqueda
result = agent.search(
    "Busco apto en Laureles, 2 habitaciones, hasta 500 millones",
    limit=5
)

# Resultado
print(f"Éxito: {result['success']}")
print(f"Criterios: {result['criteria']}")
print(f"Propiedades encontradas: {result['total_found']}")

# Ver propiedades
for i, prop in enumerate(result['results'], 1):
    print(f"\n{i}. {prop['titulo']}")
    print(f"   Precio: {prop['precio_texto']}")
    print(f"   Score: {prop['match_score']} pts")
```

## 🔐 12. Seguridad (Producción)

En producción, considera agregar autenticación al webhook:

```python
# webhook_server.py - agregar verificación de token

@app.route('/webhook', methods=['POST'])
def webhook():
    # Verificar token de seguridad
    webhook_token = request.headers.get('X-Webhook-Token')

    if webhook_token != os.getenv('WEBHOOK_SECRET_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    # ... resto del código
```

Configurar en `.env`:
```env
WEBHOOK_SECRET_TOKEN=tu_token_secreto_aqui
```

Y en UltraMSG, agregar header personalizado con el token.

## 📝 13. Logs y debugging

Los webhooks se guardan automáticamente en `webhook_logs/`:

```bash
# Ver último webhook recibido
ls -t webhook_logs/ | head -1 | xargs -I {} cat webhook_logs/{}
```

## 🎉 Conclusión

Con estos ejemplos puedes:
- ✅ Enviar mensajes de WhatsApp programáticamente
- ✅ Realizar búsquedas inteligentes de propiedades
- ✅ Integrar el bot con otros sistemas
- ✅ Simular webhooks para testing
- ✅ Usar el agente de búsqueda directamente

**¡El sistema está listo para producción! 🚀**
