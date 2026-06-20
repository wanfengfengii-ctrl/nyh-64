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
    c.execute("""
        CREATE TABLE IF NOT EXISTS schedule_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            scheme_id INTEGER,
            operator TEXT NOT NULL DEFAULT '系统管理员',
            adjust_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            adjust_reason TEXT NOT NULL,
            water_level REAL DEFAULT 0,
            water_level_date TEXT,
            rule_before TEXT,
            rule_after TEXT,
            total_flow_before REAL DEFAULT 0,
            total_flow_after REAL DEFAULT 0,
            avg_coverage_before REAL DEFAULT 0,
            avg_coverage_after REAL DEFAULT 0,
            published INTEGER NOT NULL DEFAULT 0,
            published_at TIMESTAMP,
            notes TEXT DEFAULT '',
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE,
            FOREIGN KEY (scheme_id) REFERENCES schemes(id) ON DELETE SET NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS gate_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_log_id INTEGER NOT NULL,
            gate_id INTEGER,
            branch_canal_id INTEGER NOT NULL,
            branch_canal_name TEXT NOT NULL,
            gate_name TEXT NOT NULL,
            opening_before INTEGER NOT NULL,
            opening_after INTEGER NOT NULL,
            flow_before REAL DEFAULT 0,
            flow_after REAL DEFAULT 0,
            coverage_before REAL DEFAULT 0,
            coverage_after REAL DEFAULT 0,
            FOREIGN KEY (schedule_log_id) REFERENCES schedule_logs(id) ON DELETE CASCADE,
            FOREIGN KEY (gate_id) REFERENCES gates(id) ON DELETE SET NULL,
            FOREIGN KEY (branch_canal_id) REFERENCES branch_canals(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS press_structures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            structure_type TEXT NOT NULL DEFAULT 'screw',
            screw_diameter REAL DEFAULT 0.0,
            screw_pitch REAL DEFAULT 0.0,
            screw_lead REAL DEFAULT 0.0,
            cone_angle REAL DEFAULT 0.0,
            gap_size REAL DEFAULT 0.0,
            compression_ratio REAL DEFAULT 0.0,
            rotation_speed REAL DEFAULT 0.0,
            feed_rate REAL DEFAULT 0.0,
            material_type TEXT DEFAULT '',
            moisture_content REAL DEFAULT 0.0,
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS press_experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            structure_id INTEGER,
            name TEXT NOT NULL,
            status TEXT DEFAULT 'draft',
            juice_yield REAL DEFAULT 0.0,
            peak_pressure REAL DEFAULT 0.0,
            residue_moisture REAL DEFAULT 0.0,
            steady_juice_time REAL DEFAULT 0.0,
            energy_consumption REAL DEFAULT 0.0,
            throughput REAL DEFAULT 0.0,
            experiment_date TEXT,
            operator TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE,
            FOREIGN KEY (structure_id) REFERENCES press_structures(id) ON DELETE SET NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS optimization_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            algorithm TEXT DEFAULT 'genetic',
            target_juice_yield_weight REAL DEFAULT 0.3,
            target_peak_pressure_weight REAL DEFAULT 0.25,
            target_residue_moisture_weight REAL DEFAULT 0.25,
            target_steady_time_weight REAL DEFAULT 0.2,
            param_ranges TEXT DEFAULT '',
            population_size INTEGER DEFAULT 50,
            max_iterations INTEGER DEFAULT 100,
            mutation_rate REAL DEFAULT 0.1,
            crossover_rate REAL DEFAULT 0.8,
            best_solution_id INTEGER,
            progress INTEGER DEFAULT 0,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            error_message TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE,
            FOREIGN KEY (best_solution_id) REFERENCES press_structures(id) ON DELETE SET NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS optimization_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            iteration INTEGER DEFAULT 0,
            structure_params TEXT DEFAULT '',
            juice_yield REAL DEFAULT 0.0,
            peak_pressure REAL DEFAULT 0.0,
            residue_moisture REAL DEFAULT 0.0,
            steady_juice_time REAL DEFAULT 0.0,
            fitness_score REAL DEFAULT 0.0,
            rank INTEGER DEFAULT 0,
            is_pareto INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES optimization_tasks(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS scheme_rankings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            ranking_method TEXT DEFAULT 'topsis',
            juice_yield_weight REAL DEFAULT 0.3,
            peak_pressure_weight REAL DEFAULT 0.25,
            residue_moisture_weight REAL DEFAULT 0.25,
            steady_time_weight REAL DEFAULT 0.2,
            scheme_ids TEXT DEFAULT '',
            ranking_results TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS structure_change_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            structure_id INTEGER NOT NULL,
            change_type TEXT NOT NULL,
            param_name TEXT NOT NULL,
            value_before REAL,
            value_after REAL,
            juice_yield_before REAL,
            juice_yield_after REAL,
            peak_pressure_before REAL,
            peak_pressure_after REAL,
            residue_moisture_before REAL,
            residue_moisture_after REAL,
            steady_time_before REAL,
            steady_time_after REAL,
            effect_description TEXT DEFAULT '',
            operator TEXT DEFAULT '',
            change_reason TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (structure_id) REFERENCES press_structures(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS report_comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            experiment_ids TEXT DEFAULT '',
            comparison_type TEXT DEFAULT 'side_by_side',
            include_metrics TEXT DEFAULT '',
            report_content TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS experiment_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            experiment_ids TEXT DEFAULT '',
            review_type TEXT DEFAULT 'full',
            success_summary TEXT DEFAULT '',
            issue_summary TEXT DEFAULT '',
            lesson_learned TEXT DEFAULT '',
            improvement_suggestions TEXT DEFAULT '',
            key_findings TEXT DEFAULT '',
            reviewer TEXT DEFAULT '',
            reviewed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS gap_fix_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            original_level REAL,
            fixed_level REAL NOT NULL,
            method TEXT NOT NULL DEFAULT 'interpolate',
            confidence_level TEXT NOT NULL DEFAULT 'medium',
            basis TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            operator TEXT DEFAULT '',
            confirmed_by TEXT DEFAULT '',
            confirmed_at TIMESTAMP,
            impact_total_flow_before REAL DEFAULT 0,
            impact_total_flow_after REAL DEFAULT 0,
            impact_avg_coverage_before REAL DEFAULT 0,
            impact_avg_coverage_after REAL DEFAULT 0,
            impact_scheme_publishable_before INTEGER DEFAULT 0,
            impact_scheme_publishable_after INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE,
            UNIQUE(weir_id, date)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS gap_scan_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weir_id INTEGER NOT NULL,
            total_records INTEGER DEFAULT 0,
            missing_count INTEGER DEFAULT 0,
            gap_segments INTEGER DEFAULT 0,
            longest_gap_days INTEGER DEFAULT 0,
            simulated_count INTEGER DEFAULT 0,
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (weir_id) REFERENCES weirs(id) ON DELETE CASCADE
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
