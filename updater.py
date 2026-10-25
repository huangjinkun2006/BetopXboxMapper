# -*- coding: utf-8 -*-
"""检查更新：读 GitHub 上最新的 Release，跟本地版本号比一比。

版本号跟 Release 的 tag 保持一致（v1.0.1 -> 1.0.1）。
网络走不通时不会卡界面，全部在后台线程里跑。
"""
import json
import os
import re
import ssl
import threading
import urllib.request
import webbrowser

try:
    import tkinter as tk
    from tkinter import scrolledtext, ttk, messagebox
except Exception:          # 无界面环境下也能当纯模块用
    tk = None

APP_VERSION = "1.0.25"
REPO = "huangjinkun2006/BetopXboxMapper"
API_LATEST = "https://api.github.com/repos/%s/releases/latest" % REPO
API_RELEASES = "https://api.github.com/repos/%s/releases?per_page=20" % REPO
PAGE_LATEST = "https://github.com/%s/releases/latest" % REPO

# 试过的代理端口（本机代理端口会漂，挨个试）
PROBE_PROXIES = ("http://127.0.0.1:7890", "http://127.0.0.1:7891",
                 "http://127.0.0.1:7897", "http://127.0.0.1:10809",
                 "http://127.0.0.1:1080", "http://127.0.0.1:20171")


def ver_tuple(s):
    """"v1.0.1" / "1.0.1-beta" -> (1, 0, 1)"""
    nums = re.findall(r"\d+", str(s or ""))
    return tuple(int(n) for n in nums[:4]) if nums else (0,)


def system_proxy():
    """读 Windows 系统代理（IE / 设置里那个），代理端口老变，靠这个自动跟上"""
    try:
        import winreg
        k = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        try:
            enabled, _ = winreg.QueryValueEx(k, "ProxyEnable")
            raw, _ = winreg.QueryValueEx(k, "ProxyServer")
        finally:
            winreg.CloseKey(k)
        if not enabled or not raw:
            return None
        parts = [p.strip() for p in str(raw).split(";") if p.strip()]
        pick = None
        for p in parts:
            low = p.lower()
            if low.startswith("https="):
                pick = p.split("=", 1)[1]
                break
            if low.startswith("http=") and pick is None:
                pick = p.split("=", 1)[1]
        if pick is None and parts:
            pick = parts[0]
        if not pick:
            return None
        return pick if "://" in pick else "http://" + pick
    except Exception:
        return None


def _openers():
    """先直连，再试环境变量里的代理、系统代理，最后扫常见代理端口（顺序固定，别用 set）"""
    yield urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    order = []
    for k in ("https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        v = os.environ.get(k)
        if v and v not in order:
            order.append(v)
    sp = system_proxy()
    if sp and sp not in order:
        order.append(sp)
    for p in PROBE_PROXIES:
        if p not in order:
            order.append(p)
    for p in order:
        yield urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": p, "https": p}))


def _get(url, timeout=6):
    """挨个通道试，拿到 JSON 就返回，全失败抛最后一个异常。
    直连那一发只给 3 秒，省得没代理时白等"""
    last = None
    for i, op in enumerate(_openers()):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "BetopXboxMapper/" + APP_VERSION,
                              "Accept": "application/vnd.github+json"})
            with op.open(req, timeout=(3 if i == 0 else timeout)) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            last = e
    raise last if last is not None else RuntimeError("no opener")


def plain_body(md):
    """把 Release 说明里的 markdown 符号去掉一点，纯文本读着舒服些"""
    out = []
    for ln in (md or "").splitlines():
        s = ln.strip()
        if set(s) <= set("|-: "):        # 表格分隔行
            continue
        s = s.strip("|").replace("|", "  ·  ")
        s = s.replace("**", "").replace("`", "")
        s = re.sub(r"^#{1,6}\s*", "▸ ", s)
        s = re.sub(r"^[-*]\s+", "· ", s)
        out.append(s.rstrip())
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def _pack(d):
    """把 GitHub 的 release JSON 压成我们要的几项"""
    assets = []
    for a in d.get("assets") or []:
        assets.append({
            "name": a.get("name", ""),
            "size": a.get("size", 0),
            "url": a.get("browser_download_url", ""),
            "downloads": a.get("download_count", 0),
        })
    return {
        "tag": d.get("tag_name", ""),
        "version": (d.get("tag_name") or "").lstrip("vV"),
        "name": d.get("name") or d.get("tag_name") or "",
        "body": (d.get("body") or "").strip(),
        "published": (d.get("published_at") or "")[:10],
        "url": d.get("html_url") or PAGE_LATEST,
        "assets": assets,
    }


def is_pc_release(d):
    """同一个仓库里还发安卓版（tag 用 android-vX.Y.Z），这里只认 PC 的 vX.Y.Z"""
    tag = (d.get("tag_name") or "").strip()
    return tag[:1].lower() == "v" and not tag.lower().startswith("android")


def fetch_latest(timeout=6):
    """拿最新的 PC 版 Release。

    不能直接吃 /releases/latest —— 那个仓库里安卓版也发在同一个地方，
    谁后发谁就是 latest，会把 v1.0.9 判成"没更新"。所以拉列表自己筛。
    """
    try:
        lst = _get(API_RELEASES, timeout)
        cands = [d for d in lst if is_pc_release(d)]
        if cands:
            best = max(cands, key=lambda d: ver_tuple(d.get("tag_name")))
            return _pack(best), None
        return None, "仓库里还没有 PC 版 Release"
    except Exception as e1:
        try:
            return _pack(_get(API_LATEST, timeout)), None
        except Exception as e2:
            return None, _err_text(e2 if not str(e1) else e1)


def fetch_history(limit=8, timeout=6):
    """最近几个版本，用于「历史更新」列表（同样只列 PC 的）"""
    try:
        lst = [d for d in _get(API_RELEASES, timeout) if is_pc_release(d)]
        return [_pack(d) for d in lst[:limit]], None
    except Exception as e:
        return [], _err_text(e)


def _err_text(e):
    s = "%s: %s" % (type(e).__name__, e)
    if "timed out" in s or "timeout" in s.lower():
        return "连不上 GitHub（超时）。挂了代理的话在环境变量里设 https_proxy 再试"
    if "401" in s or "403" in s:
        return "GitHub 接口被限流了，稍等几分钟再试"
    if "getaddrinfo" in s or "Name or service" in s:
        return "连不上 GitHub，检查网络 / 代理"
    return s


def compare(a_ver, b_ver=APP_VERSION):
    """a 比 b 新就 >0，一样 0，a 旧就 <0。
    查更新统一写 compare(远端版本, APP_VERSION)：>0 = 有新版本"""
    a, b = ver_tuple(a_ver), ver_tuple(b_ver)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return (a > b) - (a < b)


def check_async(on_done, timeout=6):
    """后台线程查一次，回调 (info, err, cmp)，cmp > 0 表示有新版本。
    注意：回调跑在子线程里，别在里面碰 Tk 组件（Tkinter 不是线程安全的）。
    要更新界面请用 check_async_tk。"""
    def run():
        info, err = fetch_latest(timeout)
        cmp_ = 0 if (info is None) else compare(info["version"], APP_VERSION)
        try:
            on_done(info, err, cmp_)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def check_async_tk(widget, on_done, timeout=6, interval=120):
    """给界面用的版本：后台查，主线程轮询拿结果，on_done 保证在主线程执行。
    on_done(info, err, cmp)，cmp > 0 表示有新版本。
    widget 传任意一个 Tk 组件（用来挂 after 定时器）。"""
    box = {}

    def run():
        try:
            info, err = fetch_latest(timeout)
        except Exception as e:
            info, err = None, _err_text(e)
        box["info"], box["err"] = info, err
        box["cmp"] = 0 if (info is None) else compare(info["version"], APP_VERSION)
        box["done"] = True

    threading.Thread(target=run, daemon=True).start()

    def poll():
        if not widget.winfo_exists():
            return
        if box.get("done"):
            try:
                on_done(box.get("info"), box.get("err"), box.get("cmp", 0))
            except Exception:
                pass
            return
        try:
            widget.after(interval, poll)
        except Exception:
            pass

    widget.after(interval, poll)


def main_asset(info):
    """挑一个最像安装包的资产给用户下载"""
    if not info or not info.get("assets"):
        return None
    for a in info["assets"]:
        if "setup" in a["name"].lower():
            return a
    for a in info["assets"]:
        if a["name"].lower().endswith(".exe"):
            return a
    return info["assets"][0]


def human_size(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return "%g %s" % (round(n, 1), u)
        n /= 1024
    return "%g B" % n


def open_page(url=None):
    try:
        webbrowser.open(url or PAGE_LATEST)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 下载
def default_download_dir():
    """下载到哪：优先 Downloads / 下载，都没有就用用户目录"""
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "Downloads"),
                 os.path.join(home, "下载"), home):
        if os.path.isdir(cand):
            return cand
    return home


def _unique_path(path):
    """同名文件不覆盖，加 (1) (2)"""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists("%s (%d)%s" % (base, n, ext)):
        n += 1
    return "%s (%d)%s" % (base, n, ext)


def download_file(url, dest, on_progress=None, should_stop=None, timeout=30):
    """真正把文件拉下来（不是开浏览器）。

    走和 fetch 一样的通道顺序：直连 -> 环境变量代理 -> 常见代理端口，
    某个通道断了就换下一个从头再来一次。
    on_progress(got, total) 在子线程里回调；should_stop() 返回 True 就中断。
    返回 (dest, None) 成功 / (None, 错误文本) 失败。
    """
    last = None
    for i, op in enumerate(_openers()):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "BetopXboxMapper/" + APP_VERSION})
            # 直连那一发别给太长，省得没代理时干等
            with op.open(req, timeout=(8 if i == 0 else timeout)) as r:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                with open(dest, "wb") as f:
                    while True:
                        if should_stop and should_stop():
                            raise RuntimeError("已取消")
                        chunk = r.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if on_progress:
                            on_progress(got, total)
                if got <= 0:
                    raise RuntimeError("下载到 0 字节")
                return dest, None
        except Exception as e:
            last = e
            try:
                if os.path.exists(dest):
                    os.remove(dest)
            except Exception:
                pass
    return None, (_err_text(last) if last else "下载失败")


def download_async_tk(widget, url, dest, on_progress, on_done, interval=100):
    """子线程下载，主线程收进度和结果（Tkinter 不能跨线程碰组件）。
    on_progress(got, total) / on_done(dest, err)。返回的 box 里置 stop=True 可取消。"""
    box = {"done": False, "stop": False, "got": 0, "total": 0,
           "dest": None, "err": None}

    def prog(g, t):
        box["got"], box["total"] = g, t

    def run():
        d, e = download_file(url, dest, prog, lambda: box["stop"])
        box["dest"], box["err"] = d, e
        box["done"] = True

    threading.Thread(target=run, daemon=True).start()

    def poll():
        if not widget.winfo_exists():
            return
        if box.get("done"):
            try:
                on_done(box.get("dest"), box.get("err"))
            except Exception:
                pass
            return
        try:
            on_progress(box.get("got", 0), box.get("total", 0))
        except Exception:
            pass
        try:
            widget.after(interval, poll)
        except Exception:
            pass

    widget.after(interval, poll)
    return box


# ---------------------------------------------------------------- 界面
class UpdateDialog(tk.Toplevel if tk else object):
    """检查更新窗口：显示当前版本、最新结果、更新说明、下载按钮"""

    W, H = 480, 520

    def __init__(self, master, auto=False, on_result=None):
        super().__init__(master)
        self.on_result = on_result      # 查完顺手把主界面左下角也刷一下
        self.title("检查更新")
        self.configure(bg="#f5f6f8")
        self.resizable(False, False)
        self.transient(master)
        try:
            self.grab_set()
        except Exception:
            pass
        self._place(master)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.info = None
        self.err = None
        self.cmp = 0
        self._dots = 0
        self._busy = True
        self._dl_box = None       # 下载任务的控制盒（置 stop=True 取消）
        self._dl_dest = None      # 下完的文件路径

        self._build()
        self._check()

    def _place(self, master):
        try:
            self.update_idletasks()
            x = master.winfo_rootx() + (master.winfo_width() - self.W) // 2
            y = master.winfo_rooty() + (master.winfo_height() - self.H) // 2
            self.geometry("%dx%d+%d+%d" % (self.W, self.H, max(0, x), max(0, y)))
        except Exception:
            self.geometry("%dx%d" % (self.W, self.H))

    def _build(self):
        hd = tk.Frame(self, bg="#fff", height=70)
        hd.pack(fill="x")
        hd.pack_propagate(False)
        tk.Label(hd, text="🔄  检查更新", font=("Microsoft YaHei UI", 15, "bold"),
                 fg="#22252b", bg="#fff").pack(side="left", padx=22)
        self.ver_lbl = tk.Label(hd, text="v" + APP_VERSION, font=("Consolas", 10),
                                fg="#8a8f99", bg="#fff")
        self.ver_lbl.pack(side="right", padx=22)

        self.state_lbl = tk.Label(self, text="正在连接 GitHub",
                                  font=("Microsoft YaHei UI", 12, "bold"),
                                  fg="#8a8f99", bg="#f5f6f8")
        self.state_lbl.pack(pady=(26, 2))
        self.sub_lbl = tk.Label(self, text="", font=("Microsoft YaHei UI", 9),
                                fg="#8a8f99", bg="#f5f6f8")
        self.sub_lbl.pack()

        box = tk.Frame(self, bg="#fff", highlightthickness=1,
                       highlightbackground="#e5e7ec")
        box.pack(fill="both", expand=True, padx=20, pady=(16, 8))
        self.txt = scrolledtext.ScrolledText(
            box, font=("Microsoft YaHei UI", 9), wrap="word",
            relief="flat", bg="#fff", fg="#3a3e46", padx=10, pady=8,
            spacing1=2, spacing3=2)
        self.txt.pack(fill="both", expand=True)
        self.txt.insert("1.0", "正在读取最新 Release …")
        self.txt.configure(state="disabled")

        # 进度条：只有真下载时才塞进来（放在说明框和按钮之间）
        self.pb = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.br = br = tk.Frame(self, bg="#f5f6f8")
        br.pack(fill="x", padx=20, pady=(0, 8))

        BF = ("Microsoft YaHei UI", 10)
        self.btn_dl = tk.Button(br, text="⬇ 下载新版", font=(BF[0], 10, "bold"),
                                bg="#e0334a", fg="#fff", relief="flat", padx=16, pady=7,
                                cursor="hand2", state="disabled", command=self._download)
        self.btn_dl.pack(side="left")
        self.btn_more = tk.Button(br, text="其它文件 ▾", font=BF,
                                  bg="#fff", fg="#4a4e57", relief="flat", padx=12, pady=7,
                                  cursor="hand2", state="disabled",
                                  command=self._menu)
        self.btn_more.pack(side="left", padx=8)
        self.btn_close = tk.Button(br, text="关闭", font=BF,
                                   bg="#fff", fg="#4a4e57", relief="flat", padx=14, pady=7,
                                   cursor="hand2", command=self.destroy)
        self.btn_close.pack(side="right")

        br2 = tk.Frame(self, bg="#f5f6f8")
        br2.pack(fill="x", padx=20, pady=(0, 14))
        self.btn_recheck = tk.Button(br2, text="🔄 重新检查", font=BF,
                                     bg="#fff", fg="#4a4e57", relief="flat",
                                     padx=12, pady=6, cursor="hand2",
                                     command=self._check)
        self.btn_recheck.pack(side="left")
        self.btn_page = tk.Button(br2, text="打开发布页", font=BF,
                                  bg="#fff", fg="#4a4e57", relief="flat",
                                  padx=12, pady=6, cursor="hand2",
                                  command=lambda: open_page(
                                      self.info["url"] if self.info else None))
        self.btn_page.pack(side="left", padx=8)
        self.btn_open = tk.Button(br2, text="📂 打开下载文件夹", font=BF,
                                  bg="#fff", fg="#4a4e57", relief="flat",
                                  padx=12, pady=6, cursor="hand2",
                                  state="disabled", command=self._open_dir)
        self.btn_open.pack(side="left")

    def _check(self):
        """（重新）查一次远端版本，界面回到「正在检查」"""
        self.info = self.err = None
        self.cmp = 0
        self._busy = True
        self._dots = 0
        self.btn_dl.config(state="disabled", text="⬇ 下载新版", bg="#e0334a")
        self.btn_more.config(state="disabled")
        self.btn_open.config(state="disabled")
        self.state_lbl.config(text="正在连接 GitHub", fg="#8a8f99")
        self.sub_lbl.config(text="")
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", "正在读取最新 Release …")
        self.txt.configure(state="disabled")
        self._tick()
        check_async_tk(self, self._on_done)

    def _tick(self):
        if not self._busy or not self.winfo_exists():
            return
        try:
            self._dots = (self._dots + 1) % 4
            self.state_lbl.config(text="正在连接 GitHub" + "." * self._dots)
            self._tick_id = self.after(350, self._tick)
        except Exception:
            pass

    def destroy(self):
        """窗口没了就把定时器撤了，否则空闲回调会打到已销毁的组件上"""
        self._busy = False
        try:                      # 关窗口时顺手把下载停了
            if self._dl_box:
                self._dl_box["stop"] = True
        except Exception:
            pass
        try:
            if getattr(self, "_tick_id", None):
                self.after_cancel(self._tick_id)
        except Exception:
            pass
        try:
            super().destroy()
        except Exception:
            pass

    def _on_done(self, info, err, cmp_):
        """已经回到主线程了，可以直接画"""
        self.info, self.err, self.cmp = info, err, cmp_
        self._render()
        # 主界面左下角那行字也跟着刷，别出现「弹窗说有新版本、左下角说已是最新」
        if callable(self.on_result):
            try:
                self.on_result(info, err, cmp_)
            except Exception:
                pass

    def _render(self):
        self._busy = False
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        if self.err:
            self.state_lbl.config(text="⚠ 检查失败", fg="#e0a020")
            self.sub_lbl.config(text=self.err)
            self.txt.insert("1.0", "没拿到最新版本信息，可能的原因：\n\n"
                                   "· 电脑连不上 GitHub（需要代理）\n"
                                   "· 代理端口不是 7890，软件只试了常见几个端口\n"
                                   "· GitHub 接口被限流（403）\n\n"
                                   "可以直接点「打开发布页」手动看：\n" + PAGE_LATEST)
        elif self.cmp > 0:
            i = self.info
            self.state_lbl.config(text="🎉 发现新版本 " + i["version"], fg="#e0334a")
            self.sub_lbl.config(text="当前 v%s · 发布于 %s" % (APP_VERSION, i["published"]))
            self.btn_dl.config(state="normal")
            self.txt.insert("1.0", plain_body(i["body"]) or "（这个版本没写更新说明）")
            if i["assets"]:
                self.txt.insert("end", "\n\n── 可下载 ──\n")
                for a in i["assets"]:
                    self.txt.insert("end", "· %s  (%s)\n" % (a["name"], human_size(a["size"])))
        elif self.cmp < 0:
            self.state_lbl.config(text="🛠 本地版本比远端还新", fg="#3a8f5a")
            self.sub_lbl.config(text="本地 v%s · 最新 Release %s"
                                     % (APP_VERSION, self.info["version"]))
            self.txt.insert("1.0", plain_body(self.info["body"]) or "（远端没写更新说明）")
        else:
            i = self.info
            self.state_lbl.config(text="✅ 已是最新版本", fg="#3a8f5a")
            self.sub_lbl.config(text="v%s · 发布于 %s" % (APP_VERSION, i["published"]))
            self.txt.insert("1.0", plain_body(i["body"]) or "（这个版本没写更新说明）")
            if i["assets"]:
                self.txt.insert("end", "\n\n── 当前版本下载 ──\n")
                for a in i["assets"]:
                    self.txt.insert("end", "· %s  (%s)\n" % (a["name"], human_size(a["size"])))
        self.txt.configure(state="disabled")

        # 不管有没有新版本，都给个能点的下载按钮（已是最新时可以重新下载当前版）
        a = main_asset(self.info)
        if (not self.err) and a:
            self.btn_dl.config(
                state="normal", bg="#e0334a",
                text=("⬇ 下载新版 " if self.cmp > 0 else "⬇ 下载当前版 ")
                     + human_size(a["size"]))
            self.btn_more.config(state="normal")
        self.btn_open.config(state="normal")

    # ------------------------------------------------------------ 下载
    def _menu(self):
        """列出这个 Release 的全部文件，选哪个下哪个"""
        m = tk.Menu(self, tearoff=0)
        for a in ((self.info or {}).get("assets") or []):
            m.add_command(label="%s  (%s)" % (a["name"], human_size(a["size"])),
                          command=lambda aa=a: self._start_download(aa))
        m.add_separator()
        m.add_command(label="用浏览器下载…",
                      command=lambda: open_page(
                          self.info["url"] if self.info else None))
        try:
            m.tk_popup(self.btn_more.winfo_rootx(),
                       self.btn_more.winfo_rooty() + self.btn_more.winfo_height())
        except Exception:
            pass

    def _download(self):
        """按钮的多态：下载中 = 取消；已下完 = 运行/打开；否则 = 开始下载"""
        if self._dl_box and not self._dl_box.get("done"):
            self._dl_box["stop"] = True
            self.btn_dl.config(state="disabled", text="正在取消…")
            return
        if self._dl_dest and os.path.exists(self._dl_dest):
            self._finish_action()
            return
        a = main_asset(self.info)
        if not a:
            open_page(self.info["url"] if self.info else None)
            return
        self._start_download(a)

    def _start_download(self, asset):
        dest = _unique_path(os.path.join(default_download_dir(), asset["name"]))
        self._dl_dest = dest
        self._busy = False
        self.pb.config(value=0)
        try:
            self.pb.pack(fill="x", padx=20, pady=(0, 8), before=self.br)
        except Exception:
            self.pb.pack(fill="x", padx=20, pady=(0, 8))
        self.btn_dl.config(text="✕ 取消下载", bg="#4a4e57", state="normal")
        self.btn_more.config(state="disabled")
        self.btn_recheck.config(state="disabled")
        self.state_lbl.config(text="⬇ 正在下载", fg="#2a6fd6")
        self.sub_lbl.config(text=asset["name"])
        self._dl_box = download_async_tk(self, asset["url"], dest,
                                         self._on_prog, self._on_dl_done)

    def _on_prog(self, got, total):
        try:
            if total:
                self.pb.config(value=min(100, got * 100.0 / total))
                self.state_lbl.config(text="⬇ 正在下载 %d%%" % int(got * 100.0 / total))
                self.sub_lbl.config(text="%s / %s" % (human_size(got), human_size(total)))
            else:
                self.state_lbl.config(text="⬇ 正在下载 %s" % human_size(got))
        except Exception:
            pass

    def _on_dl_done(self, dest, err):
        try:
            self.pb.pack_forget()
            self.btn_more.config(state="normal")
            self.btn_recheck.config(state="normal")
            if err:
                stopped = bool(self._dl_box and self._dl_box.get("stop"))
                self.state_lbl.config(
                    text="已取消下载" if stopped else "⚠ 下载失败",
                    fg="#8a8f99" if stopped else "#e0a020")
                self.sub_lbl.config(
                    text=("" if stopped else err + " · ")
                         + "也可以点「打开发布页」用浏览器下")
                self.btn_dl.config(text="⬇ 重试下载", bg="#e0334a", state="normal")
                return
            self._dl_dest = dest
            self.state_lbl.config(text="✅ 下载完成", fg="#3a8f5a")
            self.sub_lbl.config(text=dest)
            self.btn_open.config(state="normal")
            self.btn_dl.config(
                text=("▶ 运行安装" if str(dest).lower().endswith(".exe")
                      else "📂 打开文件"),
                bg="#3a8f5a")
            self._finish_action(ask=True)
        except Exception:
            pass

    def _finish_action(self, ask=False):
        """下完之后：exe 问一句要不要装，别的直接打开文件夹"""
        p = self._dl_dest
        if not p or not os.path.exists(p):
            return
        try:
            if str(p).lower().endswith(".exe"):
                if ask and not messagebox.askyesno(
                        "下载完成", "已保存到：\n%s\n\n现在运行安装程序吗？" % p,
                        parent=self):
                    return
                os.startfile(p)
            else:
                os.startfile(os.path.dirname(p))
        except Exception:
            pass

    def _open_dir(self):
        try:
            os.startfile(default_download_dir())
        except Exception:
            pass


if __name__ == "__main__":
    info, err = fetch_latest()
    if err:
        print("检查失败:", err)
    else:
        c = compare(info["version"], APP_VERSION)
        print("本地 v%s  最新 v%s  ->" % (APP_VERSION, info["version"]),
              "有新版本" if c > 0 else ("已是最新" if c == 0 else "本地更新"))
        print(info["body"][:400])
