const express = require('express');
const session = require('express-session');
const Database = require('better-sqlite3');
const bcrypt = require('bcryptjs');
const cheerio = require('cheerio');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = 5000;

// Database setup
const db = new Database('lamp.db');
db.pragma('journal_mode = WAL');

// Initialize tables
db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    portrait TEXT DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );
  
  CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    start_datetime DATETIME NOT NULL,
    end_datetime DATETIME,
    created_by INTEGER NOT NULL,
    tagged_users TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id)
  );
  
  CREATE TABLE IF NOT EXISTS wishlist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
  );
  
  CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    event_id INTEGER,
    is_read INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (event_id) REFERENCES events(id)
  );
`);

// Create default admin user
const adminExists = db.prepare('SELECT * FROM users WHERE username = ?').get('admin');
if (!adminExists) {
  const hashedPassword = bcrypt.hashSync('admin', 10);
  db.prepare('INSERT INTO users (username, password) VALUES (?, ?)').run('admin', hashedPassword);
  console.log('Created default admin user: admin/admin');
}

// Middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));
app.use(express.static(path.join(__dirname, 'static')));
app.use(session({
  secret: 'lamp-rip-secret-2025',
  resave: false,
  saveUninitialized: false,
  cookie: { secure: false, maxAge: 24 * 60 * 60 * 1000 }
}));

// View engine
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));

// Auth middleware
const requireAuth = (req, res, next) => {
  if (!req.session.userId) {
    return res.redirect('/login');
  }
  next();
};

// Make user available to views
app.use((req, res, next) => {
  if (req.session.userId) {
    const user = db.prepare('SELECT * FROM users WHERE id = ?').get(req.session.userId);
    res.locals.user = user;
    res.locals.notifCount = db.prepare('SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND is_read = 0').get(req.session.userId)?.count || 0;
  } else {
    res.locals.user = null;
    res.locals.notifCount = 0;
  }
  next();
});

// Helper to fetch URL title
async function fetchUrlTitle(url) {
  try {
    const https = require('https');
    return new Promise((resolve) => {
      https.get(url, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          const $ = cheerio.load(data);
          const title = $('title').text();
          resolve(title?.trim() || null);
        });
      }).on('error', () => resolve(null)).setTimeout(5000);
    });
  } catch {
    return null;
  }
}

// Routes
app.get('/', (req, res) => {
  if (req.session.userId) {
    return res.redirect('/calendar');
  }
  res.redirect('/login');
});

app.get('/login', (req, res) => {
  if (req.session.userId) return res.redirect('/calendar');
  res.render('login', { error: null });
});

app.post('/login', (req, res) => {
  const { username, password } = req.body;
  const user = db.prepare('SELECT * FROM users WHERE username = ?').get(username);
  
  if (user && bcrypt.compareSync(password, user.password)) {
    req.session.userId = user.id;
    return res.redirect('/calendar');
  }
  res.render('login', { error: 'Invalid username or password' });
});

app.get('/register', (req, res) => {
  if (req.session.userId) return res.redirect('/calendar');
  res.render('register', { error: null });
});

app.post('/register', (req, res) => {
  const { username, password } = req.body;
  
  try {
    const hashedPassword = bcrypt.hashSync(password, 10);
    db.prepare('INSERT INTO users (username, password) VALUES (?, ?)').run(username, hashedPassword);
    res.redirect('/login');
  } catch (e) {
    res.render('register', { error: 'Username already exists' });
  }
});

app.get('/logout', (req, res) => {
  req.session.destroy();
  res.redirect('/login');
});

app.get('/calendar', requireAuth, (req, res) => {
  const events = db.prepare(`
    SELECT e.*, u.username as creator_name 
    FROM events e 
    JOIN users u ON e.created_by = u.id 
    ORDER BY e.start_datetime
  `).all();
  
  const users = db.prepare('SELECT id, username FROM users').all();
  res.render('calendar', { events, users });
});

app.post('/add_event', requireAuth, (req, res) => {
  const { title, description, start_date, start_time, end_date, end_time, tagged_users } = req.body;
  
  const startDatetime = `${start_date} ${start_time}`;
  const endDatetime = end_date && end_time ? `${end_date} ${end_time}` : null;
  const taggedUsersStr = Array.isArray(tagged_users) ? tagged_users.join(',') : (tagged_users || '');
  
  const result = db.prepare(`
    INSERT INTO events (title, description, start_datetime, end_datetime, created_by, tagged_users)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(title, description, startDatetime, endDatetime, req.session.userId, taggedUsersStr);
  
  // Create notifications for tagged users
  if (taggedUsersStr) {
    const userIds = taggedUsersStr.split(',').filter(id => id);
    const insertNotif = db.prepare('INSERT INTO notifications (user_id, message) VALUES (?, ?)');
    for (const userId of userIds) {
      insertNotif.run(userId, `You were tagged in event: ${title}`);
    }
  }
  
  res.redirect('/calendar');
});

app.post('/edit_event/:id', requireAuth, (req, res) => {
  const { title, description, start_date, start_time, end_date, end_time, tagged_users } = req.body;
  
  const startDatetime = `${start_date} ${start_time}`;
  const endDatetime = end_date && end_time ? `${end_date} ${end_time}` : null;
  const taggedUsersStr = Array.isArray(tagged_users) ? tagged_users.join(',') : (tagged_users || '');
  
  db.prepare(`
    UPDATE events 
    SET title = ?, description = ?, start_datetime = ?, end_datetime = ?, tagged_users = ?
    WHERE id = ?
  `).run(title, description, startDatetime, endDatetime, taggedUsersStr, req.params.id);
  
  res.redirect('/calendar');
});

app.get('/delete_event/:id', requireAuth, (req, res) => {
  db.prepare('DELETE FROM events WHERE id = ?').run(req.params.id);
  res.redirect('/calendar');
});

app.get('/wishlist', requireAuth, (req, res) => {
  const items = db.prepare('SELECT * FROM wishlist_items WHERE user_id = ? ORDER BY created_at DESC').all(req.session.userId);
  res.render('wishlist', { items });
});

app.post('/add_wishlist_item', requireAuth, async (req, res) => {
  let { url, custom_title } = req.body;
  
  if (!custom_title && url) {
    custom_title = await fetchUrlTitle(url);
  }
  
  if (!custom_title) {
    custom_title = 'Untitled Item';
  }
  
  db.prepare('INSERT INTO wishlist_items (user_id, title, url) VALUES (?, ?, ?)').run(
    req.session.userId, custom_title, url || null
  );
  
  res.redirect('/wishlist');
});

app.get('/delete_wishlist_item/:id', requireAuth, (req, res) => {
  db.prepare('DELETE FROM wishlist_items WHERE id = ? AND user_id = ?').run(req.params.id, req.session.userId);
  res.redirect('/wishlist');
});

app.get('/profile', requireAuth, (req, res) => {
  res.render('profile');
});

app.post('/profile', requireAuth, (req, res) => {
  const { current_password, new_password } = req.body;
  
  const user = db.prepare('SELECT password FROM users WHERE id = ?').get(req.session.userId);
  
  if (bcrypt.compareSync(current_password, user.password)) {
    const hashedPassword = bcrypt.hashSync(new_password, 10);
    db.prepare('UPDATE users SET password = ? WHERE id = ?').run(hashedPassword, req.session.userId);
    res.render('profile', { success: 'Password changed successfully!' });
  } else {
    res.render('profile', { error: 'Current password is incorrect' });
  }
});

app.post('/profile/portrait', requireAuth, (req, res) => {
  // Simple base64 upload handling
  let portraitData = '';
  req.on('data', chunk => portraitData += chunk);
  req.on('end', () => {
    try {
      const { image } = JSON.parse(portraitData);
      if (image && image.startsWith('data:image')) {
        const base64Data = image.replace(/^data:image\/\w+;base64,/, '');
        const ext = image.match(/^data:image\/(\w+);base64,/)?.[1] || 'png';
        const filename = `user_${req.session.userId}_${Date.now()}.${ext}`;
        const filepath = path.join(__dirname, 'static', 'uploads', filename);
        
        fs.writeFileSync(filepath, Buffer.from(base64Data, 'base64'));
        db.prepare('UPDATE users SET portrait = ? WHERE id = ?').run(`uploads/${filename}`, req.session.userId);
        res.json({ success: true });
      } else {
        res.json({ success: false });
      }
    } catch (e) {
      res.json({ success: false });
    }
  });
});

app.get('/notifications', requireAuth, (req, res) => {
  const notifications = db.prepare(`
    SELECT n.*, e.title as event_title 
    FROM notifications n 
    LEFT JOIN events e ON n.event_id = e.id
    WHERE n.user_id = ? 
    ORDER BY n.created_at DESC
  `).all(req.session.userId);
  
  db.prepare('UPDATE notifications SET is_read = 1 WHERE user_id = ?').run(req.session.userId);
  
  res.render('notifications', { notifications });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`lamp.rip running at http://localhost:${PORT}`);
  console.log('Test account: admin / admin');
});
