from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Event, Registration


class EventFull(Exception):
    pass


class AlreadyRegistered(Exception):
    pass


def register_for_event(db: Session, user_id: int, event_id: int) -> Registration:
    """
    The concurrency-sensitive part.

    WRONG way (race condition):
        event = get event
        if event.registered_count < event.capacity:   # two requests can both pass this check
            event.registered_count += 1

    RIGHT way: let the DATABASE do check + increment in ONE atomic statement.
    The DB locks the row while updating, so two requests are handled one after another.
    The second one sees the updated count, the WHERE fails, and 0 rows are updated.
    """
    result = db.execute(
        update(Event)
        .where(Event.id == event_id, Event.registered_count < Event.capacity)
        .values(registered_count=Event.registered_count + 1)
    )
    if result.rowcount == 0:
        db.rollback()
        if db.get(Event, event_id) is None:
            raise LookupError("Event not found")
        raise EventFull()

    registration = Registration(user_id=user_id, event_id=event_id)
    db.add(registration)
    try:
        db.commit()  # counter increment + registration row saved together (one transaction)
    except IntegrityError:
        db.rollback()  # also undoes the counter increment
        raise AlreadyRegistered()
    return registration


def cancel_registration(db: Session, user_id: int, event_id: int) -> None:
    reg = db.query(Registration).filter_by(user_id=user_id, event_id=event_id).first()
    if reg is None:
        raise LookupError("Registration not found")
    db.delete(reg)
    db.execute(update(Event).where(Event.id == event_id)
               .values(registered_count=Event.registered_count - 1))
    db.commit()
