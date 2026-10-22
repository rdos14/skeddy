# Fase 2: `/list` y menús de items

La fase 2 añade menús seguros sobre las filas existentes de `reminders`. No
reinterpreta ni repara filas históricas y no modifica columnas existentes.
`Database.create_all()` crea únicamente las tablas nuevas cuando faltan.

## APIs de control

Todas las operaciones reciben `user_id` y rechazan una fila de otro usuario.
Se usan con una sesión SQLAlchemy abierta; el caller debe hacer `commit()`.

```python
items = ItemRepository(session)

# Lectura/listado paginado; completed=True muestra solo status=completed.
state = await items.create_item_state(user_id, reminder_id, "reminder")
state = await items.read_item_state(user_id, reminder_id)
rows = await items.list_item_state(
    user_id, completed=False, offset=page * 10, limit=10
)
total = await items.count_items(user_id, completed=False)

# Mutaciones explícitas (cada una hace flush, no commit).
state = await items.complete(user_id, reminder_id, scheduler=scheduler)
state = await items.delete(user_id, reminder_id, scheduler=scheduler)
state = await items.change_type(user_id, reminder_id, "reminder|task|note")

# Add time agrega un AdditionalEvent al mismo reminder; nunca reemplaza
# schedule_spec ni crea otra Reminder.
result = await items.add_time(
    user_id, reminder_id, "23/10/2026 10:30",
    now=now, scheduler=scheduler, timezone=owner_timezone,
)
# Si falta la hora: result.status == "missing_time" y queda MenuDraft.
result = await items.add_time_clock(
    user_id, reminder_id, "10:30 AM",
    now=now, scheduler=scheduler, timezone=owner_timezone,
)

# APIs de eventos durables y draft de UI.
events = await items.add_time_events(user_id, reminder_id, [due_a, due_b])
draft = await items.get_menu_draft(user_id)
await items.delete_menu_drafts(user_id)
```

`AddTimeResult.status` puede ser `added`, `duplicate`, `missing_time`,
`invalid`, `past`, `awaiting_input`, `note_requires_type`,
`reopen_required` o `not_found`. El draft tiene TTL de 24 horas; `/cancel` y
el botón/teclado `Cancel` eliminan todos los drafts de fase 1 y de menú. Una
fecha recibida sin reloj se conserva literalmente y se completa solo mediante
`combine_pending_date`, sin crear job antes de la hora. Add time acepta las
expresiones temporales completas del parser de fase 1 (`today at 19`,
`tomorrow at 9`, `in 5 minutes` y fechas numéricas), pero rechaza cualquier
payload de título: no convierte texto pegado en un Reminder nuevo.

El registro de jobs es explícito y separado del job primario:

```python
scheduler.register(reminder, owner_timezone)
scheduler.register_extras(reminder, events, owner_timezone)
scheduler.cancel_all(reminder_id)
await scheduler._reload_all()  # reconstruye primary y extra:* desde SQLite
```

Jobs primarios usan `rem:<reminder_id>` y extras usan `extra:<event_id>`.
`_fire` y `_fire_extra` vuelven a comprobar owner, status, tipo y
`AdditionalEvent.active` antes de enviar. `Reminder.active` solo representa
la alarma primaria; los extras pueden seguir activos cuando vale `False`.
Completar, borrar o convertir a Note invalida jobs antiguos. Las
notificaciones no llevan keyboard ni IDs de item.

## Handlers y callbacks

`get_routers()` sigue exponiendo el router `reminders`. El middleware inyecta
`items: ItemRepository` además de los repositorios de fase 1.

- `cmd_list(message, reminders, items=None)` muestra 10 items por página,
  números `1..N`, fechas `DD/MM/YYYY`, `Choose a number to open` y Show
  completed.
- `show_item_detail(callback, callback_data, items)` abre el item únicamente
  dentro del owner del callback.
- `complete_item`, `add_time_item`, `set_item_type`, `delete_item` y
  `confirm_delete_item` son callbacks separados. Delete siempre presenta
  confirmación y Cancel vuelve al detalle.
- `create_reminder(..., pending=None, pending_batches=None, items=None)`
  procesa primero el draft persistente de Add time; así una respuesta de menú
  no se convierte accidentalmente en Reminder nuevo.

`ItemCB` mantiene payloads cortos (acción, id, página y tipo) y todos los
handlers consultan el owner del callback. `ReminderCB` antiguo permanece
parseable; un ID inexistente o ajeno solo responde `not found`.

## Tipos

- **Reminder:** una alarma one-shot se retira después de disparar. Su
  `ItemState` comienza en `pending`; después del primary queda visible en
  `pending` aunque `Reminder.active=False`. Si se añadieron extras, pasa a
  `retired` únicamente cuando ya no quedan extras activos, y nunca pasa a
  `completed` por una entrega.
- **Task:** permanece `pending` tras la entrega y su primary queda inactivo
  para impedir duplicados tras reinicio; el usuario debe Complete.
- **Note:** no tiene notificaciones; convertir a Note cancela el primary y
  todos los extras. Convertir Note a Reminder/Task no inventa una hora futura;
  si no hay alarma activa, el detalle muestra `No active alarm` y Add time la
  añade explícitamente.

Los estados explícitos son `pending`, `completed`, `deleted` y `retired`.
Solo Complete escribe `status=completed`; Reopen solo cambia
`completed -> pending` y no reactiva horarios consumidos. `deleted` es final:
las callbacks antiguas de Complete/Change type/Add time no lo reaniman.
`Reminder.active=False` de legacy puede significar entrega, borrado o fallo y
nunca aparece en Show completed por inferencia.

## Tablas aditivas

- `item_states`: tipo, status y `completed_at` explícitos por reminder.
- `additional_events`: avisos adicionales persistentes por item.
- `menu_drafts`: contexto owner/item-scoped de Add time con TTL.

Un rollback al código anterior ignora estas tablas y conserva las filas
originales; las alarmas adicionales quedan suspendidas hasta volver al código
nuevo. No hay `ALTER TABLE`, reparse ni reemplazo automático de base de datos.
