# Project Guide

## Structure
- `backend/main.py` contains the FastAPI API and SQLite data access.
- `backend/warehouse.db` is the persistent local inventory database; do not delete or reset it as part of routine development.
- `frontend/index.html` is a standalone Russian-language interface with no build step. It calls the API at `http://127.0.0.1:8000` by default.

## Backend Development
- Run backend commands from `backend/`.
- Install dependencies with `python -m pip install -r requirements.txt`.
- Start the API with `python -m uvicorn main:app --reload`.
- The application initializes its SQLite schema on startup. Keep database changes compatible with existing local data.

## Conventions
- Keep API handlers, Pydantic request models, and database operations in `backend/main.py` unless the project grows enough to justify splitting them.
- Inventory quantity changes should use the existing `apply_change` helper so the item balance and operation journal stay consistent.
- Inventory rows use a persisted manual order; keep line groups contiguous and allow row reordering only within a line.
- Journal edits intentionally do not modify inventory balances.
- The frontend is plain HTML, CSS, and JavaScript; preserve this no-build setup unless asked to change it.
- The frontend offers four switchable visual themes; preserve theme selection in browser storage and apply themes consistently across Base, Journal, and Print.
- Keep the title and tab navigation in the sticky app header; table coloring must not intercept clicks on interactive controls.
- No automated test suite or frontend package/build configuration is currently present. Run a focused Python syntax check after backend edits and verify changed API behavior when practical.