# -*- coding: utf-8 -*-
"""监听 45 秒：只关心 FN 键。打印每次按下/松开的 usage 集合"""
import sys
import time

sys.path.insert(0, '.')
import betop
import hidraw

dev = betop.HidPad().open()
print('opened, in_len', dev.in_len, 'use_hidp', dev.use_hidp, flush=True)
print('>>> 现在请只按 FN 键：短按两下，再长按 2 秒 <<<', flush=True)

t0 = time.time()
last = None
while time.time() - t0 < 45:
    r = dev.read()
    if not r:
        continue
    raw = list(r)
    if raw == last:
        continue
    last = raw
    pressed, ok = dev.decode(raw)
    print('[%5.1fs] usages=%s raw=%s' % (time.time() - t0,
          sorted(pressed), ' '.join('%02X' % b for b in raw)), flush=True)

print('DONE', flush=True)
dev.close()
