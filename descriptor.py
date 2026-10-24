"""读手柄的 HID 报告描述符，把按钮 usage 和轴的定义全列出来。

比猜字节位靠谱：HidP_GetButtonCaps / HidP_GetValueCaps 是系统解析好的权威信息。
"""
import ctypes
from ctypes import (POINTER, byref, c_long, c_ubyte, c_ulong, c_ushort,
                    c_void_p, sizeof)
from ctypes import wintypes

import hidraw

hid = ctypes.windll.hid

HidP_Input = 0
HidP_Output = 1
HidP_Feature = 2


class HIDP_BUTTON_CAPS(ctypes.Structure):
    _fields_ = [
        ("UsagePage", c_ushort),
        ("ReportID", c_ubyte),
        ("IsAlias", c_ubyte),          # BOOLEAN
        ("BitField", c_ushort),
        ("LinkCollection", c_ushort),
        ("LinkUsage", c_ushort),
        ("LinkUsagePage", c_ushort),
        ("IsRange", c_ubyte),
        ("IsStringRange", c_ubyte),
        ("IsDesignatorRange", c_ubyte),
        ("IsAbsolute", c_ubyte),
        ("Reserved", c_ulong * 10),
        ("UsageMin", c_ushort),
        ("UsageMax", c_ushort),
        ("StringMin", c_ushort),
        ("StringMax", c_ushort),
        ("DesignatorMin", c_ushort),
        ("DesignatorMax", c_ushort),
        ("DataIndexMin", c_ushort),
        ("DataIndexMax", c_ushort),
    ]


class HIDP_VALUE_CAPS(ctypes.Structure):
    _fields_ = [
        ("UsagePage", c_ushort),
        ("ReportID", c_ubyte),
        ("IsAlias", c_ubyte),
        ("BitField", c_ushort),
        ("LinkCollection", c_ushort),
        ("LinkUsage", c_ushort),
        ("LinkUsagePage", c_ushort),
        ("IsRange", c_ubyte),
        ("IsStringRange", c_ubyte),
        ("IsDesignatorRange", c_ubyte),
        ("IsAbsolute", c_ubyte),
        ("HasNull", c_ubyte),
        ("Reserved", c_ubyte),
        ("BitSize", c_ushort),
        ("ReportCount", c_ushort),
        ("Reserved2", c_ushort * 5),
        ("UnitsExp", c_ulong),
        ("Units", c_ulong),
        ("LogicalMin", c_long),
        ("LogicalMax", c_long),
        ("PhysicalMin", c_long),
        ("PhysicalMax", c_long),
        ("UsageMin", c_ushort),
        ("UsageMax", c_ushort),
        ("StringMin", c_ushort),
        ("StringMax", c_ushort),
        ("DesignatorMin", c_ushort),
        ("DesignatorMax", c_ushort),
        ("DataIndexMin", c_ushort),
        ("DataIndexMax", c_ushort),
    ]


hid.HidP_GetButtonCaps.restype = c_ulong
hid.HidP_GetButtonCaps.argtypes = [c_ulong, POINTER(HIDP_BUTTON_CAPS),
                                   POINTER(c_ushort), c_void_p]
hid.HidP_GetValueCaps.restype = c_ulong
hid.HidP_GetValueCaps.argtypes = [c_ulong, POINTER(HIDP_VALUE_CAPS),
                                  POINTER(c_ushort), c_void_p]

# 通用桌面页 usage 名
USAGE_NAMES = {
    0x30: "X", 0x31: "Y", 0x32: "Z", 0x33: "Rx", 0x34: "Ry", 0x35: "Rz",
    0x36: "Slider", 0x37: "Dial", 0x38: "Wheel", 0x39: "Hat",
    0x3A: "CountedBuffer", 0x40: "Vx", 0x41: "Vy", 0x42: "Vz",
}


def name_of(up, us):
    if up == 0x01:
        return "Button %d" % us
    if up == 0x09:
        return "Btn%d" % us
    return USAGE_NAMES.get(us, "usage=%#x" % us)


def dump(path):
    dev = hidraw.RawHid().open_path(path)
    pp = c_void_p()
    if not hid.HidD_GetPreparsedData(dev.h, byref(pp)):
        print("拿不到 preparsed data")
        return
    caps = hidraw.HIDP_CAPS()
    hid.HidP_GetCaps(pp, byref(caps))
    print("UsagePage=%#06x Usage=%#06x  InputReport=%d OutputReport=%d FeatureReport=%d"
          % (caps.UsagePage, caps.Usage, caps.InputReportByteLength,
             caps.OutputReportByteLength, caps.FeatureReportByteLength))
    print("Caps: InputButtonCaps=%d InputValueCaps=%d"
          % (caps.NumberInputButtonCaps, caps.NumberInputValueCaps))
    print()

    nb = c_ushort(caps.NumberInputButtonCaps)
    if nb.value:
        arr = (HIDP_BUTTON_CAPS * nb.value)()
        r = hid.HidP_GetButtonCaps(HidP_Input, arr, byref(nb), pp)
        print("--- 按钮 (%d 组) ---" % nb.value)
        for i in range(nb.value):
            c = arr[i]
            print("  [%d] up=%#06x reportID=%d usage %d..%d (共%d个) alias=%d"
                  % (i, c.UsagePage, c.ReportID, c.UsageMin, c.UsageMax,
                     c.UsageMax - c.UsageMin + 1, c.IsAlias))

    nv = c_ushort(caps.NumberInputValueCaps)
    if nv.value:
        arr = (HIDP_VALUE_CAPS * nv.value)()
        r = hid.HidP_GetValueCaps(HidP_Input, arr, byref(nv), pp)
        print()
        print("--- 轴/值 (%d 组) ---" % nv.value)
        for i in range(nv.value):
            c = arr[i]
            print("  [%d] up=%#06x reportID=%d %s bits=%d count=%d logical %d..%d abs=%d"
                  % (i, c.UsagePage, c.ReportID, name_of(c.UsagePage, c.UsageMin),
                     c.BitSize, c.ReportCount, c.LogicalMin, c.LogicalMax, c.IsAbsolute))

    hid.HidD_FreePreparsedData(pp)
    dev.close()


def main():
    rows = hidraw.list_devices()
    print("=== 所有北通(20BC)接口 ===")
    mine = []
    for i, (v, p, up, us, inlen, path) in enumerate(rows):
        if v != 0x20BC:
            continue
        mine.append((path, inlen))
        print("  [%d] pid=%#06x up=%#06x us=%#06x inlen=%d" % (len(mine) - 1, p, up, us, inlen))
        print("      %s" % path)
    if not mine:
        print("  没找到北通手柄")
        return 1
    print()
    print("=== 描述符详情（gamepad 接口） ===")
    target, _ = hidraw.find_gamepad(0x20BC, None)
    dump(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
