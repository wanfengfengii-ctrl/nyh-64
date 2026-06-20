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
            farm_type TEXT DEFAULT 'general',
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
            main_canal_id INTEGER,
            status TEXT NOT NULL DEFAULT 'draft',
            version INTEGER NOT NULL DEFAULT 1,
            parent_id INTEGER,
            change_note TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE,
            FOREIGN KEY (main_canal_id) REFERENCES main_canals(id) ON DELETE SET NULL,
            FOREIGN KEY (parent_id) REFERENCES schemes(id) ON DELETE SET NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS scheme_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scheme_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            branch_canal_id INTEGER NOT NULL,
            flow REAL NOT NULL,
            coverage REAL DEFAULT 0,
            FOREIGN KEY (scheme_id) REFERENCES schemes(id) ON DELETE CASCADE,
            FOREIGN KEY (branch_canal_id) REFERENCES branch_canals(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS seasonal_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            start_month INTEGER NOT NULL DEFAULT 1,
            end_month INTEGER NOT NULL DEFAULT 12,
            rule TEXT NOT NULL DEFAULT 'equal',
            priority_farm_type TEXT DEFAULT '',
            priority_ratio REAL DEFAULT 1.0,
            water_level_threshold REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            main_canal_id INTEGER,
            year_from INTEGER,
            year_to INTEGER,
            scenario_type TEXT DEFAULT 'historical',
            status TEXT DEFAULT 'draft',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE,
            FOREIGN KEY (main_canal_id) REFERENCES main_canals(id) ON DELETE SET NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS scenario_seasonal_rule_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER NOT NULL,
            seasonal_rule_id INTEGER NOT NULL,
            FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE CASCADE,
            FOREIGN KEY (seasonal_rule_id) REFERENCES seasonal_rules(id) ON DELETE CASCADE,
            UNIQUE(scenario_id, seasonal_rule_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS scenario_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER NOT NULL,
            seasonal_rule_id INTEGER,
            date TEXT NOT NULL,
            branch_canal_id INTEGER NOT NULL,
            flow REAL NOT NULL,
            coverage REAL DEFAULT 0,
            FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE CASCADE,
            FOREIGN KEY (seasonal_rule_id) REFERENCES seasonal_rules(id) ON DELETE SET NULL,
            FOREIGN KEY (branch_canal_id) REFERENCES branch_canals(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS data_anomalies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            anomaly_type TEXT NOT NULL,
            detail TEXT NOT NULL,
            date TEXT,
            suggestion TEXT DEFAULT '',
            is_resolved INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS consistency_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_type TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            check_type TEXT NOT NULL,
            passed INTEGER NOT NULL,
            detail TEXT DEFAULT '',
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    def _has_column(table, col):
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r[1] == col for r in rows)

    migration_map = {
        "branch_canals": [
            ("farm_type", "TEXT DEFAULT 'general'"),
        ],
        "schemes": [
            ("version", "INTEGER NOT NULL DEFAULT 1"),
            ("parent_id", "INTEGER"),
            ("change_note", "TEXT DEFAULT ''"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ],
        "scheme_results": [
            ("coverage", "REAL DEFAULT 0"),
        ],
        "water_levels": [
            ("is_simulated", "INTEGER NOT NULL DEFAULT 0"),
        ],
    }
    for tbl, cols in migration_map.items():
        for cname, cdef in cols:
            if not _has_column(tbl, cname):
                try:
                    conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {cname} {cdef}")
                    print(f"[migration] {tbl}.{cname} added")
                except Exception as e:
                    print(f"[migration] skip {tbl}.{cname}: {e}")
    conn.commit()
    conn.close()
