# -*- coding: utf-8 -*-
"""监听 300 秒（5 分钟）：用户随时按 FN 和 LOGO，记录每次上报"""
import sys
import time

sys.path.insert(0, '.')
import betop
import hidraw

dev = betop.HidPad().open()
print('opened, in_len', dev.in_len, 'use_hidp', dev.use_hidp, flush=True)
print('>>> 监听已开 5 分钟：请按 FN 键 3 下，再按 LOGO(蓝色箭头) 2 下 <<<', flush=True)

t0 = time.time()
last = None
while time.time() - t0 < 300:
    r = dev.read()
    if not r:
        continue
    raw = list(r)
    if raw == last:
        continue
    last = raw
    pressed, ok = dev.decode(raw)
    print('[%6.1fs] usages=%s raw=%s' % (time.time() - t0,
          sorted(pressed), ' '.join('%02X' % b for b in raw)), flush=True)

print('DONE', flush=True)
dev.close()
