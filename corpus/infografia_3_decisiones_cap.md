# Decisiones CAP durante una partición (infografía 3/3)

Pregunta guía: ¿cómo elegir el comportamiento por servicio?

## Árbol de decisión

1. ¿Existe pérdida de comunicación entre nodos?
   - No: CAP no decide. Analice latencia y consistencia con PACELC.
   - Sí: continúe con la pregunta 2.
2. ¿La operación protege una invariante que no puede violarse?
   - Sí: elija CP. Bloquear, rechazar o poner en espera.
   - No: continúe con la pregunta 3.
3. ¿El servicio debe seguir respondiendo con datos posiblemente atrasados?
   - Sí: elija AP. Responder, versionar y reconciliar.
   - No: elija CP. Degradar el servicio de forma segura.

## Ejemplos por servicio

- Matrícula (CP): evitar la doble asignación de cupos.
- Identidad (mixta): priorizar las revocaciones y limitar la vigencia.
- Cartelera (AP): disponible aunque un aviso llegue tarde.
- Contenido (AP): servir cachés y copias locales.
- Progreso (AP): guardar localmente y sincronizar.

## Comprobación de una decisión

Toda decisión debe documentar: la decisión, el comportamiento visible para el usuario, el riesgo y la forma de recuperación.
