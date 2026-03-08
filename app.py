import os
import sqlite3
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = 'lamp-rip-secret-key-2025'

# Database setup
DB_PATH = os.path.join(os.path.dirname(__file__), 'lamp.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        portrait TEXT DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Events table (shared calendar)
    c.execute('''CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        start_datetime TIMESTAMP NOT NULL,
        end_datetime TIMESTAMP,
        created_by INTEGER NOT NULL,
        tagged_users TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (created_by) REFERENCES users(id)
    )''')
    
    # Wishlist items table
    c.execute('''CREATE TABLE IF NOT EXISTS wishlist_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    
    # Notifications table
    c.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        event_id INTEGER,
        is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (event_id) REFERENCES events(id)
    )''')
    
    # Create default admin user if not exists
    c.execute("SELECT * FROM users WHERE username = 'admin'")
    if not c.fetchone():
        hashed_pw = generate_password_hash('admin')
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", ('admin', hashed_pw))
        print("Created default admin user: admin/admin")
    
    conn.commit()
    conn.close()

# Initialize database
init_db()

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, portrait=None):
        self.id = id
        self.username = username
        self.portrait = portrait

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(user['id'], user['username'], user['portrait'])
    return None

# Configure file uploads
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Utility to fetch title from URL
def fetch_url_title(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        title = soup.title.string if soup.title else None
        if title:
            return title.strip()
    except:
        pass
    return None

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('calendar'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            login_user(User(user['id'], user['username'], user['portrait']))
            return redirect(url_for('calendar'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('Username and password required', 'error')
            return redirect(url_for('register'))
        
        conn = get_db()
        c = conn.cursor()
        
        try:
            hashed_pw = generate_password_hash(password)
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_pw))
            conn.commit()
            flash('Account created! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already exists', 'error')
        finally:
            conn.close()
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/calendar')
@login_required
def calendar():
    conn = get_db()
    
    # Get all events
    c = conn.cursor()
    c.execute('''SELECT e.*, u.username as creator_name 
                 FROM events e 
                 JOIN users u ON e.created_by = u.id 
                 ORDER BY e.start_datetime''')
    events = c.fetchall()
    
    # Get all users for tagging
    c.execute("SELECT id, username FROM users")
    users = c.fetchall()
    
    # Get notifications count
    c.execute("SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND is_read = 0", (current_user.id,))
    notif_count = c.fetchone()['count']
    
    conn.close()
    
    return render_template('calendar.html', events=events, users=users, notif_count=notif_count)

@app.route('/add_event', methods=['POST'])
@login_required
def add_event():
    title = request.form.get('title')
    description = request.form.get('description')
    start_date = request.form.get('start_date')
    start_time = request.form.get('start_time')
    end_date = request.form.get('end_date')
    end_time = request.form.get('end_time')
    tagged_users = request.form.getlist('tagged_users')
    
    if not title or not start_date or not start_time:
        flash('Title, date and time are required', 'error')
        return redirect(url_for('calendar'))
    
    start_datetime = f"{start_date} {start_time}"
    end_datetime = f"{end_date} {end_time}" if end_date and end_time else None
    
    tagged_users_str = ','.join(tagged_users) if tagged_users else ''
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO events (title, description, start_datetime, end_datetime, created_by, tagged_users)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (title, description, start_datetime, end_datetime, current_user.id, tagged_users_str))
    conn.commit()
    
    # Create notifications for tagged users
    if tagged_users:
        for user_id in tagged_users:
            c.execute("INSERT INTO notifications (user_id, message) VALUES (?, ?)",
                      (user_id, f"You were tagged in event: {title}"))
        conn.commit()
    
    conn.close()
    flash('Event created!', 'success')
    return redirect(url_for('calendar'))

@app.route('/edit_event/<int:event_id>', methods=['POST'])
@login_required
def edit_event(event_id):
    title = request.form.get('title')
    description = request.form.get('description')
    start_date = request.form.get('start_date')
    start_time = request.form.get('start_time')
    end_date = request.form.get('end_date')
    end_time = request.form.get('end_time')
    tagged_users = request.form.getlist('tagged_users')
    
    start_datetime = f"{start_date} {start_time}"
    end_datetime = f"{end_date} {end_time}" if end_date and end_time else None
    tagged_users_str = ','.join(tagged_users) if tagged_users else ''
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''UPDATE events 
                 SET title = ?, description = ?, start_datetime = ?, end_datetime = ?, tagged_users = ?
                 WHERE id = ?''',
              (title, description, start_datetime, end_datetime, tagged_users_str, event_id))
    conn.commit()
    conn.close()
    
    flash('Event updated!', 'success')
    return redirect(url_for('calendar'))

@app.route('/delete_event/<int:event_id>')
@login_required
def delete_event(event_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM events WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()
    flash('Event deleted!', 'success')
    return redirect(url_for('calendar'))

@app.route('/wishlist')
@login_required
def wishlist():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM wishlist_items WHERE user_id = ? ORDER BY created_at DESC", (current_user.id,))
    items = c.fetchall()
    
    # Get notifications count
    c.execute("SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND is_read = 0", (current_user.id,))
    notif_count = c.fetchone()['count']
    
    conn.close()
    return render_template('wishlist.html', items=items, notif_count=notif_count)

@app.route('/add_wishlist_item', methods=['POST'])
@login_required
def add_wishlist_item():
    url = request.form.get('url')
    custom_title = request.form.get('custom_title')
    
    if not custom_title and url:
        # Try to fetch title from URL
        custom_title = fetch_url_title(url)
    
    if not custom_title:
        custom_title = "Untitled Item"
    
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO wishlist_items (user_id, title, url) VALUES (?, ?, ?)",
              (current_user.id, custom_title, url))
    conn.commit()
    conn.close()
    
    flash('Item added to wishlist!', 'success')
    return redirect(url_for('wishlist'))

@app.route('/delete_wishlist_item/<int:item_id>')
@login_required
def delete_wishlist_item(item_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM wishlist_items WHERE id = ? AND user_id = ?", (item_id, current_user.id))
    conn.commit()
    conn.close()
    flash('Item removed from wishlist!', 'success')
    return redirect(url_for('wishlist'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    conn = get_db()
    c = conn.cursor()
    
    # Get notifications count
    c.execute("SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND is_read = 0", (current_user.id,))
    notif_count = c.fetchone()['count']
    
    if request.method == 'POST':
        # Handle password change
        if 'current_password' in request.form:
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            
            c.execute("SELECT password FROM users WHERE id = ?", (current_user.id,))
            user = c.fetchone()
            
            if user and check_password_hash(user['password'], current_password):
                hashed_pw = generate_password_hash(new_password)
                c.execute("UPDATE users SET password = ? WHERE id = ?", (hashed_pw, current_user.id))
                conn.commit()
                flash('Password changed successfully!', 'success')
            else:
                flash('Current password is incorrect', 'error')
        
        # Handle portrait upload
        if 'portrait' in request.files:
            file = request.files['portrait']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"user_{current_user.id}_{datetime.now().timestamp()}.{file.filename.rsplit('.', 1)[1].lower()}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                
                # Update user portrait path
                c.execute("UPDATE users SET portrait = ? WHERE id = ?", (f"uploads/{filename}", current_user.id))
                conn.commit()
                flash('Portrait updated!', 'success')
                # Reload user
                current_user.portrait = f"uploads/{filename}"
    
    conn.close()
    return render_template('profile.html', notif_count=notif_count)

@app.route('/notifications')
@login_required
def notifications():
    conn = get_db()
    c = conn.cursor()
    
    # Get notifications
    c.execute("""SELECT n.*, e.title as event_title 
                FROM notifications n 
                LEFT JOIN events e ON n.event_id = e.id
                WHERE n.user_id = ? 
                ORDER BY n.created_at DESC""", (current_user.id,))
    notifications = c.fetchall()
    
    # Mark all as read
    c.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (current_user.id,))
    conn.commit()
    
    notif_count = 0
    
    conn.close()
    return render_template('notifications.html', notifications=notifications, notif_count=notif_count)

@app.route('/get_notif_count')
@login_required
def get_notif_count():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND is_read = 0", (current_user.id,))
    count = c.fetchone()['count']
    conn.close()
    return jsonify({'count': count})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
