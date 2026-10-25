# Modelos externos: Claude y ChatGPT para las consultas complejas

Los agentes trabajan con el modelo local. Para las consultas más complejas pueden apoyarse en **Claude** (Anthropic) o **ChatGPT** (OpenAI),
pero solo mientras Dirección los tenga **conectados** en el panel. Por defecto están desconectados.

## Cómo se usa

1. **Poner la clave** (una vez por modelo, en el servidor; la clave no se escribe en ningún chat):
   ```bash
   python3 scripts/modelos_activar.py claude      # clave de console.anthropic.com
   python3 scripts/modelos_activar.py chatgpt     # clave de platform.openai.com
   docker compose up -d --force-recreate --no-deps api worker beat
   ```
   El script comprueba la clave (sin gastar ni enviar datos) y solo la guarda si funciona. Va al `.env`, que no se sube a git.
2. **Conectar** desde el panel: **Agentes → Modelos externos**. Cada modelo tiene su interruptor, un botón **Probar** (una pregunta sin datos de nadie)
   y el uso de hoy. Solo el rol `direccion` puede cambiarlos; cada cambio queda en `registro_acciones` (quién y cuándo).
3. Desconectar es inmediato: la siguiente consulta ya va al modelo local.

## Cuándo se consulta a un modelo externo

- La petición es **compleja**: un texto largo (600 caracteres o más) o que pide analizar, comparar, redactar, evaluar, una estrategia, un informe…
  (`config/modelos_externos.yaml`, sección `complejidad`).
- O el modelo local no ha dado una respuesta válida ni subiendo al modelo principal (último recurso).
- Se pregunta primero a Claude y, si no está conectado o falla, a ChatGPT; si ninguno responde, sigue el modelo local. Nunca se queda sin respuesta por esto.

## Qué sale a la nube y qué no

- **Solo agentes de sensibilidad baja o media** (`sensibilidad_maxima`). Los de sensibilidad alta (RR.HH., económico, legal…) no los usan nunca.
- **Todo pasa por la anonimización local** (la misma que Jev, `config/anonimizacion.yaml`): nombres, DNI/CIF, IBAN, correos, teléfonos, clientes y
  proveedores del ERP… se sustituyen por etiquetas (`[PERSONA_1]`). Si algo no se puede garantizar (categoría especial del RGPD, texto de más de 4.000 caracteres,
  ERP sin poder leerse), **no sale nada** y decide el modelo local.
- La respuesta vuelve con las etiquetas sustituidas por los datos reales. Esa tabla de equivalencias vive **solo en memoria** durante la consulta: no se guarda,
  no se registra en Langfuse y no sale del servidor.
- **Tope diario** por modelo (`limite_diario`, 200 llamadas): al llegar, vuelve al modelo local hasta el día siguiente.
- Todo lo que propone el modelo externo sigue las mismas reglas que lo del modelo local: las acciones que salen de la empresa piden tu firma.

## Qué no está resuelto

- **Contrato de encargado de tratamiento** con Anthropic y con OpenAI, retención cero y transferencias internacionales (RGPD): hay que validarlo con vuestro asesor
  antes de conectarlos con datos reales. La anonimización reduce el riesgo; no sustituye al contrato (`docs/SEGURIDAD.md`).
- Las etiquetas de modelo de `config/modelos_externos.yaml` (`claude-opus-5-5`, `gpt-5`) hay que comprobarlas en cada proveedor; se cambian con `CLAUDE_MODELO` y
  `CHATGPT_MODELO` en el `.env` sin tocar el código.
- La calidad de la anonimización con casos reales (ver `docs/PENDIENTES.md`).
