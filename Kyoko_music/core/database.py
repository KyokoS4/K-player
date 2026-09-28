import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "library.db"


def get_connection():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # permite acceder columnas por nombre
    return conn


def init_db():
    """Crea todas las tablas si no existen todavía."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS songs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            artist      TEXT DEFAULT 'Desconocido',
            album       TEXT DEFAULT 'Desconocido',
            duration    INTEGER DEFAULT 0,   -- segundos
            filepath    TEXT NOT NULL UNIQUE,
            audio_hash  TEXT NOT NULL,
            added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS playlists (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            source     TEXT DEFAULT 'manual',  -- 'aimp', 'manual', 'spotify'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS playlist_songs (
            playlist_id INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
            song_id     INTEGER REFERENCES songs(id) ON DELETE CASCADE,
            position    INTEGER DEFAULT 0,
            PRIMARY KEY (playlist_id, song_id)
        );

        CREATE INDEX IF NOT EXISTS idx_songs_hash     ON songs(audio_hash);
        CREATE INDEX IF NOT EXISTS idx_songs_artist   ON songs(artist);
        CREATE INDEX IF NOT EXISTS idx_playlist_songs ON playlist_songs(playlist_id);
    """)

    conn.commit()
    conn.close()
    print(f"[DB] Base de datos lista en: {DB_PATH}")


if __name__ == "__main__":
    init_db()
