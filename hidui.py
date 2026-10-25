"""HidHide 配置面板 —— 官方 HidHide Configuration Client 的核心功能搬进来。

官方客户端能做的三件事这里都有：
  1. 总开关（cloaking）：隐身功能整体验不启用
  2. 设备黑名单（Devices）：哪些 HID 设备对「非白名单进程」隐身
  3. 应用白名单（Applications）：哪些进程看得见被隐的设备

CLI 每次调用要 200~500ms（还要跟内核驱动对话），所以**所有读写都丢线程**，
跑完用 after 回主线程刷新，避免点一下卡住整个窗口。

写之后的校验原则跟 hidhide.py 一致：退出码不可信，一律回读列表再判断。
"""
import os
import sys
import re
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import hidhide

from padui import (C_BG, C_CARD, C_ACC, C_ACC_DK, C_ACC_LT, C_TEXT, C_SUB,
                   C_LINE, C_OK, FONT, apply_icon)

C_GREEN = C_OK


# ---------------------------------------------------------------- 解析
def parse_lines(out):
    """把 CLI 输出还原成值列表。

    正常行：  --dev-hide "HID\\VID_20BC&PID_503C&COL02\\7&..."
    被截断：  --app-reg "C:\\中文路径\\被CLI自 (没有收尾引号)
    """
    if out is None:
        return None
    vals = []
    for raw in (out or "").splitlines():
        line = raw.strip()
        if not line.startswith("--"):
            continue
        m = re.match(r'^--\S+\s+"(.*)"\s*$', line)
        if m:
            val = m.group(1)
        else:
            m2 = re.match(r'^--\S+\s+(.*)$', line)
            val = (m2.group(1) if m2 else "").strip().strip('"')
        if val:
            vals.append(val)
    return vals


def dev_label(inst, currents=()):
    up = (inst or "").upper()
    m = re.search(r'VID_([0-9A-F]{4})&PID_([0-9A-F]{4})', up)
    vid, pid = (m.group(1), m.group(2)) if m else ("????", "????")
    col = re.search(r'COL(\d+)', up)
    name = "北通 BTP-V1T" if vid == "20BC" else "HID 设备"
    tail = inst.split("\\")[-1]
    tag = "●" if inst in currents else "○"
    return (f"{tag} {name}   VID_{vid} PID_{pid}"
            f"   {('COL' + col.group(1)) if col else '单接口'}"
            f"   …{tail[-14:]}")


def app_label(path):
    base = os.path.basename(path) or path
    miss = "" if os.path.isfile(path) else "   ⚠ 文件已不在"
    return f"{base}      {path}{miss}"


class HidHideDialog:
    """设备屏蔽的完整设置窗口（替代官方 HidHide Configuration Client）"""

    W, H = 780, 600

    def __init__(self, root, app=None):
        self.root = root
        self.app = app
        self.devs = []          # 原始实例路径
        self.apps = []          # 原始 exe 路径
        self.cur = []           # 当前插着的北通实例
        self.installed = False
        self.cloak = False

        self.win = tk.Toplevel(root)
        self.win.title("🛡 设备屏蔽 · HidHide 设置")
        self.win.configure(bg=C_BG)
        self.win.geometry("%dx%d" % (self.W, self.H))
        self.win.minsize(700, 520)
        self.win.transient(root)
        try:
            apply_icon(self.win)
        except Exception:
            pass

        self._build()
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()

    # ------------------------------------------------------------ UI
    def _build(self):
        # 标题
        top = tk.Frame(self.win, bg=C_CARD, highlightthickness=1,
                       highlightbackground=C_LINE)
        top.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(top, text="🛡  设备屏蔽（HidHide）", font=(FONT, 13, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(side="left", padx=14, pady=10)
        tk.Label(top, text="游戏里只剩虚拟 Xbox 那一把的关键",
                 font=(FONT, 8), fg=C_SUB, bg=C_CARD).pack(side="left")

        # 状态卡
        st = tk.Frame(self.win, bg=C_CARD, highlightthickness=1,
                      highlightbackground=C_LINE)
        st.pack(fill="x", padx=14, pady=(0, 8))
        self.lbl_drv = tk.Label(st, text="驱动：检查中…", font=(FONT, 9),
                                fg=C_SUB, bg=C_CARD)
        self.lbl_drv.pack(anchor="w", padx=14, pady=(10, 2))
        row1 = tk.Frame(st, bg=C_CARD)
        row1.pack(fill="x", padx=14, pady=(2, 4))
        self.lbl_cloak = tk.Label(row1, text="总开关：检查中…", font=(FONT, 9),
                                  fg=C_SUB, bg=C_CARD)
        self.lbl_cloak.pack(side="left")
        self.btn_cloak = tk.Button(row1, text="启用", font=(FONT, 8),
                                   bg=C_ACC_LT, fg="#fff", relief="flat",
                                   padx=12, pady=2, cursor="hand2",
                                   command=self.toggle_cloak)
        self.btn_cloak.pack(side="right")

        row2 = tk.Frame(st, bg=C_CARD)
        row2.pack(fill="x", padx=14, pady=(0, 10))
        self.lbl_pad = tk.Label(row2, text="当前手柄：检查中…", font=(FONT, 9),
                                fg=C_SUB, bg=C_CARD)
        self.lbl_pad.pack(side="left")
        self.btn_pad = tk.Button(row2, text="屏蔽它", font=(FONT, 8),
                                 bg=C_ACC_LT, fg="#fff", relief="flat",
                                 padx=12, pady=2, cursor="hand2",
                                 command=self.toggle_pad)
        self.btn_pad.pack(side="right")

        # 两个名单
        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        f1 = tk.Frame(nb, bg=C_BG)
        nb.add(f1, text="  隐藏的设备（黑名单）  ")
        self._build_dev_tab(f1)

        f2 = tk.Frame(nb, bg=C_BG)
        nb.add(f2, text="  应用白名单  ")
        self._build_app_tab(f2)

        # 底部
        bot = tk.Frame(self.win, bg=C_CARD, highlightthickness=1,
                       highlightbackground=C_LINE)
        bot.pack(fill="x", padx=14, pady=(0, 12))
        tk.Label(bot, text="白名单 = 看得见被隐藏设备的程序（映射器必须在里面）；"
                          "黑名单 = 对所有其它程序隐身的 HID 设备",
                 font=(FONT, 8), fg=C_SUB, bg=C_CARD,
                 wraplength=560, justify="left").pack(side="left", padx=12,
                                                      pady=8)
        tk.Button(bot, text="官方客户端", font=(FONT, 8), bg="#f0f1f4",
                  fg=C_TEXT, relief="flat", padx=10, pady=2, cursor="hand2",
                  command=self.open_official).pack(side="right", padx=(0, 6))
        tk.Button(bot, text="刷新", font=(FONT, 8), bg=C_ACC, fg="#fff",
                  relief="flat", padx=12, pady=2, cursor="hand2",
                  command=self.refresh).pack(side="right", padx=(0, 4))

        self.bar = tk.Label(self.win, text="", font=(FONT, 8), fg=C_SUB,
                            bg=C_BG)
        self.bar.pack(anchor="w", padx=16, pady=(0, 8))

    def _mk_list(self, parent):
        wrap = tk.Frame(parent, bg=C_BG)
        wrap.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        sb = tk.Scrollbar(wrap)
        sb.pack(side="right", fill="y")
        lb = tk.Listbox(wrap, font=("Consolas", 9), bg="#fff", fg=C_TEXT,
                        selectbackground=C_ACC_LT, relief="flat",
                        highlightthickness=1, highlightbackground=C_LINE,
                        yscrollcommand=sb.set, selectmode="extended",
                        activestyle="none")
        lb.pack(side="left", fill="both", expand=True)
        sb.config(command=lb.yview)
        return lb

    def _build_dev_tab(self, f):
        tip = tk.Frame(f, bg=C_BG)
        tip.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(tip, text="● = 现在插着  ○ = 记着但没插   选中可多选",
                 font=(FONT, 8), fg=C_SUB, bg=C_BG).pack(side="left")
        self.dev_lb = self._mk_list(f)
        bar = tk.Frame(f, bg=C_BG)
        bar.pack(fill="x", padx=10, pady=(0, 8))
        for txt, cmd in (("🧹 清空", self.dev_clear),
                         ("➖ 移除选中", self.dev_rem),
                         ("🎮 加当前手柄", self.dev_add_cur),
                         ("📁 手动加…", self.dev_add_manual)):
            tk.Button(bar, text=txt, font=(FONT, 8), bg="#f0f1f4", fg=C_TEXT,
                      relief="flat", padx=8, pady=3, cursor="hand2",
                      command=cmd).pack(side="left", padx=(0, 4))

    def _build_app_tab(self, f):
        tip = tk.Frame(f, bg=C_BG)
        tip.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(tip, text="不在白名单的程序 = 看不到任何被隐藏的设备",
                 font=(FONT, 8), fg=C_SUB, bg=C_BG).pack(side="left")
        self.app_lb = self._mk_list(f)
        bar = tk.Frame(f, bg=C_BG)
        bar.pack(fill="x", padx=10, pady=(0, 8))
        for txt, cmd in (("➕ 加程序…", self.app_add_file),
                         ("🕹 加映射器自己", self.app_add_me),
                         ("➖ 移除选中", self.app_rem)):
            tk.Button(bar, text=txt, font=(FONT, 8), bg="#f0f1f4", fg=C_TEXT,
                      relief="flat", padx=8, pady=3, cursor="hand2",
                      command=cmd).pack(side="left", padx=(0, 4))
        tk.Label(f, text="提示：CLI 遇到中文路径会显示成乱码或被截断，实际已写进"
                         "驱动。添加后刷新列表若看不到完整路径不用慌。",
                 font=(FONT, 8), fg=C_SUB, bg=C_BG, wraplength=700,
                 justify="left").pack(anchor="w", padx=12, pady=(0, 8))

    # ------------------------------------------------------------ 线程壳
    def _busy(self, text):
        self.bar.config(text=text)
        self.win.config(cursor="watch")
        self.win.update_idletasks()

    def _task(self, fn, after=None):
        """后台跑 fn（可能调 CLI 几百毫秒），跑完主线程调 after(res)"""
        def run():
            try:
                res = fn()
            except Exception as e:
                res = ("__err__", str(e))
            try:
                self.win.after(0, lambda: self._finish(res, after))
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    def _finish(self, res, after):
        self.win.config(cursor="")
        if isinstance(res, tuple) and res and res[0] == "__err__":
            self.bar.config(text="出错：%s" % res[1])
            messagebox.showerror("HidHide", res[1], parent=self.win)
            return
        if after:
            after(res)

    # ------------------------------------------------------------ 读状态
    def refresh(self):
        self._busy("正在读 HidHide 状态 …")
        self._task(self._read_state, self._paint_state)

    def _read_state(self):
        inst = hidhide.installed()
        if not inst:
            return {"installed": False}
        return {
            "installed": True,
            "cli": hidhide.cli_path(),
            "cloak": hidhide.cloak_state(),
            "devs": parse_lines(hidhide.hide_list()) or [],
            "apps": parse_lines(hidhide.app_list()) or [],
            "cur": hidhide.betop_instances(0x20BC),
        }

    def _paint_state(self, s):
        self.installed = s.get("installed", False)
        if not self.installed:
            self.devs, self.apps, self.cur = [], [], []
            self._fill_lists()
            self.lbl_drv.config(text="驱动：❌ 没装 HidHide", fg=C_ACC)
            self.lbl_cloak.config(text="总开关：——")
            self.lbl_pad.config(text="当前手柄：——")
            self.btn_cloak.config(state="disabled")
            self.btn_pad.config(state="disabled")
            self.bar.config(text="没检测到 HidHide 驱动，点下面装一下")
            self._install_btn()
            return

        self.devs = s["devs"]
        self.apps = s["apps"]
        self.cur = s["cur"]
        self.cloak = s["cloak"]
        self._fill_lists()

        self.lbl_drv.config(text="驱动：✅ 已安装（%s）"
                                 % (s.get("cli") or "").split("\\x64")[0],
                            fg=C_GREEN)
        self.lbl_cloak.config(
            text="总开关：%s" % ("✅ 已启用隐身" if self.cloak
                                else "⬜ 已停用（黑名单不生效）"))
        self._paint_btn(self.btn_cloak,
                        "停用" if self.cloak else "启用", danger=not self.cloak)
        self.btn_cloak.config(state="normal")
        self.btn_pad.config(state="normal" if self.cur else "disabled")
        hid_n = sum(1 for i in self.cur
                    if any(hidhide._norm(i) in hidhide._norm(d)
                           for d in self.devs))
        if not self.cur:
            self.lbl_pad.config(text="当前手柄：没插（或没开机）")
            self._paint_btn(self.btn_pad, "屏蔽它", danger=True)
        elif hid_n == len(self.cur):
            self.lbl_pad.config(text=f"当前手柄：🔒 已隐藏（{hid_n} 个接口）")
            self._paint_btn(self.btn_pad, "解除屏蔽", danger=False)
        elif hid_n:
            self.lbl_pad.config(text=f"当前手柄：⚠ 只藏了 {hid_n}/{len(self.cur)}"
                                     f" 个接口")
            self._paint_btn(self.btn_pad, "全部屏蔽", danger=True)
        else:
            self.lbl_pad.config(text=f"当前手柄：👀 完全可见"
                                     f"（{len(self.cur)} 个接口）")
            self._paint_btn(self.btn_pad, "屏蔽它", danger=True)
        self.bar.config(text="黑名单 %d 项 · 白名单 %d 项"
                             % (len(self.devs), len(self.apps)))

    def _paint_btn(self, btn, label, danger):
        """危险动作红色（要藏）、恢复动作绿色（要放）"""
        btn.config(text=label,
                   bg=C_ACC if danger else C_OK, fg="#fff",
                   font=(FONT, 8, "bold"))

    def _fill_lists(self):
        self.dev_lb.delete(0, "end")
        for i in self.devs:
            self.dev_lb.insert("end", dev_label(i, self.cur))
        self.app_lb.delete(0, "end")
        for p in self.apps:
            self.app_lb.insert("end", app_label(p))

    def _install_btn(self):
        if getattr(self, "_has_install_btn", False):
            return
        self._has_install_btn = True
        tk.Button(self.win, text="⬇ 安装 HidHide 驱动（要 UAC）",
                  font=(FONT, 9, "bold"), bg=C_ACC, fg="#fff", relief="flat",
                  padx=14, pady=4, cursor="hand2",
                  command=self.do_install).pack(pady=(0, 10))

    # ------------------------------------------------------------ 写操作
    def _write(self, args, verify, ok_text, fail_text):
        """非提权写一轮，回读校验；不行再弹 UAC 提权一轮"""
        hidhide._write(args)
        if verify():
            return True
        hidhide._write_elevated(args)
        return verify()

    def do_install(self):
        src = None
        base = os.path.dirname(hidhide.cli_path() or "")
        for d in (os.path.dirname(os.path.abspath(__file__)),
                  os.getcwd(), base):
            cand = os.path.join(d, "HidHide_x64.exe")
            if os.path.isfile(cand):
                src = cand
                break
        if not src:
            messagebox.showinfo(
                "安装 HidHide",
                "目录里没找到 HidHide_x64.exe。\n\n"
                "去官网下（GitHub 搜 nefarius/HidHide，Releases 里那个\n"
                "HidHide_xxx_x64.exe），下载完放进程序目录再点这个按钮。",
                parent=self.win)
            return
        self._busy("正在安装 HidHide（会弹一次 UAC）…")
        self._task(lambda: hidhide.install_silent(src),
                   lambda ok: self._after_install(ok))

    def _after_install(self, ok):
        self._has_install_btn = False
        if not ok or not hidhide.installed():
            self.bar.config(text="安装没成功（点了取消？），可以再试一次")
            return
        # 装完顺手把自己加进白名单，免得第一次点屏蔽就看不到手柄
        me = self._my_exes()
        if me:
            hidhide._write(["--app-reg"] + me if False else
                           [x for e in me for x in ("--app-reg", e)])
        self.refresh()

    def _my_exes(self):
        """映射器 + 键位向导的 exe 路径（它们都得在白名单里，不然屏蔽后自读不到）"""
        try:
            me = os.path.abspath(sys.argv[0])
        except Exception:
            return []
        out = [me]
        w = os.path.join(os.path.dirname(me), "BetopWizard.exe")
        if os.path.isfile(w):
            out.append(w)
        return out

    def toggle_cloak(self):
        want = not self.cloak
        self._busy("正在改总开关 …")
        self._task(
            lambda: self._write(["--cloak-on" if want else "--cloak-off"],
                                lambda: hidhide.cloak_state() == want,
                                "", ""),
            lambda ok: self._ok_fail(ok, "总开关已%s" % ("启用" if want
                                                       else "停用")))

    def toggle_pad(self):
        cur = list(self.cur)
        hid_n = sum(1 for i in cur
                    if any(hidhide._norm(i) in hidhide._norm(d)
                           for d in self.devs))
        want = hid_n < len(cur)
        self._busy("正在%s屏蔽 …" % ("开" if want else "解除"))
        self._task(lambda: self._do_pad(cur, want),
                   lambda ok: self._ok_fail(
                       ok, "北通 %s" % ("已隐藏" if want else "已恢复可见")))

    def _do_pad(self, cur, want):
        args = []
        if want:
            apps = [e for e in self._my_exes() if os.path.isfile(e)]
            for e in apps:
                args += ["--app-reg", e]
        for i in cur:
            args += ["--dev-hide" if want else "--dev-unhide", i]
        if want:
            args += ["--cloak-on"]

        def verify():
            lst = hidhide.hide_list()
            hit = any(hidhide._norm(i) in hidhide._norm(lst or "")
                      for i in cur)
            return hit if want else not hit

        return self._write(args, verify, "", "")

    def _ok_soft(self, ok, ok_text):
        """白名单专用：中文路径会被 CLI 输出截断，回读匹配不到 ≠ 没写进去。
        没确认上也只提示不报错，让用户看刷新后的列表。"""
        if ok:
            self.bar.config(text="✅ " + ok_text)
        else:
            self.bar.config(text="⚠ 已提交；含中文的路径在 CLI 里显示不全，"
                                 "无法回读确认 —— 看上面列表有没有多出来")
        self.refresh()

    def _ok_fail(self, ok, ok_text):
        if ok:
            self.bar.config(text="✅ " + ok_text)
            self.refresh()
        else:
            self.bar.config(text="❌ 没改成：可能点了 UAC 取消，或驱动没起来")
            messagebox.showerror(
                "HidHide",
                "名单没改成功。\n\n常见原因：\n"
                "· UAC 弹窗点了「否」\n"
                "· HidHide 驱动被别的安全软件挡了\n"
                "· CLI 在跑的时候驱动服务刚好在重启\n\n"
                "重试一次；还不行就重启电脑再试。", parent=self.win)
            self.refresh()

    # ------------------------------------------------------------ 设备名单
    def _sel_devs(self):
        return [self.devs[i] for i in self.dev_lb.curselection()
                if i < len(self.devs)]

    def dev_rem(self):
        sel = self._sel_devs()
        if not sel:
            return
        self._busy("正在移出黑名单 …")
        self._task(lambda: self._rm_devs(sel),
                   lambda ok: self._ok_fail(ok, "已移出 %d 项" % len(sel)))

    def _rm_devs(self, sel):
        args = [x for d in sel for x in ("--dev-unhide", d)]

        def verify():
            lst = hidhide._norm(hidhide.hide_list() or "")
            return not any(hidhide._norm(d) in lst for d in sel)

        return self._write(args, verify, "", "")

    def dev_clear(self):
        if not self.devs:
            return
        if not messagebox.askyesno(
                "清空黑名单", "把 %d 项全部解除隐藏？\n\n"
                "（游戏里会重新出现物理手柄）" % len(self.devs),
                parent=self.win):
            return
        self._busy("正在清空 …")
        self._task(lambda: self._rm_devs(list(self.devs)),
                   lambda ok: self._ok_fail(ok, "黑名单已清空"))

    def dev_add_cur(self):
        try:
            cur = hidhide.betop_instances(0x20BC)
        except Exception:
            cur = []
        if not cur:
            messagebox.showinfo("加当前手柄",
                                "没枚举到北通手柄。\n把 USB 插上 / 按 LOGO "
                                "唤醒后刷新再试。", parent=self.win)
            return
        self._busy("正在加进黑名单 …")
        self._task(lambda: self._do_pad(cur, True),
                   lambda ok: self._ok_fail(ok, "北通已隐藏"))

    def dev_add_manual(self):
        self._busy("扫描本机 HID 设备 …")
        self._task(self._enum_all_hid,
                   lambda rows: self._pick_hid(rows))

    def _enum_all_hid(self):
        """列出所有 HID 设备的实例路径 + 友好名（PowerShell PnP）"""
        ps = ("Get-PnpDevice -Class HIDClass -PresentOnly:$true -EA 0 | "
              "ForEach-Object { $_.FriendlyName + '|' + $_.InstanceId }")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               capture_output=True, text=True, timeout=60,
                               encoding="utf-8", errors="replace",
                               creationflags=0x08000000)
            rows = []
            for line in (r.stdout or "").splitlines():
                if "|" in line:
                    name, iid = line.split("|", 1)
                    rows.append((name.strip(), iid.strip()))
            return rows
        except Exception as e:
            return ("__err__", str(e))

    def _pick_hid(self, rows):
        self.win.config(cursor="")
        if isinstance(rows, tuple) and rows and rows[0] == "__err__":
            self.bar.config(text="扫描失败：%s" % rows[1])
            return
        if not rows:
            self.bar.config(text="没扫到 HID 设备")
            return
        PickHidDialog(self.win, rows, self._add_devs)

    def _add_devs(self, devs):
        if not devs:
            return
        self._busy("正在加进黑名单 …")
        self._task(lambda: self._add_devs_job(devs),
                   lambda ok: self._ok_fail(ok, "已隐藏 %d 项" % len(devs)))

    def _add_devs_job(self, devs):
        args = []
        for d in devs:
            args += ["--dev-hide", d]
        args += ["--cloak-on"]

        def verify():
            lst = hidhide._norm(hidhide.hide_list() or "")
            return all(hidhide._norm(d) in lst for d in devs)

        return self._write(args, verify, "", "")

    # ------------------------------------------------------------ 白名单
    def _sel_apps(self):
        return [self.apps[i] for i in self.app_lb.curselection()
                if i < len(self.apps)]

    def app_add_file(self):
        paths = filedialog.askopenfilenames(
            parent=self.win, title="选择要加进白名单的程序",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")])
        if not paths:
            return
        self._busy("正在写白名单 …")
        self._task(lambda: self._add_apps(list(paths)),
                   lambda ok: self._ok_soft(ok, "已加 %d 个" % len(paths)))

    def app_add_me(self):
        me = [e for e in self._my_exes() if os.path.isfile(e)]
        if not me:
            messagebox.showinfo("加映射器自己", "定位不到本程序路径",
                                parent=self.win)
            return
        self._busy("正在写白名单 …")
        self._task(lambda: self._add_apps(me),
                   lambda ok: self._ok_soft(ok, "映射器已在白名单里"))

    def _add_apps(self, paths):
        args = [x for p in paths for x in ("--app-reg", p)]
        base = [os.path.basename(p).lower() for p in paths]

        def verify():
            lst = hidhide._norm(hidhide.app_list() or "")
            # CLI 对中文路径会输出乱码/截断，退一步只比对文件名
            return all(b in lst for b in base)

        return self._write(args, verify, "", "")

    def app_rem(self):
        sel = self._sel_apps()
        if not sel:
            return
        self._busy("正在移出白名单 …")
        self._task(lambda: self._rm_apps(sel),
                   lambda ok: self._ok_soft(ok, "已移出 %d 个" % len(sel)))

    def _rm_apps(self, sel):
        args = [x for p in sel for x in ("--app-unreg", p)]
        base = [os.path.basename(p).lower() for p in sel]

        def verify():
            lst = hidhide._norm(hidhide.app_list() or "")
            return not any(b in lst for b in base)

        return self._write(args, verify, "", "")

    # ------------------------------------------------------------ 杂
    def open_official(self):
        base = os.path.dirname(hidhide.cli_path() or "")
        cand = os.path.join(base, "HidHideClient.exe") if base else ""
        if cand and os.path.isfile(cand):
            try:
                os.startfile(cand)
                return
            except Exception:
                pass
        messagebox.showinfo(
            "官方客户端",
            "没找到 HidHideClient.exe。\n\n"
            "它跟驱动装在一起，通常在：\n"
            r"C:\Program Files\Nefarius Software Solutions\HidHide\x64"
            r"\HidHideClient.exe",
            parent=self.win)

    def close(self):
        try:
            self.win.destroy()
        except Exception:
            pass


class PickHidDialog:
    """手动加设备：列出本机所有 HID，勾选后隐藏"""

    def __init__(self, parent, rows, on_pick):
        self.rows = rows
        self.on_pick = on_pick
        self.win = tk.Toplevel(parent)
        self.win.title("选择要隐藏的 HID 设备")
        self.win.configure(bg=C_BG)
        self.win.geometry("720x460")
        self.win.transient(parent)
        self.win.grab_set()
        try:
            apply_icon(self.win)
        except Exception:
            pass

        tk.Label(self.win, text="勾选要隐藏的设备（可以多选）：", font=(FONT, 9),
                 fg=C_TEXT, bg=C_BG).pack(anchor="w", padx=12, pady=(10, 4))
        wrap = tk.Frame(self.win, bg=C_BG)
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        sb = tk.Scrollbar(wrap)
        sb.pack(side="right", fill="y")
        self.lb = tk.Listbox(wrap, font=("Consolas", 9), bg="#fff",
                             fg=C_TEXT, relief="flat", highlightthickness=1,
                             highlightbackground=C_LINE, selectmode="multiple",
                             yscrollcommand=sb.set, activestyle="none")
        self.lb.pack(side="left", fill="both", expand=True)
        sb.config(command=self.lb.yview)
        for name, iid in rows:
            self.lb.insert("end", "%-40s %s" % (name[:38], iid))

        bar = tk.Frame(self.win, bg=C_BG)
        bar.pack(fill="x", padx=12, pady=(0, 10))
        tk.Button(bar, text="确定隐藏", font=(FONT, 9, "bold"), bg=C_ACC,
                  fg="#fff", relief="flat", padx=14, pady=3, cursor="hand2",
                  command=self._ok).pack(side="right", padx=(6, 0))
        tk.Button(bar, text="取消", font=(FONT, 9), bg="#f0f1f4", fg=C_TEXT,
                  relief="flat", padx=14, pady=3, cursor="hand2",
                  command=self.win.destroy).pack(side="right")

    def _ok(self):
        sel = [self.rows[i][1] for i in self.lb.curselection()]
        self.win.destroy()
        self.on_pick(sel)
