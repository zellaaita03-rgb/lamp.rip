# lamp.rip - Modern Shared Calendar & Wishlist App

## Setup Instructions

1. Install dependencies:
   ```bash
   pip install flask flask-login flask-sqlalchemy flask-wtf wtforms email_validator beautifulsoup4 requests
   ```

2. Run the application:
   ```bash
   python app.py
   ```

3. Open http://localhost:5000 in your browser

4. Login with test account:
   - Username: `admin`
   - Password: `admin`

## Features

- **Authentication**: Login/logout with session management
- **Shared Calendar**: All users can view, create, and edit events
- **User Tagging**: Tag other users in events with @username
- **Wishlists**: Add items with URLs (auto-fetches titles), custom titles supported
- **Profile**: Upload portrait, change password
- **Notifications**: Bell icon shows when you have notifications
- **Modern UI**: Dark theme with 2025-2026 aesthetic
