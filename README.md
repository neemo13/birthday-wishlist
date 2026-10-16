# 21st Birthday Wishlist 🎀

A private, pink-and-cream gift registry built for one family using **Python, Streamlit, and Supabase (PostgreSQL + Storage)**.

The application combines a shopping-style wishlist with family-specific access, gift claims, and an admin interface.

## Features

- **Authentication:** Separate Birthday Girl and Gift Giver login flows.
- **Family profiles:** Select from four editable family names.
- **Wishlist:** Search, category filters, budget and availability filters, sorting, product details, and retailer links.
- **Gift claims:** PIN-protected claims and releases, with controls to prevent multiple active claims for the same gift.
- **Dad Only page:** A separately protected private message page.
- **Admin Studio:** Manage products, images, categories, website content, family names, credentials, claims, and activity logs.
- **Responsive interface:** Pink-and-cream styling with a product-card layout designed for desktop and mobile.

## Tech Stack

| Layer | Technologies |
|---|---|
| Frontend and application | Streamlit, Python |
| Database | Supabase PostgreSQL |
| Backend operations | PostgreSQL functions and `supabase-py` |
| Authentication security | bcrypt, SHA-256 session-token hashing |
| Image storage | Private Supabase Storage bucket and signed URLs |
| Testing | pytest, PostgreSQL integration tests, Playwright |
| CI | GitHub Actions |

## Architecture

The Streamlit application handles the interface and routes user actions through Python service modules. Database operations use PostgreSQL functions that validate sessions and permissions before modifying protected data.

```text
User
  |
  v
Streamlit application (app.py)
  |
  v
Views and Python service modules
  |
  v
Supabase RPC / PostgreSQL functions
  |
  +--> PostgreSQL tables
  |
  +--> Private image storage
```

The Supabase service key stays on the server and must never be exposed to the browser or committed to source control.

## Security and Data Integrity

- Passwords and PINs are stored as bcrypt hashes.
- Sessions use random tokens, with only their SHA-256 hashes stored in the database.
- Sensitive database operations validate the session and authorization in PostgreSQL.
- Rate limits help protect login credentials and gift claims against repeated guessing.
- Database constraints protect important data relationships and prevent multiple active claims for one gift.
- Product images are stored in a private bucket and accessed using signed URLs.

## Project Structure

```text
app.py
views/                  Streamlit pages
wishlist/               Authentication, services, validation and database access
sql/                    Database schema, functions and security migrations
tests/                  Unit and integration tests
e2e/                    Browser-based tests
scripts/                Credential setup and configuration checks
.github/workflows/      CI workflow
requirements.txt        Application dependencies
requirements-dev.txt    Development and testing dependencies
requirements-e2e.txt   Browser-testing dependencies
```

## Local Setup

1. Create and activate a Python virtual environment.
2. Install the application dependencies.
3. Configure Supabase credentials in `.streamlit/secrets.toml`.
4. Run the SQL migrations in the documented order in the Supabase SQL Editor.
5. Configure the initial admin and family credentials.
6. Start the application.

```bash
pip install -r requirements.txt
streamlit run app.py
```

Keep `.streamlit/secrets.toml` private. Never commit real credentials, API keys, or service-role keys.

## Testing

Install the development dependencies:

```bash
pip install -r requirements-dev.txt
pytest -q
```

Some database integration tests require a separate local PostgreSQL test database. Browser tests use the additional dependencies in `requirements-e2e.txt`.

## Limitations

- The application is designed for a small family audience, not high-scale public traffic.
- Shared family credentials do not provide the same identity assurance as individual user accounts.
- Signed image URLs are temporary bearer links.
- External retailer links are not automatically checked for availability.
- The application has not been load-tested for large audiences.

## Future Improvements

- Deploy the application with managed secrets and HTTPS.
- Expand automated browser and deployment tests.
- Improve monitoring and operational error reporting.
- Evaluate stronger individual authentication if the application grows.

---

**Built with Python, Streamlit, and Supabase.**
