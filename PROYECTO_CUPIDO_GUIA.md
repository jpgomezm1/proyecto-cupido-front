# 🎯 Proyecto Cupido - Sistema Inteligente de Matching Inmobiliario

## 📋 Índice
1. [Visión General](#visión-general)
2. [Flujos de Trabajo](#flujos-de-trabajo)
3. [Arquitectura del Sistema](#arquitectura-del-sistema)
4. [Base de Datos y Trazabilidad](#base-de-datos-y-trazabilidad)
5. [Sistema de Búsqueda con IA](#sistema-de-búsqueda-con-ia)
6. [Integración con Pulppo](#integración-con-pulppo)
7. [Priorización de Inventario](#priorización-de-inventario)
8. [UI de Analítica (Próximamente)](#ui-de-analítica)
9. [Casos de Uso Reales](#casos-de-uso-reales)

---

## 🎯 Visión General

**Proyecto Cupido** es un sistema inteligente de matching inmobiliario diseñado específicamente para **agentes de Bancolombia**, que funciona completamente a través de WhatsApp. El sistema conecta automáticamente compradores con vendedores, gestiona el inventario de propiedades y proporciona trazabilidad completa del proceso comercial.

### ✨ Características Principales

- 🤖 **Interfaz 100% WhatsApp** - Sin apps adicionales, todo desde WhatsApp
- 🧠 **Búsqueda Inteligente con IA** - Procesa lenguaje natural usando Claude AI
- 📥 **Captación Automática** - Los agentes captan propiedades con un simple link
- 🔄 **Matching Automático** - Conecta compradores con vendedores al instante
- 📊 **Trazabilidad Total** - Cada interacción queda registrada para comisiones
- 🎨 **Dashboard Analítico** - Visualización de métricas y comportamiento del mercado
- 🔐 **Gestión de Accesos** - Control de agentes autorizados

---

## 🔄 Flujos de Trabajo

### 1️⃣ Flujo de Captación de Propiedades

Este flujo permite a los agentes agregar propiedades al sistema simplemente compartiendo un link de Wasi en el grupo de Cupido.

```
┌─────────────────────────────────────────────────────────────┐
│  FLUJO DE CAPTACIÓN - Agente capta propiedad               │
└─────────────────────────────────────────────────────────────┘

👤 Agente (en grupo Cupido)
   │
   │ Envía: https://info.wasi.co/apartamento-venta-laureles/123456
   │
   ▼
🤖 Cupido
   │
   ├─ ✅ Detecta link de Wasi
   ├─ 🔍 Scrappea datos de la propiedad
   │    • Título, precio, ubicación
   │    • Habitaciones, baños, área
   │    • Amenidades, imágenes
   │    • Toda la información disponible
   │
   ├─ 💾 Guarda en base de datos
   │    • Marca como "Wasi_Captado"
   │    • Asocia telefono del agente captador
   │    • Estado: Disponible
   │
   └─ 📱 Confirma por privado al agente
        │
        ▼
👤 Agente (mensaje privado)
   │
   Recibe: "✅ Propiedad captada exitosamente
            🏠 Apartamento en Laureles
            📝 Código: 123456

            La propiedad está disponible para búsquedas."
```

**Información Capturada:**
- ✅ Datos completos de la propiedad
- ✅ Teléfono del agente captador
- ✅ Timestamp de captación
- ✅ Fuente: Wasi_Captado
- ✅ Estado: Disponible

**Ventajas:**
- 📥 Captación en 1 segundo (solo pegar el link)
- 🤝 Propiedad queda asociada al agente
- 💰 Trazabilidad para comisiones
- 🔄 Disponible inmediatamente para otros agentes

---

### 2️⃣ Flujo de Búsqueda desde el Grupo

Cuando un agente busca propiedades desde el grupo, Cupido responde **por mensaje privado** para mantener la privacidad de los resultados.

```
┌─────────────────────────────────────────────────────────────┐
│  FLUJO DE BÚSQUEDA - Desde Grupo Cupido                    │
└─────────────────────────────────────────────────────────────┘

👤 Agente (en grupo Cupido)
   │
   │ Escribe: "Busco apto en Laureles, 2 habitaciones,
   │          hasta 500 millones, con parqueadero"
   │
   ▼
🤖 Cupido (procesa en silencio)
   │
   ├─ 🧠 Extrae criterios con Claude AI:
   │    • Ubicación: Laureles
   │    • Tipo: Apartamento
   │    • Habitaciones: 2+
   │    • Precio máximo: $500,000,000
   │    • Amenidades: parqueadero
   │
   ├─ 🔍 Busca en base de datos:
   │    • Propiedades de Pulppo (prioridad alta)
   │    • Propiedades captadas por agentes
   │
   ├─ ⭐ Rankea por relevancia:
   │    • Score por ubicación exacta
   │    • Score por características solicitadas
   │    • Bonus para propiedades Pulppo (producción)
   │
   └─ 📱 Envía resultados POR PRIVADO
        │
        ▼
👤 Agente (mensaje privado)
   │
   Recibe: "🔍 Resultados de tu búsqueda

            ✅ Encontré 5 propiedades:

            🏠 OPCIÓN 1
            ━━━━━━━━━━━━━━━━━━
            Apartamento en Laureles - 78m²
            💰 $450,000,000 COP
            📋 2 habitaciones | 2 baños
            🅿️ 1 parqueadero

            [... opciones 2-5 ...]

            📝 ¿Cuáles te interesan?
            Responde: '1', '1 y 3', 'todas', 'ninguna'"
```

**¿Por qué responde por privado?**
- 🔐 **Privacidad**: Los resultados son solo para el agente que preguntó
- 📊 **Trazabilidad**: Sabemos qué agente recibió qué propiedades
- 🎯 **Foco**: No satura el grupo con resultados
- 💼 **Profesional**: Cada agente maneja su negocio de forma independiente

---

### 3️⃣ Flujo de Selección y Contacto

Después de recibir los resultados, el agente selecciona las propiedades que le interesan.

```
┌─────────────────────────────────────────────────────────────┐
│  FLUJO DE SELECCIÓN - Agente elige propiedades             │
└─────────────────────────────────────────────────────────────┘

👤 Agente (mensaje privado)
   │
   │ Responde: "1 y 3"
   │
   ▼
🤖 Cupido
   │
   ├─ ✅ Registra selección en DB
   │    • ID solicitud
   │    • Propiedades seleccionadas: [1, 3]
   │    • Timestamp
   │    • Estado: Seleccionado
   │
   ├─ 🔍 Determina información de contacto:
   │
   │   Para OPCIÓN 1 (Wasi_Captado):
   │   ├─ Verifica origen en DB
   │   ├─ Obtiene teléfono del agente captador
   │   └─ Prepara contacto directo
   │
   │   Para OPCIÓN 3 (Pulppo):
   │   ├─ Verifica origen en DB
   │   ├─ Obtiene contacto de Pulppo
   │   └─ Prepara contacto empresa
   │
   ├─ 📱 Envía información al agente solicitante:
   │
   └─ Responde: "✅ Perfecto! Seleccionaste 2 propiedades

                 📞 Información de contacto:

                 🏠 Apartamento en Laureles
                 📱 Contactar a: Juan Pérez (Agente)
                    Teléfono: +573001234567
                    (Propiedad captada por este agente)

                 🏠 Casa en Envigado
                 📱 Contactar a: Pulppo
                    Teléfono: +573183351733
                    (Inventario Pulppo)

                 💡 Coordina con ellos para visitas"
        │
        ▼
🤖 Cupido (notificación automática)
   │
   └─ 📲 Notifica al agente dueño (solo Wasi_Captado)
        │
        ▼
👤 Juan Pérez (agente dueño)
   │
   Recibe: "🎯 ¡Buenas noticias!

            Un agente está interesado en tu propiedad:

            🏠 Apartamento en Laureles
            💰 $450,000,000

            👤 Agente interesado:
            📱 +573002222222

            💡 Contáctalo pronto para coordinar."
```

**Diferenciación de Contactos:**

| Origen | Contacto | Notificación al Dueño |
|--------|----------|----------------------|
| **Wasi_Captado** | Teléfono del agente captador | ✅ Sí, se notifica al agente dueño |
| **Pulppo** | Teléfono fijo de Pulppo (+573183351733) | ❌ No aplica |

**Trazabilidad Registrada:**
- ✅ Quién buscó
- ✅ Qué propiedades encontró
- ✅ Cuáles seleccionó
- ✅ Cuándo ocurrió cada evento
- ✅ Estado de cada interacción

---

### 4️⃣ Flujo de Búsqueda Privada (Directo con Cupido)

Los agentes también pueden buscar directamente en el chat privado con Cupido.

```
┌─────────────────────────────────────────────────────────────┐
│  FLUJO DE BÚSQUEDA - Chat Privado                          │
└─────────────────────────────────────────────────────────────┘

👤 Agente (chat privado con Cupido)
   │
   │ Escribe: "Hola, busco casa en Envigado,
   │          3 habitaciones, piscina"
   │
   ▼
🤖 Cupido
   │
   [... mismo proceso de búsqueda ...]
   │
   └─ 📱 Responde en el mismo chat privado

   [... mismo flujo de selección ...]
```

**Diferencia con búsqueda en grupo:**
- 📍 **Contexto**: El agente ya está en privado
- 🔄 **Flujo**: Idéntico al de grupo, pero todo en el mismo chat
- ✅ **Ventaja**: Más discreto para búsquedas sensibles

---

## 🏗️ Arquitectura del Sistema

### Componentes Principales

```
┌──────────────────────────────────────────────────────────────┐
│                    PROYECTO CUPIDO                           │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │  WhatsApp (UltraMSG API)                           │    │
│  │  • Recibe mensajes vía webhook                      │    │
│  │  • Envía mensajes a agentes                         │    │
│  │  • Gestiona grupos y chats privados                 │    │
│  └──────────────────┬─────────────────────────────────┘    │
│                     │                                        │
│                     ▼                                        │
│  ┌────────────────────────────────────────────────────┐    │
│  │  WhatsApp Bot (whatsapp_bot.py)                    │    │
│  │  • Procesa eventos de webhook                       │    │
│  │  • Detecta tipo de mensaje                          │    │
│  │  • Filtra grupo vs privado                          │    │
│  │  • Extrae participante en grupos                    │    │
│  └──────────────────┬─────────────────────────────────┘    │
│                     │                                        │
│                     ▼                                        │
│  ┌────────────────────────────────────────────────────┐    │
│  │  Cupido Manager (cupido_manager.py)                │    │
│  │  • Lógica de negocio principal                      │    │
│  │  • Determina: captación vs búsqueda                 │    │
│  │  • Orquesta flujos de trabajo                       │    │
│  │  • Gestiona sesiones de usuario                     │    │
│  └──────┬────────────────────────────────┬────────────┘    │
│         │                                │                  │
│         ▼                                ▼                  │
│  ┌─────────────────┐          ┌──────────────────────┐    │
│  │ Property Search │          │  Wasi Scraper        │    │
│  │ (busqueda_      │          │  (scrapper_wasi.py)  │    │
│  │  propiedades.py)│          │                      │    │
│  │                 │          │  • Extrae datos      │    │
│  │ • Claude AI     │          │  • Parsea HTML       │    │
│  │ • NLP Query     │          │  • Valida info       │    │
│  │ • SQL Builder   │          │                      │    │
│  │ • Ranking       │          │                      │    │
│  └────────┬────────┘          └──────────┬───────────┘    │
│           │                              │                  │
│           └──────────┬───────────────────┘                  │
│                      ▼                                      │
│  ┌────────────────────────────────────────────────────┐    │
│  │  Database Manager (database.py)                    │    │
│  │  • PostgreSQL (Neon)                               │    │
│  │  • CRUD operations                                  │    │
│  │  • Transacciones                                    │    │
│  │  • Logging de eventos                               │    │
│  └──────────────────┬─────────────────────────────────┘    │
│                     │                                        │
│                     ▼                                        │
│  ┌────────────────────────────────────────────────────┐    │
│  │  PostgreSQL Database (Neon Cloud)                  │    │
│  │  • agentes                                          │    │
│  │  • propiedades                                      │    │
│  │  • solicitudes_mercado                              │    │
│  │  • interacciones                                    │    │
│  │  • eventos_log                                      │    │
│  │  • configuracion_sistema                            │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Tecnologías Utilizadas

| Componente | Tecnología | Propósito |
|------------|-----------|-----------|
| **Backend** | Python 3.x | Lógica de negocio |
| **Bot Framework** | Flask + UltraMSG | Webhook server |
| **IA** | Claude 3.5 Sonnet (Anthropic) | Procesamiento de lenguaje natural |
| **Base de Datos** | PostgreSQL (Neon) | Persistencia y trazabilidad |
| **Web Scraping** | BeautifulSoup + Requests | Extracción de datos de Wasi |
| **Hosting** | Ngrok (dev) / Cloud (prod) | Exposición de webhooks |

---

## 💾 Base de Datos y Trazabilidad

El sistema utiliza PostgreSQL con un esquema diseñado específicamente para **trazabilidad completa** del proceso comercial.

### Tablas Principales

#### 1️⃣ `agentes`
Registro de todos los agentes que usan Cupido.

```sql
CREATE TABLE agentes (
    id SERIAL PRIMARY KEY,
    telefono VARCHAR(20) UNIQUE NOT NULL,
    nombre VARCHAR(255),
    email VARCHAR(255),
    activo BOOLEAN DEFAULT TRUE,

    -- Métricas
    total_solicitudes INTEGER DEFAULT 0,
    total_propiedades_captadas INTEGER DEFAULT 0,
    total_matches_logrados INTEGER DEFAULT 0,

    -- Auditoría
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ultima_actividad TIMESTAMP
);
```

**Campos Clave:**
- `telefono`: Identificador único del agente (+573001234567)
- `total_propiedades_captadas`: Cuenta propiedades que el agente ha agregado
- `total_matches_logrados`: Cuenta veces que sus propiedades fueron seleccionadas
- `ultima_actividad`: Para seguimiento de uso

---

#### 2️⃣ `propiedades`
Inventario completo de propiedades (Pulppo + Captadas).

```sql
CREATE TABLE propiedades (
    id SERIAL PRIMARY KEY,
    codigo_propiedad VARCHAR(100) UNIQUE NOT NULL,

    -- Origen
    fuente VARCHAR(50) NOT NULL, -- 'Pulppo' o 'Wasi_Captado'
    url TEXT,

    -- Captación (solo para Wasi_Captado)
    captada_por_telefono VARCHAR(20),
    fecha_captacion TIMESTAMP,

    -- Información básica
    titulo TEXT,
    precio BIGINT,
    precio_texto VARCHAR(50),
    tipo_propiedad VARCHAR(100),
    estado VARCHAR(50),

    -- Ubicación
    ciudad VARCHAR(100),
    zona VARCHAR(200),
    direccion_completa TEXT,

    -- Características
    area_construida DECIMAL(10,2),
    habitaciones INTEGER,
    banos INTEGER,
    parqueaderos INTEGER,
    estrato INTEGER,
    piso INTEGER,

    -- Amenidades
    amenidades_internas TEXT,
    amenidades_externas TEXT,
    total_amenidades INTEGER,

    -- Contacto
    asesor VARCHAR(255),
    telefono VARCHAR(50),
    inmobiliaria VARCHAR(255),

    -- Estado
    activa BOOLEAN DEFAULT TRUE,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Índices para búsqueda rápida
    CONSTRAINT fk_captador FOREIGN KEY (captada_por_telefono)
        REFERENCES agentes(telefono)
);
```

**Campos Clave:**
- `fuente`: Diferencia entre propiedades de Pulppo y captadas por agentes
- `captada_por_telefono`: NULL para Pulppo, teléfono del agente para Wasi_Captado
- `activa`: Permite desactivar propiedades sin eliminarlas

---

#### 3️⃣ `solicitudes_mercado`
Registro de cada búsqueda realizada por un agente.

```sql
CREATE TABLE solicitudes_mercado (
    id SERIAL PRIMARY KEY,
    agente_telefono VARCHAR(20) NOT NULL,

    -- Solicitud
    mensaje_original TEXT NOT NULL,
    criterios_extraidos JSONB, -- Criterios parseados por Claude

    -- Resultados
    total_resultados INTEGER DEFAULT 0,
    propiedades_ids INTEGER[], -- Array de IDs encontrados

    -- Estado
    estado VARCHAR(50) DEFAULT 'Pendiente',
    -- Estados: Pendiente, Enviado, Seleccionado, Sin_Respuesta

    -- Auditoría
    fecha_solicitud TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_cambio_estado TIMESTAMP,

    CONSTRAINT fk_agente FOREIGN KEY (agente_telefono)
        REFERENCES agentes(telefono)
);
```

**Campos Clave:**
- `mensaje_original`: La búsqueda tal cual la escribió el agente
- `criterios_extraidos`: JSON con lo que Claude interpretó
- `propiedades_ids`: Array con IDs de propiedades que se mostraron
- `estado`: Tracking del flujo de la solicitud

---

#### 4️⃣ `interacciones`
Registro de cada match (agente selecciona propiedad).

```sql
CREATE TABLE interacciones (
    id SERIAL PRIMARY KEY,

    -- Relaciones
    solicitud_id INTEGER NOT NULL,
    propiedad_id INTEGER NOT NULL,
    agente_comprador_telefono VARCHAR(20) NOT NULL,
    agente_vendedor_telefono VARCHAR(20), -- NULL si es Pulppo

    -- Estado
    estado VARCHAR(50) DEFAULT 'Seleccionado',
    -- Estados: Seleccionado, Contactado, Visita_Agendada,
    --          Negociacion, Cerrado, Descartado

    -- Notificaciones
    notificacion_enviada BOOLEAN DEFAULT FALSE,
    fecha_notificacion TIMESTAMP,

    -- Auditoría
    fecha_interaccion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMP,

    -- Comisiones (futuro)
    comision_vendedor DECIMAL(15,2),
    comision_comprador DECIMAL(15,2),

    CONSTRAINT fk_solicitud FOREIGN KEY (solicitud_id)
        REFERENCES solicitudes_mercado(id),
    CONSTRAINT fk_propiedad FOREIGN KEY (propiedad_id)
        REFERENCES propiedades(id),
    CONSTRAINT fk_comprador FOREIGN KEY (agente_comprador_telefono)
        REFERENCES agentes(telefono)
);
```

**Campos Clave:**
- `solicitud_id`: Referencia a la búsqueda original
- `propiedad_id`: Propiedad seleccionada
- `agente_comprador_telefono`: Quien busca/compra
- `agente_vendedor_telefono`: Quien captó (NULL si es Pulppo)
- `estado`: Permite seguimiento del embudo comercial
- `comision_*`: Para cálculo futuro de comisiones

---

#### 5️⃣ `eventos_log`
Auditoría completa de TODOS los eventos del sistema.

```sql
CREATE TABLE eventos_log (
    id SERIAL PRIMARY KEY,

    tipo_evento VARCHAR(100) NOT NULL,
    -- Tipos: Propiedad_Captada, Solicitud_Creada,
    --        Resultado_Enviado, Propiedad_Seleccionada,
    --        Notificacion_Enviada, etc.

    agente_telefono VARCHAR(20),
    propiedad_id INTEGER,
    solicitud_id INTEGER,
    interaccion_id INTEGER,

    detalles JSONB, -- Información adicional en JSON
    exito BOOLEAN DEFAULT TRUE,
    mensaje_error TEXT,

    fecha_evento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Campos Clave:**
- `tipo_evento`: Clasificación del evento
- `detalles`: JSON flexible con información adicional
- `exito`: Indica si el evento se completó exitosamente
- `fecha_evento`: Para análisis temporal

---

## 🧠 Sistema de Búsqueda con IA

El sistema de búsqueda utiliza **Claude 3.5 Sonnet** de Anthropic para procesar lenguaje natural y encontrar propiedades relevantes.

### Proceso de Búsqueda

```
┌─────────────────────────────────────────────────────────────┐
│  PROCESO DE BÚSQUEDA INTELIGENTE                            │
└─────────────────────────────────────────────────────────────┘

📝 Input del Agente:
   "Busco apto en Laureles, 2 habitaciones, hasta 500 millones,
    con parqueadero y gimnasio"
   │
   ▼
┌──────────────────────────────────────────────────────────┐
│ PASO 1: Extracción de Criterios con Claude AI           │
└──────────────────────────────────────────────────────────┘
   │
   ├─ Claude analiza el mensaje
   ├─ Identifica entidades y valores
   └─ Retorna JSON estructurado:

   {
     "ubicaciones": ["Laureles"],
     "tipo_propiedad": "Apartamento",
     "habitaciones_min": 2,
     "precio_max": 500000000,
     "amenidades_requeridas": ["parqueadero", "gimnasio"]
   }
   │
   ▼
┌──────────────────────────────────────────────────────────┐
│ PASO 2: Construcción de Query SQL                       │
└──────────────────────────────────────────────────────────┘
   │
   ├─ Convierte criterios a condiciones SQL
   ├─ Aplica filtros:
   │   • Ubicación: zona ILIKE '%Laureles%' OR titulo ILIKE '%Laureles%'
   │   • Tipo: tipo_propiedad ILIKE '%Apartamento%'
   │   • Habitaciones: habitaciones >= 2
   │   • Precio: precio <= 500000000
   │   • Amenidades: amenidades_* ILIKE '%parqueadero%'
   │
   └─ Query optimizada con índices
   │
   ▼
┌──────────────────────────────────────────────────────────┐
│ PASO 3: Ejecución en Base de Datos                      │
└──────────────────────────────────────────────────────────┘
   │
   ├─ Ejecuta query en PostgreSQL
   ├─ Obtiene resultados candidatos
   └─ Si no hay resultados → búsqueda relajada
       (relaja algunos criterios no críticos)
   │
   ▼
┌──────────────────────────────────────────────────────────┐
│ PASO 4: Ranking por Relevancia                          │
└──────────────────────────────────────────────────────────┘
   │
   ├─ Calcula score de match para cada propiedad:
   │
   │   • Ubicación exacta: +10 pts
   │   • Tipo correcto: +5 pts
   │   • Precio en presupuesto: +8 pts
   │   • Habitaciones exactas: +7 pts
   │   • Tiene amenidad requerida: +6 pts c/u
   │   • Muchas amenidades: +4 pts
   │   • BONUS Pulppo (producción): +15 pts
   │
   ├─ Ordena por score descendente
   └─ Selecciona top 5-10 propiedades
   │
   ▼
┌──────────────────────────────────────────────────────────┐
│ PASO 5: Formateo y Envío                                │
└──────────────────────────────────────────────────────────┘
   │
   └─ Formatea resultados para WhatsApp
   └─ Envía por privado al agente
```

### Sistema de Scoring

El sistema calcula un **match_score** para cada propiedad encontrada:

| Criterio | Puntos | Condición |
|----------|--------|-----------|
| **Ubicación exacta** | +10 | Zona/título contiene ubicación buscada |
| **Tipo de propiedad** | +5 | Tipo coincide (ej: Apartamento) |
| **Precio óptimo** | +8 | Precio ≤ 90% del máximo |
| **Precio en rango** | +5 | Precio ≤ 100% del máximo |
| **Habitaciones exactas** | +7 | Número exacto de habitaciones |
| **Habitaciones suficientes** | +3 | Cumple mínimo de habitaciones |
| **Amenidad requerida** | +6 | Por cada amenidad solicitada que tiene |
| **Muchas amenidades** | +4 | >15 amenidades totales |
| **Piso específico** | +8 | Coincide piso solicitado |
| **🎯 BONUS Pulppo** | +15 | **Solo en producción: prioriza inventario Pulppo** |

### Ejemplo de Ranking

```
Búsqueda: "Apto en Laureles, 2 hab, hasta 500M, parqueadero"

RESULTADOS RANKEADOS:

🥇 OPCIÓN 1 - Score: 53 pts
   Apartamento en Laureles - $450M - 2 hab
   • Ubicación: Laureles (+10)
   • Tipo: Apartamento (+5)
   • Precio: $450M (+8)
   • Habitaciones: 2 exactas (+7)
   • Tiene parqueadero (+6)
   • 18 amenidades (+4)
   • BONUS Pulppo (+15) ⭐
   Origen: Pulppo

🥈 OPCIÓN 2 - Score: 38 pts
   Apartamento en Laureles - $480M - 2 hab
   • Ubicación: Laureles (+10)
   • Tipo: Apartamento (+5)
   • Precio: $480M (+5)
   • Habitaciones: 2 exactas (+7)
   • Tiene parqueadero (+6)
   • 12 amenidades (+0)
   • Sin bonus Pulppo (+0)
   Origen: Wasi_Captado (Agente Juan Pérez)

🥉 OPCIÓN 3 - Score: 36 pts
   Apartamento en Laureles - $490M - 3 hab
   • Ubicación: Laureles (+10)
   • Tipo: Apartamento (+5)
   • Precio: $490M (+5)
   • Habitaciones: 3 (+3, cumple mínimo)
   • Sin parqueadero (+0)
   • 16 amenidades (+4)
   • Sin bonus Pulppo (+0)
   Origen: Wasi_Captado (Agente María López)
```

---

## 🔗 Integración con Pulppo

### Estado Actual (Demo)

Actualmente el sistema tiene propiedades de Pulppo **hardcodeadas** en la base de datos para propósitos de demostración. Estas fueron cargadas inicialmente con el script de scraping.

```sql
-- Ejemplo de propiedades Pulppo actuales
SELECT COUNT(*) FROM propiedades WHERE fuente = 'Pulppo';
-- Resultado: ~150 propiedades

SELECT codigo_propiedad, titulo, precio, zona
FROM propiedades
WHERE fuente = 'Pulppo'
LIMIT 3;

-- Ejemplo de resultados:
-- pulppo-00001 | Apartamento en Laureles | $450,000,000 | Laureles
-- pulppo-00002 | Casa en Envigado       | $850,000,000 | Envigado
-- pulppo-00003 | Penthouse en El Poblado | $1,200,000,000 | El Poblado
```

### Integración Futura (Producción)

En producción, el sistema se integrará con la **API de Pulppo** para:

#### 1️⃣ Sincronización Automática

```python
# Pseudo-código de integración futura

class PulppoIntegration:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.pulppo.com/v1"

    def sync_properties(self):
        """
        Sincroniza propiedades de Pulppo con la DB local
        Se ejecuta cada X horas
        """
        # Obtener propiedades activas de Pulppo
        properties = self.fetch_active_properties()

        for prop in properties:
            # Actualizar o insertar en DB local
            self.upsert_property(prop)

        # Desactivar propiedades que ya no están en Pulppo
        self.deactivate_removed_properties()

    def fetch_active_properties(self):
        """Obtiene inventario activo de Pulppo"""
        response = requests.get(
            f"{self.base_url}/properties",
            headers={"Authorization": f"Bearer {self.api_key}"},
            params={"status": "active", "limit": 1000}
        )
        return response.json()

    def upsert_property(self, pulppo_data):
        """Inserta o actualiza propiedad en DB"""
        db = DatabaseManager()

        # Transformar datos de Pulppo a formato local
        property_data = self.transform_pulppo_data(pulppo_data)

        # Upsert en DB
        db.upsert_property(property_data)
```

#### 2️⃣ Webhook de Pulppo

Pulppo enviará webhooks cuando:
- ✅ Se agregue una nueva propiedad
- ✅ Se actualice una propiedad existente
- ✅ Se desactive/venda una propiedad

```python
# Endpoint para recibir webhooks de Pulppo

@app.route('/webhook/pulppo', methods=['POST'])
def pulppo_webhook():
    """Recibe notificaciones de cambios desde Pulppo"""

    data = request.json
    event_type = data.get('event')

    if event_type == 'property.created':
        # Nueva propiedad en Pulppo
        sync_single_property(data['property_id'])

    elif event_type == 'property.updated':
        # Propiedad actualizada
        update_property(data['property_id'], data['changes'])

    elif event_type == 'property.sold':
        # Propiedad vendida - desactivar
        deactivate_property(data['property_id'])

    return {'status': 'ok'}
```

#### 3️⃣ Contacto Dinámico

En producción, el contacto de Pulppo será **dinámico** según la propiedad:

```python
def get_property_contact(property_id):
    """
    Obtiene información de contacto de una propiedad
    """
    property = db.get_property(property_id)

    if property['fuente'] == 'Pulppo':
        # Consultar API de Pulppo por contacto específico
        contact = pulppo_api.get_property_contact(property['codigo_propiedad'])
        return {
            'nombre': contact['agent_name'],
            'telefono': contact['phone'],
            'email': contact['email'],
            'tipo': 'Pulppo'
        }

    elif property['fuente'] == 'Wasi_Captado':
        # Contacto es el agente que captó
        agente = db.get_agente(property['captada_por_telefono'])
        return {
            'nombre': agente['nombre'],
            'telefono': agente['telefono'],
            'tipo': 'Agente'
        }
```

#### 4️⃣ Flujo de Sincronización

```
┌─────────────────────────────────────────────────────────────┐
│  SINCRONIZACIÓN CON PULPPO (Producción)                    │
└─────────────────────────────────────────────────────────────┘

⏰ Cada 4 horas (configurable):
   │
   ▼
🔄 Tarea Programada (Cron/Celery)
   │
   ├─ 📞 Consulta API de Pulppo
   │    GET /api/v1/properties?status=active
   │
   ├─ 🔍 Compara con DB local
   │    • Nuevas propiedades → INSERT
   │    • Propiedades actualizadas → UPDATE
   │    • Propiedades removidas → UPDATE activa=FALSE
   │
   ├─ 💾 Actualiza base de datos
   │
   └─ 📊 Log de sincronización
        ✅ 15 propiedades nuevas
        ✅ 8 propiedades actualizadas
        ✅ 3 propiedades desactivadas

🔔 Webhooks en tiempo real:
   │
   Pulppo → Cupido
   │
   └─ Actualizaciones inmediatas para eventos críticos
```

---

## ⭐ Priorización de Inventario Pulppo

En **producción**, las propiedades de Pulppo tendrán **prioridad en los resultados de búsqueda** para garantizar que el inventario de la empresa rote más rápido.

### Estrategia de Priorización

#### 1️⃣ Bonus de Ranking

```python
# En busqueda_propiedades.py - método _rank_results()

def _rank_results(self, results: List[Dict], criteria: Dict[str, Any]) -> List[Dict]:
    """
    Rankea los resultados según qué tan bien coinciden con los criterios
    """

    for result in results:
        score = 0
        reasons = []

        # ... cálculos de score normales ...

        # 🎯 BONUS PULPPO (solo en producción)
        if result.get('fuente') == 'Pulppo':
            score += 15  # Bonus significativo
            reasons.append("⭐ Inventario Pulppo")

        result['match_score'] = score
        result['match_reasons'] = reasons

    # Ordenar por score descendente
    results.sort(key=lambda x: x.get('match_score', 0), reverse=True)

    return results
```

#### 2️⃣ Configuración Flexible

El bonus de Pulppo será **configurable** en la base de datos:

```sql
-- Tabla configuracion_sistema

INSERT INTO configuracion_sistema (clave, valor, descripcion)
VALUES
    ('pulppo_bonus_score', '15', 'Puntos extra para propiedades Pulppo en ranking'),
    ('pulppo_bonus_activo', 'true', 'Activar/desactivar bonus de Pulppo'),
    ('min_propiedades_pulppo', '3', 'Mínimo de propiedades Pulppo a mostrar si existen');
```

Esto permite ajustar la priorización sin cambiar código:

```python
def get_pulppo_bonus():
    """Obtiene configuración de bonus Pulppo"""
    config = db.get_config('pulppo_bonus_activo')

    if config == 'true':
        return int(db.get_config('pulppo_bonus_score'))
    return 0
```

#### 3️⃣ Estrategia de Mezcla

Los resultados se mostrarán con una **mezcla estratégica**:

```
📊 Estrategia de Resultados (10 propiedades mostradas):

CONFIGURACIÓN:
• Top 3: Mejores matches (independiente de fuente)
• Posiciones 4-7: Al menos 2 deben ser Pulppo si existen
• Posiciones 8-10: Mejores matches restantes

EJEMPLO DE RESULTADO:

🥇 Opción 1 - Score: 53 pts - Pulppo ⭐
🥈 Opción 2 - Score: 48 pts - Wasi_Captado
🥉 Opción 3 - Score: 46 pts - Pulppo ⭐
   Opción 4 - Score: 42 pts - Pulppo ⭐
   Opción 5 - Score: 40 pts - Wasi_Captado
   Opción 6 - Score: 38 pts - Pulppo ⭐
   Opción 7 - Score: 36 pts - Wasi_Captado
   Opción 8 - Score: 34 pts - Wasi_Captado
   Opción 9 - Score: 32 pts - Pulppo ⭐
   Opción 10 - Score: 30 pts - Wasi_Captado

Resultado: 5 Pulppo + 5 Wasi_Captado
```

#### 4️⃣ Métricas de Rotación

El sistema registrará métricas para validar la estrategia:

```sql
-- Query para analizar rotación

SELECT
    fuente,
    COUNT(*) as total_matches,
    AVG(EXTRACT(EPOCH FROM (fecha_interaccion - p.fecha_creacion))/86400) as dias_promedio_match
FROM interacciones i
INNER JOIN propiedades p ON i.propiedad_id = p.id
WHERE i.fecha_interaccion >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY fuente;

-- Resultado esperado:
-- Pulppo        | 150 | 8.5 días  (rotación rápida)
-- Wasi_Captado  | 80  | 15.2 días (rotación más lenta)
```

---

## 📊 UI de Analítica (Próximamente)

El sistema incluirá una **interfaz web completa** para visualización de métricas, gestión de inventario y administración de agentes.

### Módulos del Dashboard

#### 1️⃣ Panel de Inventario

Visualización completa del inventario disponible.

**Funcionalidades:**
- ✅ Filtrado avanzado por múltiples criterios
- ✅ Búsqueda por código o texto
- ✅ Vista detallada de cada propiedad
- ✅ Edición rápida de campos
- ✅ Activar/desactivar propiedades
- ✅ Exportación a CSV/Excel
- ✅ Importación masiva

**Preview:**
```
┌─────────────────────────────────────────────────────────────┐
│  📦 INVENTARIO DE PROPIEDADES                               │
└─────────────────────────────────────────────────────────────┘

Filtros: [Fuente] [Zona] [Tipo] [Precio] [Estado]

Resumen:
• Total: 320 propiedades
• Pulppo: 150 (47%) | Wasi_Captado: 170 (53%)
• Activas: 295 | Inactivas: 25
• Precio Promedio: $485M | Área Promedio: 85m²

Lista con acciones: Ver, Editar, Desactivar, Exportar
```

---

#### 2️⃣ Panel de Agentes

Gestión completa de agentes autorizados.

**Funcionalidades:**
- ✅ Agregar nuevos agentes (por teléfono)
- ✅ Activar/desactivar acceso
- ✅ Ver historial de actividad por agente
- ✅ Métricas individuales (solicitudes, captaciones, matches)
- ✅ Exportar lista de agentes
- ✅ Enviar invitación automática por WhatsApp
- ✅ Búsqueda por nombre o teléfono

**Preview:**
```
┌─────────────────────────────────────────────────────────────┐
│  👥 GESTIÓN DE AGENTES                                      │
└─────────────────────────────────────────────────────────────┘

Total: 45 agentes | Activos: 42 | Nuevos (7 días): 5

Lista:
• Juan Pérez - 28 solicitudes, 15 captadas, 8 matches
• María López - 35 solicitudes, 8 captadas, 12 matches
• Carlos Ruiz - 12 solicitudes, 22 captadas, 5 matches

Acciones: [+ Agregar] [Exportar] [Enviar Invitación]
```

---

#### 3️⃣ Panel de Analítica

Dashboard con métricas clave y visualizaciones.

**Funcionalidades:**
- ✅ Métricas en tiempo real
- ✅ Gráficos interactivos
- ✅ Filtros por periodo
- ✅ Comparación vs periodos anteriores
- ✅ Exportar reportes en PDF
- ✅ Programar envío automático

**Preview:**
```
┌─────────────────────────────────────────────────────────────┐
│  📈 ANALÍTICA DE CUPIDO                                     │
└─────────────────────────────────────────────────────────────┘

Periodo: [Últimos 30 días]

MÉTRICAS CLAVE:
• Total Solicitudes: 145 (↑ 23% vs mes anterior)
• Propiedades: 320 (↑ 8%)
• Matches Logrados: 87 (↑ 31%)
• Agentes Activos: 42 (↑ 12%)

ACTIVIDAD EN EL TIEMPO:
[Gráfico de línea con solicitudes por día]

PROPIEDADES MÁS SOLICITADAS:
1. Apartamentos en Laureles (23 matches)
2. Apartamentos en El Poblado (18 matches)
3. Casas en Envigado (15 matches)

AGENTES MÁS ACTIVOS:
🥇 María López - 35 solicitudes, 12 matches
🥈 Juan Pérez - 28 solicitudes, 8 matches
🥉 Carlos Ruiz - 22 solicitudes, 5 matches

TASA DE CONVERSIÓN:
Embudo: Solicitudes → Resultados → Selección → Match
        145 (100%) → 138 (95%) → 102 (70%) → 87 (60%)
Tasa de Match: 60% ✅ (objetivo: 50%)

ROTACIÓN DE INVENTARIO:
• Pulppo: 8.5 días promedio ✅
• Wasi_Captado: 15.2 días
📊 Pulppo rota 1.8x más rápido
```

---

#### 4️⃣ Panel de Comportamiento del Mercado

Análisis profundo de tendencias y patrones.

**Funcionalidades:**
- ✅ Análisis de demanda por zona
- ✅ Análisis de rangos de precio
- ✅ Características más solicitadas
- ✅ Gaps en inventario (qué falta)
- ✅ Recomendaciones automáticas
- ✅ Tendencias temporales
- ✅ Predicción de demanda (ML futuro)

**Preview:**
```
┌─────────────────────────────────────────────────────────────┐
│  🔍 INTELIGENCIA DE MERCADO                                 │
└─────────────────────────────────────────────────────────────┘

ZONAS MÁS BUSCADAS:
1. Laureles (85 búsquedas)
2. El Poblado (72 búsquedas)
3. Envigado (55 búsquedas)

RANGO DE PRECIOS DEMANDADO:
• < $300M: 18%
• $300M - $500M: 45% ⭐ Mayor demanda
• $500M - $800M: 25%
• $800M - $1.2B: 12%

CARACTERÍSTICAS MÁS SOLICITADAS:
• Parqueadero: 128 menciones (88%)
• Balcón: 95 menciones (65%)
• Piscina: 82 menciones (56%)
• Gimnasio: 78 menciones (54%)

HABITACIONES DEMANDADAS:
• 2 habitaciones: 52% ⭐
• 3 habitaciones: 35%
• 1 habitación: 8%

INSIGHTS AUTOMÁTICOS:
💡 Hay 15 propiedades en Laureles sin matches
   Sugerencia: Ajustar precios o destacar

📈 Demanda de apartamentos 2 hab aumentó 23%
   Sugerencia: Captar más inventario en Laureles

⚠️  Solo 3 propiedades Pulppo con piscina
   Oportunidad: Ampliar inventario premium
```

---

#### 5️⃣ Panel de Matches y Trazabilidad

Vista detallada de todas las interacciones.

**Funcionalidades:**
- ✅ Historial completo de matches
- ✅ Filtrado por estado, agente, periodo
- ✅ Vista detallada con línea de tiempo
- ✅ Actualización de estados
- ✅ Exportar reportes individuales
- ✅ Notificaciones pendientes

**Preview:**
```
┌─────────────────────────────────────────────────────────────┐
│  🤝 MATCHES Y TRAZABILIDAD                                  │
└─────────────────────────────────────────────────────────────┘

Filtros: [Estado] [Periodo] [Agente] [Fuente]

Match #145 - 2025-11-03 09:42
├─ 🔍 Solicitud: "Busco apto en La Estrella, 2 hab..."
├─ 🏠 Propiedad: Apartamento en La Estrella - $430M
├─ 👤 Comprador: Juan Pérez
├─ 👤 Vendedor: María López
├─ 📊 Estado: Seleccionado
└─ 🔔 Notificación enviada ✅
    [Ver Detalles] [Actualizar Estado]

[Lista de más matches...]

Estados: Seleccionado | Contactado | Visita_Agendada |
         Negociacion | Cerrado | Descartado
```

---

### Tecnología del Dashboard

**Stack Técnico Propuesto:**

```
Frontend:
├── React.js / Next.js
├── TailwindCSS / Material-UI
├── Chart.js / Recharts (gráficos)
├── React Table (tablas)
└── Axios (API calls)

Backend:
├── Python (Flask/FastAPI)
├── PostgreSQL (misma DB)
└── JWT (autenticación)

Hosting:
├── Frontend: Vercel / Netlify
├── Backend: Railway / Render
└── Base de Datos: Neon (actual)
```

---

## 💼 Casos de Uso Reales

### Caso 1: Agente Nuevo se Une al Sistema

```
Día 1 - Martes 10:00 AM
👤 María López (Agente Nueva)
   │
   ├─ Administrador la agrega al sistema (Dashboard)
   │   • Teléfono: +573001234567
   │   • Nombre: María López
   │   • Email: maria.lopez@bancolombia.com
   │
   ├─ Sistema envía mensaje de bienvenida:
   │
   📱 Cupido → María
      "¡Hola María! 👋

      Bienvenida a Cupido, tu asistente inteligente
      inmobiliario.

      Puedes:
      • Captar propiedades enviando links de Wasi
      • Buscar propiedades con lenguaje natural
      • Recibir matches automáticos

      ¿Necesitas ayuda? Escribe 'ayuda'"
   │
   └─ María está lista para usar Cupido
```

---

### Caso 2: Agente Capta Múltiples Propiedades

```
Día 2 - Miércoles 2:00 PM
👤 María López
   │
   ├─ En grupo Cupido, envía:
   │   https://info.wasi.co/apartamento-laureles/123456
   │
   ├─ Cupido procesa y confirma por privado
   │
   ├─ 10 minutos después, María envía:
   │   https://info.wasi.co/casa-envigado/789012
   │
   ├─ Cupido procesa y confirma por privado
   │
   └─ María ahora tiene 2 propiedades en el sistema

📊 Dashboard actualiza:
   • Total propiedades: 322 (+2)
   • Propiedades María: 2
   • Estado: Disponibles para otros agentes
```

---

### Caso 3: Agente Busca y Encuentra Propiedad de Otro Agente

```
Día 3 - Jueves 11:30 AM
👤 Juan Pérez (Comprador)
   │
   ├─ En grupo Cupido escribe:
   │   "Busco apto en Laureles, 2 hab,
   │    hasta 500 millones, con parqueadero"
   │
   ▼
🤖 Cupido procesa (por privado a Juan):
   │
   ├─ Encuentra 5 propiedades, incluyendo:
   │   • OPCIÓN 2: Apto en Laureles captado por María
   │     $450M, 2 hab, 1 parqueadero
   │
   └─ Juan responde: "2"

🤖 Cupido responde a Juan:
   "✅ Te envié contacto de María López
    📱 +573001234567"

🤖 Cupido notifica a María:
   "🎯 ¡Buenas noticias!
    Juan Pérez está interesado en tu propiedad
    📱 +573123456789"

📊 Sistema registra:
   • Match entre Juan y María
   • Propiedad: 123456
   • Timestamp: 2025-11-06 11:32:00
   • Estado: Seleccionado
```

---

### Caso 4: Match con Propiedad Pulppo

```
Día 4 - Viernes 4:00 PM
👤 Carlos Ruiz
   │
   ├─ Busca directamente con Cupido (privado):
   │   "Casa en Envigado, 3 habitaciones,
   │    piscina, hasta 900 millones"
   │
   ▼
🤖 Cupido procesa:
   │
   ├─ Encuentra 4 propiedades:
   │   • OPCIÓN 1: Casa Envigado - Pulppo ⭐
   │     $850M, 3 hab, piscina, 180m²
   │     Score: 58 pts (incluye bonus Pulppo)
   │
   │   • OPCIÓN 2: Casa Envigado - Wasi_Captado
   │     $880M, 4 hab, piscina, 200m²
   │     Score: 45 pts
   │
   └─ Carlos responde: "1"

🤖 Cupido responde:
   "✅ Información de contacto:

    🏠 Casa en Envigado
    💰 $850,000,000

    📞 Contactar a: Pulppo
    📱 +573183351733

    (Inventario Pulppo)"

📊 Sistema registra:
   • Match con propiedad Pulppo
   • NO se envía notificación (es Pulppo)
   • Métrica: Rotación Pulppo +1
```

---

### Caso 5: Seguimiento desde Dashboard

```
Día 5 - Lunes 9:00 AM
👨‍💼 Gerente de Pulppo
   │
   └─ Accede al Dashboard

📊 Ve en Panel de Analítica:
   │
   ├─ Últimos 7 días:
   │   • 45 solicitudes nuevas
   │   • 28 matches logrados
   │   • Tasa de match: 62%
   │
   ├─ Top 3 Agentes:
   │   1. María López - 8 captaciones, 3 matches
   │   2. Juan Pérez - 6 solicitudes, 4 matches
   │   3. Carlos Ruiz - 5 solicitudes, 2 matches
   │
   └─ Rotación de Inventario:
       • Pulppo: 7.2 días promedio ✅
       • Wasi_Captado: 14.5 días promedio

📈 Insights:
   "💡 Demanda de apartamentos 2 hab en Laureles
    aumentó 35% esta semana. Sugerencia:
    Ampliar inventario en esta zona."

👨‍💼 Gerente toma acción:
   └─ Solicita a equipo Pulppo priorizar
      captación en Laureles
```

---

## 🚀 Próximos Pasos

### Fase 1: Demo y Validación (Actual) ✅
- ✅ Sistema funcional con WhatsApp
- ✅ Búsqueda inteligente con IA
- ✅ Captación de propiedades
- ✅ Trazabilidad completa en DB
- ✅ Demo con propiedades hardcodeadas

### Fase 2: Integración Pulppo (Próxima)
- 🔄 Integración con API de Pulppo
- 🔄 Sincronización automática de inventario
- 🔄 Webhooks en tiempo real
- 🔄 Contactos dinámicos por propiedad

### Fase 3: Dashboard Analítico
- 🔄 Desarrollo de UI web
- 🔄 Panel de inventario
- 🔄 Gestión de agentes
- 🔄 Visualización de métricas
- 🔄 Inteligencia de mercado

### Fase 4: Optimización y Escalado
- 🔄 Machine Learning para mejor matching
- 🔄 Predicción de demanda
- 🔄 Recomendaciones automáticas
- 🔄 Integración con múltiples fuentes
- 🔄 App móvil nativa (opcional)

---

## 📞 Soporte y Contacto

Para dudas, sugerencias o soporte técnico:

- **Email**: soporte@cupido.pulppo.com
- **WhatsApp**: +573183351733
- **Documentación**: [docs.cupido.pulppo.com](https://docs.cupido.pulppo.com)

---

**🎯 Proyecto Cupido** - Conectando compradores con vendedores de forma inteligente.

*Desarrollado por Pulppo para Bancolombia* 🏦✨
