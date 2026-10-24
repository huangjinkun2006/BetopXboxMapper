"""监听并记录手柄报告变化。用来确定每个物理键到底对应哪个 usage / 哪一位。

用法：python sniff.py [秒数]
运行期间随便按键、推摇杆、扣扳机，所有变化都会记到 sniff_log.txt
"""
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import betop

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0
LOG = betop.os.path.join(betop.HERE, "sniff_log.txt")


def main():
    print("正在连接手柄...")
    dev = betop.open_device(wait=True, timeout=180)
    print(f"连上了（{'HidP 解码' if dev.use_hidp else '字节兜底'}），监听 {SECONDS:.0f} 秒")
    print("现在开始随便按：A B X Y LB RB BACK START LS RS LOGO，再推推摇杆扣扣扳机")
    print("日志:", LOG)

    lines = []
    prev = None
    t0 = time.time()
    while time.time() - t0 < SECONDS:
        r = dev.read()
        if not r:
            continue
        r = list(r)
        raw = " ".join("%02X" % b for b in r)
        pressed, ok = dev.decode(r)
        pset = sorted(pressed) if ok else None
        key = (raw, tuple(pset or []))
        if key != prev:
            prev = key
            dt = time.time() - t0
            us = ",".join(str(u) for u in pset) if pset is not None else "?"
            lines.append(f"[{dt:6.2f}s] {raw}   按下:{us or '-'}")
            print(f"[{dt:6.2f}s] {raw}   按下:{us or '-'}", flush=True)
        time.sleep(0.01)

    with open(LOG, "w", encoding="utf-8") as f:
        f.write("时间     原始报告(hex)                按下按钮usage\n")
        f.write("\n".join(lines))
        f.write("\n")
    print("\n监听结束，已写入", LOG)
    dev.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
