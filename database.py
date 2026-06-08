import sqlite3
import hashlib

def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()

    # Create users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Create interviews table
    c.execute('''CREATE TABLE IF NOT EXISTS interviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        skills TEXT,
        resume_text TEXT,
        score INTEGER,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')
    
    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(name, email, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                  (name, email, hash_password(password)))
        conn.commit()
        user_id = c.lastrowid
        conn.close()
        return user_id, True
    except sqlite3.IntegrityError:
        conn.close()
        return None, False

def verify_user(email, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT id, name, email FROM users WHERE email = ? AND password = ?",
              (email, hash_password(password)))
    user = c.fetchone()
    conn.close()
    return user

def get_user_by_id(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT id, name, email FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def save_interview(user_id, skills, resume_text, score):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("INSERT INTO interviews (user_id, skills, resume_text, score) VALUES (?, ?, ?, ?)",
              (user_id, skills, resume_text, score))
    conn.commit()
    conn.close()

init_db()
