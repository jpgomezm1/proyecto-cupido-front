# 🚀 Inicio Rápido - Sistema de Búsqueda Inteligente

Guía rápida para empezar a usar el sistema de búsqueda en **3 minutos**.

---

## ⚡ Pasos Rápidos

### 1. Obtener API Key de Anthropic (2 min)

1. Ve a https://console.anthropic.com/
2. Crea cuenta o inicia sesión
3. Click en **API Keys** en el menú izquierdo
4. Click en **Create Key**
5. Copia la clave que empieza con `sk-ant-api03-...`

---

### 2. Configurar `.env` (30 seg)

Abre el archivo `.env` y agrega:

```env
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxxxxx
```

**Importante**: Reemplaza `xxxxxxxxxxxxxxxxxxxxx` con tu clave real.

---

### 3. Instalar Anthropic SDK (30 seg)

```powershell
pip install anthropic
```

---

### 4. Verificar Configuración (10 seg)

```powershell
python verificar_busqueda.py
```

Deberías ver:

```
✅ SISTEMA COMPLETAMENTE CONFIGURADO

🚀 Listo para usar!
```

Si ves errores, el script te dirá qué falta.

---

### 5. Probar el Sistema (30 seg)

```powershell
python ejemplo_busqueda.py
```

Verás resultados como:

```
🏠 PROPIEDADES ENCONTRADAS
==================================================

📋 Criterios de búsqueda:
   📍 Ubicación: Laureles, El Poblado
   🏢 Tipo: Apartamento
   💰 Hasta: $800M

✅ 8 propiedades coinciden

━━━ #1 - Match: 42 pts ━━━
🏠 Apartamento en Laureles - 95m²
💵 $520,000,000 COP
...
```

---

## 🎯 Usar en tu Código

```python
from busqueda_propiedades import PropertySearchAgent

# Crear agente
agent = PropertySearchAgent()

# Tu consulta
consulta = """
Busco apartamento en Laureles
Hasta 800 millones
2 habitaciones
Con piscina
"""

# Buscar
resultados = agent.search(consulta, limit=10)

# Formatear para WhatsApp
mensaje = agent.format_results_for_agent(resultados)

print(mensaje)
```

---

## 📝 Ejemplos de Consultas

El sistema entiende mensajes como estos:

```
Busco apto en Laureles o El Poblado
Hasta 1000 millones
3 habitaciones
Con gimnasio y piscina
```

```
Necesito casa urgente en Envigado
Máximo $1.5 billones
4 habitaciones
Parqueadero para 2 carros
```

```
Cliente busca penthouse en zona exclusiva
Presupuesto flexible hasta $2B
Vista panorámica
Balcón grande
```

---

## 💰 Costos

- **~$0.003 USD por búsqueda** (3 centavos cada 10 búsquedas)
- Modelo usado: `claude-3-5-sonnet-20241022`
- Costo estimado mensual (1000 búsquedas): **~$3 USD**

---

## 🔧 Solución Rápida de Problemas

### Error: `ANTHROPIC_API_KEY no configurada`

→ Verifica que agregaste la clave en `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
```

---

### Error: `Módulo 'anthropic' no instalado`

→ Instala:

```powershell
pip install anthropic
```

---

### No encuentra propiedades

→ Asegúrate de tener propiedades en la DB:

```powershell
python cargar_pulppo_auto.py
```

Esto cargará 20 propiedades de prueba.

---

## 📚 Documentación Completa

- **Guía completa**: `README_BUSQUEDA_INTELIGENTE.md`
- **Código fuente**: `busqueda_propiedades.py`
- **Ejemplo simple**: `ejemplo_busqueda.py`

---

## ✅ Checklist

- [ ] Obtuve mi API key de Anthropic
- [ ] Agregué `ANTHROPIC_API_KEY` al archivo `.env`
- [ ] Instalé `pip install anthropic`
- [ ] Ejecuté `python verificar_busqueda.py` sin errores
- [ ] Probé `python ejemplo_busqueda.py` con éxito

---

## 🎉 ¡Listo!

Si completaste el checklist, **el sistema está funcionando**.

**Siguiente paso**: Integra el agente en tu aplicación, bot de WhatsApp, o API.

---

**¿Dudas?** Consulta `README_BUSQUEDA_INTELIGENTE.md` para documentación completa.
