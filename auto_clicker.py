# -*- coding: utf-8 -*-
"""
轻量鼠标连点器 Auto Clicker v1.4(开源免费)
界面:主窗口只保留高频参数,高级功能收进顶部菜单
功能:
- 全局热键启停,热键可自定义(设置 → 热键设置)
- 点击间隔可调 + 随机浮动(避免机械节拍)
- 左/右/中键,单击 / 双击 / 按住模式
- 位置:跟随鼠标 / 固定坐标 / 多点循环(位置 → 点击位置)
- 次数限制、倒计时启动(设置 → 高级选项)
- 配置自动保存与恢复、系统托盘、高精度计时、DPI 感知
运行:pip install pynput && python auto_clicker.py
"""
import ctypes
import json
import os
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from pynput import mouse, keyboard

TRAY_OK = True          # 托盘用 Win32 原生 API 实现,不再依赖 pystray / Pillow

APP_TITLE = "轻量连点器 Auto Clicker"
APP_VERSION = "v1.4"
APP_ID = "AutoClicker.MouseTool.1"
GREEN = "#0a7d32"
AMBER = "#c47f00"
GRAY = "#8a8a8a"

BTN_MAP = {"左键": "left", "右键": "right", "中键": "middle"}
BTN_RMAP = {v: k for k, v in BTN_MAP.items()}

MOD_ALIAS = {"ctrl_l": "ctrl", "ctrl_r": "ctrl", "alt_l": "alt", "alt_r": "alt",
             "shift": "shift", "shift_l": "shift", "shift_r": "shift",
             "cmd": "cmd", "cmd_l": "cmd", "cmd_r": "cmd"}
MODS = {"ctrl", "alt", "shift", "cmd"}

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".auto_clicker.json")


def resource_path(name):
    """兼容源码运行与 PyInstaller 打包后的资源路径"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def enable_dpi_awareness():
    """启用 Windows DPI 感知,高分屏下界面清晰不模糊"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def set_app_user_model_id():
    """让任务栏正确识别本程序(否则可能仍显示 Python 图标)"""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def key_to_name(key):
    if isinstance(key, keyboard.Key):
        return MOD_ALIAS.get(key.name, key.name)
    if isinstance(key, keyboard.KeyCode) and key.char:
        return key.char.lower()
    return None


def combo_to_display(combo):
    """'<ctrl>+<f6>' → 'CTRL + F6'"""
    return " + ".join(part.strip("<>").upper() for part in combo.split("+"))


class PreciseTimer:
    """把 Windows 系统定时器精度提升到 1ms,退出时还原"""

    def __enter__(self):
        try:
            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            pass
        return self

    def __exit__(self, *exc):
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass


class AutoClicker:
    """核心逻辑:点击循环与状态,不依赖界面"""

    def __init__(self):
        self.running = threading.Event()
        self.count = 0
        self.phase = "idle"          # idle / countdown / running
        self._mouse = mouse.Controller()
        self._idx = 0

        self.interval_ms = 100
        self.jitter_pct = 0
        self.button = mouse.Button.left
        self.double = False
        self.hold_ms = 0
        self.repeat = 0
        self.fixed_pos = None
        self.points = []
        self.mode = "cursor"         # cursor / fixed / points
        self.countdown_s = 0
        self.hotkey = "<f6>"

    # ---------- 控制 ----------

    def start(self):
        if self.running.is_set():
            return
        self.count = 0
        self.running.set()
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.running.clear()
        self.phase = "idle"

    def toggle(self):
        if self.running.is_set():
            self.stop()
        else:
            self.start()

    def _run(self):
        if self.countdown_s > 0:
            self.phase = "countdown"
            end = time.perf_counter() + self.countdown_s
            while self.running.is_set() and time.perf_counter() < end:
                time.sleep(0.05)
            if not self.running.is_set():
                self.phase = "idle"
                return
        self.phase = "running"
        self._loop()
        self.phase = "idle"

    def _sleep_precise(self, ms):
        """高精度等待:sleep 掉大部分时间,最后 2ms 忙等校准"""
        if ms <= 0:
            return
        end = time.perf_counter() + ms / 1000.0
        if ms > 3:
            time.sleep((ms - 2) / 1000.0)
        while self.running.is_set() and time.perf_counter() < end:
            pass

    def _loop(self):
        n = 0
        self._idx = 0
        while self.running.is_set():
            if self.mode == "points" and self.points:
                self._mouse.position = self.points[self._idx % len(self.points)]
                self._idx += 1
            elif self.mode == "fixed" and self.fixed_pos:
                self._mouse.position = self.fixed_pos

            if self.hold_ms > 0:
                self._mouse.press(self.button)
                self._sleep_precise(self.hold_ms)
                self._mouse.release(self.button)
            else:
                self._mouse.click(self.button, 2 if self.double else 1)

            n += 1
            self.count = n
            if self.repeat and n >= self.repeat:
                self.running.clear()
                break

            iv = self.interval_ms
            if self.jitter_pct > 0:
                delta = iv * self.jitter_pct / 100.0
                iv = max(1, int(iv + random.uniform(-delta, delta)))
            self._sleep_precise(iv)


class HotkeyManager:
    """全局热键注册 + 按键捕获"""

    def __init__(self, on_trigger):
        self.on_trigger = on_trigger
        self.listener = None
        self.combo = None

    def register(self, combo) -> bool:
        self.unregister()
        try:
            listener = keyboard.GlobalHotKeys({combo: self.on_trigger})
            listener.daemon = True
            listener.start()
            self.listener, self.combo = listener, combo
            return True
        except Exception:
            self.listener = None
            return False

    def unregister(self):
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
            self.listener = None

    def capture(self, on_done, on_cancel):
        state = {"mods": set(), "done": False}

        def on_press(key):
            if state["done"]:
                return False
            name = key_to_name(key)
            if name is None:
                return
            if name in MODS:
                state["mods"].add(name)
                return
            state["done"] = True
            combo = "+".join([f"<{m}>" for m in sorted(state["mods"])] + [f"<{name}>"])
            listener.stop()
            on_done(combo)

        def on_release(key):
            if not state["done"] and key_to_name(key) == "esc":
                state["done"] = True
                listener.stop()
                on_cancel()

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_void_p, ctypes.c_uint,
                             ctypes.c_size_t, ctypes.c_ssize_t)


class NativeTray:
    """系统托盘:直接调 Win32 Shell_NotifyIcon,替代 pystray + Pillow。

    pystray 会带进 Pillow(约 11MB),Pillow 又连带 OpenSSL(约 10MB),
    而托盘图标只需要一个 HICON,用 LoadImage 从 ico 直接加载即可。
    """

    NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
    NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
    WM_APP = 0x8000
    WM_TRAY = WM_APP + 1
    WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0203, 0x0205
    WM_COMMAND, WM_CLOSE, WM_DESTROY = 0x0111, 0x0010, 0x0002
    ID_SHOW, ID_TOGGLE, ID_EXIT = 2001, 2002, 2003
    MF_STRING, MF_SEPARATOR = 0x0, 0x800
    IMAGE_ICON = 1
    LR_LOADFROMFILE, LR_DEFAULTSIZE = 0x0010, 0x0040
    TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0002, 0x0100

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong), ("hWnd", ctypes.c_void_p),
            ("uID", ctypes.c_uint), ("uFlags", ctypes.c_uint),
            ("uCallbackMessage", ctypes.c_uint), ("hIcon", ctypes.c_void_p),
            ("szTip", ctypes.c_wchar * 128), ("dwState", ctypes.c_ulong),
            ("dwStateMask", ctypes.c_ulong), ("szInfo", ctypes.c_wchar * 256),
            ("uVersion", ctypes.c_uint), ("szInfoTitle", ctypes.c_wchar * 64),
            ("dwInfoFlags", ctypes.c_ulong), ("guidItem", ctypes.c_byte * 16),
            ("hBalloonIcon", ctypes.c_void_p),
        ]

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint), ("style", ctypes.c_uint),
            ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int), ("hInstance", ctypes.c_void_p),
            ("hIcon", ctypes.c_void_p), ("hCursor", ctypes.c_void_p),
            ("hbrBackground", ctypes.c_void_p), ("lpszMenuName", ctypes.c_wchar_p),
            ("lpszClassName", ctypes.c_wchar_p), ("hIconSm", ctypes.c_void_p),
        ]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
            ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
            ("time", ctypes.c_ulong), ("pt", ctypes.c_long * 2),
        ]

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    def __init__(self, tip, icon_path, on_show, on_toggle, on_quit):
        self.tip = tip
        self.icon_path = icon_path
        self.on_show, self.on_toggle, self.on_quit = on_show, on_toggle, on_quit
        self._hwnd = None
        self._hicon = None
        self._ready = threading.Event()

    # ---------- 对外接口 ----------

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(3)
        return self._hwnd is not None

    def set_tip(self, text):
        self.tip = text[:127]
        if self._hwnd:
            ctypes.windll.user32.PostMessageW(self._hwnd, self.WM_APP + 2, 0, 0)

    def stop(self):
        if self._hwnd:
            ctypes.windll.user32.PostMessageW(self._hwnd, self.WM_CLOSE, 0, 0)

    # ---------- 内部实现 ----------

    def _run(self):
        u = ctypes.windll.user32
        shell = ctypes.windll.shell32
        u.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        u.LoadImageW.restype = ctypes.c_void_p
        shell.Shell_NotifyIconW.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        # 必须显式声明 64 位参数类型,否则 ctypes 默认按 32 位 c_int 转换,LPARAM 会溢出报错
        u.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                     ctypes.c_size_t, ctypes.c_ssize_t]
        u.DefWindowProcW.restype = ctypes.c_longlong
        u.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                   ctypes.c_size_t, ctypes.c_ssize_t]
        u.GetMessageW.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_uint, ctypes.c_uint]

        self._cb = WNDPROC(self._wnd_proc)

        cls_name = "AutoClickerTrayWindow"
        wcex = self.WNDCLASSEXW()
        wcex.cbSize = ctypes.sizeof(wcex)
        wcex.lpfnWndProc = self._cb
        wcex.lpszClassName = cls_name
        u.RegisterClassExW(ctypes.byref(wcex))

        hwnd = u.CreateWindowExW(0, cls_name, "", 0, 0, 0, 0, 0,
                                 ctypes.c_void_p(-3), None, None, None)  # HWND_MESSAGE
        if not hwnd:
            self._ready.set()
            return
        self._hwnd = hwnd

        self._hicon = u.LoadImageW(None, self.icon_path, self.IMAGE_ICON, 16, 16,
                                   self.LR_LOADFROMFILE | self.LR_DEFAULTSIZE)
        self._add_icon(shell)
        self._ready.set()

        msg = self.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

    def _add_icon(self, shell, modify=False):
        nid = self.NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        nid.uCallbackMessage = self.WM_TRAY
        nid.hIcon = self._hicon
        nid.szTip = self.tip[:127]
        shell.Shell_NotifyIconW(self.NIM_MODIFY if modify else self.NIM_ADD,
                                ctypes.byref(nid))

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        u = ctypes.windll.user32
        # LPARAM 在 Python 里是无符号传入的,超出 int64 正数范围时转成有符号,避免 ctypes 报错
        if lparam >= (1 << 63):
            lparam -= (1 << 64)
        if msg == self.WM_TRAY:
            if lparam == self.WM_LBUTTONDBLCLK:
                self.on_show()
                return 0
            if lparam == self.WM_RBUTTONUP:
                self._popup_menu(hwnd)
                return 0
        elif msg == self.WM_COMMAND:
            cmd = wparam & 0xFFFF
            if cmd == self.ID_SHOW:
                self.on_show()
            elif cmd == self.ID_TOGGLE:
                self.on_toggle()
            elif cmd == self.ID_EXIT:
                self.on_quit()
            return 0
        elif msg == self.WM_APP + 2:
            self._add_icon(ctypes.windll.shell32, modify=True)
            return 0
        elif msg == self.WM_CLOSE:
            u.DestroyWindow(hwnd)
            return 0
        elif msg == self.WM_DESTROY:
            nid = self.NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(nid)
            nid.hWnd = hwnd
            nid.uID = 1
            ctypes.windll.shell32.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(nid))
            u.PostQuitMessage(0)
            return 0
        return u.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _popup_menu(self, hwnd):
        u = ctypes.windll.user32
        u.AppendMenuW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t,
                                  ctypes.c_wchar_p]
        u.TrackPopupMenu.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                     ctypes.c_void_p]
        hmenu = u.CreatePopupMenu()
        u.AppendMenuW(hmenu, self.MF_STRING, self.ID_SHOW, "显示窗口")
        u.AppendMenuW(hmenu, self.MF_STRING, self.ID_TOGGLE, "启动 / 停止")
        u.AppendMenuW(hmenu, self.MF_SEPARATOR, 0, None)
        u.AppendMenuW(hmenu, self.MF_STRING, self.ID_EXIT, "退出")
        pt = self.POINT()
        u.GetCursorPos(ctypes.byref(pt))
        u.SetForegroundWindow(hwnd)
        cmd = u.TrackPopupMenu(hmenu, self.TPM_RIGHTBUTTON | self.TPM_RETURNCMD,
                               pt.x, pt.y, 0, hwnd, None)
        u.PostMessageW(hwnd, self.WM_COMMAND, cmd, 0)
        u.DestroyMenu(hmenu)


class App:
    """主窗口:只有高频参数;高级功能在菜单里"""

    def __init__(self, root: tk.Tk, clicker: AutoClicker):
        self.clicker = clicker
        self.root = root
        self.tray = None
        self._picked = None
        self._capturing = False
        self._last_tip = ""

        try:
            dpi = root.winfo_fpixels("1i")
            root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass

        root.withdraw()          # 先隐藏,布局完成后再显示,避免默认位置闪现
        root.title(f"{APP_TITLE} {APP_VERSION}")
        root.resizable(False, False)   # 固定尺寸(不启用自适应)
        # 窗口图标(标题栏左上角 / 任务栏)
        try:
            root.iconbitmap(resource_path("app.ico"))
        except Exception:
            pass

        cfg = self._load_config()
        self.hotkeys = HotkeyManager(self._on_hotkey)
        self._init_vars(cfg)
        self._build_menu()
        self._build_ui()

        combo = cfg.get("hotkey", "<f6>")
        self.hotkeys.register(combo)
        self.clicker.hotkey = combo

        if TRAY_OK:
            self._setup_tray()

        self._center_window()
        self._apply_topmost(save=False)   # 启动时应用置顶设置(不重复写配置)
        self._poll()

    # ---------------- 变量初始化 ----------------

    def _init_vars(self, cfg):
        c = self.clicker
        self.var_interval = tk.StringVar(value=str(cfg.get("interval_ms", 100)))
        self.var_jitter = tk.StringVar(value=str(cfg.get("jitter_pct", 0)))
        self.var_btn = tk.StringVar(value=BTN_RMAP.get(cfg.get("button", "left"), "左键"))
        self.var_double = tk.BooleanVar(value=bool(cfg.get("double", False)))
        hold = int(cfg.get("hold_ms", 0) or 0)
        self.var_hold_enable = tk.BooleanVar(value=hold > 0)
        self.var_hold_ms = tk.StringVar(value=str(hold if hold > 0 else 500))
        self.var_repeat = tk.StringVar(
            value=str(cfg["repeat"]) if cfg.get("repeat") else "")
        self.var_countdown = tk.StringVar(value=str(cfg.get("countdown_s", 0)))
        self.var_hotkey = tk.StringVar(value="F6")
        self.var_pos_summary = tk.StringVar(value="")
        self.var_state = tk.StringVar(value="已停止")
        self.var_topmost = tk.BooleanVar(value=bool(cfg.get("topmost", False)))

        c.mode = cfg.get("mode", "cursor")
        fp = cfg.get("fixed_pos")
        self._picked = tuple(fp) if fp else None
        c.points = [tuple(p) for p in cfg.get("points", [])]

    # ---------------- 菜单 ----------------

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="保存配置", command=self._menu_save)
        m_file.add_separator()
        m_file.add_command(label="退出", command=self.quit_app)
        menubar.add_cascade(label="文件", menu=m_file)

        m_pos = tk.Menu(menubar, tearoff=0)
        m_pos.add_command(label="点击位置...", command=self.open_position_dialog)
        menubar.add_cascade(label="位置", menu=m_pos)

        m_set = tk.Menu(menubar, tearoff=0)
        m_set.add_command(label="热键设置...", command=self.open_hotkey_dialog)
        m_set.add_command(label="高级选项...", command=self.open_advanced_dialog)
        menubar.add_cascade(label="设置", menu=m_set)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="使用说明", command=self.open_help_dialog)
        m_help.add_command(label="关于", command=self.open_about_dialog)
        menubar.add_cascade(label="帮助", menu=m_help)

        self.root.config(menu=menubar)

    # ---------------- 主界面 ----------------

    def _build_ui(self):
        pad = {"padx": 6, "pady": 5}
        frm = ttk.Frame(self.root, padding=16)
        frm.grid(sticky="nsew")

        # ---- 第 1 行:间隔 / 随机浮动 ----
        ttk.Label(frm, text="点击间隔(毫秒):").grid(row=0, column=0, sticky="w", **pad)
        ttk.Spinbox(frm, from_=1, to=60000, textvariable=self.var_interval,
                    width=8).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(frm, text="随机浮动 ±%:").grid(row=0, column=2, sticky="w", **pad)
        ttk.Spinbox(frm, from_=0, to=90, textvariable=self.var_jitter,
                    width=5).grid(row=0, column=3, sticky="w", **pad)

        # ---- 第 2 行:按键 / 双击 / 按住 ----
        ttk.Label(frm, text="鼠标按键:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Combobox(frm, textvariable=self.var_btn, values=["左键", "右键", "中键"],
                     width=6, state="readonly").grid(row=1, column=1, sticky="w", **pad)
        ttk.Checkbutton(frm, text="双击", variable=self.var_double).grid(
            row=1, column=2, sticky="w", **pad)
        ttk.Checkbutton(frm, text="按住", variable=self.var_hold_enable).grid(
            row=1, column=3, sticky="w", **pad)

        # ---- 第 3 行:点击次数 + 窗口置顶 ----
        ttk.Label(frm, text="点击次数(留空=无限):").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.var_repeat, width=10).grid(
            row=2, column=1, sticky="w", **pad)
        ttk.Checkbutton(frm, text="窗口置顶", variable=self.var_topmost,
                        command=self._apply_topmost).grid(
            row=2, column=2, columnspan=2, sticky="w", **pad)

        # ---- 启动按钮 ----
        self.btn_toggle = ttk.Button(frm, text="启动(F6)", command=self.toggle)
        self.btn_toggle.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(10, 8))

        # ---- 状态栏 ----
        bar = ttk.Frame(frm)
        bar.grid(row=4, column=0, columnspan=4, sticky="ew")
        bar.columnconfigure(0, weight=1)
        bar.columnconfigure(1, weight=1)
        self.lbl_state = ttk.Label(bar, textvariable=self.var_state,
                                   foreground=GRAY, font=("", 11, "bold"))
        self.lbl_state.grid(row=0, column=0, sticky="w")
        self.var_count = tk.StringVar(value="已点击:0 次")
        ttk.Label(bar, textvariable=self.var_count).grid(row=0, column=1, sticky="e")

        self.lbl_pos = ttk.Label(frm, textvariable=self.var_pos_summary, foreground=GRAY)
        self.lbl_pos.grid(row=5, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Label(frm, text="更多设置见上方菜单", foreground=GRAY).grid(
            row=6, column=0, columnspan=4, sticky="w", pady=(2, 0))

    # ---------------- 对话框基础 ----------------

    def _make_dialog(self, title):
        dlg = tk.Toplevel(self.root)
        dlg.withdraw()           # 先隐藏,定位后再显示,避免闪一下
        dlg.title(title)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        box = ttk.Frame(dlg, padding=16)
        box.grid(sticky="nsew")
        return dlg, box

    def _place_dialog(self, dlg):
        """按内容自适应并居中于主窗口,然后一次性显示并抓取焦点"""
        dlg.update_idletasks()
        w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        self.root.update_idletasks()
        pw, ph = self.root.winfo_width(), self.root.winfo_height()
        x = self.root.winfo_rootx() + (pw - w) // 2
        y = self.root.winfo_rooty() + (ph - h) // 2
        dlg.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dlg.deiconify()
        dlg.grab_set()

    # ---------------- 位置对话框 ----------------

    def open_position_dialog(self):
        c = self.clicker
        dlg, box = self._make_dialog("点击位置")
        pad = {"padx": 6, "pady": 4}
        state = {"picked": self._picked, "points": list(c.points)}
        mode_var = tk.StringVar(value=c.mode)
        pos_text = tk.StringVar(
            value=f"已拾取:{state['picked']}" if state["picked"] else "未拾取")

        ttk.Radiobutton(box, text="跟随当前鼠标", variable=mode_var,
                        value="cursor").grid(row=0, column=0, columnspan=3, sticky="w", **pad)

        r1 = ttk.Frame(box)
        r1.grid(row=1, column=0, columnspan=3, sticky="w", **pad)
        ttk.Radiobutton(r1, text="固定坐标", variable=mode_var,
                        value="fixed").grid(row=0, column=0, sticky="w")
        ttk.Button(r1, text="拾取位置(3秒)", command=lambda: pick()).grid(
            row=0, column=1, padx=8)
        ttk.Label(r1, textvariable=pos_text, foreground=GRAY).grid(row=0, column=2)

        ttk.Radiobutton(box, text="多点循环(依次点击下列坐标)", variable=mode_var,
                        value="points").grid(row=2, column=0, columnspan=3,
                                             sticky="w", **pad)

        lf = ttk.Frame(box)
        lf.grid(row=3, column=0, columnspan=3, sticky="w", **pad)
        lst = tk.Listbox(lf, height=6, width=26, activestyle="none")
        lst.grid(row=0, column=0)
        for p in state["points"]:
            lst.insert("end", f"({p[0]}, {p[1]})")
        btns = ttk.Frame(lf)
        btns.grid(row=0, column=1, sticky="n", padx=8)
        ttk.Button(btns, text="添加当前位置", width=13,
                   command=lambda: add_point()).grid(row=0, column=0, pady=2)
        ttk.Button(btns, text="删除选中", width=13,
                   command=lambda: del_point()).grid(row=1, column=0, pady=2)
        ttk.Button(btns, text="清空列表", width=13,
                   command=lambda: clear_points()).grid(row=2, column=0, pady=2)

        act = ttk.Frame(box)
        act.grid(row=4, column=0, columnspan=3, sticky="e", pady=(12, 0))

        def pick():
            pos_text.set("3 秒后拾取...")

            def grab():
                if not dlg.winfo_exists():
                    return
                xy = c._mouse.position
                state["picked"] = xy
                mode_var.set("fixed")
                pos_text.set(f"已拾取:{xy}")

            self.root.after(3000, grab)

        def add_point():
            xy = c._mouse.position
            state["points"].append(xy)
            lst.insert("end", f"({xy[0]}, {xy[1]})")

        def del_point():
            sel = lst.curselection()
            if sel:
                lst.delete(sel[0])
                del state["points"][sel[0]]

        def clear_points():
            lst.delete(0, "end")
            state["points"].clear()

        def ok():
            c.mode = mode_var.get()
            self._picked = state["picked"]
            c.fixed_pos = self._picked if c.mode == "fixed" else None
            c.points = list(state["points"])
            self.save_config()
            self._refresh_pos_summary()
            dlg.destroy()

        ttk.Button(act, text="取消", command=dlg.destroy, width=10).grid(
            row=0, column=0, padx=(0, 8))
        ttk.Button(act, text="确定", command=ok, width=10).grid(row=0, column=1)

        self._place_dialog(dlg)

    # ---------------- 热键对话框 ----------------

    def open_hotkey_dialog(self):
        dlg, box = self._make_dialog("热键设置")
        pad = {"padx": 6, "pady": 6}
        text = tk.StringVar(value=f"当前热键:{combo_to_display(self.clicker.hotkey)}")
        btn = ttk.Button(box, text="设置热键", width=14)
        btn.grid(row=1, column=0, pady=(4, 0))

        ttk.Label(box, textvariable=text, font=("", 11, "bold")).grid(
            row=0, column=0, sticky="w", **pad)
        ttk.Label(box, text="点击按钮后按任意组合键绑定,ESC 取消",
                  foreground=GRAY).grid(row=2, column=0, sticky="w", **pad)
        ttk.Button(box, text="关闭", command=dlg.destroy, width=10).grid(
            row=3, column=0, sticky="e", pady=(10, 0))

        def start_capture():
            if self._capturing:
                return
            self._capturing = True
            btn.config(text="请按键...")
            text.set("等待输入(ESC 取消)")

            def done(combo):
                ok_reg = self.hotkeys.register(combo)
                if ok_reg:
                    self.clicker.hotkey = combo
                self._capturing = False
                btn.config(text="设置热键")
                text.set(f"当前热键:{combo_to_display(self.clicker.hotkey)}")
                self.var_hotkey.set(combo_to_display(self.clicker.hotkey))
                self.save_config()
                if not ok_reg:
                    messagebox.showwarning(APP_TITLE, "该热键注册失败,已保留原热键")

            def cancel():
                self._capturing = False
                btn.config(text="设置热键")
                text.set(f"当前热键:{combo_to_display(self.clicker.hotkey)}")

            self.hotkeys.capture(lambda cb: self.root.after(0, lambda: done(cb)),
                                 lambda: self.root.after(0, cancel))

        btn.config(command=start_capture)
        self._place_dialog(dlg)

    # ---------------- 高级选项对话框 ----------------

    def open_advanced_dialog(self):
        dlg, box = self._make_dialog("高级选项")
        pad = {"padx": 6, "pady": 5}

        ttk.Label(box, text="倒计时启动(秒):").grid(row=0, column=0, sticky="w", **pad)
        ttk.Spinbox(box, from_=0, to=60, textvariable=self.var_countdown,
                    width=12).grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(box, text="按住时长(毫秒):").grid(row=1, column=0, sticky="w", **pad)
        ttk.Spinbox(box, from_=0, to=600000, textvariable=self.var_hold_ms,
                    width=12).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(box, text="主界面勾选「按住」后生效", foreground=GRAY).grid(
            row=2, column=0, columnspan=2, sticky="w", **pad)

        act = ttk.Frame(box)
        act.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))

        def ok():
            if self.apply_settings():
                self.save_config()
                dlg.destroy()

        ttk.Button(act, text="取消", command=dlg.destroy, width=10).grid(
            row=0, column=0, padx=(0, 8))
        ttk.Button(act, text="确定", command=ok, width=10).grid(row=0, column=1)

        self._place_dialog(dlg)

    # ---------------- 说明 / 关于 ----------------

    def open_help_dialog(self):
        dlg, box = self._make_dialog("使用说明")
        lines = [
            "1. 在主界面设好间隔与按键,按热键(默认 F6)开始 / 停止。",
            "2. 要点击固定位置或多点轮流点:菜单「位置 → 点击位置…」。",
            "3. 想换热键:菜单「设置 → 热键设置…」(点按钮后按任意键)。",
            "4. 要限定次数或延迟启动:菜单「设置 → 高级选项…」。",
            "5. 关闭窗口会最小化到托盘;彻底退出请用托盘右键「退出」。",
            "6. 所有设置自动保存,下次打开自动恢复。",
        ]
        for i, s in enumerate(lines):
            ttk.Label(box, text=s).grid(row=i, column=0, sticky="w", pady=2)
        ttk.Button(box, text="知道了", command=dlg.destroy, width=10).grid(
            row=len(lines), column=0, sticky="e", pady=(12, 0))
        self._place_dialog(dlg)

    def open_about_dialog(self):
        dlg, box = self._make_dialog("关于")
        ttk.Label(box, text=f"{APP_TITLE}  {APP_VERSION}",
                  font=("", 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(box, text="开源免费 · 单文件 · 无广告 · MIT License").grid(
            row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(box, text="仅用于合法的重复性操作辅助(软件测试、表单填写等),\n"
                            "请勿用于游戏作弊或违反平台规则的场景。",
                  foreground=GRAY, justify="left").grid(row=2, column=0, sticky="w",
                                                        pady=(8, 0))
        ttk.Button(box, text="确定", command=dlg.destroy, width=10).grid(
            row=3, column=0, sticky="e", pady=(12, 0))
        self._place_dialog(dlg)

    # ---------------- 配置 ----------------

    @staticmethod
    def _load_config() -> dict:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _menu_save(self):
        self.apply_settings()
        self.save_config()
        messagebox.showinfo(APP_TITLE, "配置已保存")

    def save_config(self):
        c = self.clicker
        data = {
            "interval_ms": c.interval_ms,
            "jitter_pct": c.jitter_pct,
            "button": BTN_MAP.get(self.var_btn.get(), "left"),
            "double": c.double,
            "hold_ms": c.hold_ms,
            "repeat": c.repeat,
            "countdown_s": c.countdown_s,
            "hotkey": c.hotkey,
            "mode": c.mode,
            "fixed_pos": list(c.fixed_pos) if c.fixed_pos else None,
            "points": [list(p) for p in c.points],
            "topmost": self.var_topmost.get(),
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------------- 行为 ----------------

    def toggle(self):
        if self.apply_settings():
            self.clicker.toggle()
            self.save_config()

    def _on_hotkey(self):
        self.root.after(0, self.toggle)

    def apply_settings(self) -> bool:
        c = self.clicker
        try:
            c.interval_ms = max(1, int(self.var_interval.get()))
            c.jitter_pct = max(0, min(90, int(self.var_jitter.get())))
            c.countdown_s = max(0, int(self.var_countdown.get()))
            hold = max(0, int(self.var_hold_ms.get()))
        except ValueError:
            messagebox.showwarning(APP_TITLE, "间隔 / 浮动 / 倒计时 / 按住时长 必须是数字")
            return False
        # 勾选"按住"但时长为 0 时给个默认值,避免无效
        c.hold_ms = (hold if hold > 0 else 500) if self.var_hold_enable.get() else 0
        rep = self.var_repeat.get().strip()
        if rep:
            try:
                c.repeat = max(1, int(rep))
            except ValueError:
                messagebox.showwarning(APP_TITLE, "点击次数必须是数字,或留空表示无限")
                return False
        else:
            c.repeat = 0
        c.button = getattr(mouse.Button, BTN_MAP.get(self.var_btn.get(), "left"))
        c.double = self.var_double.get()
        c.fixed_pos = self._picked if c.mode == "fixed" else None
        self._refresh_pos_summary()
        return True

    def _refresh_pos_summary(self):
        c = self.clicker
        if c.mode == "fixed":
            txt = f"位置:固定 {c.fixed_pos}" if c.fixed_pos else "位置:固定坐标(未拾取)"
        elif c.mode == "points":
            txt = f"位置:多点循环({len(c.points)} 个坐标)"
        else:
            txt = "位置:跟随当前鼠标"
        self.var_pos_summary.set(txt)

    # ---------------- 托盘 ----------------

    def _setup_tray(self):
        """托盘:完全走 Win32 API,不需要 pystray / Pillow"""
        try:
            self.tray = NativeTray(
                APP_TITLE,
                resource_path("app.ico"),
                lambda: self.root.after(0, self.show_window),
                lambda: self.root.after(0, self.toggle),
                lambda: self.root.after(0, self.quit_app),
            )
            if not self.tray.start():
                self.tray = None
        except Exception:
            self.tray = None

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        if self.var_topmost.get():
            self.root.attributes("-topmost", True)

    def on_close(self):
        if self.tray:
            self.save_config()
            self.root.withdraw()
        else:
            self.quit_app()

    def quit_app(self):
        self.clicker.stop()
        self.hotkeys.unregister()
        self.save_config()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()

    # ---------------- 其它 ----------------

    def _center_window(self):
        """在窗口显示前算好位置并一次性显示,避免先出现在默认位置再跳动"""
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x, y = max((sw - w) // 2, 0), max((sh - h) // 3, 0)
        self.root.geometry(f"+{x}+{y}")
        self.root.deiconify()

    def _apply_topmost(self, save=True):
        """窗口置顶开关(保存到配置,下次启动自动恢复)"""
        try:
            self.root.attributes("-topmost", bool(self.var_topmost.get()))
        except Exception:
            pass
        if save:
            self.save_config()

    def _poll(self):
        c = self.clicker
        if c.phase == "countdown":
            self.var_state.set("● 倒计时中")
            self.lbl_state.config(foreground=AMBER)
        elif c.running.is_set():
            self.var_state.set("● 运行中")
            self.lbl_state.config(foreground=GREEN)
        else:
            self.var_state.set("已停止")
            self.lbl_state.config(foreground=GRAY)
        if not self._capturing:
            self.btn_toggle.config(
                text=("停止" if c.running.is_set() else "启动")
                     + f"({combo_to_display(c.hotkey)})")
        self.var_count.set(f"已点击:{c.count} 次")
        tip = f"{APP_TITLE} · {self.var_state.get()}"
        if self.tray and tip != self._last_tip:     # 状态变化时同步托盘提示
            self._last_tip = tip
            self.tray.set_tip(tip)
        self.root.after(100, self._poll)


def main():
    enable_dpi_awareness()
    set_app_user_model_id()
    clicker = AutoClicker()
    root = tk.Tk()
    app = App(root, clicker)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    with PreciseTimer():
        root.mainloop()


if __name__ == "__main__":
    main()
