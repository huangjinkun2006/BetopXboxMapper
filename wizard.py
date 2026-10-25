"""键位识别向导（图形版）：界面上高亮一个键，你按手柄上对应的键，自动记录 HID usage。

用法：python wizard.py
和主界面 gui.py 共用 padui.py 里那张 Xbox 手柄图。
"""
import os
import sys

# 依赖在 main() 里统一自检，打包成 exe 后会自动跳过

import threading
import time
import tkinter as tk
from tkinter import messagebox

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import betop
import padui
from padui import (C_BG, C_CARD, C_ACC, C_ACC_DK, C_ACC_LT, C_TEXT, C_SUB,
                   C_LINE, C_OK, C_HL, FONT, FT, S, PadView, apply_icon)

import win11ui
C_BG = win11ui.HOLE
C_LINE = "#e3e5ea"

BTN_STEPS = [
    ("A", "A 键 — 右边靠下那个（MC 里跳跃）"),
    ("B", "B 键 — 右边靠右那个（MC 里潜行/放下）"),
    ("X", "X 键 — 右边靠左那个"),
    ("Y", "Y 键 — 右边靠上那个"),
    ("LB", "LB 左肩键 — 左上方那个"),
    ("RB", "RB 右肩键 — 右上方那个"),
    ("BACK", "BACK / SELECT — 左边那个小键（◁）"),
    ("START", "START — 右边那个小键（▷）"),
    ("LS", "左摇杆垂直往下按（L3）"),
    ("RS", "右摇杆垂直往下按（R3）"),
    ("GUIDE", "中间 LOGO 键（◎，没有就点「跳过」）"),
]
STICK_STEPS = [("左摇杆", "LY", "LX"), ("右摇杆", "RY", "RX")]


class Wizard:
    def __init__(self, root):
        self.root = root
        root.title("键位识别向导 · 北通手柄")
        root.geometry("%dx%d" % (S(940), S(650)))
        root.resizable(True, True)
        root.minsize(S(880), S(600))
        root.configure(bg=C_BG)
        apply_icon(root)
        win11ui.apply(root)

        self.dev = None
        self.km = betop.load_keymap()
        self.phase = "connect"
        self.i = 0            # 当前按钮步骤
        self.si = 0           # 当前摇杆步骤
        self.sub = "up"       # 摇杆子步骤：up / right
        self.best = 0.0
        self.deadline = 0.0
        self.wait_sec = 10.0     # 每个键的等待时间（秒）
        self.cand = None         # 待确认的候选 usage（防抖用）
        self.settle = False      # 切步骤后第一帧丢弃
        self.cand_n = 0
        self.prev_pressed = set()
        self.log_lines = []
        self.state = {"buttons": {}, "axes": {k: 0.0 for k in betop.AXIS_TARGETS}}

        self.tip = tk.StringVar(value="正在连接手柄…")
        self.prog = tk.StringVar(value="")
        self.detail = tk.StringVar(value="把手柄插好、开机")
        self._build()
        threading.Thread(target=self._connect, daemon=True).start()
        self.root.after(80, self._tick)

    # ------------------------------------------------------------ 界面
    def _build(self):
        # 顶部条
        top = tk.Frame(self.root, bg=C_CARD)
        top.pack(fill="x")
        inner = tk.Frame(top, bg=C_CARD)
        inner.pack(fill="x", padx=S(22), pady=S(11))
        tk.Label(inner, text="键位识别向导", font=FT(15, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(side="left")
        self.chip = tk.Label(inner, text="● 连接中", font=FT(9), fg=C_SUB,
                             bg="#f4f5f8", padx=S(10), pady=S(4))
        self.chip.pack(side="left", padx=S(14))
        tk.Label(inner, text="每键等待", font=FT(9), fg=C_SUB,
                 bg=C_CARD).pack(side="left")
        self.wait_var = tk.StringVar(value="10")
        tk.Spinbox(inner, from_=3, to=60, width=3, font=FT(9),
                   textvariable=self.wait_var, relief="flat", bg="#f4f5f8",
                   buttonbackground="#e8e9ee", command=self._on_wait).pack(side="left",
                                                                            padx=(4, 0))
        self.wait_var.trace_add("write", lambda *_: self._on_wait())
        tk.Label(inner, text="秒", font=FT(9), fg=C_SUB,
                 bg=C_CARD).pack(side="left", padx=(2, 12))
        tk.Button(inner, text="完成并保存", font=FT(10, "bold"), fg="white",
                  bg=C_ACC, activebackground=C_ACC_DK, activeforeground="white",
                  relief="flat", padx=S(18), pady=S(6), cursor="hand2",
                  command=self.finish).pack(side="right")

        row = tk.Frame(self.root, bg=C_BG)
        row.pack(fill="both", expand=True, padx=S(18), pady=S(14))

        # 左：手柄图
        lc_card = win11ui.Card(row, radius=12, bg=C_CARD, outline=C_LINE, pad=3)
        lc_card.pack(side="left")
        lc = lc_card.body
        hdr = tk.Frame(lc, bg=C_CARD)
        hdr.pack(fill="x", padx=S(16), pady=(S(10), S(2)))
        tk.Label(hdr, text="按住这个键", font=FT(11, "bold"), fg=C_TEXT,
                 bg=C_CARD).pack(side="left")
        tk.Label(hdr, text="橙色的就是要你按的键", font=FT(8), fg=C_SUB,
                 bg=C_CARD).pack(side="left", padx=S(8))
        self.canvas = tk.Canvas(lc, width=S(560), height=S(370), bg=C_CARD,
                                highlightthickness=0)
        self.canvas.pack(padx=S(8), pady=(S(2), S(10)))
        self.pv = PadView(self.canvas)

        # 手柄图跟着窗口缩放（同主界面的量化重绘策略）
        self._pad_sz = (560, 370)
        self._pad_job = None

        def _pad_fit(e=None):
            try:
                rw, rh = row.winfo_width(), row.winfo_height()
            except Exception:
                return
            if rw < 60 or rh < 60:
                return
            bw = max(280, min(rw - 380, 760))
            bh = max(280, min(rh - 84, 900))
            if bw / bh > 480 / 474:
                bw = int(bh * 480 / 474)
            else:
                bh = int(bw * 474 / 480)
            bw = max(200, bw // 40 * 40)
            bh = int(bw * 474 / 480)
            if (bw, bh) == self._pad_sz:
                return
            self._pad_sz = (bw, bh)
            self.canvas.configure(width=bw, height=bh)
            self.pv.draw()

        def _pad_fit_debounced(e=None):
            if self._pad_job:
                self.root.after_cancel(self._pad_job)
            self._pad_job = self.root.after(120, _pad_fit)

        row.bind("<Configure>", _pad_fit_debounced)
        self.root.after(200, _pad_fit)

        # 右：提示 / 进度 / 日志
        rc_card = win11ui.Card(row, radius=12, bg=C_CARD, outline=C_LINE, pad=6)
        rc_card.pack(side="left", fill="both", expand=True, padx=(10, 0))
        rc = rc_card.body
        tk.Label(rc, textvariable=self.prog, font=FT(9), fg=C_SUB,
                 bg=C_CARD).pack(anchor="w", padx=S(18), pady=(S(14), S(2)))
        tk.Label(rc, textvariable=self.tip, font=FT(13, "bold"), fg=C_TEXT,
                 bg=C_CARD, wraplength=S(290), justify="left").pack(anchor="w", padx=S(18))
        tk.Label(rc, textvariable=self.detail, font=FT(9), fg=C_SUB,
                 bg=C_CARD, wraplength=S(290), justify="left").pack(anchor="w",
                                                                 padx=S(18), pady=(S(4), S(6)))
        # 倒计时
        cdr = tk.Frame(rc, bg=C_CARD)
        cdr.pack(fill="x", padx=S(18), pady=(S(0), S(6)))
        self.cd = tk.Label(cdr, text="", font=FT(20, "bold", family="Consolas"),
                           fg=C_HL, bg=C_CARD)
        self.cd.pack(side="left")
        self.cdbar = tk.Canvas(cdr, width=S(150), height=S(8), bg="#f0f1f4",
                               highlightthickness=0)
        self.cdbar.pack(side="left", padx=S(10))
        tk.Frame(rc, bg=C_LINE, height=1).pack(fill="x", padx=S(16))
        btns = tk.Frame(rc, bg=C_CARD)
        btns.pack(fill="x", padx=S(12), pady=S(10))
        for t, cmd in (("跳过此键", self.skip), ("再等一会", self.more_time),
                       ("重新开始", self.restart)):
            tk.Button(btns, text=t, font=FT(9), fg=C_TEXT, bg="#f4f5f8",
                      activebackground="#e8e9ee", relief="flat", padx=S(9), pady=S(5),
                      cursor="hand2", command=cmd).pack(side="left", padx=(0, 5))
        tk.Label(rc, text="识别记录", font=FT(9, "bold"), fg=C_TEXT,
                 bg=C_CARD).pack(anchor="w", padx=S(18), pady=(S(6), S(2)))
        self.logbox = tk.Text(rc, width=35, height=12, font=FT(9, family="Consolas"),
                              bg="#fafbfc", fg="#4a4e57", relief="flat",
                              highlightthickness=1, highlightbackground=C_LINE)
        self.logbox.pack(padx=S(18), pady=(S(0), S(14)))
        self.logbox.configure(state="disabled")

    def _as_dict(self, pressed):
        """原始 usage 集合 -> {目标键名: True}，用于点亮手柄图"""
        rev = {}
        for k, v in self.km.get("buttons", {}).items():
            rev.setdefault(v, k)
        return {rev[u]: True for u in pressed if u in rev}

    def log(self, s):
        self.log_lines.append(s)
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.insert("1.0", "\n".join(self.log_lines[-40:]))
        self.logbox.configure(state="disabled")

    # ------------------------------------------------------------ 连接
    def _connect(self):
        try:
            self.dev = betop.open_device(wait=True, timeout=120)
            self._dev_ok = True
        except Exception as e:
            self._dev_err = str(e)
            self._dev_ok = False

    # ------------------------------------------------------------ 主循环
    def _tick(self):
        if self.phase == "connect":
            if getattr(self, "_dev_ok", None) is True:
                self.phase = "btn"
                self.chip.config(text="● 已连接", fg=C_OK)
                self.log(f"连上了（后端：{'HidP 精确解码' if self.dev.use_hidp else '字节兜底'}）")
                self.start_btn()
            elif getattr(self, "_dev_ok", None) is False:
                self.tip.set("没找到手柄")
                self.detail.set(f"{getattr(self, '_dev_err', '')}\n\n"
                                "插好 USB、开开机再点「重新开始」。"
                                "如果主程序正在跑映射，先把它停掉。")
                self.chip.config(text="● 未连接", fg=C_SUB)
                self._dev_ok = None
            self.root.after(120, self._tick)
            return

        r = None
        try:
            r = self.dev.read() if self.dev else None
        except Exception:
            r = None
        if r:
            pressed, _ = self.dev.decode(list(r))
            _, axes = betop.parse_report(self.dev, list(r), self.km)
            self.state["buttons"] = pressed
            self.state["axes"] = axes
            self.pv.set_state(self._as_dict(pressed), axes)
            if self.settle:
                # 刚切到新键时的第一帧可能还带着上一个键的残留，丢掉不算数
                self.settle = False
                self.prev_pressed = set(pressed)
            else:
                self._advance(pressed, axes)
                self.prev_pressed = set(pressed)
        self._tick_cd()
        self.root.after(60, self._tick)

    # ------------------------------------------------------------ 步骤
    def start_btn(self):
        if self.i >= len(BTN_STEPS):
            self.start_stick()
            return
        name, desc = BTN_STEPS[self.i]
        self.pv.highlight(name)
        self.prog.set(f"第 1 步 · 按钮 {self.i + 1}/{len(BTN_STEPS)}")
        self.tip.set(f"按住 {name}")
        self.detail.set(desc)
        self.phase = "btn"
        self._arm()

    # ---- 计时 ----
    def _on_wait(self):
        """等待时间输入框变化时更新"""
        try:
            v = float(self.wait_var.get())
        except Exception:
            return
        self.wait_sec = max(1.0, min(120.0, v))
        if self.phase in ("btn", "release", "stick", "trig"):
            self.deadline = time.time() + self.wait_sec

    def _arm(self):
        """给当前步骤重新装填计时，并清掉上一次按键的残留"""
        self.deadline = time.time() + self.wait_sec
        self.settle = True
        self.prev_pressed = set()
        self.cand = None
        self.cand_n = 0

    def more_time(self):
        self.deadline = time.time() + self.wait_sec
        self.log("再等一轮")

    def _tick_cd(self):
        """刷新倒计时数字和进度条"""
        if self.phase not in ("btn", "release", "stick", "trig"):
            self.cd.config(text="")
            self.cdbar.delete("all")
            return
        left = max(0.0, self.deadline - time.time())
        self.cd.config(text=f"{left:.1f}", fg=(C_HL if left > 3 else "#e8474f"))
        self.cdbar.delete("all")
        frac = 0.0 if self.wait_sec <= 0 else max(0.0, min(1.0, left / self.wait_sec))
        self.cdbar.create_rectangle(0, 0, 150 * frac, 8, fill=C_ACC, outline="")

    def start_stick(self):
        self.pv.highlight(None)
        if self.si >= len(STICK_STEPS):
            self.start_trig()
            return
        label, ky, kx = STICK_STEPS[self.si]
        self.prog.set(f"第 2 步 · {label}方向 {self.si + 1}/{len(STICK_STEPS)}")
        self.phase = "stick"
        self.sub = "up"
        self.best = 0.0
        self._arm()
        self.tip.set(f"把{label}往上推到底，保持住")
        self.detail.set(f"推住别松，{self.wait_sec:.0f} 秒内自动判定；推得够狠会提前结束")

    def start_trig(self):
        self.prog.set("第 3 步 · 扳机")
        self.phase = "trig"
        self._arm()
        self.tip.set("把 LT 和 RT 都扣到底")
        self.detail.set(f"{self.wait_sec:.0f} 秒内读数，扣到底会提前结束")
        self.tmax = {"LT": 0.0, "RT": 0.0}

    def _advance(self, pressed, axes):
        if self.phase == "btn":
            new = set(pressed) - self.prev_pressed
            if new:
                u = sorted(new)[0]
                name = BTN_STEPS[self.i][0]
                self.km["buttons"][name] = u
                self.log(f"{name} = 按钮 {u}")
                self.phase = "release"
                self.deadline = time.time() + self.wait_sec
                self.tip.set(f"记录好了：{name} = {u}")
                self.detail.set("松开手，继续下一个")
            elif time.time() >= self.deadline:
                name = BTN_STEPS[self.i][0]
                self.log(f"{name}：等了 {self.wait_sec:.0f} 秒没按，跳过（保持原值）")
                self.i += 1
                self.start_btn()
        elif self.phase == "release":
            if not pressed or time.time() >= self.deadline:
                self.i += 1
                self.start_btn()
        elif self.phase == "stick":
            label, ky, kx = STICK_STEPS[self.si]
            key = ky if self.sub == "up" else kx
            v = axes.get(key, 0.0)
            if abs(v) > abs(self.best):
                self.best = v
            # 推得够狠就提前判定，不用干等；一直没推就耗到超时
            held = self.wait_sec - (self.deadline - time.time())
            if (abs(self.best) > 0.5 and held > 0.7) or time.time() >= self.deadline:
                self._finish_stick_sub()
        elif self.phase == "trig":
            for k in ("LT", "RT"):
                self.tmax[k] = max(self.tmax[k], axes.get(k, 0.0))
            held = self.wait_sec - (self.deadline - time.time())
            hit = max(self.tmax.values()) > 0.5
            if (hit and held > 0.9) or time.time() >= self.deadline:
                self.log(f"扳机峰值  LT {self.tmax['LT']:+.2f}  RT {self.tmax['RT']:+.2f}")
                self.phase = "done"
                self.tip.set("全部搞定，点「完成并保存」")
                self.detail.set("也可以在主界面点任意键单独微调")

    def _finish_stick_sub(self):
        label, ky, kx = STICK_STEPS[self.si]
        key = ky if self.sub == "up" else kx
        v = self.best
        spec = self.km["axes"].get(key, {})
        if abs(v) < 0.5:
            self.log(f"{label} {key}：没检测到推动，跳过")
        elif v < 0:
            spec["invert"] = not spec.get("invert", False)
            self.log(f"{label} {key}：方向反了（{v:+.2f}），已自动翻转")
        else:
            self.log(f"{label} {key}：方向 OK（{v:+.2f}）")
        if self.sub == "up":
            self.sub = "right"
            self.best = 0.0
            self._arm()
            self.tip.set(f"再把{label}往右推到底，保持住")
        else:
            self.si += 1
            self.start_stick()

    # ------------------------------------------------------------ 操作
    def skip(self):
        if self.phase in ("btn", "release"):
            name = BTN_STEPS[self.i][0]
            self.log(f"{name}：跳过（保持原值）")
            self.i += 1
            self.start_btn()
        elif self.phase == "stick":
            self.log(f"{STICK_STEPS[self.si][0]}：跳过校准")
            self.si += 1
            self.start_stick()
        elif self.phase == "trig":
            self.phase = "done"
            self.tip.set("搞定，点「完成并保存」")

    def restart(self):
        self.i = self.si = 0
        self.sub = "up"
        self.log_lines.clear()
        self.log("重新开始")
        if self.dev:
            self.start_btn()
        else:
            self.phase = "connect"
            self._dev_ok = None
            threading.Thread(target=self._connect, daemon=True).start()

    def finish(self):
        try:
            betop.save_keymap(self.km)
            messagebox.showinfo("完成", "键位已保存到 keymap.json\n"
                                       "打开主界面点「启动映射」就能用了")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
        try:
            if self.dev:
                self.dev.close()
        except Exception:
            pass
        self.root.destroy()


def main():
    # 缺依赖就弹窗告诉用户怎么装（打包成 exe 时依赖已内置，跳过）
    if not getattr(sys, "frozen", False):
        try:
            import vgamepad  # noqa: F401
        except ImportError as exc:
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror(
                "缺少依赖 vgamepad",
                "请先安装依赖：\n\n    pip install vgamepad\n\n"
                f"当前错误：{exc}")
            try:
                r.destroy()
            except Exception:
                pass
            sys.exit(1)
    # 高分屏：必须在建窗口前声明 DPI 感知（padui 导入时也设过一次，双保险）
    try:
        padui.enable_dpi()
    except Exception:
        pass
    # 跟主界面一样的用户界面大小设置
    try:
        _mult = betop.load_keymap().get("ui_scale")
        if _mult:
            padui.apply_user_scale(_mult)
    except Exception:
        pass
    root = tk.Tk()
    Wizard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
