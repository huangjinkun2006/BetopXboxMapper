"""震动实验室（主程序里「🧪 震动实验室」那个窗口的后台）。

手柄的震动协议没公开，靠猜是不行的，只能挨个发、靠手感挑。
这个模块做的事：
    1. 生成一批候选命令（命令头 / 字节位置 / 强度值 各种组合）
    2. 挨个发，你感觉到震就按空格记下来
    3. 记下来的那些再走「最强对决」两两对比，自动决出冠军
    4. 冠军命令直接变成 keymap.json 里的 rumble_custom，主程序照着发

pairs 的写法：[(字节偏移, 值), ...]，偏移 0 是 report id（固定 2）。
"""
import os
import threading
import time
import tkinter as tk
from tkinter import messagebox

import betop
import hidraw
from padui import apply_icon

RID = 2
FONT = "Microsoft YaHei UI"
OUT = os.path.join(betop.HERE, "rumble_lab_result.txt")


def mk(pairs):
    b = [RID] + [0] * 63
    for off, val in pairs:
        b[off] = val
    return b


def candidates():
    """候选命令表。实测先把 0x08 这个命令头坐实了，所以后面的都带它。"""
    c = []
    # A：命令头扫描（两个马达都拉满），看还有没有更猛的头
    for m in range(0x00, 0x10):
        c.append((f"A · 头0x{m:02X} + 大255 小255", [(1, m), (3, 255), (4, 255)]))
    # B：头固定 0x08，单个字节拉满，找出到底哪几个字节是马达
    for p in range(2, 16):
        c.append((f"B · 头08 只第{p}字节=255", [(1, 0x08), (p, 255)]))
    # C：大马达拉满，再额外拉满另一个字节，看会不会叠加变猛
    for p in range(2, 16):
        if p in (3, 4):
            continue
        c.append((f"C · 头08 第3字节=255 + 第{p}字节=255",
                  [(1, 0x08), (3, 255), (p, 255)]))
    # D：强度递增，验证值域是不是 0..255 线性
    for v in (32, 64, 128, 192, 255):
        c.append((f"D · 头08 只大马达={v}", [(1, 0x08), (3, v)]))
        c.append((f"D · 头08 只小马达={v}", [(1, 0x08), (4, v)]))
    # E：第2字节当总强度位来扫（实测它单独拉满也会震，很可疑）
    for v in (16, 64, 128, 255):
        c.append((f"E · 头08 第2字节={v} + 大马达255",
                  [(1, 0x08), (2, v), (3, 255)]))
    # F：能震的字节全拉满
    c.append(("F · 头08 第2+3+4 字节全 255",
              [(1, 0x08), (2, 255), (3, 255), (4, 255)]))
    c.append(("F · 头08 第2+3 字节全 255", [(1, 0x08), (2, 255), (3, 255)]))
    return c


class Lab(tk.Toplevel):
    def __init__(self, master, km, on_apply=None, on_clear=None):
        super().__init__(master)
        self.km = km
        self.on_apply = on_apply
        self.on_clear = on_clear
        self.title("震动实验室 · 找最猛的那条命令")
        self.geometry("760x620")
        self.configure(bg="#f5f6f8")
        apply_icon(self)
        self.transient(master)

        self.cands = candidates()
        self.idx = 0
        self.hits = []
        self._load_hits()
        self.running = False
        self.bracket = []
        self._pair = (0, 1)
        self._round = 1
        self.dev = None
        self.chan = tk.StringVar(value="WriteFile")

        err = ""
        try:
            path = hidraw.find_output_iface(betop.VID)
            if path is None:
                raise RuntimeError("没找到私有通道（手柄插着吗？）")
            self.dev = hidraw.RawHid().open_path(path)
        except Exception as e:
            err = str(e)

        self._build(err)
        if not err:
            self.show()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------------------------------------------------- 界面
    def _build(self, err):
        top = tk.Frame(self, bg="#f5f6f8")
        top.pack(fill="x", padx=20, pady=(14, 0))
        tk.Label(top, text="震动实验室", font=(FONT, 15, "bold"),
                 bg="#f5f6f8").pack(anchor="w")
        tk.Label(top, text="挨个发命令，感觉到震就按空格；记够 2 条就能开"
                           "「最强对决」两两比出冠军，冠军会直接写进配置。",
                 font=(FONT, 9), fg="#666", bg="#f5f6f8",
                 wraplength=700, justify="left").pack(anchor="w", pady=(2, 8))

        if err:
            tk.Label(self, text="通道打不开：" + err, fg="#c0392b",
                     font=(FONT, 10), bg="#f5f6f8").pack(pady=30)
            return

        box = tk.Frame(self, bg="white", highlightthickness=1,
                       highlightbackground="#dfe1e6")
        box.pack(fill="x", padx=20)
        self.lbl_idx = tk.Label(box, text="", font=(FONT, 9), fg="#888",
                                bg="white")
        self.lbl_idx.pack(anchor="w", padx=14, pady=(10, 0))
        self.lbl_cmd = tk.Label(box, text="", font=("Consolas", 13, "bold"),
                                fg="#1a73e8", bg="white", justify="left")
        self.lbl_cmd.pack(anchor="w", padx=14, pady=(2, 10))

        bar = tk.Frame(self, bg="#f5f6f8")
        bar.pack(fill="x", padx=20, pady=(8, 0))
        self.btn_run = tk.Button(bar, text="▶ 开始扫描", font=(FONT, 10, "bold"),
                                 fg="white", bg="#1a73e8", relief="flat",
                                 padx=12, pady=5, cursor="hand2",
                                 command=self.toggle_run)
        self.btn_run.pack(side="left")
        tk.Button(bar, text="⏮ 上一个", font=(FONT, 9), relief="flat",
                  bg="white", padx=8, pady=5, command=lambda: self.jump(-1)
                  ).pack(side="left", padx=5)
        tk.Button(bar, text="下一个 ⏭", font=(FONT, 9), relief="flat",
                  bg="white", padx=8, pady=5, command=lambda: self.jump(1)
                  ).pack(side="left")
        tk.Button(bar, text="🔁 震这条 1.5 秒", font=(FONT, 9), relief="flat",
                  bg="white", padx=8, pady=5, command=self.play_once
                  ).pack(side="left", padx=5)
        tk.Button(bar, text="♾ 一直震", font=(FONT, 9), relief="flat",
                  bg="#8e44ad", fg="white", padx=8, pady=5,
                  command=lambda: self.hold(True)).pack(side="left")
        tk.Button(bar, text="⏹ 停止震动", font=(FONT, 9, "bold"), fg="#c0392b",
                  bg="#fdecea", relief="flat", padx=8, pady=5,
                  command=lambda: self.hold(False)).pack(side="left", padx=5)
        ch = tk.Frame(self, bg="#f5f6f8")
        ch.pack(fill="x", padx=20, pady=(6, 0))
        tk.Label(ch, text="通道：", font=(FONT, 9), bg="#f5f6f8").pack(
            side="left")
        for v in ("WriteFile", "SET_REPORT"):
            tk.Radiobutton(ch, text=v, variable=self.chan, value=v,
                           font=(FONT, 9), bg="#f5f6f8",
                           command=self.show).pack(side="left")

        tk.Button(self, text="有感觉！（空格）", font=(FONT, 12, "bold"),
                  fg="white", bg="#0f9d58", relief="flat", padx=14, pady=7,
                  cursor="hand2", command=self.mark).pack(pady=(10, 0))

        # 最强对决
        dbar = tk.Frame(self, bg="#f5f6f8")
        dbar.pack(fill="x", padx=20, pady=(8, 0))
        self.btn_duel = tk.Button(dbar, text="🏆 最强对决（两两比出冠军）",
                                  font=(FONT, 10, "bold"), fg="white",
                                  bg="#e37400", relief="flat", padx=10,
                                  pady=5, cursor="hand2",
                                  command=self.start_duel)
        self.btn_duel.pack(side="left")
        self.duel_lbl = tk.Label(dbar, text="", font=(FONT, 9),
                                 fg="#e37400", bg="#f5f6f8",
                                 wraplength=430, justify="left")
        self.duel_lbl.pack(side="left", padx=8)
        dbar2 = tk.Frame(self, bg="#f5f6f8")
        dbar2.pack(fill="x", padx=20, pady=(4, 0))
        self.btn_a = tk.Button(dbar2, text="A 更猛", font=(FONT, 10, "bold"),
                               fg="white", bg="#1a73e8", relief="flat",
                               padx=12, pady=5, state="disabled",
                               command=lambda: self._duel_pick("a"))
        self.btn_a.pack(side="left")
        self.btn_b = tk.Button(dbar2, text="B 更猛", font=(FONT, 10, "bold"),
                               fg="white", bg="#0f9d58", relief="flat",
                               padx=12, pady=5, state="disabled",
                               command=lambda: self._duel_pick("b"))
        self.btn_b.pack(side="left", padx=6)
        self.btn_eq = tk.Button(dbar2, text="差不多，跳过", font=(FONT, 9),
                                relief="flat", bg="white", padx=8, pady=5,
                                state="disabled",
                                command=lambda: self._duel_pick("eq"))
        self.btn_eq.pack(side="left")
        self.btn_quit = tk.Button(dbar2, text="结束对决", font=(FONT, 9),
                                  relief="flat", bg="white", padx=8, pady=5,
                                  state="disabled", command=self._end_duel)
        self.btn_quit.pack(side="left", padx=6)

        hdr = tk.Frame(self, bg="#f5f6f8")
        hdr.pack(fill="x", padx=20, pady=(8, 0))
        tk.Label(hdr, text="记录：", font=(FONT, 9, "bold"),
                 bg="#f5f6f8").pack(side="left")
        self.hit_lbl = tk.Label(hdr, text="", font=(FONT, 8), fg="#888",
                                bg="#f5f6f8")
        self.hit_lbl.pack(side="left", padx=2)
        tk.Button(hdr, text="🗑 清空全部", font=(FONT, 8), relief="flat",
                  bg="#fdecea", fg="#c0392b", padx=8, pady=2, cursor="hand2",
                  command=self.clear_hits).pack(side="right")
        tk.Button(hdr, text="✕ 删选中", font=(FONT, 8), relief="flat",
                  bg="white", padx=8, pady=2, cursor="hand2",
                  command=self.del_sel).pack(side="right", padx=4)
        self.lst = tk.Listbox(self, font=("Consolas", 9), height=8)
        self.lst.pack(fill="both", padx=20, pady=(2, 10), expand=True)
        self._refresh_lst()
        self.bind("<Delete>", lambda e: self.del_sel())

        self.bind("<space>", lambda e: self.mark())
        self.bind("<Right>", lambda e: self.jump(1))
        self.bind("<Left>", lambda e: self.jump(-1))

    # ---------------------------------------------------------- 收发
    def send(self, data):
        if self.dev is None:
            return
        try:
            if self.chan.get() == "WriteFile":
                self.dev.write(data)
            else:
                self.dev.set_report(data)
        except Exception:
            pass

    def zero(self):
        if self.dev is None:
            return
        for m in range(0x00, 0x10):
            self.send(mk([(1, m)]))
        for rid in (0, 1, 2, 3, 4, 8):
            for ln in (5, 9, 64, 65):
                b = [rid] + [0] * (ln - 1)
                try:
                    self.dev.write(b)
                    self.dev.set_report(b)
                except Exception:
                    pass

    def payload(self, i=None):
        i = self.idx if i is None else i
        return mk(self.cands[i][1])

    def show(self):
        if self.dev is None:
            return
        name, pairs = self.cands[self.idx]
        self.lbl_idx.config(text=f"第 {self.idx + 1} / {len(self.cands)} 条")
        self.lbl_cmd.config(
            text=name + "\n" + " ".join(f"b[{o}]={v}" for o, v in pairs))

    def jump(self, d):
        self.idx = max(0, min(len(self.cands) - 1, self.idx + d))
        self.show()

    def play_once(self):
        threading.Thread(target=self._burst, daemon=True).start()

    def _burst(self, secs=1.5):
        self.zero()
        self.send(self.payload())
        time.sleep(secs)
        self.zero()

    def hold(self, on):
        if on:
            self.running = False
            self.btn_run.config(text="▶ 开始扫描")
            self.send(self.payload())
            self.lbl_idx.config(text="一直震着（点「停止震动」结束）")
        else:
            self.zero()
            self.show()

    # ---------------------------------------------------------- 记录
    def _load_hits(self):
        if not os.path.exists(OUT):
            return
        try:
            for line in open(OUT, encoding="utf-8"):
                p = line.strip().split("\t")
                if len(p) >= 2 and p[0].startswith("#"):
                    try:
                        n = int(p[0][1:]) - 1
                    except ValueError:
                        continue
                    if 0 <= n < len(self.cands) and \
                            not any(i == n for i, _ in self.hits):
                        self.hits.append((n, self.cands[n][0]))
        except Exception:
            pass

    def mark(self):
        if self.dev is None:
            return
        if self.hits and self.hits[-1][0] == self.idx:
            self.hits[-1] = (self.idx, "★ " + self.cands[self.idx][0])
        else:
            self.hits.append((self.idx, self.cands[self.idx][0]))
        self._refresh_lst()

    def _refresh_lst(self):
        self.lst.delete(0, "end")
        for n, t in self.hits:
            self.lst.insert("end", f"#{n + 1:>3}  {t}")
        if self.hits:
            self.lst.see("end")
        n = len(self.hits)
        self.hit_lbl.config(
            text=f"共 {n} 条" + ("（够 2 条就能对决）" if n >= 2 else ""))
        try:
            self.btn_run.config(state="normal")
        except Exception:
            pass

    def _save_hits(self):
        """记录写盘；一条都没有就把文件删掉，免得下次又读回来"""
        try:
            if not self.hits:
                if os.path.exists(OUT):
                    os.remove(OUT)
                return
            with open(OUT, "w", encoding="utf-8") as f:
                for n, t in self.hits:
                    f.write(f"#{n + 1}\t{t}\n")
        except Exception:
            pass

    def del_sel(self):
        """删掉列表里选中的那几条（记错了用这个）"""
        sel = list(self.lst.curselection())
        if not sel:
            messagebox.showinfo("删除记录",
                                "先在下面的列表里点中要删的那条，再点「✕ 删选中」",
                                parent=self)
            return
        for i in sorted(sel, reverse=True):
            if 0 <= i < len(self.hits):
                del self.hits[i]
        self._refresh_lst()
        self._save_hits()

    def clear_hits(self):
        """清空所有扫描记录，可选连冠军命令一起清"""
        if not self.hits:
            if not messagebox.askyesno(
                    "清空记录", "当前没有扫描记录。\n\n"
                    "继续的话会连同已选的冠军命令一起清掉，"
                    "回到「命令格式」下拉里选的那条。", parent=self):
                return
        else:
            r = messagebox.askyesnocancel(
                "清空记录",
                f"要清掉这 {len(self.hits)} 条扫描记录吗？\n\n"
                "「是」   = 记录 + 冠军命令一起清（回到命令格式下拉）\n"
                "「否」   = 只清记录，保留已选的冠军命令\n"
                "「取消」 = 什么都不做",
                parent=self)
            if r is None:
                return
            if not r:                       # 只清记录
                self.hits = []
                self.idx = 0
                self._refresh_lst()
                self._save_hits()
                self.duel_lbl.config(text="记录已清空")
                return
        self.hits = []
        self.idx = 0
        self._refresh_lst()
        self._save_hits()
        if callable(self.on_clear):
            try:
                self.on_clear()
            except Exception:
                pass
        self.duel_lbl.config(text="已清空，回到默认命令格式")

    # ---------------------------------------------------------- 扫描
    def toggle_run(self):
        if self.running:
            self.running = False
            self.btn_run.config(text="▶ 开始扫描")
            self.zero()
            return
        self.running = True
        self.btn_run.config(text="⏸ 暂停")
        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self):
        while self.running and self.idx < len(self.cands):
            self.after(0, self.show)
            self.zero()
            self.send(self.payload())
            time.sleep(1.1)
            self.zero()
            for _ in range(11):
                if not self.running:
                    break
                time.sleep(0.05)
            self.idx += 1
        self.running = False
        self.after(0, lambda: self.btn_run.config(text="▶ 开始扫描"))
        self.after(0, self.show)

    # ---------------------------------------------------------- 最强对决
    def _duel_btns(self, on):
        st = "normal" if on else "disabled"
        for b in (self.btn_a, self.btn_b, self.btn_eq, self.btn_quit):
            b.config(state=st)

    def _fire_at(self, i, secs=1.3):
        self.zero()
        self.send(mk(self.cands[i][1]))
        self.after(int(secs * 1000) + 200, self.zero)

    def start_duel(self):
        idxs = sorted({i for i, _t in self.hits})
        if len(idxs) < 2:
            self.duel_lbl.config(text="先至少记 2 条（按空格）再对决")
            return
        self.running = False
        self.btn_run.config(text="▶ 开始扫描")
        self.bracket = idxs
        self._round = 1
        self.btn_duel.config(state="disabled")
        self._duel_btns(False)
        self._duel_step()

    def _duel_step(self):
        if len(self.bracket) == 1:
            self._finish(self.bracket[0])
            return
        a, b = self.bracket[0], self.bracket[1]
        self._pair = (a, b)
        self.duel_lbl.config(
            text=f"第 {self._round} 轮 · 还剩 {len(self.bracket)} 条："
                 f"先震 A，再震 B，仔细感受…")
        self._fire_at(a)
        self.after(2200, lambda: self._fire_at(b))
        self.after(4500, self._duel_ask)

    def _duel_ask(self):
        a, b = self._pair
        self.duel_lbl.config(
            text=f"第 {self._round} 轮：A = #{a + 1} {self.cands[a][0]}   |   "
                 f"B = #{b + 1} {self.cands[b][0]} —— 哪个更猛？")
        self._duel_btns(True)

    def _duel_pick(self, w):
        a, b = self._pair
        self._duel_btns(False)
        if w == "eq":
            self.bracket = self.bracket[1:] + [self.bracket[0]]
        else:
            win = a if w == "a" else b
            self.bracket = self.bracket[2:] + [win]
        self._round += 1
        self._duel_step()

    def _finish(self, champ):
        name = self.cands[champ][0]
        self.duel_lbl.config(text=f"🏆 冠军：#{champ + 1} {name}")
        self.btn_duel.config(state="normal")
        self.zero()
        spec = self._to_spec(self.cands[champ][1])
        try:
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(f"CHAMPION\t#{champ + 1}\t{name}\n")
        except Exception:
            pass
        self.km["rumble_custom"] = spec
        if callable(self.on_apply):
            try:
                self.on_apply(spec, f"#{champ + 1} {name}")
            except Exception:
                pass

    @staticmethod
    def _to_spec(pairs):
        """把一条候选命令翻译成主程序认得的 rumble_custom。

        motor 用「马达名 -> 字节偏移」的字典（左柄/右柄/左扳机/右扳机），
        拉满的那几个字节按顺序认成 big、small、tl、tr。
        """
        fixed, motor = [], []
        for off, val in pairs:
            if off == 1:                 # 命令头固定不变
                fixed.append((off, val))
            elif val == 255:             # 拉满的那些字节 = 跟着马达强度走
                motor.append(off)
            else:
                fixed.append((off, val))
        keys = ("big", "small", "tl", "tr")
        md = {}
        for i, off in enumerate(motor):
            if i < len(keys):
                md[keys[i]] = off
        if not md:
            md = {"big": 3, "small": 4}
        return {"chan": "write", "fixed": fixed, "motor": md}

    def _end_duel(self):
        self._duel_btns(False)
        self.btn_duel.config(state="normal")
        self.zero()
        self.duel_lbl.config(text="对决结束（随时可以再开）")

    # ----------------------------------------------------------
    def on_close(self):
        self.running = False
        self.zero()
        try:
            if self.dev:
                self.dev.close()
        except Exception:
            pass
        self._save_hits()
        self.destroy()
