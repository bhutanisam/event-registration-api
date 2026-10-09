# Event Registration API

A simple REST API where an admin creates events and members register for them.
Built with Python, FastAPI, SQLAlchemy and SQLite.

## Features
- 3 related tables: `users`, `events`, `registrations` (join table with foreign keys)
- Roles: `admin` (create/delete events, see attendees) and `member` (browse, register, cancel)
- Auth: 15-minute access token (JWT) + 7-day refresh token (stored hashed in DB, single use)
- Concurrency-safe registration: capacity check + seat increment happen in ONE atomic SQL statement
- Pagination, search filter, availability filter and sorting on `GET /events`
- 6 automated tests (including a 20-thread race test)

## Run it
```
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000/docs to try every endpoint in the browser.
The first user who signs up becomes the admin.

## Run tests
```
python -m pytest
```

## Endpoints
| Method | Path | Who |
|---|---|---|
| POST | /auth/signup, /auth/login, /auth/refresh | anyone |
| GET | /events?page=&page_size=&q=&available_only=&sort= | logged in |
| POST | /events | admin |
| DELETE | /events/{id} | admin |
| GET | /events/{id}/registrations | admin |
| POST / DELETE | /events/{id}/register | logged in |
| GET | /me/registrations | logged in |

## How the concurrency problem is solved
A normal `if seats_left: register` check can let two simultaneous requests both pass.
Here the check lives inside the SQL: `UPDATE events SET registered_count = registered_count + 1
WHERE id = ? AND registered_count < capacity`. The database locks the row, so requests are
processed one after another, and if 0 rows are updated the event is full. The seat increment and
the registration row are committed in one transaction, and a UNIQUE(user_id, event_id) constraint
stops duplicate registrations (the transaction rolls back, so the count stays correct).
