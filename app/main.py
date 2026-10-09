from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from . import auth, services
from .database import Base, engine, get_db
from .models import Event, Registration, User

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Event Registration API")


# ---------- request bodies ----------
class Credentials(BaseModel):
    email: str
    password: str


class RefreshBody(BaseModel):
    refresh_token: str


class EventIn(BaseModel):
    title: str
    date: datetime
    capacity: int


# ---------- auth ----------
@app.post("/auth/signup", status_code=201)
def signup(body: Credentials, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=body.email).first():
        raise HTTPException(409, "Email already registered")
    # the very first user becomes admin, everyone after is a member
    role = "admin" if db.query(User).count() == 0 else "member"
    user = User(email=body.email, password_hash=auth.hash_password(body.password), role=role)
    db.add(user)
    db.commit()
    return {"id": user.id, "email": user.email, "role": user.role}


def _token_pair(db: Session, user: User):
    return {"access_token": auth.create_access_token(user),
            "refresh_token": auth.create_refresh_token(db, user),
            "token_type": "bearer"}


@app.post("/auth/login")
def login(body: Credentials, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=body.email).first()
    if user is None or not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return _token_pair(db, user)


@app.post("/auth/refresh")
def refresh(body: RefreshBody, db: Session = Depends(get_db)):
    user = auth.use_refresh_token(db, body.refresh_token)
    return _token_pair(db, user)


# ---------- events ----------
@app.get("/events")
def list_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    q: Optional[str] = None,                 # filter: title contains
    available_only: bool = False,            # filter: only events with free seats
    sort: str = "date",                      # sort: "date" or "-date"
    db: Session = Depends(get_db),
    user: User = Depends(auth.get_current_user),
):
    query = select(Event)
    if q:
        query = query.where(Event.title.ilike(f"%{q}%"))
    if available_only:
        query = query.where(Event.registered_count < Event.capacity)
    query = query.order_by(Event.date.desc() if sort == "-date" else Event.date)

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return {"page": page, "page_size": page_size, "total": total,
            "items": [{"id": e.id, "title": e.title, "date": e.date,
                       "capacity": e.capacity, "registered": e.registered_count} for e in items]}


@app.post("/events", status_code=201)
def create_event(body: EventIn, db: Session = Depends(get_db),
                 admin: User = Depends(auth.require_role("admin"))):
    if body.capacity < 1:
        raise HTTPException(400, "Capacity must be at least 1")
    event = Event(title=body.title, date=body.date, capacity=body.capacity)
    db.add(event)
    db.commit()
    return {"id": event.id, "title": event.title}


@app.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, db: Session = Depends(get_db),
                 admin: User = Depends(auth.require_role("admin"))):
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(404, "Event not found")
    db.query(Registration).filter_by(event_id=event_id).delete()
    db.delete(event)
    db.commit()


@app.get("/events/{event_id}/registrations")
def event_registrations(event_id: int, db: Session = Depends(get_db),
                        admin: User = Depends(auth.require_role("admin"))):
    rows = db.query(Registration).filter_by(event_id=event_id).all()
    return [{"user_id": r.user_id, "registered_at": r.created_at} for r in rows]


# ---------- registrations ----------
@app.post("/events/{event_id}/register", status_code=201)
def register(event_id: int, db: Session = Depends(get_db),
             user: User = Depends(auth.get_current_user)):
    try:
        services.register_for_event(db, user.id, event_id)
    except LookupError:
        raise HTTPException(404, "Event not found")
    except services.EventFull:
        raise HTTPException(409, "Event is full")
    except services.AlreadyRegistered:
        raise HTTPException(409, "You are already registered")
    return {"message": "Registered"}


@app.delete("/events/{event_id}/register", status_code=204)
def cancel(event_id: int, db: Session = Depends(get_db),
           user: User = Depends(auth.get_current_user)):
    try:
        services.cancel_registration(db, user.id, event_id)
    except LookupError:
        raise HTTPException(404, "You are not registered for this event")


@app.get("/me/registrations")
def my_registrations(db: Session = Depends(get_db), user: User = Depends(auth.get_current_user)):
    rows = db.query(Registration).filter_by(user_id=user.id).all()
    return [{"event_id": r.event_id, "title": r.event.title} for r in rows]
