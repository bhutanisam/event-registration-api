import threading
from datetime import datetime, timedelta

from app import auth, services
from app.database import SessionLocal
from app.models import Event, User
from .conftest import auth_header, make_user

EVENT = {"title": "AWS Workshop", "date": "2026-12-01T10:00:00", "capacity": 2}


def test_member_cannot_create_event_but_admin_can(client):
    admin = make_user(client, "admin@x.com")     # first user = admin
    member = make_user(client, "member@x.com")

    r1 = client.post("/events", json=EVENT, headers=auth_header(member))
    r2 = client.post("/events", json=EVENT, headers=auth_header(admin))
    assert r1.status_code == 403
    assert r2.status_code == 201


def test_cannot_register_twice_and_count_stays_correct(client):
    admin = make_user(client, "admin@x.com")
    event_id = client.post("/events", json=EVENT, headers=auth_header(admin)).json()["id"]

    first = client.post(f"/events/{event_id}/register", headers=auth_header(admin))
    second = client.post(f"/events/{event_id}/register", headers=auth_header(admin))
    assert first.status_code == 201
    assert second.status_code == 409

    events = client.get("/events", headers=auth_header(admin)).json()["items"]
    assert events[0]["registered"] == 1   # the failed attempt did not bump the counter


def test_event_full_returns_409(client):
    admin = make_user(client, "admin@x.com")
    event_id = client.post("/events", json=EVENT, headers=auth_header(admin)).json()["id"]  # capacity 2
    codes = []
    for i in range(3):
        tokens = make_user(client, f"u{i}@x.com")
        codes.append(client.post(f"/events/{event_id}/register", headers=auth_header(tokens)).status_code)
    assert codes == [201, 201, 409]


def test_concurrent_registrations_never_exceed_capacity(client):
    """20 users try to grab 5 seats at the same time. Exactly 5 must succeed."""
    db = SessionLocal()
    event = Event(title="Hot event", date=datetime.now() + timedelta(days=1), capacity=5)
    db.add(event)
    db.add_all([User(email=f"u{i}@x.com", password_hash="x") for i in range(20)])
    db.commit()
    event_id = event.id
    user_ids = [u.id for u in db.query(User).all()]
    db.close()

    results = []

    def worker(uid):
        session = SessionLocal()          # each thread = its own DB session
        try:
            services.register_for_event(session, uid, event_id)
            results.append("ok")
        except services.EventFull:
            results.append("full")
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(uid,)) for uid in user_ids]
    for t in threads: t.start()
    for t in threads: t.join()

    db = SessionLocal()
    assert results.count("ok") == 5
    assert db.get(Event, event_id).registered_count == 5
    db.close()


def test_refresh_token_flow_and_expired_access_token(client):
    tokens = make_user(client, "admin@x.com")

    # an already-expired access token must be rejected
    db = SessionLocal()
    user = db.query(User).first()
    expired = auth.create_access_token(user, minutes=-1)
    db.close()
    r = client.get("/events", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401

    # refresh token gives a new pair; the old refresh token can't be reused
    new = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert new.status_code == 200
    reuse = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reuse.status_code == 401


def test_pagination_and_filtering(client):
    admin = make_user(client, "admin@x.com")
    for i in range(7):
        client.post("/events", json={**EVENT, "title": f"Event {i}"}, headers=auth_header(admin))
    client.post("/events", json={**EVENT, "title": "Hackathon"}, headers=auth_header(admin))

    page2 = client.get("/events?page=2&page_size=3", headers=auth_header(admin)).json()
    assert page2["total"] == 8 and len(page2["items"]) == 3

    found = client.get("/events?q=hack", headers=auth_header(admin)).json()
    assert found["total"] == 1
