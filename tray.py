# -*- coding: utf-8 -*-
"""系统托盘图标（纯 ctypes，不引第三方依赖，PyInstaller 打进去就行）。

用法：
    tray = TrayIcon(tip="北通手柄映射器")
    tray.start([(1, "显示主界面"), None, (2, "退出")])
    ... Tk 主循环里定期 tray.poll() 拿被点的菜单 id ...
    tray.stop()

菜单项写成 (id, 文字, 是否打勾, 是否可用)，后两项可省；None 是分隔线。
双击图标 / 点菜单产生的动作都进内部队列，由 Tk 侧 poll() 取走，
**不直接从托盘线程碰 Tk 组件**（Tkinter 不是线程安全的）。
"""
import ctypes
import queue
import threading
from ctypes import wintypes

_user32 = ctypes.windll.user32
_shell32 = ctypes.windll.shell32
_gdi32 = ctypes.windll.gdi32

WM_NULL = 0x0000
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
TRAY_MSG = 0x0400 + 1          # uCallbackMessage

NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_INFO, NIIF_WARNING, NIIF_ERROR = 0x01, 0x02, 0x03

MF_STRING, MF_SEPARATOR = 0x0000, 0x0800
MF_CHECKED, MF_DISABLED, MF_GRAYED = 0x0008, 0x0002, 0x0001
TPM_LEFTALIGN, TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0000, 0x0002, 0x0100

HWND_MESSAGE = ctypes.c_void_p(-3)      # 只收消息、不显示的窗口

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)
_OWNERS = {}                            # hwnd(int) -> TrayIcon
_CLASS_OK = False


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_ubyte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_int),
        ("biHeight", ctypes.c_int), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_int),
        ("biYPelsPerMeter", ctypes.c_int), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def make_icon(size=32):
    """优先加载打包好的 icon.ico（手柄图），没有再退回程序画的圆盘"""
    try:
        from padui import app_icon_path
        p = app_icon_path()
        if p:
            h = _user32.LoadImageW(None, p, 1, size, size, 0x0010)
            if h:
                return h
    except Exception:
        pass
    return _procedural_icon(size)


def _procedural_icon(size=32):
    """兜底：程序画的图标——红圈 + 深色盘面 + 中心亮点"""
    bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), size, -size,
                          1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    hdc = _user32.GetDC(None)
    hbm = _gdi32.CreateDIBSection(hdc, ctypes.byref(bi), 0,
                                  ctypes.byref(bits), None, 0)
    _user32.ReleaseDC(None, hdc)
    if not hbm or not bits:
        return None
    px = ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint32))
    c = size / 2.0 - 0.5
    red = 0xFF4A33E0        # BGRA -> 0xAARRGGBB 里的 R=0xE0 G=0x33 B=0x4A
    dark = 0xFF2B2522
    light = 0xFFF4F0EE
    for y in range(size):
        for x in range(size):
            dx, dy = x - c, y - c
            d = (dx * dx + dy * dy) ** 0.5
            if d > c:
                px[y * size + x] = 0            # 圈外全透明
            elif d > c * 0.66:
                px[y * size + x] = red
            elif d > c * 0.24:
                px[y * size + x] = dark
            else:
                px[y * size + x] = light
    hmask = _gdi32.CreateBitmap(size, size, 1, 1, None)
    ii = ICONINFO(True, 0, 0, hmask, hbm)
    return _user32.CreateIconIndirect(ctypes.byref(ii))


def _wndproc(hwnd, msg, wparam, lparam):
    self = _OWNERS.get(hwnd)
    if msg == TRAY_MSG:
        if self is not None:
            if lparam in (WM_RBUTTONUP, WM_CONTEXTMENU):
                self._popup()
            elif lparam == WM_LBUTTONDBLCLK:
                self.queue.put("show")
        return 0
    if msg == WM_DESTROY:
        _user32.PostQuitMessage(0)
        return 0
    return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_PROC = WNDPROC(_wndproc)


def _register_class():
    """注册一个只收消息的隐藏窗口类（一个进程只需注册一次）"""
    global _CLASS_OK
    if _CLASS_OK:
        return True
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = _PROC
    wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
    wc.lpszClassName = "BetopMapperTray"
    _CLASS_OK = bool(_user32.RegisterClassExW(ctypes.byref(wc)))
    return _CLASS_OK


class TrayIcon:
    def __init__(self, tip="北通手柄映射器", balloon_title="北通手柄映射器"):
        self.tip = tip[:127]
        self.balloon_title = balloon_title
        self.queue = queue.Queue()
        self.items = []
        self.hwnd = None
        self.hicon = None
        self.alive = False
        self._thread = None

    # ------------------------------------------------------------ 生命周期
    def start(self, items=()):
        self.items = list(items or [])
        if not _register_class():
            return False
        self.hwnd = _user32.CreateWindowExW(
            0, "BetopMapperTray", "BetopMapperTray", 0,
            0, 0, 0, 0, HWND_MESSAGE, None,
            ctypes.windll.kernel32.GetModuleHandleW(None), None)
        if not self.hwnd:
            return False
        _OWNERS[int(self.hwnd)] = self
        self.hicon = make_icon()
        nid = self._nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        if not _shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            self.hwnd = None
            return False
        ver = self._nid(0)
        ver.uVersion = 3
        _shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(ver))
        self.alive = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        if not self.hwnd:
            return
        try:
            nid = self._nid(0)
            _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        except Exception:
            pass
        try:
            _user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        except Exception:
            pass
        if self.hicon:
            try:
                _user32.DestroyIcon(self.hicon)
            except Exception:
                pass
        _OWNERS.pop(int(self.hwnd), None)
        self.hwnd, self.hicon, self.alive = None, None, False

    def _loop(self):
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    # ------------------------------------------------------------ 菜单 / 提示
    def set_items(self, items):
        self.items = list(items or [])

    def set_tip(self, text):
        self.tip = (text or "")[:127]
        if self.hwnd:
            try:
                nid = self._nid(NIF_TIP)
                _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
            except Exception:
                pass

    def notify(self, text, title=None, kind=NIIF_INFO):
        """气泡提示"""
        if not self.hwnd:
            return
        try:
            nid = self._nid(NIF_INFO)
            nid.dwInfoFlags = kind
            nid.szInfo = (text or "")[:255]
            nid.szInfoTitle = ((title or self.balloon_title))[:63]
            _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    def poll(self):
        """Tk 侧每隔一会儿调一次，取走被点的菜单 id（"show" 表示双击图标）"""
        out = []
        while True:
            try:
                out.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return out

    # ------------------------------------------------------------ 内部
    def _nid(self, flags):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = TRAY_MSG
        nid.hIcon = self.hicon
        nid.szTip = self.tip
        return nid

    def _popup(self):
        """右键菜单。跑在托盘线程里（TrackPopupMenu 是阻塞的）"""
        hmenu = _user32.CreatePopupMenu()
        try:
            for it in self.items:
                if it is None:
                    _user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                    continue
                mid = it[0]
                text = it[1]
                checked = it[2] if len(it) > 2 else False
                enabled = it[3] if len(it) > 3 else True
                flags = MF_STRING | (MF_CHECKED if checked else 0)
                if not enabled:
                    flags |= MF_GRAYED | MF_DISABLED
                _user32.AppendMenuW(hmenu, flags, mid, text)
            pt = wintypes.POINT()
            _user32.GetCursorPos(ctypes.byref(pt))
            _user32.SetForegroundWindow(self.hwnd)
            cmd = _user32.TrackPopupMenu(
                hmenu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_LEFTALIGN,
                pt.x, pt.y, 0, self.hwnd, None)
            _user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)   # 修焦点残留
            if cmd:
                self.queue.put(cmd)
        finally:
            _user32.DestroyMenu(hmenu)


# 让签名固定下来，免得 ctypes 猜错参数类型
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR,
                                    wintypes.LPCWSTR, wintypes.DWORD,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                    wintypes.HINSTANCE, wintypes.LPVOID]
_user32.DefWindowProcW.restype = ctypes.c_ssize_t
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM]
_user32.TrackPopupMenu.restype = ctypes.c_int
_user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.LPCRECT if hasattr(wintypes, "LPCRECT")
                                   else ctypes.c_void_p]
_user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT,
                                ctypes.c_size_t, wintypes.LPCWSTR]
_gdi32.CreateDIBSection.restype = wintypes.HBITMAP
_gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                    ctypes.POINTER(ctypes.c_void_p),
                                    wintypes.HANDLE, wintypes.DWORD]
_shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
