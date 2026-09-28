from pathlib import Path
from core.database import get_connection, init_db
from core.scanner import get_audio_hash, read_metadata, AUDIO_EXTENSIONS


def parse_m3u(filepath: Path) -> list:
    """
    Lee un archivo .m3u o .m3u8 de AIMP.
    Extrae ruta + hint de artista/título del #EXTINF.
    """
    entries = []
    current_artist = None
    current_title = None

    with open(filepath, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line == "#EXTM3U":
                continue

            if line.startswith("#EXTINF:"):
                # Formato: #EXTINF:duracion,Artista - Título
                parts = line.split(",", 1)
                if len(parts) > 1:
                    hint = parts[1].strip()
                    if " - " in hint:
                        artist_hint, title_hint = hint.split(" - ", 1)
                        current_artist = artist_hint.strip()
                        current_title = title_hint.strip()
                    else:
                        current_title = hint
                        current_artist = None

            elif not line.startswith("#"):
                entries.append({
                    "filepath": Path(line),
                    "artist_hint": current_artist,
                    "title_hint": current_title,
                })
                current_artist = None
                current_title = None

    return entries


def find_in_library(cursor, filepath: Path, artist_hint: str, title_hint: str):
    """
    Busca una canción en la biblioteca con 3 estrategias en orden:
    1. Por ruta exacta
    2. Por hash de audio (si el archivo existe en otra ubicación)
    3. Por artista + título del #EXTINF (fallback)
    Retorna el song_id o None.
    """
    # Estrategia 1: ruta exacta
    row = cursor.execute(
        "SELECT id FROM songs WHERE filepath = ?", (str(filepath),)
    ).fetchone()
    if row:
        return row["id"], "ruta"

    # Estrategia 2: hash (el archivo existe pero en otra carpeta)
    if filepath.exists():
        audio_hash = get_audio_hash(filepath)
        row = cursor.execute(
            "SELECT id FROM songs WHERE audio_hash = ?", (audio_hash,)
        ).fetchone()
        if row:
            return row["id"], "hash"

    # Estrategia 3: título + artista del #EXTINF
    if title_hint:
        if artist_hint:
            row = cursor.execute("""
                SELECT id FROM songs
                WHERE LOWER(title) = LOWER(?)
                  AND LOWER(artist) = LOWER(?)
                LIMIT 1
            """, (title_hint, artist_hint)).fetchone()
        else:
            row = cursor.execute("""
                SELECT id FROM songs
                WHERE LOWER(title) = LOWER(?)
                LIMIT 1
            """, (title_hint,)).fetchone()
        if row:
            return row["id"], "metadatos"

    return None, None


def import_aimp_playlist(m3u_path: str) -> dict:
    """
    Importa una playlist de AIMP (.m3u / .m3u8).
    Si no encuentra el archivo por ruta, lo busca en la biblioteca
    por artista + título extraídos del #EXTINF.
    """
    m3u = Path(m3u_path)
    if not m3u.exists():
        print(f"[AIMP] Archivo no encontrado: {m3u_path}")
        return {"linked": 0, "added": 0, "not_found": 0}

    playlist_name = m3u.stem
    entries = parse_m3u(m3u)
    print(f"[AIMP] Importando '{playlist_name}' ({len(entries)} entradas)\n")

    conn = get_connection()
    cursor = conn.cursor()

    # Borrar playlist anterior con el mismo nombre si existe
    cursor.execute("DELETE FROM playlists WHERE name = ? AND source = 'aimp'", (playlist_name,))

    cursor.execute(
        "INSERT INTO playlists (name, source) VALUES (?, 'aimp')",
        (playlist_name,)
    )
    playlist_id = cursor.lastrowid

    linked = 0
    added = 0
    not_found = 0
    position = 0

    for entry in entries:
        filepath = entry["filepath"]
        artist_hint = entry["artist_hint"]
        title_hint = entry["title_hint"]

        song_id, method = find_in_library(cursor, filepath, artist_hint, title_hint)

        if song_id:
            linked += 1
            label = f"{artist_hint} — {title_hint}" if artist_hint else title_hint
            print(f"  [OK:{method}]  {label}")
        elif filepath.exists() and filepath.suffix.lower() in AUDIO_EXTENSIONS:
            # Archivo existe pero no estaba en la biblioteca — agregarlo
            meta = read_metadata(filepath)
            audio_hash = get_audio_hash(filepath)
            cursor.execute("""
                INSERT OR IGNORE INTO songs (title, artist, album, duration, filepath, audio_hash)
                VALUES (:title, :artist, :album, :duration, :filepath, :audio_hash)
            """, {**meta, "filepath": str(filepath), "audio_hash": audio_hash})
            song_id = cursor.lastrowid
            added += 1
            print(f"  [+nuevo]  {meta['artist']} — {meta['title']}")
        else:
            not_found += 1
            print(f"  [?]  No encontrado: {title_hint or filepath.name}")
            continue

        position += 1
        cursor.execute("""
            INSERT OR IGNORE INTO playlist_songs (playlist_id, song_id, position)
            VALUES (?, ?, ?)
        """, (playlist_id, song_id, position))

    conn.commit()
    conn.close()

    print(f"""
[AIMP] '{playlist_name}' lista
  Enlazadas:     {linked}
  Nuevas en BD:  {added}
  No encontradas:{not_found}
""")
    return {"linked": linked, "added": added, "not_found": not_found}


def get_playlists() -> list:
    conn = get_connection()
    playlists = conn.execute("""
        SELECT p.*, COUNT(ps.song_id) as song_count
        FROM playlists p
        LEFT JOIN playlist_songs ps ON p.id = ps.playlist_id
        GROUP BY p.id
        ORDER BY p.name
    """).fetchall()
    conn.close()
    return [dict(p) for p in playlists]


def get_playlist_songs(playlist_id: int) -> list:
    conn = get_connection()
    songs = conn.execute("""
        SELECT s.* FROM songs s
        JOIN playlist_songs ps ON s.id = ps.song_id
        WHERE ps.playlist_id = ?
        ORDER BY ps.position
    """, (playlist_id,)).fetchall()
    conn.close()
    return [dict(s) for s in songs]


if __name__ == "__main__":
    init_db()
    ruta = input("Ruta del archivo .m3u de AIMP: ").strip()
    import_aimp_playlist(ruta)

    print("\n--- Playlists en la biblioteca ---")
    for pl in get_playlists():
        print(f"  [{pl['source']}] {pl['name']} — {pl['song_count']} canciones")
