# 🎯 Proyecto Cupido - Sistema Completo

## ✨ ¿Qué es esto?

**Proyecto Cupido** es un sistema inteligente de WhatsApp diseñado para **agentes inmobiliarios de Bancolombia** que automatiza y facilita:

- 🔍 **Búsqueda inteligente de propiedades** con lenguaje natural
- 📥 **Captación automática** de propiedades desde links de Wasi
- 🤝 **Matching de compradores con vendedores**
- 📊 **Trazabilidad completa** del proceso comercial
- 💰 **Registro de comisiones** con auditoría total

---

## 🚀 Inicio Rápido (5 minutos)

### 1. Activar entorno virtual

```powershell
.\venv\Scripts\Activate.ps1
```

### 2. Configurar ID del Grupo (IMPORTANTE)

```powershell
# Opción A: Script helper
python get_grupo_id.py

# Opción B: Manual
# 1. Inicia: python webhook_server.py
# 2. Envía mensaje en el grupo
# 3. Copia el ID que termina en @g.us
# 4. Pégalo en .env → GRUPO_CUPIDO_ID=
```

### 3. Iniciar el sistema

```powershell
# Terminal 1 - Servidor
python webhook_server.py

# Terminal 2 - Exponer públicamente
ngrok http 5000
```

### 4. Configurar webhook

1. Ve a https://user.ultramsg.com/
2. Settings → Webhooks
3. URL: `https://tu-url-ngrok.ngrok.io/webhook`
4. Activa "Incoming messages"
5. Guarda

### 5. ¡Probar!

En el grupo de Cupido:
```
Busco apto en Laureles, 2 habitaciones, hasta 500 millones
```

→ Recibirás resultados por privado

---

## 📚 Documentación Completa

### Para empezar:
1. **[GUIA_WINDOWS.md](GUIA_WINDOWS.md)** - Instalación en Windows
2. **[get_grupo_id.py](get_grupo_id.py)** - Obtener ID del grupo

### Para usar el sistema:
3. **[PROYECTO_CUPIDO_GUIA.md](PROYECTO_CUPIDO_GUIA.md)** - Guía completa y detallada
4. **[RESUMEN_IMPLEMENTACION.md](RESUMEN_IMPLEMENTACION.md)** - Resumen de lo implementado

### Técnica:
5. **[schema_cupido.sql](schema_cupido.sql)** - Schema de base de datos
6. **[README_WHATSAPP.md](README_WHATSAPP.md)** - Bot de WhatsApp
7. **[EJEMPLOS_API.md](EJEMPLOS_API.md)** - Ejemplos de uso de la API

---

## 🔄 ¿Cómo Funciona?

### En el Grupo de Cupido:

#### 📥 Captación de Propiedades
```
Agente: https://wasi.co/propertyid/123456
        ↓
Bot scrappea y guarda la propiedad
        ↓
Bot confirma por privado al agente
```

#### 🔍 Búsqueda de Propiedades
```
Agente: "Busco apto en Laureles, 2 habitaciones, hasta 500 millones"
        ↓
Bot busca con IA
        ↓
Bot envía resultados POR PRIVADO
        ↓
Agente selecciona: "1 y 3"
        ↓
Bot entrega información de contacto
        ↓
Bot notifica al vendedor (si aplica)
```

### En Chat Privado con Cupido:

Mismo flujo, pero todo en privado desde el inicio.

---

## 💡 Casos de Uso Reales

### Caso 1: Agente capta propiedad en el grupo

**Agente en grupo**:
```
https://wasi.co/propertyid/LAU-123456
```

**Cupido por privado**:
```
✅ Propiedad captada exitosamente

🏠 Apartamento en Laureles
📝 Código: LAU-123456

La propiedad está disponible para búsquedas.
```

---

### Caso 2: Agente busca desde el grupo

**Agente en grupo**:
```
Busco apto en Poblado, 3 habitaciones, gimnasio, hasta 800 millones
```

**Cupido por privado**:
```
🔍 Resultados de tu búsqueda

✅ Encontré 5 propiedades:

🏠 OPCIÓN 1
━━━━━━━━━━━━━━━━━━

Apartamento en El Poblado
💰 $750,000,000
📋 Características:
• 3 habitaciones | 2 baños
• 120 m²
• Parqueadero: 2

[4 opciones más...]

📝 ¿Cuáles te interesan?
Responde: "1", "1 y 3", "todas", "ninguna"
```

---

### Caso 3: Agente selecciona propiedades

**Agente responde**:
```
1 y 3
```

**Cupido responde**:
```
✅ Perfecto! Seleccionaste 2 propiedades

📞 Información de contacto

🏠 Apartamento en El Poblado
📱 Contactar a: Juan Pérez
   Teléfono: +573001111111
   (Propiedad captada por este agente)

🏠 Casa en Envigado
📱 Contactar a: Pulppo
   Teléfono: +573183351733
   (Propiedad de nuestra base de datos)

💡 Coordina con ellos para visitas...
```

**Cupido notifica a Juan Pérez** (dueño de la propiedad 1):
```
🎯 ¡Buenas noticias!

Un agente está interesado en tu propiedad:

🏠 Apartamento en El Poblado
💰 $750,000,000

👤 Agente interesado:
📱 +573002222222

💡 Contáctalo pronto para coordinar la visita.
```

---

## 🗄️ Trazabilidad y Reportes

Toda la actividad se registra en PostgreSQL (Neon):

### Ver solicitudes de hoy:
```sql
SELECT * FROM v_solicitudes_con_resultados
WHERE DATE(fecha_solicitud) = CURRENT_DATE;
```

### Ver matches activos:
```sql
SELECT * FROM v_interacciones_completas
WHERE estado = 'Seleccionado';
```

### Dashboard de un agente:
```sql
SELECT * FROM v_dashboard_agentes
WHERE telefono = '+573001234567';
```

### Top agentes por captación:
```sql
SELECT telefono, nombre, total_propiedades_captadas
FROM agentes
ORDER BY total_propiedades_captadas DESC
LIMIT 10;
```

---

## 🔧 Arquitectura

```
┌─────────────────────────────────────────────┐
│            PROYECTO CUPIDO                   │
├─────────────────────────────────────────────┤
│                                               │
│  WhatsApp (UltraMSG)                         │
│         │                                     │
│         ▼                                     │
│  WhatsAppBot ◄──► CupidoManager             │
│         │               │                     │
│         ▼               ▼                     │
│  PropertySearch   DatabaseManager            │
│  (Claude AI)      (PostgreSQL/Neon)          │
│                                               │
└─────────────────────────────────────────────┘
```

### Componentes:

1. **WhatsAppBot** - Interfaz con WhatsApp
2. **CupidoManager** - Lógica de negocio
3. **PropertySearch** - Búsqueda con IA
4. **DatabaseManager** - Persistencia y trazabilidad

---

## 📊 Base de Datos

### Tablas Principales:

- **agentes** - Registro de agentes
- **propiedades** - Propiedades (Pulppo + Captadas)
- **solicitudes_mercado** - Búsquedas realizadas
- **interacciones** - Selecciones (matches)
- **eventos_log** - Auditoría completa

### Vistas:

- **v_dashboard_agentes** - Métricas por agente
- **v_interacciones_completas** - Matches con toda la info
- **v_solicitudes_con_resultados** - Solicitudes completas

---

## ⚙️ Configuración Avanzada

### Cambiar contacto de Pulppo:

```sql
UPDATE configuracion_sistema
SET valor = '+573001234567'
WHERE clave = 'contacto_pulppo';
```

### Desactivar notificaciones:

```sql
UPDATE configuracion_sistema
SET valor = 'false'
WHERE clave = 'notificaciones_activas';
```

### Cambiar límite de propiedades:

```sql
UPDATE configuracion_sistema
SET valor = '10'
WHERE clave = 'max_propiedades_por_busqueda';
```

---

## 🛡️ Seguridad

### Filtros Implementados:

✅ Solo procesa grupo configurado en `.env`
✅ Ignora mensajes propios del bot
✅ Ignora eventos duplicados
✅ Valida longitud y palabras clave
✅ Filtra mensajes sin sentido

---

## 🐛 Troubleshooting

### El grupo no responde

```
✗ Problema: No se procesan mensajes del grupo
✓ Solución: Verifica GRUPO_CUPIDO_ID en .env
```

### No llegan notificaciones

```
✗ Problema: Vendedor no recibe notificación
✓ Solución: Verifica configuracion_sistema
  SELECT * FROM configuracion_sistema WHERE clave = 'notificaciones_activas';
```

### Error de DB

```
✗ Problema: Error al guardar en base de datos
✓ Solución: Verifica DATABASE_URL en .env
  python -c "from database import DatabaseManager; db = DatabaseManager(); db.connect()"
```

---

## 📞 Comandos del Bot

### En cualquier chat:

- `hola` - Mensaje de bienvenida
- `ayuda` - Instrucciones de uso
- `[búsqueda]` - Buscar propiedades

### En el grupo:

- `[link wasi]` - Captar propiedad
- `[búsqueda]` - Buscar (responde por privado)

### Durante selección:

- `1` - Seleccionar opción 1
- `1 y 3` - Seleccionar opciones 1 y 3
- `todas` - Seleccionar todas
- `ninguna` - No seleccionar ninguna

---

## 📈 Métricas

El sistema registra automáticamente:

- ✅ Total de solicitudes por agente
- ✅ Total de propiedades captadas por agente
- ✅ Total de matches logrados
- ✅ Tasa de conversión
- ✅ Propiedades más solicitadas
- ✅ Agentes más activos

---

## 🎓 Para Desarrolladores

### Estructura de archivos:

```
proyecto-cupido-tu360/
├── whatsapp_bot.py          # Bot de WhatsApp
├── cupido_manager.py        # Lógica de negocio
├── database.py              # Manager de BD
├── busqueda_propiedades.py  # Búsqueda con IA
├── scrapper_wasi.py         # Scraper de Wasi
├── webhook_server.py        # Servidor Flask
├── schema_cupido.sql        # Schema de BD
└── .env                     # Configuración
```

### Agregar nueva funcionalidad:

1. Modifica `cupido_manager.py` para la lógica
2. Extiende `database.py` si necesitas nuevas tablas
3. Actualiza `whatsapp_bot.py` para la interfaz

---

## 🚀 Siguiente Nivel

### Ideas futuras:

1. **Dashboard Web** - Panel de métricas en tiempo real
2. **Reportes Automáticos** - Envío diario/semanal por WhatsApp
3. **Multi-fuente** - Integrar Fincaraiz, Properati, etc.
4. **IA Mejorada** - Mejor matching con ML
5. **Análisis Predictivo** - Predecir matches exitosos

---

## 📝 Licencia

Este proyecto es propiedad de Bancolombia y está destinado exclusivamente para uso interno de agentes inmobiliarios autorizados.

---

## ✅ Checklist de Inicio

- [ ] Entorno virtual activado
- [ ] Dependencias instaladas
- [ ] `.env` configurado
- [ ] `GRUPO_CUPIDO_ID` configurado
- [ ] Base de datos creada (schema aplicado)
- [ ] Webhook server corriendo
- [ ] Ngrok exponiendo el puerto
- [ ] Webhook configurado en UltraMSG
- [ ] Test de captación exitoso
- [ ] Test de búsqueda exitoso
- [ ] Test de selección exitoso

---

## 🎉 ¡Listo para Usar!

El sistema está **100% funcional y listo para producción**.

Para dudas, consulta:
- **[PROYECTO_CUPIDO_GUIA.md](PROYECTO_CUPIDO_GUIA.md)** - Guía detallada
- **[RESUMEN_IMPLEMENTACION.md](RESUMEN_IMPLEMENTACION.md)** - Resumen técnico

---

**¡Que tengas muchos matches exitosos! 🎯🚀**
