import hashlib
from pathlib import Path
from mutagen import File as MutagenFile
from core.database import get_connection, init_db


AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".m4a", ".wav", ".opus"}


def get_audio_hash(filepath: Path) -> str:
    """
    Genera un hash de los primeros 128KB del archivo.
    Suficiente para detectar duplicados sin leer el archivo entero.
    """
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        hasher.update(f.read(131072))  # 128 KB
    return hasher.hexdigest()


def read_metadata(filepath: Path) -> dict:
    """Lee título, artista, álbum y duración del archivo de audio."""
    audio = MutagenFile(filepath, easy=True)

    if audio is None:
        # Si mutagen no puede leer el archivo, usa el nombre del archivo
        return {
            "title": filepath.stem,
            "artist": "Desconocido",
            "album": "Desconocido",
            "duration": 0,
        }

    def get_tag(key):
        val = audio.get(key)
        return val[0] if val else None

    return {
        "title":    get_tag("title")  or filepath.stem,
        "artist":   get_tag("artist") or "Desconocido",
        "album":    get_tag("album")  or "Desconocido",
        "duration": int(audio.info.length) if audio.info else 0,
    }


def scan_folder(folder_path: str) -> dict:
    """
    Escanea una carpeta recursivamente buscando archivos de audio.
    Retorna un resumen: cuántas se agregaron, cuántas eran duplicado, cuántas fallaron.
    """
    folder = Path(folder_path)
    if not folder.exists():
        print(f"[SCANNER] La carpeta no existe: {folder_path}")
        return {"added": 0, "duplicates": 0, "errors": 0}

    archivos = [f for f in folder.rglob("*") if f.suffix.lower() in AUDIO_EXTENSIONS]
    print(f"[SCANNER] Encontrados {len(archivos)} archivos de audio en '{folder}'")

    conn = get_connection()
    cursor = conn.cursor()

    added = 0
    duplicates = 0
    errors = 0

    for filepath in archivos:
        try:
            audio_hash = get_audio_hash(filepath)

            # ¿Ya existe esta canción (por hash)?
            existing = cursor.execute(
                "SELECT id, filepath FROM songs WHERE audio_hash = ?", (audio_hash,)
            ).fetchone()

            if existing:
                duplicates += 1
                print(f"  [DUP]  {filepath.name}  →  ya existe como '{Path(existing['filepath']).name}'")
                continue

            # ¿Existe la misma ruta exacta?
            same_path = cursor.execute(
                "SELECT id FROM songs WHERE filepath = ?", (str(filepath),)
            ).fetchone()
            if same_path:
                duplicates += 1
                continue

            # Nueva canción — leer metadatos e insertar
            meta = read_metadata(filepath)
            cursor.execute("""
                INSERT INTO songs (title, artist, album, duration, filepath, audio_hash)
                VALUES (:title, :artist, :album, :duration, :filepath, :audio_hash)
            """, {**meta, "filepath": str(filepath), "audio_hash": audio_hash})

            added += 1
            print(f"  [OK]   {meta['artist']} — {meta['title']}")

        except Exception as e:
            errors += 1
            print(f"  [ERR]  {filepath.name}: {e}")

    conn.commit()
    conn.close()

    print(f"\n[SCANNER] Listo — Agregadas: {added} | Duplicadas: {duplicates} | Errores: {errors}")
    return {"added": added, "duplicates": duplicates, "errors": errors}


def get_all_songs() -> list:
    """Retorna todas las canciones de la biblioteca."""
    conn = get_connection()
    songs = conn.execute(
        "SELECT * FROM songs ORDER BY artist, album, title"
    ).fetchall()
    conn.close()
    return [dict(s) for s in songs]


def search_songs(query: str) -> list:
    """Busca canciones por título o artista."""
    conn = get_connection()
    like = f"%{query}%"
    songs = conn.execute("""
        SELECT * FROM songs
        WHERE title LIKE ? OR artist LIKE ? OR album LIKE ?
        ORDER BY artist, title
    """, (like, like, like)).fetchall()
    conn.close()
    return [dict(s) for s in songs]


if __name__ == "__main__":
    init_db()
    carpeta = input("Ruta de la carpeta de música: ").strip()
    scan_folder(carpeta)

    print("\n--- Biblioteca actual ---")
    for song in get_all_songs():
        print(f"  {song['artist']} — {song['title']} ({song['duration']}s)")
