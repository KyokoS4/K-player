import customtkinter as ctk
import threading
from tkinter import filedialog, simpledialog, messagebox

from core.database import init_db, get_connection
from core.scanner import scan_folder, search_songs, get_all_songs
from core.importer import import_aimp_playlist, get_playlists, get_playlist_songs
from core.player import Player

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

BG_BASE    = "#0D0D0D"
BG_SIDEBAR = "#111111"
BG_CARD    = "#1C1C1C"
BG_HOVER   = "#242424"
BG_PLAYER  = "#111111"
ACCENT     = "#C8A0E0"
ACCENT_DIM = "#7B5EA0"
TEXT_PRI   = "#F0F0F0"
TEXT_SEC   = "#888888"
TEXT_DIM   = "#444444"
BORDER     = "#2A2A2A"


# ── Helpers de playlist en BD ──────────────────────────────────────────────────

def create_playlist(name: str) -> int:
    conn = get_connection()
    cur = conn.execute("INSERT INTO playlists (name, source) VALUES (?, 'manual')", (name,))
    pl_id = cur.lastrowid
    conn.commit()
    conn.close()
    return pl_id

def add_song_to_playlist(playlist_id: int, song_id: int):
    conn = get_connection()
    pos = conn.execute(
        "SELECT COUNT(*) FROM playlist_songs WHERE playlist_id=?", (playlist_id,)
    ).fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO playlist_songs (playlist_id, song_id, position) VALUES (?,?,?)",
        (playlist_id, song_id, pos)
    )
    conn.commit()
    conn.close()

def delete_playlist(playlist_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM playlists WHERE id=?", (playlist_id,))
    conn.commit()
    conn.close()


# ── App principal ──────────────────────────────────────────────────────────────

class KyokoApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        init_db()
        self.player       = Player()
        self.current_songs = []
        self.current_view  = "library"
        self._render_offset   = 0
        self._load_more_btn   = None

        self.title("Kyoko Music")
        self.geometry("1100x680")
        self.minsize(900, 560)
        self.configure(fg_color=BG_BASE)

        self._build_layout()
        self._start_player_ui_loop()
        self.after(150, self._load_library_async)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()
        self._build_player_bar()

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=BG_SIDEBAR, corner_radius=0, width=210)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(5, weight=1)
        self.sidebar = sb

        ctk.CTkLabel(sb, text="kyoko",
                     font=ctk.CTkFont(family="Courier New", size=22, weight="bold"),
                     text_color=ACCENT).grid(row=0, column=0, padx=20, pady=(22,18), sticky="w")

        for i, (label, view) in enumerate([("  biblioteca","library"),("  buscar","search")]):
            ctk.CTkButton(sb, text=label, font=ctk.CTkFont(size=13),
                          fg_color="transparent", hover_color=BG_HOVER,
                          text_color=TEXT_SEC, anchor="w", height=36, corner_radius=6,
                          command=lambda v=view: self._switch_view(v)
                          ).grid(row=i+1, column=0, padx=10, pady=2, sticky="ew")

        ctk.CTkFrame(sb, fg_color=BORDER, height=1).grid(row=3, column=0, padx=16, pady=12, sticky="ew")

        # Header playlists + botón nueva
        pl_header = ctk.CTkFrame(sb, fg_color="transparent")
        pl_header.grid(row=4, column=0, padx=12, pady=(0,4), sticky="ew")
        pl_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(pl_header, text="PLAYLISTS",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=TEXT_DIM).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(pl_header, text="+", width=24, height=24,
                      font=ctk.CTkFont(size=14), corner_radius=6,
                      fg_color=ACCENT_DIM, hover_color=ACCENT,
                      text_color=BG_BASE,
                      command=self._create_playlist
                      ).grid(row=0, column=1)

        self.playlist_frame = ctk.CTkScrollableFrame(sb, fg_color="transparent", corner_radius=0)
        self.playlist_frame.grid(row=5, column=0, padx=6, sticky="nsew")

        ctk.CTkButton(sb, text="+ importar .m3u",
                      font=ctk.CTkFont(size=12),
                      fg_color="transparent", hover_color=BG_HOVER,
                      text_color=ACCENT_DIM, border_color=ACCENT_DIM,
                      border_width=1, height=32, corner_radius=6,
                      command=self._import_playlist
                      ).grid(row=6, column=0, padx=12, pady=(8,16), sticky="ew")

        self._refresh_playlists()

    def _refresh_playlists(self):
        for w in self.playlist_frame.winfo_children():
            w.destroy()
        for pl in get_playlists():
            row = ctk.CTkFrame(self.playlist_frame, fg_color="transparent")
            row.pack(fill="x", pady=1)
            row.grid_columnconfigure(0, weight=1)

            btn = ctk.CTkButton(row, text=f"  {pl['name']}",
                                font=ctk.CTkFont(size=12),
                                fg_color="transparent", hover_color=BG_HOVER,
                                text_color=TEXT_SEC, anchor="w", height=30, corner_radius=6,
                                command=lambda p=pl: self._load_playlist_view(p))
            btn.grid(row=0, column=0, sticky="ew")

            # Botón eliminar playlist
            ctk.CTkButton(row, text="✕", width=22, height=22,
                          font=ctk.CTkFont(size=10),
                          fg_color="transparent", hover_color="#3A1A1A",
                          text_color=TEXT_DIM, corner_radius=4,
                          command=lambda pid=pl['id'], pn=pl['name']: self._delete_playlist(pid, pn)
                          ).grid(row=0, column=1, padx=(0,4))

    # ── Main area ─────────────────────────────────────────────────────────────

    def _build_main(self):
        self.main = ctk.CTkFrame(self, fg_color=BG_BASE, corner_radius=0)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_rowconfigure(1, weight=1)
        self.main.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self.main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20,10))
        header.grid_columnconfigure(0, weight=1)

        self.view_title = ctk.CTkLabel(header, text="Biblioteca",
                                        font=ctk.CTkFont(family="Courier New", size=20, weight="bold"),
                                        text_color=TEXT_PRI)
        self.view_title.grid(row=0, column=0, sticky="w")

        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", self._on_search)
        self.search_entry = ctk.CTkEntry(header, textvariable=self.search_var,
                                          placeholder_text="buscar...",
                                          width=200, height=32,
                                          fg_color=BG_CARD, border_color=BORDER,
                                          text_color=TEXT_PRI, placeholder_text_color=TEXT_DIM,
                                          font=ctk.CTkFont(size=12), corner_radius=6)
        self.search_entry.grid(row=0, column=1, sticky="e")

        self.song_list = ctk.CTkScrollableFrame(self.main, fg_color="transparent", corner_radius=0)
        self.song_list.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0,8))
        self.song_list.grid_columnconfigure(0, weight=1)

    # ── Song rows ─────────────────────────────────────────────────────────────

    PAGE_SIZE = 80

    def _render_songs(self, songs: list):
        for w in self.song_list.winfo_children():
            w.destroy()
        self.current_songs  = songs
        self._render_offset = 0
        self._load_more_btn = None

        if not songs:
            ctk.CTkLabel(self.song_list, text="Sin canciones",
                         text_color=TEXT_DIM, font=ctk.CTkFont(size=13)).pack(pady=40)
            return
        self._render_batch()

    def _render_batch(self):
        offset = self._render_offset
        batch  = self.current_songs[offset:offset + self.PAGE_SIZE]
        for i, song in enumerate(batch):
            self._song_row(offset + i, song)
        self._render_offset += len(batch)

        if self._render_offset < len(self.current_songs):
            remaining = len(self.current_songs) - self._render_offset
            if self._load_more_btn:
                try: self._load_more_btn.destroy()
                except: pass
            self._load_more_btn = ctk.CTkButton(
                self.song_list,
                text=f"cargar {min(self.PAGE_SIZE, remaining)} mas  ({remaining} restantes)",
                font=ctk.CTkFont(size=12),
                fg_color="transparent", hover_color=BG_HOVER,
                text_color=ACCENT_DIM, border_color=BORDER,
                border_width=1, height=34, corner_radius=6,
                command=self._load_more)
            self._load_more_btn.pack(fill="x", padx=4, pady=8)

    def _load_more(self):
        if self._load_more_btn:
            try: self._load_more_btn.destroy()
            except: pass
            self._load_more_btn = None
        self._render_batch()

    def _song_row(self, index: int, song: dict):
        row = ctk.CTkFrame(self.song_list, fg_color="transparent", corner_radius=6)
        row.pack(fill="x", pady=1)
        row.grid_columnconfigure(1, weight=1)

        num = ctk.CTkLabel(row, text=str(index+1),
                           font=ctk.CTkFont(size=11), text_color=TEXT_DIM, width=30)
        num.grid(row=0, column=0, padx=(8,4), pady=8, sticky="w")

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.grid(row=0, column=1, sticky="ew", padx=4)
        info.grid_columnconfigure(0, weight=1)

        title_lbl = ctk.CTkLabel(info, text=song["title"],
                                  font=ctk.CTkFont(size=13, weight="bold"),
                                  text_color=TEXT_PRI, anchor="w")
        title_lbl.grid(row=0, column=0, sticky="w")

        artist_lbl = ctk.CTkLabel(info, text=song["artist"],
                                   font=ctk.CTkFont(size=11),
                                   text_color=TEXT_SEC, anchor="w")
        artist_lbl.grid(row=1, column=0, sticky="w")

        mins, secs = divmod(song.get("duration", 0), 60)
        dur_lbl = ctk.CTkLabel(row, text=f"{mins}:{secs:02d}",
                                font=ctk.CTkFont(size=11, family="Courier New"),
                                text_color=TEXT_DIM, width=50)
        dur_lbl.grid(row=0, column=2, padx=(4,4))

        # Botón añadir a playlist
        add_btn = ctk.CTkButton(row, text="＋", width=26, height=26,
                                 font=ctk.CTkFont(size=13),
                                 fg_color="transparent", hover_color=BG_HOVER,
                                 text_color=TEXT_DIM, corner_radius=4,
                                 command=lambda s=song: self._add_to_playlist_dialog(s))
        add_btn.grid(row=0, column=3, padx=(0,8))

        def on_enter(e, r=row): r.configure(fg_color=BG_HOVER)
        def on_leave(e, r=row): r.configure(fg_color="transparent")
        def on_click(e, idx=index): self._play_from(idx)

        for w in [row, num, info, title_lbl, artist_lbl]:
            try:
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)
                w.bind("<Button-1>", on_click)
            except: pass

    # ── Player bar ────────────────────────────────────────────────────────────

    def _build_player_bar(self):
        bar = ctk.CTkFrame(self, fg_color=BG_PLAYER, corner_radius=0, height=80)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)
        self.player_bar = bar

        # Info canción (izquierda)
        info_f = ctk.CTkFrame(bar, fg_color="transparent", width=240)
        info_f.grid(row=0, column=0, padx=20, sticky="w")
        info_f.grid_propagate(False)

        self.np_title  = ctk.CTkLabel(info_f, text="—",
                                       font=ctk.CTkFont(size=13, weight="bold"),
                                       text_color=TEXT_PRI, anchor="w")
        self.np_title.pack(anchor="w", pady=(18,0))

        self.np_artist = ctk.CTkLabel(info_f, text="",
                                       font=ctk.CTkFont(size=11),
                                       text_color=TEXT_SEC, anchor="w")
        self.np_artist.pack(anchor="w")

        # Controles (centro)
        ctrl = ctk.CTkFrame(bar, fg_color="transparent")
        ctrl.grid(row=0, column=1)

        icon_cfg = dict(fg_color="transparent", hover_color=BG_HOVER,
                        text_color=TEXT_SEC, width=36, height=36, corner_radius=18)

        self.btn_shuffle = ctk.CTkButton(ctrl, text="⇄", font=ctk.CTkFont(size=15),
                                          command=self._toggle_shuffle, **icon_cfg)
        self.btn_shuffle.grid(row=0, column=0, padx=3)

        ctk.CTkButton(ctrl, text="⏮", font=ctk.CTkFont(size=15),
                      command=self._prev, **icon_cfg).grid(row=0, column=1, padx=3)

        self.btn_play = ctk.CTkButton(ctrl, text="▶", font=ctk.CTkFont(size=18),
                                       fg_color=ACCENT_DIM, hover_color=ACCENT,
                                       text_color=BG_BASE, width=44, height=44,
                                       corner_radius=22, command=self._play_pause)
        self.btn_play.grid(row=0, column=2, padx=6)

        ctk.CTkButton(ctrl, text="⏭", font=ctk.CTkFont(size=15),
                      command=self._next, **icon_cfg).grid(row=0, column=3, padx=3)

        self.btn_repeat = ctk.CTkButton(ctrl, text="↺", font=ctk.CTkFont(size=15),
                                         command=self._toggle_repeat, **icon_cfg)
        self.btn_repeat.grid(row=0, column=4, padx=3)

        # Progreso (derecha)
        prog_f = ctk.CTkFrame(bar, fg_color="transparent", width=300)
        prog_f.grid(row=0, column=2, padx=20, sticky="e")
        prog_f.grid_propagate(False)

        time_row = ctk.CTkFrame(prog_f, fg_color="transparent")
        time_row.pack(fill="x", pady=(20,2))

        self.lbl_pos = ctk.CTkLabel(time_row, text="0:00",
                                     font=ctk.CTkFont(size=10, family="Courier New"),
                                     text_color=TEXT_DIM)
        self.lbl_pos.pack(side="left")

        self.lbl_dur = ctk.CTkLabel(time_row, text="0:00",
                                     font=ctk.CTkFont(size=10, family="Courier New"),
                                     text_color=TEXT_DIM)
        self.lbl_dur.pack(side="right")

        self.progress_bar = ctk.CTkProgressBar(prog_f, width=260, height=3,
                                                fg_color=BORDER, progress_color=ACCENT,
                                                corner_radius=2)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x")

    # ── Vistas ────────────────────────────────────────────────────────────────

    def _switch_view(self, view: str):
        self.current_view = view
        if view == "library":
            self._load_library_async()
        elif view == "search":
            self.view_title.configure(text="Buscar")
            self.search_entry.focus()

    def _load_library_async(self):
        self.current_view = "library"
        self.view_title.configure(text="Biblioteca")
        self._show_loading()
        def _f():
            songs = get_all_songs()
            self.after(0, lambda: self._render_songs(songs))
        threading.Thread(target=_f, daemon=True).start()

    def _load_playlist_view(self, playlist: dict):
        self.current_view = "playlist"
        self.view_title.configure(text=playlist["name"])
        self._show_loading()
        def _f():
            songs = get_playlist_songs(playlist["id"])
            self.after(0, lambda: self._render_songs(songs))
        threading.Thread(target=_f, daemon=True).start()

    def _show_loading(self):
        for w in self.song_list.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.song_list, text="cargando...",
                     text_color=TEXT_DIM, font=ctk.CTkFont(size=13)).pack(pady=40)

    def _on_search(self, *args):
        query = self.search_var.get().strip()
        if len(query) < 2:
            if self.current_view == "library":
                self._load_library_async()
            return
        def _f():
            results = search_songs(query)
            self.after(0, lambda: self._render_songs(results))
        threading.Thread(target=_f, daemon=True).start()

    # ── Controles reproducción ────────────────────────────────────────────────

    def _play_from(self, index: int):
        self.player.load_queue(self.current_songs, start_index=index)
        self._update_now_playing()

    def _play_pause(self):
        self.player.play_pause()
        self._update_play_btn()

    def _next(self):
        self.player.next()
        self._update_now_playing()

    def _prev(self):
        self.player.previous()
        self._update_now_playing()

    def _toggle_shuffle(self):
        active = self.player.toggle_shuffle()
        self.btn_shuffle.configure(text_color=ACCENT if active else TEXT_SEC)

    def _toggle_repeat(self):
        mode = self.player.toggle_repeat()
        labels = {0: ("↺", TEXT_SEC), 1: ("↺¹", ACCENT), 2: ("↺", ACCENT)}
        text, color = labels[mode]
        self.btn_repeat.configure(text=text, text_color=color)

    def _update_now_playing(self):
        song = self.player.get_current_song()
        if song:
            self.np_title.configure(text=song["title"])
            self.np_artist.configure(text=song["artist"])
        self._update_play_btn()

    def _update_play_btn(self):
        self.btn_play.configure(text="⏸" if self.player.is_playing else "▶")

    # ── Gestión de playlists ──────────────────────────────────────────────────

    def _create_playlist(self):
        name = simpledialog.askstring("Nueva playlist", "Nombre:", parent=self)
        if name and name.strip():
            create_playlist(name.strip())
            self._refresh_playlists()

    def _delete_playlist(self, playlist_id: int, name: str):
        if messagebox.askyesno("Eliminar playlist", f"¿Eliminar '{name}'?", parent=self):
            delete_playlist(playlist_id)
            self._refresh_playlists()
            if self.current_view == "playlist":
                self._load_library_async()

    def _add_to_playlist_dialog(self, song: dict):
        playlists = get_playlists()
        if not playlists:
            messagebox.showinfo("Sin playlists", "Crea una playlist primero con el botón +", parent=self)
            return

        win = ctk.CTkToplevel(self)
        win.title("Añadir a playlist")
        win.geometry("280x360")
        win.configure(fg_color=BG_CARD)
        win.grab_set()

        ctk.CTkLabel(win, text=f"Añadir a playlist",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEXT_PRI).pack(pady=(16,4))
        ctk.CTkLabel(win, text=song["title"],
                     font=ctk.CTkFont(size=12),
                     text_color=TEXT_SEC).pack(pady=(0,12))

        frame = ctk.CTkScrollableFrame(win, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=12)

        def pick(pl):
            add_song_to_playlist(pl["id"], song["id"])
            win.destroy()

        for pl in playlists:
            ctk.CTkButton(frame, text=pl["name"],
                          font=ctk.CTkFont(size=12),
                          fg_color="transparent", hover_color=BG_HOVER,
                          text_color=TEXT_PRI, anchor="w", height=34, corner_radius=6,
                          command=lambda p=pl: pick(p)).pack(fill="x", pady=2)

        ctk.CTkButton(win, text="Cancelar",
                      fg_color="transparent", hover_color=BG_HOVER,
                      text_color=TEXT_SEC, height=32,
                      command=win.destroy).pack(pady=12)

    # ── Importar .m3u ─────────────────────────────────────────────────────────

    def _import_playlist(self):
        path = filedialog.askopenfilename(
            title="Seleccionar playlist de AIMP",
            filetypes=[("Playlist M3U", "*.m3u *.m3u8")])
        if path:
            def _f():
                import_aimp_playlist(path)
                self.after(0, self._refresh_playlists)
            threading.Thread(target=_f, daemon=True).start()

    # ── Loop UI del player ────────────────────────────────────────────────────

    def _start_player_ui_loop(self):
        self._player_ui_loop()

    def _player_ui_loop(self):
        try:
            pos_ms = self.player.get_position_ms()
            dur_ms = self.player.get_duration_ms()

            if dur_ms > 0:
                self.progress_bar.set(max(0, min(1, pos_ms / dur_ms)))
                mp, ms = divmod(pos_ms // 1000, 60)
                dp, ds = divmod(dur_ms // 1000, 60)
                self.lbl_pos.configure(text=f"{mp}:{ms:02d}")
                self.lbl_dur.configure(text=f"{dp}:{ds:02d}")

            song = self.player.get_current_song()
            if song and self.np_title.cget("text") != song["title"]:
                self._update_now_playing()

        except Exception:
            pass

        self.after(1000, self._player_ui_loop)


def run():
    app = KyokoApp()
    app.mainloop()

if __name__ == "__main__":
    run()
