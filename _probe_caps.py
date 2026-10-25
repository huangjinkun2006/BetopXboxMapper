import sys
sys.path.insert(0, '.')
import ctypes
from ctypes import byref, c_ulong, c_ushort
import hidraw, betop

path, in_len = hidraw.find_gamepad(betop.VID, None)
d = hidraw.RawHid().open_path(path)
pp = d.preparsed
from ctypes import POINTER, c_void_p
import hidraw as H

caps = H.HIDP_CAPS()
st = H.hid_dll.HidP_GetCaps(pp, byref(caps))
print('GetCaps NTSTATUS', hex(st))
print('UsagePage', hex(caps.UsagePage), 'InputLen', caps.InputReportByteLength,
      'OutputLen', caps.OutputReportByteLength,
      'BtnCaps', caps.NumberInputButtonCaps, 'ValCaps', caps.NumberInputValueCaps)

# 按钮 usage 范围
bcaps = (H.HIDP_BUTTON_CAPS * 8)()
n = c_ushort(8)
st = H.hid_dll.HidP_GetButtonCaps(H.HidP_Input, bcaps, byref(n), pp)
print('GetButtonCaps', hex(st), 'count', n.value)
for i in range(n.value):
    b = bcaps[i]
    print('  btn page', hex(b.UsagePage), 'usage', b.UsageMin, '->', b.UsageMax,
          'isRange', b.IsRange)
d.close()
