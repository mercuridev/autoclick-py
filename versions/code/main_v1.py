import json
import math
import threading
import time
import tkinter as tk
from dataclasses import dataclass, asdict
from pathlib import Path
from tkinter import ttk, messagebox

# -------- backends de input --------
# Preferir pydirectinput (melhor em jogos); se não houver, usa pyautogui
HAVE_PDI = True
try:
    import pydirectinput as pdi
    pdi.PAUSE = 0
    pdi.FAILSAFE = False
except Exception:
    HAVE_PDI = False

import pyautogui
pyautogui.FAILSAFE = True  # mover mouse p/ canto sup. esquerdo = aborta quando usando pyautogui

from pynput import keyboard, mouse

# ----------------- CONFIG BÁSICA -----------------
SETTINGS_FILE = Path(__file__).with_name("settings.json")

# ----------------- MODELOS -----------------
@dataclass
class AppSettings:
    delay_seconds: float = 0.20
    delay_variation_pct: float = 0.0
    start_countdown: float = 0.0
    mouse_button: str = "left"     # left/right/middle
    click_type: str = "single"     # single/double
    use_fixed_position: bool = False
    fixed_x: int | None = None
    fixed_y: int | None = None
    run_mode: str = "until_stop"   # until_stop | fixed_amount
    run_amount: int = 100

    # atalhos (tokens)
    hotkey_toggle: str = "f8"      # inicia/para (toggle)
    hotkey_capture: str = "f9"     # captura posição
    hotkey_emergency: str = "esc"  # parada de emergência

    def clamp(self):
        self.delay_seconds = max(0.0, float(self.delay_seconds))
        self.delay_variation_pct = max(0.0, min(100.0, float(self.delay_variation_pct)))
        self.start_countdown = max(0.0, float(self.start_countdown))
        self.run_amount = max(1, int(self.run_amount))
        if self.mouse_button not in ("left", "right", "middle"):
            self.mouse_button = "left"
        if self.click_type not in ("single", "double"):
            self.click_type = "single"
        if self.run_mode not in ("until_stop", "fixed_amount"):
            self.run_mode = "until_stop"

def load_settings() -> AppSettings:
    try:
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            s = AppSettings(**data)
            s.clamp()
            return s
    except Exception:
        pass
    return AppSettings()

def save_settings(s: AppSettings):
    try:
        s.clamp()
        SETTINGS_FILE.write_text(json.dumps(asdict(s), indent=2), encoding="utf-8")
    except Exception as e:
        print("Falha ao salvar settings:", e)

# ------------ util: delay humano -------------
def human_delay(base: float, variation_pct: float) -> float:
    if variation_pct <= 0:
        return max(0.0, base)
    import random
    amp = base * (variation_pct / 100.0)
    return max(0.0, base + random.uniform(-amp, amp))

# ------------ normalização de atalhos -------------
def key_to_token(k) -> str | None:
    """Converte teclas do pynput em um token minúsculo padronizado."""
    if isinstance(k, keyboard.KeyCode) and k.char:
        return k.char.lower()
    if isinstance(k, keyboard.Key):
        name = str(k).split(".")[-1].lower()  # 'f8', 'esc', 'page_up'
        if name == "page_up":
            return "pgup"
        if name == "page_down":
            return "pgdn"
        if name == "space":
            return "space"
        return name
    return None

def mouse_to_token(btn) -> str | None:
    """Converte botões do mouse do pynput em token 'mouse.xxx'."""
    try:
        name = btn.name.lower()  # 'left','right','middle', possivelmente 'x1','x2' ou 'button8/9'
        if name in ("button8",): name = "x1"
        if name in ("button9",): name = "x2"
        return f"mouse.{name}"
    except Exception:
        return None

def token_label(tok: str) -> str:
    """Label amigável para a UI."""
    if tok.startswith("mouse."):
        return tok.replace("mouse.", "mouse ")
    if tok == "pgup":
        return "PgUp"
    if tok == "pgdn":
        return "PgDn"
    return tok.upper()

# ------------ Listener global (teclado e mouse) -------------
class GlobalListener(threading.Thread):
    def __init__(self, app_ref):
        super().__init__(daemon=True)
        self.app = app_ref
        self.k_listener = None
        self.m_listener = None
        self._stop = threading.Event()
        self.record_mode: str | None = None  # 'toggle' | 'capture' | 'emergency' | None

    def run(self):
        self.k_listener = keyboard.Listener(on_press=self.on_key_press)
        self.m_listener = mouse.Listener(on_click=self.on_click)
        self.k_listener.start()
        self.m_listener.start()
        while not self._stop.is_set():
            time.sleep(0.05)
        try:
            self.k_listener.stop()
            self.m_listener.stop()
        except Exception:
            pass

    def stop(self):
        self._stop.set()

    def set_record_mode(self, field: str | None):
        self.record_mode = field
        if field:
            self.app.set_status(f"Gravando atalho para {field}… pressione uma tecla OU botão do mouse.")
        else:
            self.app.set_status("Parado")

    # eventos
    def on_key_press(self, k):
        tok = key_to_token(k)
        if not tok:
            return
        if self.record_mode:
            self._persist_record(tok)
            return
        self._dispatch_token(tok)

    def on_click(self, x, y, button, pressed):
        if not pressed:
            return
        tok = mouse_to_token(button)
        if not tok:
            return
        if self.record_mode:
            self._persist_record(tok)
            return
        self._dispatch_token(tok)

    def _persist_record(self, tok: str):
        if self.record_mode == "toggle":
            self.app.update_hotkey("toggle", tok)
        elif self.record_mode == "capture":
            self.app.update_hotkey("capture", tok)
        elif self.record_mode == "emergency":
            self.app.update_hotkey("emergency", tok)
        self.set_record_mode(None)
        self.app.flash_info(f"Atalho definido: {token_label(tok)}")

    def _dispatch_token(self, tok: str):
        s = self.app.settings
        if tok == s.hotkey_emergency:
            self.app.root.after(0, self.app.stop_clicking)
            return
        if tok == s.hotkey_capture:
            self.app.root.after(0, self.app.capture_position_ui)
            return
        if tok == s.hotkey_toggle:
            self.app.root.after(0, self.app.toggle_start_stop)

# ----------------- APP -----------------
class AutoClickerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("AutoClicker Pro – hotkeys configuráveis")
        root.geometry("520x520")
        root.resizable(False, False)

        self.settings = load_settings()

        self.stop_event = threading.Event()
        self.click_thread: threading.Thread | None = None
        self.start_time = None
        self.click_count = 0

        self._build_ui()

        self.listener = GlobalListener(self)
        self.listener.start()

        self._tick()

    # ---- UI ----
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        # linha delay
        r1 = ttk.Frame(main)
        r1.pack(fill="x")
        ttk.Label(r1, text="Delay base (s):").pack(side="left")
        self.delay_var = tk.StringVar(value=str(self.settings.delay_seconds))
        ttk.Entry(r1, width=10, textvariable=self.delay_var).pack(side="left", padx=(6, 14))

        ttk.Label(r1, text="Variação (%)").pack(side="left")
        self.var_var = tk.StringVar(value=str(self.settings.delay_variation_pct))
        ttk.Entry(r1, width=8, textvariable=self.var_var).pack(side="left")

        # contagem
        r2 = ttk.Frame(main); r2.pack(fill="x", pady=(6,0))
        ttk.Label(r2, text="Contagem inicial (s):").pack(side="left")
        self.count_var = tk.StringVar(value=str(self.settings.start_countdown))
        ttk.Entry(r2, width=10, textvariable=self.count_var).pack(side="left", padx=(6, 14))

        # mouse e tipo clique
        r3 = ttk.Frame(main); r3.pack(fill="x", pady=(6,0))
        ttk.Label(r3, text="Botão do mouse:").pack(side="left")
        self.btn_var = tk.StringVar(value=self.settings.mouse_button)
        ttk.Combobox(r3, width=10, state="readonly", textvariable=self.btn_var,
                     values=["left","right","middle"]).pack(side="left", padx=(6, 14))
        ttk.Label(r3, text="Tipo de clique:").pack(side="left")
        self.type_var = tk.StringVar(value=self.settings.click_type)
        ttk.Combobox(r3, width=10, state="readonly", textvariable=self.type_var,
                     values=["single","double"]).pack(side="left")

        # execução
        r4 = ttk.Frame(main); r4.pack(fill="x", pady=(6,0))
        ttk.Label(r4, text="Execução:").pack(side="left")
        self.runmode_var = tk.StringVar(value=self.settings.run_mode)
        ttk.Combobox(r4, width=15, state="readonly", textvariable=self.runmode_var,
                     values=["until_stop","fixed_amount"]).pack(side="left", padx=(6, 14))
        ttk.Label(r4, text="Qtde (se 'fixed_amount'):").pack(side="left")
        self.amount_var = tk.StringVar(value=str(self.settings.run_amount))
        ttk.Entry(r4, width=8, textvariable=self.amount_var).pack(side="left")

        # posição
        pos = ttk.LabelFrame(main, text="Destino do clique", padding=10)
        pos.pack(fill="x", pady=8)
        self.use_fixed = tk.BooleanVar(value=self.settings.use_fixed_position)
        ttk.Checkbutton(pos, text="Usar posição fixa", variable=self.use_fixed,
                        command=self._toggle_pos).grid(row=0,column=0,sticky="w")
        self.pos_label = ttk.Label(pos, text=self._pos_text())
        self.pos_label.grid(row=1, column=0, sticky="w", pady=(6,0))
        ttk.Button(pos, text="Capturar agora", command=self.capture_position_ui).grid(row=1, column=1, padx=8)

        # atalhos
        hot = ttk.LabelFrame(main, text="Atalhos (clique em GRAVAR e pressione uma tecla ou botão do mouse)", padding=10)
        hot.pack(fill="x", pady=8)

        self.toggle_var = tk.StringVar(value=token_label(self.settings.hotkey_toggle))
        self.capture_var = tk.StringVar(value=token_label(self.settings.hotkey_capture))
        self.emerg_var = tk.StringVar(value=token_label(self.settings.hotkey_emergency))

        self._hotrow(hot, "Iniciar/Parar (toggle):", self.toggle_var, lambda: self._record_hotkey("toggle"))
        self._hotrow(hot, "Capturar posição:", self.capture_var, lambda: self._record_hotkey("capture"))
        self._hotrow(hot, "Emergência (parar):", self.emerg_var, lambda: self._record_hotkey("emergency"))

        # botões
        btns = ttk.Frame(main); btns.pack(fill="x", pady=(6,0))
        self.start_btn = ttk.Button(btns, text="Iniciar", command=self.start_clicking)
        self.start_btn.pack(side="left", padx=(0,8))
        self.stop_btn = ttk.Button(btns, text="Parar", command=self.stop_clicking, state="disabled")
        self.stop_btn.pack(side="left")
        ttk.Button(btns, text="Salvar Config", command=self.save_current_settings).pack(side="right")

        # status
        st = ttk.LabelFrame(main, text="Status", padding=10)
        st.pack(fill="x", pady=8)
        self.status_var = tk.StringVar(value="Parado")
        ttk.Label(st, textvariable=self.status_var).pack(anchor="w")
        self.stats_var = tk.StringVar(value="Cliques: 0 • Tempo: 00:00")
        ttk.Label(st, textvariable=self.stats_var, foreground="#555").pack(anchor="w", pady=(6,0))

        tip = ("Dica: F-keys, PgUp/PgDn, letras/números e mouse.middle/x1/x2 funcionam nos atalhos.\n"
               "Para jogos, execute o programa como Administrador e use modo janela/borderless se necessário.")
        ttk.Label(main, text=tip, foreground="#666", wraplength=480, justify="left").pack(fill="x", pady=(6,0))

    def _hotrow(self, parent, label, var, cmd):
        row = ttk.Frame(parent); row.pack(fill="x", pady=3)
        ttk.Label(row, text=label).pack(side="left")
        ttk.Label(row, textvariable=var, width=10, relief="groove", anchor="center").pack(side="left", padx=8)
        ttk.Button(row, text="Gravar", command=cmd).pack(side="left")

    # helpers UI
    def _pos_text(self):
        if not self.settings.use_fixed_position:
            return "Posição: cursor atual do mouse"
        if self.settings.fixed_x is None or self.settings.fixed_y is None:
            return "Posição fixa: (não definida)"
        return f"Posição fixa: ({self.settings.fixed_x}, {self.settings.fixed_y})"

    def _toggle_pos(self):
        self.settings.use_fixed_position = bool(self.use_fixed.get())
        self.pos_label.config(text=self._pos_text())

    def _record_hotkey(self, field: str):
        self.listener.set_record_mode(field)

    def update_hotkey(self, field: str, token: str):
        if field == "toggle":
            self.settings.hotkey_toggle = token
            self.toggle_var.set(token_label(token))
        elif field == "capture":
            self.settings.hotkey_capture = token
            self.capture_var.set(token_label(token))
        elif field == "emergency":
            self.settings.hotkey_emergency = token
            self.emerg_var.set(token_label(token))
        save_settings(self.settings)

    def set_status(self, text: str):
        self.status_var.set(text)

    def flash_info(self, text: str):
        messagebox.showinfo("Atalho", text)

    # ações principais
    def toggle_start_stop(self):
        if self.click_thread and self.click_thread.is_alive():
            self.stop_clicking()
        else:
            self.start_clicking()

    def save_current_settings(self):
        try:
            s = self._read_settings_from_ui()
            save_settings(s)
            self.settings = s
            self.pos_label.config(text=self._pos_text())
            messagebox.showinfo("Configurações", "Configurações salvas.")
        except ValueError as e:
            messagebox.showerror("Erro", str(e))

    def _read_settings_from_ui(self) -> AppSettings:
        try:
            s = AppSettings(
                delay_seconds=float(self.delay_var.get()),
                delay_variation_pct=float(self.var_var.get()),
                start_countdown=float(self.count_var.get()),
                mouse_button=str(self.btn_var.get()),
                click_type=str(self.type_var.get()),
                use_fixed_position=bool(self.use_fixed.get()),
                fixed_x=self.settings.fixed_x,
                fixed_y=self.settings.fixed_y,
                run_mode=str(self.runmode_var.get()),
                run_amount=int(self.amount_var.get()),
                hotkey_toggle=self.settings.hotkey_toggle,
                hotkey_capture=self.settings.hotkey_capture,
                hotkey_emergency=self.settings.hotkey_emergency,
            )
            s.clamp()
            if s.use_fixed_position and (s.fixed_x is None or s.fixed_y is None):
                raise ValueError("Você marcou 'Usar posição fixa', mas não capturou as coordenadas.")
            return s
        except ValueError:
            raise ValueError("Valores inválidos. Verifique delay, variação, contagem e quantidade.")

    def capture_position_ui(self):
        pos = pyautogui.position()
        self.settings.fixed_x, self.settings.fixed_y = int(pos.x), int(pos.y)
        self.settings.use_fixed_position = True
        self.use_fixed.set(True)
        self.pos_label.config(text=self._pos_text())
        save_settings(self.settings)
        self.flash_info(f"Posição capturada em ({pos.x}, {pos.y}).")

    def start_clicking(self):
        if self.click_thread and self.click_thread.is_alive():
            return
        try:
            self.settings = self._read_settings_from_ui()
            save_settings(self.settings)
        except ValueError as e:
            messagebox.showerror("Erro", str(e)); return

        self.stop_event.clear()
        self.click_count = 0
        self.start_time = None

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("Preparando...")

        self.click_thread = threading.Thread(target=self._worker, daemon=True)
        self.click_thread.start()

    def stop_clicking(self):
        self.stop_event.set()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("Parado")

    def _worker(self):
        try:
            if self.settings.start_countdown > 0:
                start = time.time()
                while not self.stop_event.is_set():
                    rem = self.settings.start_countdown - (time.time() - start)
                    if rem <= 0:
                        break
                    self.root.after(0, lambda r=max(0, rem): self.status_var.set(f"Iniciando em {r:0.1f}s…"))
                    time.sleep(0.05)

            if self.stop_event.is_set(): return

            self.start_time = time.time()
            self.root.after(0, lambda: self.status_var.set("Rodando…"))

            total = math.inf if self.settings.run_mode == "until_stop" else self.settings.run_amount

            while not self.stop_event.is_set() and self.click_count < total:
                if self.settings.use_fixed_position:
                    x = int(self.settings.fixed_x)
                    y = int(self.settings.fixed_y)
                    self._do_click(x, y)
                else:
                    self._do_click(None, None)

                self.click_count += 1

                d = human_delay(self.settings.delay_seconds, self.settings.delay_variation_pct)
                end = time.time() + d
                while time.time() < end and not self.stop_event.is_set():
                    time.sleep(min(0.02, end - time.time()))
        except pyautogui.FailSafeException:
            self.root.after(0, lambda: self.status_var.set("Parado (FailSafe)"))
        except Exception as e:
            print("Erro no worker:", repr(e))
            self.root.after(0, lambda: self.status_var.set("Erro — veja o console"))
        finally:
            self.root.after(0, self._finish)

    def _finish(self):
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _do_click(self, x: int | None, y: int | None):
        """Clica usando pydirectinput (se disponível) ou pyautogui."""
        btn = self.settings.mouse_button
        dbl = (self.settings.click_type == "double")

        if HAVE_PDI:
            # pydirectinput aceita x/y; se None, clica na posição atual
            if x is not None and y is not None:
                pdi.moveTo(x, y)
            if dbl:
                if x is None: pdi.doubleClick(button=btn)
                else:         pdi.doubleClick(x=x, y=y, button=btn)
            else:
                if x is None: pdi.click(button=btn)
                else:         pdi.click(x=x, y=y, button=btn)
        else:
            if dbl:
                if x is None: pyautogui.doubleClick(button=btn)
                else:         pyautogui.doubleClick(x=x, y=y, button=btn)
            else:
                if x is None: pyautogui.click(button=btn)
                else:         pyautogui.click(x=x, y=y, button=btn)

    def _tick(self):
        if self.start_time and (self.click_thread and self.click_thread.is_alive()):
            elapsed = int(time.time() - self.start_time)
            mm, ss = divmod(elapsed, 60)
            self.stats_var.set(f"Cliques: {self.click_count} • Tempo: {mm:02d}:{ss:02d}")
        else:
            self.stats_var.set("Cliques: 0 • Tempo: 00:00")
        self.root.after(100, self._tick)

    def on_close(self):
        try:
            self.stop_event.set()
            if self.listener:
                self.listener.stop()
        finally:
            self.root.destroy()

# ----------------- MAIN -----------------
def main():
    # DPI awareness no Windows (opcional)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass

    app = AutoClickerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()

if __name__ == "__main__":
    main()
