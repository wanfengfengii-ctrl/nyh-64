import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "weir.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS weirs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location TEXT DEFAULT '',
            description TEXT DEFAULT ''
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS main_canals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            width REAL NOT NULL DEFAULT 1.0,
            description TEXT DEFAULT '',
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS branch_canals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            main_canal_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            width REAL NOT NULL DEFAULT 0.5,
            acreage REAL NOT NULL DEFAULT 0.0,
            position INTEGER NOT NULL DEFAULT 0,
            description TEXT DEFAULT '',
            FOREIGN KEY (main_canal_id) REFERENCES main_canals(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS gates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_canal_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            opening INTEGER NOT NULL DEFAULT 100,
            description TEXT DEFAULT '',
            FOREIGN KEY (branch_canal_id) REFERENCES branch_canals(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS water_levels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            level REAL NOT NULL,
            is_simulated INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE,
            UNIQUE(weir_id, date)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS schemes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            rule TEXT NOT NULL DEFAULT 'equal',
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS scheme_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scheme_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            branch_canal_id INTEGER NOT NULL,
            flow REAL NOT NULL,
            FOREIGN KEY (scheme_id) REFERENCES schemes(id) ON DELETE CASCADE,
            FOREIGN KEY (branch_canal_id) REFERENCES branch_canals(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()
