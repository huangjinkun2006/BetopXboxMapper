"""手机通知 -> 手柄震动。

思路：本机在局域网里起一个极简 HTTP 服务，手机上用「自动化 / 宏」把通知
转发成一次 HTTP 请求打过来，程序收到就按选好的铃声震一下手柄。

手机端（安卓 MacroDroid / Tasker，iOS 快捷指令）只要能发 HTTP 请求就行。
手机浏览器直接打开本机地址也能用（页面上有测试按钮）。
"""

import collections
import json
import queue
import re
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import tkinter as tk
    from tkinter import messagebox
except Exception:
    tk = None
    messagebox = None

# W/H 是类属性，导入时就求值，FT/S 必须在模块级就能拿到
from padui import FT, S

try:
    import alarm          # 复用闹钟那套铃声
except Exception:
    alarm = None

DEFAULT_PORT = 9595

# 过滤模式：存英文，界面显示中文
MODES = {"all": "全部通知", "allow": "只震这些", "block": "屏蔽这些"}


# ---------------------------------------------------------------- 本机地址
def lan_ips():
    """列出本机局域网 IPv4（用于给手机填地址）"""
    ips = []
    try:                                  # 不需要真发包，只为拿到出口网卡 IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip:
            ips.append(ip)
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips or ["127.0.0.1"]


def split_keys(s):
    return [k.strip().lower() for k in re.split(r"[,，;；\s]+", s or "")
            if k.strip()]


# ---------------------------------------------------------------- HTTP
def _make_handler(owner):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "BetopNotify"

        def log_message(self, *a):        # 别把每条请求都打到控制台
            pass

        # ------------------------------------------------ 输出
        def _send(self, body, ctype, code=200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def _json(self, obj, code=200):
            self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", code)

        def _html(self, text):
            self._send(text.encode("utf-8"), "text/html; charset=utf-8")

        # ------------------------------------------------ 入口
        def do_GET(self):
            self._handle({})

        def do_POST(self):
            n = 0
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except Exception:
                n = 0
            raw = self.rfile.read(n) if n else b""
            extra = {}
            if raw:
                try:
                    j = json.loads(raw.decode("utf-8"))
                    if isinstance(j, dict):
                        extra = {str(k): str(v) for k, v in j.items()
                                 if v is not None}
                except Exception:
                    try:
                        extra = dict(urllib.parse.parse_qsl(
                            raw.decode("utf-8", "replace")))
                    except Exception:
                        extra = {}
            self._handle(extra)

        def do_OPTIONS(self):
            self._send(b"", "text/plain")

        # ------------------------------------------------ 分发
        def _handle(self, extra):
            u = urllib.parse.urlparse(self.path)
            path = (u.path or "/").rstrip("/") or "/"
            q = {}
            try:
                q = dict(urllib.parse.parse_qsl(u.query, encoding="utf-8"))
            except Exception:
                q = {}
            q.update(extra)
            peer = ""
            try:
                peer = self.client_address[0]
            except Exception:
                pass

            if path == "/":
                return self._html(owner.home_html())
            if path in ("/status", "/state"):
                return self._json({"on": True, "port": owner.port,
                                   "ring": owner.km.get("notify_ring", 4)})
            if path in ("/notify", "/ping", "/send", "/test", "/buzz"):
                ok, why = owner.hit(q, peer)
                return self._json({"ok": ok, "reason": why})
            return self._json({"ok": False, "reason": "no such path"}, 404)

    return H


# ---------------------------------------------------------------- 服务
class NotifyServer:
    """局域网收通知，命中就回调让手柄震一下"""

    def __init__(self, km, on_hit=None):
        self.km = km
        self.on_hit = on_hit       # 在工作线程里调，别直接碰 UI
        self.q = queue.Queue()     # (kind, info) 给主界面轮询
        self.log = collections.deque(maxlen=20)
        self.srv = None
        self.th = None
        self.err = ""
        self._bound = None         # 实际监听的端口（改端口要重启）
        self._last = {}            # app -> 上次震的时间（冷却用）

    # ------------------------------------------------------------ 配置
    @property
    def port(self):
        try:
            return int(self.km.get("notify_port") or DEFAULT_PORT)
        except Exception:
            return DEFAULT_PORT

    @property
    def ring(self):
        try:
            return int(self.km.get("notify_ring", 4))
        except Exception:
            return 4

    @property
    def strength(self):
        try:
            return float(self.km.get("notify_strength", 1.0))
        except Exception:
            return 1.0

    @property
    def seconds(self):
        try:
            return float(self.km.get("notify_secs", 1.2))
        except Exception:
            return 1.2

    def running(self):
        return self.srv is not None

    def urls(self):
        return ["http://%s:%d" % (ip, self.port) for ip in lan_ips()]

    # ------------------------------------------------------------ 启停
    def start(self):
        if self.srv is not None:
            return True, ""
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", self.port),
                                      _make_handler(self))
            srv.daemon_threads = True
        except Exception as e:
            self.err = str(e)
            return False, str(e)
        self.srv = srv
        self.err = ""
        self._bound = self.port
        self.th = threading.Thread(target=srv.serve_forever, daemon=True)
        self.th.start()
        self.q.put(("on", {"port": self.port, "urls": self.urls()}))
        return True, ""

    def stop(self):
        self._bound = None
        srv, self.srv = self.srv, None
        if srv is None:
            return
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass
        self.q.put(("off", {}))

    # ------------------------------------------------------------ 命中
    def hit(self, params, peer=""):
        """一条通知到了：过滤 -> 冷却 -> 入队 -> 回调"""
        app = str(params.get("app") or params.get("pkg")
                  or params.get("package") or "")
        title = str(params.get("title") or params.get("text")
                    or params.get("msg") or "")
        text = str(params.get("body") or params.get("content") or "")
        info = {"app": app, "title": title, "text": text, "from": peer,
                "ts": time.time()}

        tok = (self.km.get("notify_token") or "").strip()
        if tok and str(params.get("token") or "") != tok:
            self._push(info, "令牌不对")
            return False, "令牌不对"

        mode = self.km.get("notify_filter_mode", "all")
        keys = split_keys(self.km.get("notify_filter", ""))
        if mode in ("allow", "block") and keys:
            hay = ("%s %s %s" % (app, title, text)).lower()
            hit = any(k in hay for k in keys)
            if mode == "allow" and not hit:
                self._push(info, "不在名单里")
                return False, "不在名单里"
            if mode == "block" and hit:
                self._push(info, "被屏蔽")
                return False, "被屏蔽"

        try:
            cd = float(self.km.get("notify_cooldown", 3) or 0)
        except Exception:
            cd = 3.0
        key = (app or title or "?").lower()
        now = time.time()
        if cd > 0 and now - self._last.get(key, 0) < cd:
            self._push(info, "冷却中（%.0fs）" % cd)
            return False, "冷却中"
        self._last[key] = now

        self._push(info, "已震动")
        try:
            if self.on_hit is not None:
                self.on_hit(info)
        except Exception:
            pass
        return True, ""

    def _push(self, info, why):
        self.log.appendleft((info, why))
        self.q.put(("hit", dict(info, why=why)))

    def test(self):
        """本地自测：假装来了一条通知"""
        return self.hit({"app": "本机测试",
                         "title": "这是测试通知"}, "127.0.0.1")

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.q.get_nowait())
            except Exception:
                break
        return out

    # ------------------------------------------------------------ 网页
    def home_html(self):
        url = self.urls()[0]
        return """<!doctype html><meta name="viewport"
content="width=device-width,initial-scale=1">
<title>手柄震动</title>
<!--URL:__URL__-->
<body style="font-family:system-ui;margin:0;padding:18px;background:#f5f6f8">
<h3 style="margin:0 0 6px">✅ 连上电脑了</h3>
<p style="color:#666;font-size:14px">点下面的按钮，手柄应该会震一下：</p>
<button onclick="go('/notify?app=%E6%89%8B%E6%9C%BA%E6%B5%8B%E8%AF%95')"
 style="font-size:17px;padding:12px 20px;border:0;border-radius:8px;
 background:#e0334a;color:#fff">震一下</button>
<button onclick="go('/notify?app=test&title=hello')"
 style="font-size:14px;padding:10px 14px;border:0;border-radius:8px;
 background:#e8eaee">再震（带标题）</button>
<p id="r" style="font-family:monospace;font-size:13px"></p>
<hr style="border:0;border-top:1px solid #e3e5e9;margin:16px 0">
<p style="color:#666;font-size:13px">把这段地址填进手机自动化里就行：</p>
<code style="background:#e8eaee;padding:6px 8px;border-radius:6px;
 display:block;word-break:break-all">__URL__/notify</code>
<p style="color:#999;font-size:12px">安卓用 MacroDroid / Tasker，
苹果用「快捷指令」自动化（收到通知 -> 获取 URL 内容）。</p>
<script>
function go(u){fetch(u).then(r=>r.json()).then(j=>{
 document.getElementById('r').textContent=JSON.stringify(j);}).catch(e=>{
 document.getElementById('r').textContent=String(e);});}
</script></body>""".replace("__URL__", url)


# ---------------------------------------------------------------- 防火墙
def allow_firewall(exe_path=None):
    """请求放行入站（要弹 UAC）。返回 (有没有发出请求, 说明)"""
    import os
    import subprocess
    if not exe_path:
        exe_path = os.path.abspath(__file__)
    name = "BetopMapper 手机通知"
    ps = ('New-NetFirewallRule -DisplayName "%s" -Direction Inbound '
          '-Program "%s" -Action Allow -Profile Any -ErrorAction SilentlyContinue'
          % (name, exe_path))
    try:
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "powershell.exe",
            '-NoProfile -Command "%s"' % ps.replace('"', '\\"'), None, 0)
        if rc > 32:
            return True, "已提交（UAC 里点了「是」就生效）"
        return False, "没弹出来或被取消（代码 %s）" % rc
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------- 界面
if tk is not None:
    class NotifyDialog(tk.Toplevel):
        """手机通知设置窗"""

        W, H = S(462), S(620)
        FONT = "Microsoft YaHei UI"

        def __init__(self, master, app):
            super().__init__(master)
            self.app = app
            self.km = app.km
            self.ns = app.notify
            self.title("手机通知 → 手柄震动")
            self.configure(bg="#f5f6f8")
            try:
                from padui import apply_icon
                apply_icon(self)
            except Exception:
                pass
            self.resizable(False, False)
            self.transient(master)
            try:
                self.grab_set()
            except Exception:
                pass
            self._place(master)
            self.protocol("WM_DELETE_WINDOW", self.destroy)
            self._build()
            self._tick()

        def _place(self, master):
            try:
                self.update_idletasks()
                x = master.winfo_rootx() + (master.winfo_width() - self.W) // 2
                y = master.winfo_rooty() + (master.winfo_height() - self.H) // 2
                self.geometry("%dx%d+%d+%d" % (self.W, self.H, max(0, x),
                                               max(0, y)))
            except Exception:
                self.geometry("%dx%d" % (self.W, self.H))

        # -------------------------------------------------------- 构建
        def _build(self):
            from padui import FT, S
            F = self.FONT
            hd = tk.Frame(self, bg="#fff", height=64)
            hd.pack(fill="x")
            hd.pack_propagate(False)
            tk.Label(hd, text="📱  手机通知", font=FT(15, "bold"),
                     fg="#22252b", bg="#fff").pack(side="left", padx=S(22))
            tk.Label(hd, text="来消息就震一下", font=FT(9),
                     fg="#8a8f99", bg="#fff").pack(side="right", padx=S(22))

            box = tk.Frame(self, bg="#fff", highlightthickness=1,
                           highlightbackground="#e5e7ec")
            box.pack(fill="both", expand=True, padx=S(20), pady=S(14))

            # 开关
            self.on_var = tk.BooleanVar(value=bool(self.km.get("notify_on")))
            tk.Checkbutton(box, text="开启（局域网接收手机通知）",
                           variable=self.on_var, font=FT(10, "bold"),
                           fg="#3a3e46", bg="#fff", activebackground="#fff",
                           selectcolor="#fff",
                           command=self._on_toggle).pack(anchor="w", padx=S(18),
                                                        pady=(S(14), S(4)))

            # 地址
            self.url_lbl = tk.Label(box, text="", font=FT(10, family="Consolas"),
                                    fg="#1e7e34", bg="#eef7f0",
                                    wraplength=S(390), justify="left")
            self.url_lbl.pack(fill="x", padx=S(18), pady=(S(2), S(4)))
            br = tk.Frame(box, bg="#fff")
            br.pack(fill="x", padx=S(18), pady=(S(0), S(6)))
            tk.Button(br, text="复制地址", font=FT(8), bg="#f0f1f4",
                      relief="flat", padx=S(8), pady=S(3), cursor="hand2",
                      command=self._copy).pack(side="left")
            tk.Button(br, text="放行防火墙", font=FT(8), bg="#f0f1f4",
                      relief="flat", padx=S(8), pady=S(3), cursor="hand2",
                      command=self._fw).pack(side="left", padx=S(6))
            tk.Button(br, text="测试震动", font=FT(8), fg="white",
                      bg="#e0334a", activebackground="#c02a3e",
                      activeforeground="white", relief="flat", padx=S(8), pady=S(3),
                      cursor="hand2", command=self.ns.test).pack(side="left")

            # 端口
            pr = tk.Frame(box, bg="#fff")
            pr.pack(fill="x", padx=S(18), pady=(S(4), S(2)))
            tk.Label(pr, text="端口", font=FT(9), fg="#3a3e46",
                     bg="#fff").pack(side="left")
            self.port_var = tk.StringVar(value=str(self.ns.port))
            e = tk.Entry(pr, textvariable=self.port_var, width=7,
                         font=FT(10, family="Consolas"), relief="flat", bg="#f4f5f8",
                         justify="center")
            e.pack(side="left", padx=S(8))
            e.bind("<Return>", lambda _e: self._apply())

            # 铃声
            rr = tk.Frame(box, bg="#fff")
            rr.pack(fill="x", padx=S(18), pady=(S(10), S(2)))
            tk.Label(rr, text="震动样式", font=FT(9), fg="#3a3e46",
                     bg="#fff").pack(side="left")
            names = alarm.ring_names() if alarm else ["连续猛震"]
            self.ring_var = tk.StringVar(value=names[min(
                self.ns.ring, len(names) - 1)])
            om = tk.OptionMenu(rr, self.ring_var, *names)
            om.config(font=FT(9), bg="#fff", relief="flat", width=11,
                      highlightthickness=0, cursor="hand2")
            try:
                om["menu"].config(font=FT(9), bg="#fff")
            except Exception:
                pass
            om.pack(side="left", padx=S(8))
            self.ring_var.trace_add("write", lambda *_a: self._apply())

            # 强度 + 时长
            sr = tk.Frame(box, bg="#fff")
            sr.pack(fill="x", padx=S(18), pady=(S(6), S(2)))
            tk.Label(sr, text="强度", font=FT(9), fg="#3a3e46",
                     bg="#fff").pack(side="left")
            self.st_var = tk.DoubleVar(value=self.ns.strength)
            tk.Scale(sr, from_=0.1, to=3.0, resolution=0.05,
                     variable=self.st_var, orient="horizontal", length=150,
                     bg="#fff", highlightthickness=0, troughcolor="#f0f1f4",
                     command=lambda _v: self._apply()).pack(side="left",
                                                            padx=S(6))
            tk.Label(sr, text="秒", font=FT(9), fg="#3a3e46",
                     bg="#fff").pack(side="left", padx=(10, 0))
            self.sec_var = tk.StringVar(value="%.1f" % self.ns.seconds)
            tk.Spinbox(sr, from_=0.3, to=10, increment=0.3, width=4,
                       textvariable=self.sec_var, font=FT(10, family="Consolas"),
                       relief="flat", bg="#f4f5f8", justify="center",
                       command=self._apply).pack(side="left", padx=S(4))

            # 过滤
            fr = tk.Frame(box, bg="#fff")
            fr.pack(fill="x", padx=S(18), pady=(S(12), S(2)))
            self.mode_var = tk.StringVar(value=MODES.get(
                self.km.get("notify_filter_mode", "all"), MODES["all"]))
            om2 = tk.OptionMenu(fr, self.mode_var, *MODES.values())
            om2.config(font=FT(9), bg="#fff", relief="flat", width=8,
                       highlightthickness=0, cursor="hand2")
            try:
                om2["menu"].config(font=FT(9), bg="#fff")
            except Exception:
                pass
            om2.pack(side="left")
            tk.Label(fr, text="关键词（逗号分隔，留空=全部通知）",
                     font=FT(8), fg="#8a8f99", bg="#fff").pack(side="left",
                                                                padx=S(6))
            self.flt_var = tk.StringVar(value=self.km.get("notify_filter", ""))
            tk.Entry(fr, textvariable=self.flt_var, width=22, font=FT(9),
                     relief="flat", bg="#f4f5f8").pack(side="left", padx=S(4))
            self.flt_var.trace_add("write", lambda *_a: self._apply())
            self.mode_var.trace_add("write", lambda *_a: self._apply())

            # 冷却 + 令牌
            cr = tk.Frame(box, bg="#fff")
            cr.pack(fill="x", padx=S(18), pady=(S(8), S(2)))
            tk.Label(cr, text="同一个 app 冷却", font=FT(9), fg="#3a3e46",
                     bg="#fff").pack(side="left")
            self.cd_var = tk.StringVar(
                value=str(self.km.get("notify_cooldown", 3)))
            tk.Spinbox(cr, from_=0, to=60, increment=1, width=4,
                       textvariable=self.cd_var, font=FT(10, family="Consolas"),
                       relief="flat", bg="#f4f5f8", justify="center",
                       command=self._apply).pack(side="left", padx=S(6))
            tk.Label(cr, text="秒", font=FT(9), fg="#8a8f99",
                     bg="#fff").pack(side="left")
            tk.Label(cr, text="口令", font=FT(9), fg="#3a3e46",
                     bg="#fff").pack(side="left", padx=(14, 0))
            self.tok_var = tk.StringVar(value=self.km.get("notify_token", ""))
            tk.Entry(cr, textvariable=self.tok_var, width=10, font=FT(9),
                     relief="flat", bg="#f4f5f8").pack(side="left", padx=S(4))

            # 最近收到
            tk.Label(box, text="最近收到", font=FT(9, "bold"), fg="#3a3e46",
                     bg="#fff").pack(anchor="w", padx=S(18), pady=(S(14), S(2)))
            self.txt = tk.Text(box, height=7, font=FT(9, family="Consolas"),
                               relief="flat", bg="#f7f8fa", fg="#3a3e46",
                               highlightthickness=0, wrap="word")
            self.txt.pack(fill="x", padx=S(18))
            self.txt.config(state="disabled")

            # 手机端怎么配
            self.help_lbl = tk.Label(
                box, text="", font=FT(8), fg="#8a8f99", bg="#fff",
                wraplength=S(400), justify="left")
            self.help_lbl.pack(anchor="w", padx=S(18), pady=(S(10), S(4)))
            self._upd_help()

        # -------------------------------------------------------- 动作
        def _upd_help(self):
            self.help_lbl.config(text=PHONE_HELP)

        def _on_toggle(self):
            self.km["notify_on"] = bool(self.on_var.get())
            try:
                import betop
                betop.save_keymap(self.km)
            except Exception:
                pass
            self.app.apply_notify_cfg()

        def _apply(self):
            try:
                self.km["notify_port"] = int(self.port_var.get())
            except Exception:
                pass
            if alarm is not None:
                try:
                    self.km["notify_ring"] = alarm.ring_names().index(
                        self.ring_var.get())
                except Exception:
                    pass
            self.km["notify_strength"] = float(self.st_var.get())
            try:
                self.km["notify_secs"] = float(self.sec_var.get())
            except Exception:
                pass
            self.km["notify_filter"] = self.flt_var.get().strip()
            for k, v in MODES.items():       # 中文标签 -> 存回英文
                if v == self.mode_var.get():
                    self.km["notify_filter_mode"] = k
                    break
            try:
                self.km["notify_cooldown"] = float(self.cd_var.get())
            except Exception:
                pass
            self.km["notify_token"] = self.tok_var.get().strip()
            try:
                import betop
                betop.save_keymap(self.km)
            except Exception:
                pass

        def _copy(self):
            urls = self.ns.urls()
            txt = urls[0] if urls else ""
            try:
                self.clipboard_clear()
                self.clipboard_append(txt)
                self.url_lbl.config(text=txt + "   （已复制）")
            except Exception:
                pass

        def _fw(self):
            import os
            import sys
            exe = os.path.abspath(sys.argv[0])
            ok, msg = allow_firewall(exe)
            if messagebox is not None:
                if ok:
                    messagebox.showinfo("放行防火墙", msg, parent=self)
                else:
                    messagebox.showwarning("放行防火墙",
                                           "没成：" + msg +
                                           "\n\n可以手动：Windows 防火墙 → "
                                           "允许应用通过 → 勾上本程序（专用网络）",
                                           parent=self)

        # -------------------------------------------------------- 刷新
        def _tick(self):
            try:
                if self.ns.running():
                    urls = self.ns.urls()
                    tip = "手机填这个地址（一般第一个）：\n"
                    if len(urls) > 1:
                        tip += "\n".join(urls[:2])
                    else:
                        tip += "\n".join(urls)
                    self.url_lbl.config(text=tip, fg="#1e7e34",
                                        bg="#eef7f0")
                else:
                    self.url_lbl.config(
                        text="没在监听" + ("（%s）" % self.ns.err
                                          if self.ns.err else ""),
                        fg="#a0a4ad", bg="#f4f5f8")
                self.txt.config(state="normal")
                self.txt.delete("1.0", "end")
                for info, why in list(self.ns.log)[:7]:
                    ts = time.strftime("%H:%M:%S",
                                       time.localtime(info.get("ts", 0)))
                    src = info.get("app") or info.get("from") or "?"
                    ttl = (info.get("title") or "")[:28]
                    self.txt.insert("end", "%s  %-10s %-8s %s\n"
                                    % (ts, src, why, ttl))
                self.txt.config(state="disabled")
            except Exception:
                pass
            self.after(400, self._tick)


PHONE_HELP = (
    "手机怎么配：\n"
    "1. 手机和电脑连同一个 WiFi\n"
    "2. 安卓装 MacroDroid（免费）→ 加宏：触发器「收到通知」→ 选应用；\n"
    "   动作「HTTP 请求」→ GET，地址填上面那个 + /notify\n"
    "   （想带内容就加参数 ?app=微信&title=新消息）\n"
    "3. 苹果：快捷指令 → 自动化 → 「收到通知时」→ 添加操作「获取 URL 内容」\n"
    "4. 手机浏览器直接打开那个地址，也能点按钮测震动\n"
    "连不上多半是防火墙拦了 → 点「放行防火墙」"
)
