import threading
import time
import random
import vlc
from core.database import get_connection


class Player:
    REPEAT_OFF  = 0
    REPEAT_ONE  = 1
    REPEAT_ALL  = 2

    def __init__(self):
        self.instance     = vlc.Instance()
        self.media_player = self.instance.media_player_new()
        self.queue        = []
        self.current_index = -1
        self.is_playing   = False
        self.shuffle      = False
        self.repeat       = self.REPEAT_OFF
        self._shuffle_order = []   # índices en orden aleatorio
        self._shuffle_pos   = -1
        self._monitor_thread = None
        self._monitoring     = False

    # ── Carga ──────────────────────────────────────────────────────────────

    def load_queue(self, songs: list, start_index: int = 0):
        self.queue = songs
        self.current_index = start_index
        if self.shuffle:
            self._build_shuffle_order(start_index)
        self._play_current()

    def load_playlist(self, playlist_id: int):
        conn = get_connection()
        songs = conn.execute("""
            SELECT s.* FROM songs s
            JOIN playlist_songs ps ON s.id = ps.song_id
            WHERE ps.playlist_id = ?
            ORDER BY ps.position
        """, (playlist_id,)).fetchall()
        conn.close()
        self.load_queue([dict(s) for s in songs])

    # ── Shuffle ────────────────────────────────────────────────────────────

    def _build_shuffle_order(self, current: int):
        indices = list(range(len(self.queue)))
        indices.remove(current)
        random.shuffle(indices)
        self._shuffle_order = [current] + indices
        self._shuffle_pos   = 0

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        if self.shuffle and self.queue:
            self._build_shuffle_order(self.current_index)
        return self.shuffle

    # ── Repeat ────────────────────────────────────────────────────────────

    def toggle_repeat(self):
        self.repeat = (self.repeat + 1) % 3
        return self.repeat

    # ── Controles ──────────────────────────────────────────────────────────

    def _play_current(self):
        if not self.queue or self.current_index < 0:
            return
        song = self.queue[self.current_index]
        media = self.instance.media_new(song["filepath"])
        self.media_player.set_media(media)
        self.media_player.play()
        self.is_playing = True
        self._start_monitor()

    def play_pause(self):
        if self.media_player.is_playing():
            self.media_player.pause()
            self.is_playing = False
        else:
            self.media_player.play()
            self.is_playing = True

    def next(self, auto=False):
        """auto=True cuando lo llama el monitor (fin de canción)."""
        if self.repeat == self.REPEAT_ONE and auto:
            self.media_player.set_time(0)
            self.media_player.play()
            self.is_playing = True
            return

        if self.shuffle:
            if self._shuffle_pos < len(self._shuffle_order) - 1:
                self._shuffle_pos += 1
                self.current_index = self._shuffle_order[self._shuffle_pos]
                self._play_current()
            elif self.repeat == self.REPEAT_ALL:
                self._build_shuffle_order(self.current_index)
                self._play_current()
        else:
            if self.current_index < len(self.queue) - 1:
                self.current_index += 1
                self._play_current()
            elif self.repeat == self.REPEAT_ALL:
                self.current_index = 0
                self._play_current()

    def previous(self):
        pos = self.media_player.get_time() // 1000
        if pos > 3:
            self.media_player.set_time(0)
            return

        if self.shuffle:
            if self._shuffle_pos > 0:
                self._shuffle_pos -= 1
                self.current_index = self._shuffle_order[self._shuffle_pos]
                self._play_current()
        else:
            if self.current_index > 0:
                self.current_index -= 1
                self._play_current()

    def stop(self):
        self.media_player.stop()
        self.is_playing  = False
        self._monitoring = False

    def set_volume(self, volume: int):
        self.media_player.audio_set_volume(max(0, min(100, volume)))

    # ── Info ───────────────────────────────────────────────────────────────

    def get_current_song(self) -> dict | None:
        if self.queue and 0 <= self.current_index < len(self.queue):
            return self.queue[self.current_index]
        return None

    def get_position_ms(self) -> int:
        return self.media_player.get_time()

    def get_duration_ms(self) -> int:
        return self.media_player.get_length()

    # ── Monitor ────────────────────────────────────────────────────────────

    def _start_monitor(self):
        self._monitoring = True
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _monitor_loop(self):
        time.sleep(2)
        while self._monitoring:
            state = self.media_player.get_state()
            if state == vlc.State.Ended:
                self.next(auto=True)
            time.sleep(1)
