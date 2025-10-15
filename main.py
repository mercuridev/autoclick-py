import json, math, threading, time, tkinter as tk
from dataclasses import dataclass, asdict, field
from pathlib import Path
from tkinter import ttk, messagebox

# ===== Backends de input (compatível com jogos) =====
HAVE_PDI = True
try:
    import pydirectinput as pdi
    pdi.PAUSE = 0
    pdi.FAILSAFE = False
except Exception:
    HAVE_PDI = False

import pyautogui
pyautogui.FAILSAFE = True

from pynput import keyboard, mouse

# ===== Tray (opcional) =====
HAVE_TRAY = True
try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    HAVE_TRAY = False

APP_NAME = "MTechClicker"
SETTINGS_FILE = Path(__file__).with_name("settings.json")

# ----------------- MODELOS -----------------
@dataclass
class AppSettings:
    # Comuns
    start_countdown: float = 0.0
    hotkey_toggle: str = "f8"      # inicia/para (toggle)
    hotkey_emergency: str = "esc"  # parada de emergência

    # Autoclick
    delay_seconds: float = 0.20
    delay_variation_pct: float = 0.0
    mouse_button: str = "left"     # left/right/middle
    click_type: str = "single"     # single/double
    use_fixed_position: bool = False
    fixed_x: int | None = None
    fixed_y: int | None = None
    run_mode: str = "until_stop"   # until_stop | fixed_amount
    run_amount: int = 100

    # Macro
    macro_steps: list[dict] = field(default_factory=list)   # [{"kind":"key|click|delay","value":{...}},...]
    macro_use_recorded_delays: bool = True
    macro_forced_delay: float = 1.0
    macro_loops: int = 0          # 0 = infinito

    def clamp(self):
        # comuns
        self.start_countdown = max(0.0, float(self.start_countdown))
        # autoclick
        self.delay_seconds = max(0.0, float(self.delay_seconds))
        self.delay_variation_pct = max(0.0, min(100.0, float(self.delay_variation_pct)))
        self.run_amount = max(1, int(self.run_amount))
        if self.mouse_button not in ("left", "right", "middle"): self.mouse_button = "left"
        if self.click_type not in ("single", "double"): self.click_type = "single"
        if self.run_mode not in ("until_stop", "fixed_amount"): self.run_mode = "until_stop"
        # macro
        self.macro_forced_delay = max(0.0, float(self.macro_forced_delay))
        self.macro_loops = max(0, int(self.macro_loops))  # 0 = infinito

def load_settings() -> AppSettings:
    try:
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            s = AppSettings(**data); s.clamp(); return s
    except Exception:
        pass
    return AppSettings()

def save_settings(s: AppSettings):
    try:
        s.clamp()
        SETTINGS_FILE.write_text(json.dumps(asdict(s), indent=2), encoding="utf-8")
    except Exception as e:
        print("Falha ao salvar settings:", e)

# ------------ util -------------
def human_delay(base: float, variation_pct: float) -> float:
    if variation_pct <= 0:
        return max(0.0, base)
    import random
    amp = base * (variation_pct / 100.0)
    return max(0.0, base + random.uniform(-amp, amp))

def key_to_token(k) -> str | None:
    if isinstance(k, keyboard.KeyCode) and k.char:
        return k.char.lower()
    if isinstance(k, keyboard.Key):
        name = str(k).split(".")[-1].lower()
        if name == "page_up": return "pgup"
        if name == "page_down": return "pgdn"
        if name == "space": return "space"
        return name
    return None

def mouse_to_token(btn) -> str | None:
    """Normaliza botões do mouse para 'mouse.left/right/middle/x1/x2'."""
    try:
        name = btn.name.lower()
    except Exception:
        return None

    aliases = {
        "button8": "x1", "x_button1": "x1", "xbutton1": "x1",
        "button9": "x2", "x_button2": "x2", "xbutton2": "x2",
    }
    name = aliases.get(name, name)  # mantém left/right/middle/x1/x2

    if name in {"left", "right", "middle", "x1", "x2"}:
        return f"mouse.{name}"
    return None

def token_label(tok: str) -> str:
    if tok.startswith("mouse."): return tok.replace("mouse.", "mouse ")
    if tok == "pgup": return "PgUp"
    if tok == "pgdn": return "PgDn"
    return tok.upper()

# -------- envio de inputs --------
def do_mouse_click(button: str, double: bool, x: int | None = None, y: int | None = None):
    if HAVE_PDI:
        if x is not None and y is not None: pdi.moveTo(x, y)
        if double:
            if x is None: pdi.doubleClick(button=button)
            else:         pdi.doubleClick(x=x, y=y, button=button)
        else:
            if x is None: pdi.click(button=button)
            else:         pdi.click(x=x, y=y, button=button)
    else:
        if double:
            if x is None: pyautogui.doubleClick(button=button)
            else:         pyautogui.doubleClick(x=x, y=y, button=button)
        else:
            if x is None: pyautogui.click(button=button)
            else:         pyautogui.click(x=x, y=y, button=button)

def press_key_token(tok: str):
    if HAVE_PDI:
        pdi.press(tok); return
    from pynput import keyboard as _kb
    ctrl = _kb.Controller()
    key_map = {"esc":_kb.Key.esc,"space":_kb.Key.space,"pgup":_kb.Key.page_up,"pgdn":_kb.Key.page_down,
               "home":_kb.Key.home,"end":_kb.Key.end,"insert":_kb.Key.insert,"delete":_kb.Key.delete,
               "up":_kb.Key.up,"down":_kb.Key.down,"left":_kb.Key.left,"right":_kb.Key.right,
               "tab":_kb.Key.tab,"enter":_kb.Key.enter,"backspace":_kb.Key.backspace}
    if tok.startswith("f") and tok[1:].isdigit():
        n = int(tok[1:])
        if 1 <= n <= 24:
            k = getattr(_kb.Key, f"f{n}")
            ctrl.press(k); ctrl.release(k); return
    if tok in key_map:
        k = key_map[tok]; ctrl.press(k); ctrl.release(k); return
    if len(tok) == 1:
        ctrl.press(tok); ctrl.release(tok)

# ------------ Listener global -------------
class GlobalListener(threading.Thread):
    def __init__(self, app_ref):
        super().__init__(daemon=True)
        self.app = app_ref
        self.k_listener = None
        self.m_listener = None
        self._stop = threading.Event()
        # gravação de macro?
        self.record_macro = False
        self._last_event_ts: float | None = None
        # gravação de hotkeys?
        self.record_field: str | None = None  # 'toggle'|'emergency'|None

    def run(self):
        self.k_listener = keyboard.Listener(on_press=self.on_key_press)
        self.m_listener = mouse.Listener(on_click=self.on_click)
        self.k_listener.start(); self.m_listener.start()
        while not self._stop.is_set():
            time.sleep(0.05)
        try:
            self.k_listener.stop(); self.m_listener.stop()
        except Exception: pass

    def stop(self): self._stop.set()

    def set_record_field(self, field: str | None):
        self.record_field = field
        if field: self.app.set_status(f"Gravando atalho para {field}…")
        else:     self.app.set_status("Parado")

    def start_macro_rec(self):
        self.record_macro = True
        self._last_event_ts = time.time()
        self.app.clear_macro_steps_ui()
        self.app.set_status("Gravando macro… (use 'Parar gravação' para finalizar)")

    def stop_macro_rec(self):
        self.record_macro = False
        self._last_event_ts = None
        self.app.set_status("Macro gravada.")

    def on_key_press(self, k):
        tok = key_to_token(k)
        if not tok: return

        if self.record_field:
            self.app.update_hotkey(self.record_field, tok)
            self.set_record_field(None)
            self.app.flash_info(f"Atalho definido: {token_label(tok)}")
            return

        if self.record_macro:
            now = time.time()
            if self._last_event_ts is not None:
                self.app.append_macro_delay(now - self._last_event_ts)
            self._last_event_ts = now
            self.app.append_macro_key(tok)
            return

        s = self.app.settings
        if tok == s.hotkey_emergency: self.app.root.after(0, self.app.stop_all)
        elif tok == s.hotkey_toggle:  self.app.root.after(0, self.app.toggle_start_stop)

    def on_click(self, x, y, button, pressed):
        # DISPARA SÓ NO PRESS (evita duplo-toggle press+release)
        if not pressed:
            return
        tok = mouse_to_token(button)
        if not tok: return

        if self.record_field:
            self.app.update_hotkey(self.record_field, tok)
            self.set_record_field(None)
            self.app.flash_info(f"Atalho definido: {token_label(tok)}")
            return

        if self.record_macro:
            now = time.time()
            if self._last_event_ts is not None:
                self.app.append_macro_delay(now - self._last_event_ts)
            self._last_event_ts = now
            btn = tok.split(".", 1)[-1]  # left/right/middle/x1/x2
            self.app.append_macro_click(btn, int(x), int(y))
            return

        s = self.app.settings
        if tok == s.hotkey_emergency:
            self.app.root.after(0, self.app.stop_all)
        elif tok == s.hotkey_toggle:
            self.app.root.after(0, self.app.toggle_start_stop)

# ----------------- Tray (bandeja) -----------------
class TrayIcon:
    def __init__(self, app):
        self.app = app
        self.icon = None
        self.thread = None
        self.visible = False

    def _build_image(self, running=False):
        size = 128
        img = Image.new("RGBA", (size, size), (0,0,0,0))
        d = ImageDraw.Draw(img)
        bg = (60,130,246,255) if not running else (26,188,156,255)
        d.ellipse((8,8,size-8,size-8), fill=bg)
        try:
            font = ImageFont.truetype("arial.ttf", 72)
        except Exception:
            font = ImageFont.load_default()
        text = "M"
        tw, th = d.textsize(text, font=font)
        d.text(((size-tw)//2,(size-th)//2), text, fill="white", font=font)
        return img

    def _menu(self):
        return pystray.Menu(
            pystray.MenuItem("Mostrar/Ocultar", self.toggle_window),
            pystray.MenuItem("Iniciar/Parar", self.toggle_run),
            pystray.MenuItem("Sair", self.exit_app)
        )

    def show(self):
        if not HAVE_TRAY or self.visible: return
        self.visible = True
        self.icon = pystray.Icon(APP_NAME, self._build_image(self.app.engine_running()), APP_NAME, self._menu())
        self.thread = threading.Thread(target=self.icon.run, daemon=True); self.thread.start()

    def hide(self):
        if self.icon: self.icon.stop()
        self.icon = None; self.visible = False

    def toggle_window(self, icon=None, item=None): self.app.toggle_window_visibility()
    def toggle_run(self, icon=None, item=None): self.app.toggle_start_stop()
    def exit_app(self, icon=None, item=None): self.app.quit_from_tray()
    def update_running(self):
        if self.icon: self.icon.icon = self._build_image(self.app.engine_running())

# ----------------- APP -----------------
class MTechClickerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"{APP_NAME} – autoclick + macro (jogos)")
        self._apply_theme()
        root.geometry("760x720"); root.minsize(760, 720); root.resizable(False, False)

        self.settings = load_settings()

        self.stop_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self.start_time = None
        self.click_count = 0

        self.tray = TrayIcon(self) if HAVE_TRAY else None

        self._build_ui()

        self.listener = GlobalListener(self)
        self.listener.start()

        if HAVE_TRAY: self.root.bind("<Unmap>", self._on_minimize)
        self._tick()

    # ---- tema ----
    def _apply_theme(self):
        try:
            import ttkbootstrap as tb
            tb.Style("darkly")
        except Exception:
            try:
                style = ttk.Style()
                if "vista" in style.theme_names(): style.theme_use("vista")
                elif "clam" in style.theme_names(): style.theme_use("clam")
            except Exception: pass

    # ---- UI ----
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=12); main.pack(fill="both", expand=True)

        hdr = ttk.Frame(main); hdr.pack(fill="x", pady=(0,6))
        ttk.Label(hdr, text=APP_NAME, font=("Segoe UI", 14, "bold")).pack(side="left")
        ttk.Label(hdr, text="  Autoclick + Macro • Compatível com jogos", foreground="#6b7280").pack(side="left")

        # ===== Opções COMUNS =====
        commons = ttk.LabelFrame(main, text="Geral", padding=10); commons.pack(fill="x", pady=(0,8))
        hot = ttk.Frame(commons); hot.pack(fill="x")
        self.toggle_var = tk.StringVar(value=token_label(self.settings.hotkey_toggle))
        self.emerg_var  = tk.StringVar(value=token_label(self.settings.hotkey_emergency))
        self._hotrow(hot, "Atalho Iniciar/Parar (toggle):", self.toggle_var, lambda: self._record_hotkey("toggle"))
        self._hotrow(hot, "Atalho Emergência (parar):", self.emerg_var,  lambda: self._record_hotkey("emergency"))
        cnt = ttk.Frame(commons); cnt.pack(fill="x", pady=(6,0))
        ttk.Label(cnt, text="⏳ Contagem inicial (s):").pack(side="left")
        self.count_var = tk.StringVar(value=str(self.settings.start_countdown))
        ttk.Entry(cnt, width=10, textvariable=self.count_var).pack(side="left", padx=(6, 14))

        # ===== Abas =====
        self.tabs = ttk.Notebook(main); self.tabs.pack(fill="both", expand=True)

        # --- Aba Autoclick ---
        auto = ttk.Frame(self.tabs, padding=8); self.tabs.add(auto, text="Autoclick")
        r1 = ttk.Frame(auto); r1.pack(fill="x")
        ttk.Label(r1, text="⏱ Delay base (s):").pack(side="left")
        self.delay_var = tk.StringVar(value=str(self.settings.delay_seconds))
        ttk.Entry(r1, width=10, textvariable=self.delay_var).pack(side="left", padx=(6, 14))
        ttk.Label(r1, text="Variação (%)").pack(side="left")
        self.var_var = tk.StringVar(value=str(self.settings.delay_variation_pct))
        ttk.Entry(r1, width=8, textvariable=self.var_var).pack(side="left")

        r3 = ttk.Frame(auto); r3.pack(fill="x", pady=(6,0))
        ttk.Label(r3, text="🖱 Botão do mouse:").pack(side="left")
        self.btn_var = tk.StringVar(value=self.settings.mouse_button)
        ttk.Combobox(r3, width=10, state="readonly", textvariable=self.btn_var,
                     values=["left","right","middle"]).pack(side="left", padx=(6, 14))
        ttk.Label(r3, text="🔁 Tipo de clique:").pack(side="left")
        self.type_var = tk.StringVar(value=self.settings.click_type)
        ttk.Combobox(r3, width=10, state="readonly", textvariable=self.type_var,
                     values=["single","double"]).pack(side="left")

        r4 = ttk.Frame(auto); r4.pack(fill="x", pady=(6,0))
        ttk.Label(r4, text="▶ Execução:").pack(side="left")
        self.runmode_var = tk.StringVar(value=self.settings.run_mode)
        ttk.Combobox(r4, width=15, state="readonly", textvariable=self.runmode_var,
                     values=["until_stop","fixed_amount"]).pack(side="left", padx=(6, 14))
        ttk.Label(r4, text="Qtde (se 'fixed_amount'):").pack(side="left")
        self.amount_var = tk.StringVar(value=str(self.settings.run_amount))
        ttk.Entry(r4, width=8, textvariable=self.amount_var).pack(side="left")

        pos = ttk.LabelFrame(auto, text="Destino do clique", padding=10)
        pos.pack(fill="x", pady=8)
        self.use_fixed = tk.BooleanVar(value=self.settings.use_fixed_position)
        ttk.Checkbutton(pos, text="Usar posição fixa", variable=self.use_fixed,
                        command=self._toggle_pos).grid(row=0,column=0,sticky="w")
        self.pos_label = ttk.Label(pos, text=self._pos_text()); self.pos_label.grid(row=1, column=0, sticky="w", pady=(6,0))
        ttk.Button(pos, text="📍 Capturar agora", command=self.capture_position_ui).grid(row=1, column=1, padx=8)

        # --- Aba Macro ---
        macro = ttk.Frame(self.tabs, padding=8); self.tabs.add(macro, text="Macro")
        top = ttk.Frame(macro); top.pack(fill="x")
        ttk.Button(top, text="⏺ Gravar macro", command=self.start_macro_record).pack(side="left")
        ttk.Button(top, text="⏹ Parar gravação", command=self.stop_macro_record).pack(side="left", padx=6)
        ttk.Button(top, text="🧹 Limpar", command=self.clear_macro_steps).pack(side="left", padx=6)

        opts = ttk.Frame(macro); opts.pack(fill="x", pady=(8,0))
        self.macro_use_rec_var = tk.BooleanVar(value=self.settings.macro_use_recorded_delays)
        ttk.Checkbutton(opts, text="Usar delays gravados", variable=self.macro_use_rec_var).pack(side="left")
        ttk.Label(opts, text="Delay fixo (s):").pack(side="left", padx=(12,4))
        self.macro_fixed_delay_var = tk.StringVar(value=str(self.settings.macro_forced_delay))
        ttk.Entry(opts, width=8, textvariable=self.macro_fixed_delay_var).pack(side="left")

        loop = ttk.Frame(macro); loop.pack(fill="x", pady=(8,0))
        ttk.Label(loop, text="Loops (0 = infinito):").pack(side="left")
        self.macro_loops_var = tk.StringVar(value=str(self.settings.macro_loops))
        ttk.Entry(loop, width=8, textvariable=self.macro_loops_var).pack(side="left", padx=(6,14))

        mid = ttk.LabelFrame(macro, text="Passos gravados", padding=8)
        mid.pack(fill="both", expand=True, pady=8)
        self.steps_list = tk.Listbox(mid, height=12)
        self.steps_list.pack(fill="both", expand=True)

        # ===== Status (acima dos botões) =====
        st = ttk.LabelFrame(main, text="Status", padding=14)
        st.pack(fill="x", pady=10)
        self.status_var = tk.StringVar(value="Parado")
        ttk.Label(st, textvariable=self.status_var, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.stats_var = tk.StringVar(value="Cliques/Passos: 0 • Tempo: 00:00")
        ttk.Label(st, textvariable=self.stats_var).pack(anchor="w", pady=(6,2))

        # ===== Botões (sempre visíveis) =====
        btns = ttk.Frame(main); btns.pack(fill="x", pady=(6,0))
        self.start_btn = ttk.Button(btns, text="▶ Iniciar", command=self.start_current_tab_mode)
        self.start_btn.pack(side="left", padx=(0,8))
        self.stop_btn = ttk.Button(btns, text="⏹ Parar", command=self.stop_all, state="disabled")
        self.stop_btn.pack(side="left")
        ttk.Button(btns, text="💾 Salvar Config", command=self.save_current_settings).pack(side="right")

        self._load_macro_list_from_settings()

    def _hotrow(self, parent, label, var, cmd):
        row = ttk.Frame(parent); row.pack(fill="x", pady=3)
        ttk.Label(row, text=label).pack(side="left")
        ttk.Label(row, textvariable=var, width=12, relief="groove", anchor="center").pack(side="left", padx=8)
        ttk.Button(row, text="Gravar", command=cmd).pack(side="left")

    # helpers UI
    def _pos_text(self):
        if not self.settings.use_fixed_position:
            return "Posição: cursor atual do mouse"
        if self.settings.fixed_x is None or self.settings.fixed_y is None:
            return "Posição fixa: (não definida)"
        return f"Posição fixa: ({self.settings.fixed_x}, {self.settings.fixed_y})"

    def _toggle_pos(self):
        self.settings.use_fixed_position = True if self.use_fixed.get() else False
        self.pos_label.config(text=self._pos_text())

    def _record_hotkey(self, field: str):
        self.listener.set_record_field(field)

    def update_hotkey(self, field: str, token: str):
        if field == "toggle":
            self.settings.hotkey_toggle = token
            self.toggle_var.set(token_label(token))
        elif field == "emergency":
            self.settings.hotkey_emergency = token
            self.emerg_var.set(token_label(token))
        save_settings(self.settings)

    def set_status(self, text: str): self.status_var.set(text)
    def flash_info(self, text: str): messagebox.showinfo("Info", text)

    # --------- Macro helpers ----------
    def _load_macro_list_from_settings(self):
        self.steps_list.delete(0, tk.END)
        for step in self.settings.macro_steps:
            self.steps_list.insert(tk.END, self._step_to_str(step))

    def _step_to_str(self, step: dict) -> str:
        k = step["kind"]; v = step["value"]
        if k == "delay": return f"delay {v['seconds']:.3f}s"
        if k == "key":   return f"key {token_label(v['token'])}"
        if k == "click": return f"click {v['button']} @({v['x']},{v['y']})"
        return str(step)

    def clear_macro_steps_ui(self):
        self.settings.macro_steps = []
        self.steps_list.delete(0, tk.END); save_settings(self.settings)

    def clear_macro_steps(self): self.clear_macro_steps_ui()

    def append_macro_delay(self, seconds: float):
        seconds = max(0.0, float(seconds))
        step = {"kind":"delay", "value":{"seconds": seconds}}
        self.settings.macro_steps.append(step)
        self.steps_list.insert(tk.END, self._step_to_str(step)); save_settings(self.settings)

    def append_macro_key(self, token: str):
        step = {"kind":"key", "value":{"token": token}}
        self.settings.macro_steps.append(step)
        self.steps_list.insert(tk.END, self._step_to_str(step)); save_settings(self.settings)

    def append_macro_click(self, button: str, x: int, y: int):
        step = {"kind":"click", "value":{"button": button, "x": int(x), "y": int(y)}}
        self.settings.macro_steps.append(step)
        self.steps_list.insert(tk.END, self._step_to_str(step)); save_settings(self.settings)

    def start_macro_record(self): self.listener.start_macro_rec()
    def stop_macro_record(self):  self.listener.stop_macro_rec()

    # --------- ações principais ----------
    def current_mode(self) -> str:
        tab = self.tabs.tab(self.tabs.select(), "text")
        return "autoclick" if tab.lower().startswith("autoclick") else "macro"

    def toggle_start_stop(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.stop_all()
        else:
            self.start_current_tab_mode()

    def start_current_tab_mode(self):
        if self.worker_thread and self.worker_thread.is_alive(): return
        try:
            self._sync_ui_to_settings(); save_settings(self.settings)
        except ValueError as e:
            messagebox.showerror("Erro", str(e)); return

        self.stop_event.clear(); self.click_count = 0; self.start_time = None
        self.start_btn.config(state="disabled"); self.stop_btn.config(state="normal")
        self.status_var.set("Preparando...")

        mode = self.current_mode()
        target = self._worker_autoclick if mode == "autoclick" else self._worker_macro
        self.worker_thread = threading.Thread(target=target, daemon=True)
        self.worker_thread.start()
        if self.tray: self.tray.update_running()

    def stop_all(self):
        self.stop_event.set()
        self.start_btn.config(state="normal"); self.stop_btn.config(state="disabled")
        self.status_var.set("Parado")
        if self.tray: self.tray.update_running()

    def save_current_settings(self):
        try:
            self._sync_ui_to_settings(); save_settings(self.settings)
            self.pos_label.config(text=self._pos_text())
            messagebox.showinfo("Configurações", "Configurações salvas.")
        except ValueError as e:
            messagebox.showerror("Erro", str(e))

    def _sync_ui_to_settings(self):
        s = self.settings
        # comuns
        s.start_countdown = float(self.count_var.get())
        # autoclick
        s.delay_seconds = float(self.delay_var.get())
        s.delay_variation_pct = float(self.var_var.get())
        s.mouse_button = str(self.btn_var.get())
        s.click_type = str(self.type_var.get())
        s.use_fixed_position = bool(self.use_fixed.get())
        s.run_mode = str(self.runmode_var.get())
        s.run_amount = int(self.amount_var.get())
        # macro
        s.macro_use_recorded_delays = bool(self.macro_use_rec_var.get())
        s.macro_forced_delay = float(self.macro_fixed_delay_var.get())
        s.macro_loops = int(self.macro_loops_var.get())
        s.clamp()
        if s.use_fixed_position and (s.fixed_x is None or s.fixed_y is None):
            raise ValueError("Você marcou 'Usar posição fixa', mas não capturou as coordenadas.")

    def capture_position_ui(self):
        pos = pyautogui.position()
        self.settings.fixed_x, self.settings.fixed_y = int(pos.x), int(pos.y)
        self.settings.use_fixed_position = True
        self.use_fixed.set(True)
        self.pos_label.config(text=self._pos_text())
        save_settings(self.settings)
        self.flash_info(f"Posição capturada em ({pos.x}, {pos.y}).")

    # --------- apoio ---------
    def _countdown_block(self):
        if self.settings.start_countdown > 0:
            start = time.time()
            while not self.stop_event.is_set():
                rem = self.settings.start_countdown - (time.time() - start)
                if rem <= 0: break
                self.root.after(0, lambda r=max(0, rem): self.status_var.set(f"Iniciando em {r:0.1f}s…"))
                time.sleep(0.05)

    # --------- workers ----------
    def _worker_autoclick(self):
        try:
            self._countdown_block()
            if self.stop_event.is_set(): return
            self.start_time = time.time()
            self.root.after(0, lambda: self.status_var.set("Rodando (autoclick)…"))

            total = math.inf if self.settings.run_mode == "until_stop" else self.settings.run_amount
            while not self.stop_event.is_set() and self.click_count < total:
                if self.settings.use_fixed_position:
                    do_mouse_click(self.settings.mouse_button, self.settings.click_type=="double",
                                   x=int(self.settings.fixed_x), y=int(self.settings.fixed_y))
                else:
                    do_mouse_click(self.settings.mouse_button, self.settings.click_type=="double")

                self.click_count += 1

                d = human_delay(self.settings.delay_seconds, self.settings.delay_variation_pct)
                end = time.time() + d
                while time.time() < end and not self.stop_event.is_set():
                    time.sleep(min(0.02, end - time.time()))
        except pyautogui.FailSafeException:
            self.root.after(0, lambda: self.status_var.set("Parado (FailSafe)"))
        except Exception as e:
            print("Erro no autoclick:", repr(e))
            self.root.after(0, lambda: self.status_var.set("Erro — veja o console"))
        finally:
            self.root.after(0, self._finish)

    def _worker_macro(self):
        try:
            if not self.settings.macro_steps:
                self.root.after(0, lambda: messagebox.showwarning("Macro", "Nenhuma macro gravada.")); return

            self._countdown_block()
            if self.stop_event.is_set(): return

            self.start_time = time.time()
            self.root.after(0, lambda: self.status_var.set("Rodando (macro)…"))

            loops_left = math.inf if self.settings.macro_loops == 0 else self.settings.macro_loops

            while not self.stop_event.is_set() and loops_left > 0:
                for step in list(self.settings.macro_steps):
                    if self.stop_event.is_set(): break
                    k = step["kind"]; v = step["value"]
                    if k == "delay":
                        sec = v["seconds"] if self.settings.macro_use_recorded_delays else self.settings.macro_forced_delay
                        end = time.time() + max(0.0, float(sec))
                        while time.time() < end and not self.stop_event.is_set():
                            time.sleep(min(0.02, end - time.time()))
                    elif k == "key":
                        press_key_token(v["token"])
                    elif k == "click":
                        do_mouse_click(v["button"], False, x=int(v["x"]), y=int(v["y"]))
                if loops_left is not math.inf:
                    loops_left -= 1
        except pyautogui.FailSafeException:
            self.root.after(0, lambda: self.status_var.set("Parado (FailSafe)"))
        except Exception as e:
            print("Erro na macro:", repr(e))
            self.root.after(0, lambda: self.status_var.set("Erro — veja o console"))
        finally:
            self.root.after(0, self._finish)

    def _finish(self):
        self.start_btn.config(state="normal"); self.stop_btn.config(state="disabled")
        if self.tray: self.tray.update_running()

    def _tick(self):
        if self.start_time and (self.worker_thread and self.worker_thread.is_alive()):
            elapsed = int(time.time() - self.start_time); mm, ss = divmod(elapsed, 60)
            self.stats_var.set(f"Cliques/Passos: {self.click_count} • Tempo: {mm:02d}:{ss:02d}")
        else:
            self.stats_var.set("Cliques/Passos: 0 • Tempo: 00:00")
        self.root.after(100, self._tick)

    # --- tray/window helpers ---
    def _on_minimize(self, event):
        if self.root.state() == "iconic" and self.tray:
            self.root.withdraw(); self.tray.show()

    def toggle_window_visibility(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify(); self.tray.hide() if self.tray else None
        else:
            self.root.withdraw();  self.tray.show() if self.tray else None

    def engine_running(self): return bool(self.worker_thread and self.worker_thread.is_alive())

    def quit_from_tray(self):
        self.stop_all()
        if self.listener: self.listener.stop()
        if self.tray: self.tray.hide()
        self.root.after(100, self.root.destroy)

    def on_close(self): self.quit_from_tray()

# ----------------- MAIN -----------------
def main():
    try:
        import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception: pass

    root = tk.Tk()
    app = MTechClickerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()

if __name__ == "__main__":
    main()
