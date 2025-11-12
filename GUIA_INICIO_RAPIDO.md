# 🚀 Guía de Inicio Rápido - Bot de WhatsApp TU360

## ✅ Estado actual

- ✅ Credenciales de UltraMSG configuradas y verificadas
- ✅ Conexión con API exitosa (status: authenticated + connected)
- ✅ Base de datos con 145 propiedades cargadas
- ✅ Sistema de búsqueda inteligente con Claude funcionando
- ✅ Bot de WhatsApp creado e integrado

## 🎯 Opciones para probar el bot

### 1️⃣ Test más rápido: Enviar mensaje manual

```bash
python3 quick_test.py
```

Cuando pregunte si quieres enviar mensaje, responde `s` e ingresa tu número (+573001234567)

### 2️⃣ Test completo interactivo

```bash
python3 test_whatsapp.py
```

Menú con opciones:
1. Enviar mensaje simple
2. Búsqueda completa (envía 5 propiedades)
3. Simular webhook

### 3️⃣ Iniciar servidor webhook (para recibir mensajes)

```bash
python3 webhook_server.py
```

O usa el script de inicio:
```bash
./start_bot.sh
```

## 📱 Para usar desde WhatsApp (producción)

### Paso 1: Iniciar servidor

```bash
python3 webhook_server.py
```

El servidor quedará corriendo en `http://localhost:5000`

### Paso 2: Exponer servidor públicamente

En otra terminal:

```bash
# Opción A: ngrok (recomendado)
ngrok http 5000

# Opción B: localtunnel
npx localtunnel --port 5000
```

Copia la URL pública que te dan (ej: `https://abc123.ngrok.io`)

### Paso 3: Configurar webhook en UltraMSG

1. Ve a https://user.ultramsg.com/
2. Login con tus credenciales
3. Selecciona tu instancia: `instance106153`
4. Ve a **Settings** → **Webhooks**
5. En "Webhook URL" pega: `https://abc123.ngrok.io/webhook` (reemplaza con tu URL)
6. Activa "Incoming messages"
7. Guarda

### Paso 4: ¡Probar!

Envía un mensaje de WhatsApp al número conectado a UltraMSG:

```
Busco apto en Laureles, 2 habitaciones, hasta 500 millones
```

El bot te responderá con las 5 mejores propiedades!

## 🧪 Test sin WhatsApp (API directo)

### Test 1: Enviar mensaje por API

```bash
curl -X POST http://localhost:5000/send \
  -H "Content-Type: application/json" \
  -d '{
    "to": "+573001234567",
    "message": "Hola desde la API"
  }'
```

### Test 2: Búsqueda por API

```bash
curl -X POST http://localhost:5000/search \
  -H "Content-Type: application/json" \
  -d '{
    "to": "+573001234567",
    "query": "Busco apto en Laureles, 2 habitaciones, hasta 500 millones"
  }'
```

### Test 3: Simular webhook

```bash
curl -X POST http://localhost:5000/test \
  -H "Content-Type: application/json" \
  -d '{
    "from": "+573001234567",
    "body": "Busco apartamento en El Poblado",
    "type": "chat"
  }'
```

## 💬 Comandos que entiende el bot

Desde WhatsApp, puedes enviar:

### Comandos especiales:
- `hola` - Mensaje de bienvenida
- `ayuda` - Instrucciones de uso

### Búsquedas libres:
- "Busco apto en Laureles, 2 habitaciones, hasta 500 millones"
- "Casa en Envigado, 3 alcobas, con jardín"
- "Apartamento nuevo en Poblado, presupuesto 800 millones"

El bot entiende lenguaje natural y extrae:
- 📍 Ubicaciones
- 🏠 Tipo de propiedad
- 💰 Presupuesto
- 🛏️ Habitaciones
- 📐 Área
- 🌟 Amenidades

## 🔧 Archivos creados

```
whatsapp_bot.py          # Clase principal del bot de WhatsApp
webhook_server.py         # Servidor Flask con endpoints
test_whatsapp.py         # Tests interactivos
quick_test.py            # Test rápido de conexión
start_bot.sh             # Script de inicio automático
README_WHATSAPP.md       # Documentación completa
GUIA_INICIO_RAPIDO.md    # Esta guía
```

## 📊 Flujo del sistema

```
Usuario → WhatsApp → UltraMSG → Webhook → Flask Server
                                              ↓
                                         Bot procesa
                                              ↓
                                      Claude extrae criterios
                                              ↓
                                      Búsqueda en PostgreSQL
                                              ↓
                                      Ranking de resultados
                                              ↓
                                    UltraMSG → WhatsApp → Usuario
```

## 🎨 Ejemplo de respuesta del bot

Cuando un usuario busca, recibe:

```
🤖 BÚSQUEDA INTELIGENTE DE PROPIEDADES
==================================================

📋 Criterios de búsqueda detectados:

📍 Ubicación: Laureles
🏠 Tipo: Apartamento
💰 Presupuesto máx: $500.000.000
🛏️ Habitaciones: 2

==================================================
🔍 Encontramos 5 propiedades

📊 Mostrando los mejores 5 resultados:

==================================================
🏠 RESULTADO #1 (Score: 36 pts)
==================================================

📋 Apartamento en Laureles, Laureles - 78m²

💰 Precio: $260,500,396 COP
📍 Zona: Laureles
🛏️ Habitaciones: 2
🚿 Baños: 3
📐 Área: 78m²

✅ ¿Por qué te recomendamos esta propiedad?
   • Ubicación: Laureles
   • Tipo: Apartamento
   • Precio dentro del presupuesto

🌟 Amenidades:
   • Cocina integral
   • Balcón
   • Closets

🔗 Ver más: https://pulppo.com/...
```

## 🐛 Solución de problemas

### "Module not found"
```bash
pip3 install -r requirements.txt --break-system-packages
```

### "Webhook no recibe mensajes"
1. Verifica que el servidor esté corriendo
2. Verifica la URL en UltraMSG (debe terminar en `/webhook`)
3. Verifica que ngrok/localtunnel esté activo
4. Revisa logs en `webhook_logs/`

### "No se envían mensajes"
1. Verifica credenciales en `.env`
2. Número debe tener formato: `+573001234567`
3. Verifica que la instancia esté conectada (run `python3 quick_test.py`)

## ✅ Checklist

- [x] Credenciales configuradas en `.env`
- [x] Dependencias instaladas
- [x] Conexión con UltraMSG verificada
- [x] Base de datos con propiedades
- [ ] Test de envío: `python3 quick_test.py` (responder 's')
- [ ] Servidor iniciado: `python3 webhook_server.py`
- [ ] ngrok/localtunnel corriendo
- [ ] Webhook configurado en UltraMSG dashboard
- [ ] Test desde WhatsApp enviado

## 🎉 ¡Ya estás listo!

El sistema está completamente funcional. Solo falta:

1. Exponer el servidor públicamente (ngrok)
2. Configurar el webhook en UltraMSG
3. Enviar mensaje de prueba desde WhatsApp

**¡Disfruta tu bot de búsqueda inteligente de propiedades! 🏠🤖**
