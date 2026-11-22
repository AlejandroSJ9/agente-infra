# Teorema CAP (infografía 2/3)

Pregunta guía: ¿qué ocurre cuando la red se divide?

## C – Consistencia

Cada lectura ve el último valor confirmado o falla.

## A – Disponibilidad

Todo nodo operativo responde, aunque el dato pueda estar atrasado.

## P – Tolerancia a particiones

El sistema opera pese a la pérdida o el retraso de mensajes entre nodos.

## Durante una partición

Se prioriza C o A según la operación o el servicio.

- CP: protege invariantes. Puede bloquear, rechazar o poner en espera.
- AP: mantiene la respuesta. Puede aceptar divergencia y reconciliar después.

## Advertencia

CAP no significa escoger siempre dos de tres. La partición no es una elección: es una falla que el diseño debe soportar.
