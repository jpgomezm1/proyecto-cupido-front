# 🤖 Bot de WhatsApp - Búsqueda Inteligente de Propiedades TU360

Sistema de búsqueda de propiedades inmobiliarias mediante WhatsApp, integrado con UltraMSG API y Claude (Anthropic) para procesamiento de lenguaje natural.

## 📋 Descripción

Este bot permite a los usuarios buscar propiedades inmobiliarias directamente desde WhatsApp usando lenguaje natural. El sistema:

1. ✅ Recibe mensajes de WhatsApp vía webhook de UltraMSG
2. 🧠 Procesa el mensaje con Claude AI para extraer criterios de búsqueda
3. 🔍 Busca en la base de datos PostgreSQL
4. 📊 Rankea resultados por relevancia
5. 📱 Envía las propiedades más relevantes de vuelta por WhatsApp

## 🚀 Instalación

### 1. Instalar dependencias

```bash
pip install -r requirements.txt
```

O manualmente:
```bash
pip install flask requests python-dotenv anthropic psycopg2-binary
```

### 2. Configurar variables de entorno

El archivo `.env` ya está configurado con:

```env
# Base de datos
DATABASE_URL=postgresql://...

# Claude AI
ANTHROPIC_API_KEY=sk-ant-api03-...

# UltraMSG WhatsApp API
ULTRAMSG_INSTANCE_ID=instance106153
ULTRAMSG_TOKEN=b4azkwiyillsz4dr5ggg
```

### 3. Configurar webhook en UltraMSG

1. Accede a tu dashboard: https://user.ultramsg.com/
2. Ve a Settings → Webhook
3. Configura la URL de tu webhook (ver sección "Exponer servidor públicamente")
4. Activa el webhook para "incoming messages"

## 🎯 Uso

### Opción 1: Test rápido (recomendado para probar)

```bash
python3 test_whatsapp.py
```

Este script interactivo te permite:
- Enviar mensaje de prueba
- Realizar búsqueda completa
- Simular webhook

### Opción 2: Correr servidor webhook

```bash
python3 webhook_server.py
```

El servidor escuchará en `http://0.0.0.0:5000`

### Opción 3: Test directo del bot

```bash
python3 whatsapp_bot.py
```

Te pedirá un número de WhatsApp y enviará un mensaje de prueba.

## 🌐 Exponer servidor públicamente

Para que UltraMSG pueda enviar webhooks a tu servidor local, necesitas exponerlo públicamente:

### Opción 1: ngrok (Recomendado)

```bash
# Instalar ngrok
# Windows: descargar de https://ngrok.com/download
# Linux/Mac: brew install ngrok

# Exponer puerto 5000
ngrok http 5000
```

Copiar la URL `https://xxxx.ngrok.io` y configurarla en UltraMSG como:
```
https://xxxx.ngrok.io/webhook
```

### Opción 2: Localtunnel

```bash
npm install -g localtunnel
lt --port 5000
```

### Opción 3: Serveo

```bash
ssh -R 80:localhost:5000 serveo.net
```

## 📡 Endpoints del servidor

### GET `/`
Información del servidor

### GET `/health`
Health check del servidor

### POST `/webhook`
**Endpoint principal** - Recibe mensajes de UltraMSG

### POST `/send`
Enviar mensaje manual

```bash
curl -X POST http://localhost:5000/send \
  -H "Content-Type: application/json" \
  -d '{
    "to": "+573001234567",
    "message": "Hola, esto es una prueba"
  }'
```

### POST `/search`
Realizar búsqueda y enviar resultados

```bash
curl -X POST http://localhost:5000/search \
  -H "Content-Type: application/json" \
  -d '{
    "to": "+573001234567",
    "query": "Busco apto en Laureles, 2 habitaciones, hasta 500 millones"
  }'
```

### POST `/test`
Simular webhook para testing

```bash
curl -X POST http://localhost:5000/test \
  -H "Content-Type: application/json" \
  -d '{
    "from": "+573001234567",
    "body": "Busco apartamento en El Poblado",
    "type": "chat"
  }'
```

## 💬 Comandos de WhatsApp

Los usuarios pueden enviar estos comandos desde WhatsApp:

### `hola` / `hi` / `hello`
Mensaje de bienvenida con instrucciones

### `ayuda` / `help` / `?`
Información sobre cómo usar el bot

### Búsqueda libre
Cualquier otro mensaje se procesa como consulta de búsqueda:

**Ejemplos:**
```
Busco apto en Laureles, 2 habitaciones, hasta 500 millones

Casa en Envigado, 3 alcobas, con jardín y parqueadero

Apartamento nuevo en Poblado o Laureles
Presupuesto 800 millones
2 o 3 habitaciones
Con balcón y piscina
```

## 🧪 Testing

### Test completo interactivo
```bash
python3 test_whatsapp.py
```

### Test individual de envío
```python
from whatsapp_bot import WhatsAppBot

bot = WhatsAppBot()
bot.send_message("+573001234567", "Mensaje de prueba")
```

### Test de búsqueda
```python
from whatsapp_bot import WhatsAppBot

bot = WhatsAppBot()
bot.send_search_results(
    "+573001234567",
    "Busco apto en Laureles, 2 habitaciones, hasta 500 millones"
)
```

## 📁 Estructura de archivos

```
proyecto-cupido-tu360/
├── whatsapp_bot.py          # Clase principal del bot
├── webhook_server.py         # Servidor Flask con webhooks
├── test_whatsapp.py         # Suite de tests
├── busqueda_propiedades.py  # Motor de búsqueda con Claude
├── database.py              # Conexión a PostgreSQL
├── .env                     # Credenciales (configurado)
├── requirements.txt         # Dependencias
└── webhook_logs/            # Logs de webhooks (se crea automáticamente)
```

## 🔧 Configuración avanzada

### Cambiar puerto del servidor

```bash
PORT=8080 python3 webhook_server.py
```

O editar en `webhook_server.py`:
```python
port = int(os.environ.get('PORT', 5000))  # Cambiar 5000 por el puerto deseado
```

### Desactivar modo debug

En `webhook_server.py`, cambiar:
```python
app.run(host='0.0.0.0', port=port, debug=False)  # False para producción
```

### Logs de webhooks

Los webhooks se guardan automáticamente en `webhook_logs/webhook_TIMESTAMP.json` para debugging.

## 📊 Flujo del sistema

```
Usuario envía mensaje por WhatsApp
           ↓
    UltraMSG recibe el mensaje
           ↓
    UltraMSG envía webhook a tu servidor
           ↓
    webhook_server.py recibe el webhook (/webhook endpoint)
           ↓
    whatsapp_bot.py procesa el mensaje
           ↓
    busqueda_propiedades.py usa Claude para extraer criterios
           ↓
    Búsqueda en PostgreSQL (database.py)
           ↓
    Ranking de resultados por relevancia
           ↓
    whatsapp_bot.py formatea las propiedades
           ↓
    Envío de resultados vía UltraMSG API
           ↓
    Usuario recibe las propiedades por WhatsApp
```

## 🎨 Formato de mensajes

Los mensajes enviados incluyen:

- 🏠 Título de la propiedad
- 💰 Precio
- 📍 Zona/Ubicación
- 🛏️ Habitaciones
- 🚿 Baños
- 📐 Área construida
- ✅ Razones de coincidencia (por qué se recomienda)
- 🌟 Amenidades principales
- 🔗 Link a la propiedad

## 🐛 Troubleshooting

### Error: "Faltan credenciales de UltraMSG"
Verifica que `.env` tenga `ULTRAMSG_INSTANCE_ID` y `ULTRAMSG_TOKEN`

### Error: "Module 'flask' not found"
```bash
pip install flask
```

### El webhook no recibe mensajes
1. Verifica que el servidor esté corriendo
2. Verifica que la URL pública esté configurada en UltraMSG
3. Verifica que la URL termine en `/webhook`
4. Revisa logs en `webhook_logs/`

### Mensajes no se envían
1. Verifica credenciales de UltraMSG en `.env`
2. Verifica que el Instance ID esté activo en el dashboard
3. Revisa el formato del número: `+573001234567` (con +)

## 📝 Notas importantes

1. **Número de teléfono**: Debe estar en formato internacional: `+573001234567`
2. **Rate limits**: UltraMSG tiene límites de mensajes por minuto según tu plan
3. **Logs**: Se guardan automáticamente en `webhook_logs/` para debugging
4. **Seguridad**: En producción, considera agregar autenticación al webhook
5. **Base de datos**: Asegúrate de tener propiedades cargadas en la BD

## 🚀 Despliegue en producción

Para producción, considera usar:

- **Heroku**: Fácil despliegue de Flask
- **Railway**: Alternativa moderna a Heroku
- **DigitalOcean**: Droplet con Ubuntu
- **AWS EC2**: Mayor control y escalabilidad
- **Google Cloud Run**: Serverless para Flask

## 📞 Soporte

Para problemas con:
- **UltraMSG**: [email protected] o +971507032874
- **Bot TU360**: Revisar logs en `webhook_logs/`
- **Claude API**: https://console.anthropic.com/

## ✅ Checklist de inicio

- [x] Instalar dependencias (`pip install -r requirements.txt`)
- [x] Configurar `.env` con credenciales
- [ ] Correr test: `python3 test_whatsapp.py`
- [ ] Iniciar servidor: `python3 webhook_server.py`
- [ ] Exponer servidor con ngrok/localtunnel
- [ ] Configurar webhook URL en UltraMSG dashboard
- [ ] Enviar mensaje de prueba desde WhatsApp
- [ ] Verificar recepción de webhook en logs
- [ ] ¡Listo para usar! 🎉
