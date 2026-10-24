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
    from tkinter import scrolledtext
except Exception:          # 无界面环境下也能当纯模块用
    tk = None

APP_VERSION = "1.0.3"
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


def _openers():
    """先直连，再试环境变量里的代理，最后扫常见代理端口（顺序固定，别用 set）"""
    yield urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    order = []
    for k in ("https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        v = os.environ.get(k)
        if v and v not in order:
            order.append(v)
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


def fetch_latest(timeout=6):
    """拿最新 Release；拿不到就去列表里挑版本号最大的那个"""
    try:
        return _pack(_get(API_LATEST, timeout)), None
    except Exception as e1:
        try:
            lst = _get(API_RELEASES, timeout)
            if lst:
                best = max(lst, key=lambda d: ver_tuple(d.get("tag_name")))
                return _pack(best), None
            return None, "仓库里还没有 Release"
        except Exception as e2:
            return None, _err_text(e2 if not str(e1) else e1)


def fetch_history(limit=8, timeout=6):
    """最近几个版本，用于「历史更新」列表"""
    try:
        lst = _get(API_RELEASES, timeout)[:limit]
        return [_pack(d) for d in lst], None
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


# ---------------------------------------------------------------- 界面
class UpdateDialog(tk.Toplevel if tk else object):
    """检查更新窗口：显示当前版本、最新结果、更新说明、下载按钮"""

    W, H = 460, 430

    def __init__(self, master, auto=False):
        super().__init__(master)
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

        self._build()
        self._tick()
        check_async_tk(self, self._on_done)

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

        br = tk.Frame(self, bg="#f5f6f8")
        br.pack(fill="x", padx=20, pady=(0, 16))
        self.btn_dl = tk.Button(br, text="⬇ 下载新版", font=("Microsoft YaHei UI", 10, "bold"),
                                bg="#e0334a", fg="#fff", relief="flat", padx=16, pady=7,
                                cursor="hand2", state="disabled", command=self._download)
        self.btn_dl.pack(side="left")
        tk.Button(br, text="打开发布页", font=("Microsoft YaHei UI", 10),
                  bg="#fff", fg="#4a4e57", relief="flat", padx=14, pady=7,
                  cursor="hand2", command=lambda: open_page(
                      self.info["url"] if self.info else None)).pack(side="left", padx=8)
        tk.Button(br, text="关闭", font=("Microsoft YaHei UI", 10),
                  bg="#fff", fg="#4a4e57", relief="flat", padx=14, pady=7,
                  cursor="hand2", command=self.destroy).pack(side="right")

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

    def _download(self):
        a = main_asset(self.info)
        if not a:
            open_page()
            return
        try:
            webbrowser.open(a["url"])
        except Exception:
            open_page()


if __name__ == "__main__":
    info, err = fetch_latest()
    if err:
        print("检查失败:", err)
    else:
        c = compare(info["version"], APP_VERSION)
        print("本地 v%s  最新 v%s  ->" % (APP_VERSION, info["version"]),
              "有新版本" if c > 0 else ("已是最新" if c == 0 else "本地更新"))
        print(info["body"][:400])
