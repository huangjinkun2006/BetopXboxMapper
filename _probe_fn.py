# -*- coding: utf-8 -*-
"""监听 90 秒：把每次按下的 usage 和原始 11 字节报告全打出来（抓 FN 键用）"""
import sys
import time

sys.path.insert(0, '.')
import betop
import hidraw

dev = betop.HidPad().open()
print('opened, in_len', dev.in_len, 'use_hidp', dev.use_hidp, flush=True)

idle = None
t0 = time.time()
seen = {}
last_raw = None
while time.time() - t0 < 90:
    r = dev.read()
    if not r:
        continue
    raw = list(r)
    if raw == last_raw:
        continue
    last_raw = raw
    pressed, ok = dev.decode(raw)
    if idle is None and not pressed:
        idle = raw
    if pressed or (idle and raw[:3] != idle[:3]):
        key = tuple(sorted(pressed)) if pressed else ('?raw',)
        if key not in seen:
            seen[key] = 0
        seen[key] += 1
        if seen[key] <= 3:
            print('[%5.1fs] usages=%s raw=%s' % (time.time() - t0,
                  sorted(pressed), ' '.join('%02X' % b for b in raw)), flush=True)

print('DONE. idle raw:', idle and ' '.join('%02X' % b for b in idle))
print('seen:', {str(k): v for k, v in seen.items()})
dev.close()
