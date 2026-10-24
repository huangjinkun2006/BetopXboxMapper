"""纯 ctypes 的 HID 读取后端（不依赖 hidapi，装不上第三方包时用它）。

接口刻意做成和 hidapi 的 hid.device() 一致：open_path() / read(n) / close()
"""
import ctypes
import time
from ctypes import (POINTER, addressof, byref, c_char_p, c_ubyte, c_ulong,
                    c_ushort, c_void_p, create_string_buffer, sizeof, wstring_at)
from ctypes import wintypes

setupapi = ctypes.windll.setupapi
hid_dll = ctypes.windll.hid
k32 = ctypes.windll.kernel32

H = ctypes.c_ssize_t
INVALID_HANDLE_VALUE = -1
DIGCF_PRESENT = 0x10
DIGCF_INTERFACEDEVICE = 0x02
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", c_void_p), ("InternalHigh", c_void_p),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", c_void_p)]


HidP_Input = 0


def nt_success(status):
    """HidP_* 返回 NTSTATUS，成功是 0x00110000(HIDP_STATUS_SUCCESS)，不是 0。

    只看最高两位（severity）：0=成功 1=信息 2=警告 3=错误。
    """
    return (status & 0xC0000000) == 0


class GUID(ctypes.Structure):
    _fields_ = [("Data1", c_ulong), ("Data2", c_ushort), ("Data3", c_ushort),
                ("Data4", c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD), ("Reserved", POINTER(c_ulong))]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", c_ulong), ("VendorID", c_ushort), ("ProductID", c_ushort),
                ("VersionNumber", c_ushort)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", c_ushort), ("UsagePage", c_ushort),
        ("InputReportByteLength", c_ushort), ("OutputReportByteLength", c_ushort),
        ("FeatureReportByteLength", c_ushort),
        ("Reserved", c_ushort * 17),
        ("NumberLinkCollectionNodes", c_ushort),
        ("NumberInputButtonCaps", c_ushort), ("NumberInputValueCaps", c_ushort),
        ("NumberInputDataIndices", c_ushort), ("NumberOutputButtonCaps", c_ushort),
        ("NumberOutputValueCaps", c_ushort), ("NumberOutputDataIndices", c_ushort),
        ("NumberFeatureButtonCaps", c_ushort), ("NumberFeatureValueCaps", c_ushort),
        ("NumberFeatureDataIndices", c_ushort),
    ]


k32.CreateFileW.restype = H
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                            c_void_p, wintypes.DWORD, wintypes.DWORD, c_void_p]
k32.CloseHandle.restype = wintypes.BOOL
k32.CloseHandle.argtypes = [H]
k32.ReadFile.restype = wintypes.BOOL
k32.ReadFile.argtypes = [H, c_void_p, wintypes.DWORD, POINTER(wintypes.DWORD),
                         POINTER(OVERLAPPED)]
k32.CreateEventW.restype = H
k32.CreateEventW.argtypes = [c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
k32.WaitForSingleObject.restype = wintypes.DWORD
k32.WaitForSingleObject.argtypes = [H, wintypes.DWORD]
k32.GetOverlappedResult.restype = wintypes.BOOL
k32.GetOverlappedResult.argtypes = [H, POINTER(OVERLAPPED),
                                    POINTER(wintypes.DWORD), wintypes.BOOL]
k32.CancelIo.restype = wintypes.BOOL
k32.CancelIo.argtypes = [H]
k32.GetLastError.restype = wintypes.DWORD
k32.GetLastError.argtypes = []
k32.WriteFile.restype = wintypes.BOOL
k32.WriteFile.argtypes = [H, c_void_p, wintypes.DWORD, POINTER(wintypes.DWORD),
                          POINTER(OVERLAPPED)]

setupapi.SetupDiGetClassDevsW.restype = H
setupapi.SetupDiGetClassDevsW.argtypes = [POINTER(GUID), wintypes.LPCWSTR,
                                          wintypes.HWND, wintypes.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [H, c_void_p, POINTER(GUID),
                                                 wintypes.DWORD,
                                                 POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    H, POINTER(SP_DEVICE_INTERFACE_DATA), c_void_p, wintypes.DWORD,
    POINTER(wintypes.DWORD), c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [H]

hid_dll.HidD_GetHidGuid.restype = None
hid_dll.HidD_GetHidGuid.argtypes = [POINTER(GUID)]
hid_dll.HidD_GetAttributes.restype = wintypes.BOOL
hid_dll.HidD_GetAttributes.argtypes = [H, POINTER(HIDD_ATTRIBUTES)]
hid_dll.HidD_GetPreparsedData.restype = wintypes.BOOL
hid_dll.HidD_GetPreparsedData.argtypes = [H, POINTER(c_void_p)]
hid_dll.HidD_FreePreparsedData.restype = wintypes.BOOL
hid_dll.HidD_FreePreparsedData.argtypes = [c_void_p]
class USAGE_AND_PAGE(ctypes.Structure):
    _fields_ = [("Usage", c_ushort), ("UsagePage", c_ushort)]


hid_dll.HidP_GetCaps.restype = c_ulong
hid_dll.HidP_GetCaps.argtypes = [c_void_p, POINTER(HIDP_CAPS)]
hid_dll.HidD_GetInputReport.restype = wintypes.BOOL
hid_dll.HidD_GetInputReport.argtypes = [H, c_void_p, c_ulong]
hid_dll.HidP_GetUsagesEx.restype = c_ulong
hid_dll.HidP_GetUsagesEx.argtypes = [c_ulong, c_ushort, POINTER(USAGE_AND_PAGE),
                                     POINTER(c_ulong), c_void_p, c_char_p, c_ulong]
hid_dll.HidP_GetUsageValue.restype = c_ulong
hid_dll.HidP_GetUsageValue.argtypes = [c_ulong, c_ushort, c_ushort, c_ushort,
                                       POINTER(c_ulong), c_void_p, c_char_p, c_ulong]


def list_devices(vid=None, pid=None):
    """返回 [(vid, pid, usage_page, usage, in_len, path), ...]"""
    guid = GUID()
    hid_dll.HidD_GetHidGuid(byref(guid))
    hdev = setupapi.SetupDiGetClassDevsW(byref(guid), None, None,
                                         DIGCF_PRESENT | DIGCF_INTERFACEDEVICE)
    if hdev == INVALID_HANDLE_VALUE:
        return []
    rows = []
    idx = 0
    while True:
        ifdata = SP_DEVICE_INTERFACE_DATA()
        ifdata.cbSize = sizeof(SP_DEVICE_INTERFACE_DATA)
        if not setupapi.SetupDiEnumDeviceInterfaces(hdev, None, byref(guid), idx,
                                                    byref(ifdata)):
            break
        idx += 1
        need = wintypes.DWORD()
        setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, byref(ifdata), None, 0,
                                                  byref(need), None)
        if need.value == 0:
            continue
        buf = create_string_buffer(need.value)
        ctypes.cast(buf, POINTER(c_ulong))[0] = 8
        out = wintypes.DWORD()
        if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, byref(ifdata), ctypes.cast(buf, c_void_p), need.value,
                byref(out), None):
            continue
        path = None
        for off in (4, 8):
            cand = wstring_at(addressof(buf) + off)
            if cand.startswith("\\\\?\\"):
                path = cand
                break
        if path is None:
            continue
        h = k32.CreateFileW(path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                            OPEN_EXISTING, 0, None)
        if h == INVALID_HANDLE_VALUE:
            continue
        try:
            attr = HIDD_ATTRIBUTES()
            attr.Size = sizeof(HIDD_ATTRIBUTES)
            if not hid_dll.HidD_GetAttributes(h, byref(attr)):
                continue
            if vid is not None and attr.VendorID != vid:
                continue
            if pid is not None and attr.ProductID != pid:
                continue
            caps = HIDP_CAPS()
            pp = c_void_p()
            up = us = 0
            inlen = 64
            if hid_dll.HidD_GetPreparsedData(h, byref(pp)):
                hid_dll.HidP_GetCaps(pp, byref(caps))
                hid_dll.HidD_FreePreparsedData(pp)
                up, us = caps.UsagePage, caps.Usage
                inlen = max(caps.InputReportByteLength, 1)
            rows.append((attr.VendorID, attr.ProductID, up, us, inlen, path))
        finally:
            k32.CloseHandle(h)
    setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return rows


class RawHid:
    """模仿 hidapi 的 hid.device 接口。

    注意：手柄走中断端点，HidD_GetInputReport 读不到东西，必须用带超时的
    异步 ReadFile，否则没数据时直接永久阻塞。
    """

    def __init__(self):
        self.h = INVALID_HANDLE_VALUE
        self.in_len = 64
        self.out_len = 0        # 0 = 这个接口不支持输出报告
        self.path = None
        self.preparsed = None

    def open_path(self, path):
        self.h = k32.CreateFileW(
            path, GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED, None)
        if self.h == INVALID_HANDLE_VALUE:
            raise OSError(f"打不开 {path}  (err={k32.GetLastError()})")
        self.path = path
        pp = c_void_p()
        if hid_dll.HidD_GetPreparsedData(self.h, byref(pp)):
            caps = HIDP_CAPS()
            hid_dll.HidP_GetCaps(pp, byref(caps))
            self.in_len = max(caps.InputReportByteLength, 1)
            self.out_len = caps.OutputReportByteLength
            self.preparsed = pp
        return self

    def set_report(self, data, timeout_ms=400):
        """用控制通道发 HID SET_REPORT（骨子里就是设备要的 HID_REQ_SET_REPORT）。

        有些手柄（北通内核驱动 hid-betopff.c 就是这么干的）只吃控制通道的
        SET_REPORT，不走 WriteFile 的中断 OUT 端点。两者都试才知道。
        """
        n = max(len(data), self.out_len, 1)
        buf = create_string_buffer(bytes(data).ljust(n, b"\x00"), n)
        fn = getattr(hid_dll, "HidD_SetOutputReport", None)
        if fn is None:
            return False
        fn.argtypes = [H, c_void_p, wintypes.ULONG]
        fn.restype = wintypes.BOOLEAN
        if not fn(self.h, buf, n):
            # 有的设备在报告长度不符时也会失败，再按实际长度试一次
            buf2 = create_string_buffer(bytes(data), len(data))
            return bool(fn(self.h, buf2, len(data)))
        return True

    def write(self, data, timeout_ms=400):
        """写一帧输出报告（比如震动命令）。成功返回 True。

        句柄是 OVERLAPPED 打开的，所以必须带事件等待，不能传 NULL。
        """
        n = max(len(data), self.out_len, 1)
        buf = create_string_buffer(bytes(data).ljust(n, b"\x00"), n)
        ov = OVERLAPPED()
        ov.hEvent = k32.CreateEventW(None, True, False, None)
        if not ov.hEvent:
            return False
        try:
            nw = wintypes.DWORD()
            ok = k32.WriteFile(self.h, buf, n, byref(nw), byref(ov))
            if not ok:
                if k32.GetLastError() != ERROR_IO_PENDING:
                    return False
                if k32.WaitForSingleObject(ov.hEvent, timeout_ms) != WAIT_OBJECT_0:
                    k32.CancelIo(self.h)
                    return False
                if not k32.GetOverlappedResult(self.h, byref(ov), byref(nw), False):
                    return False
            return True
        finally:
            k32.CloseHandle(ov.hEvent)

    def set_nonblocking(self, v):
        pass

    def decode(self, report):
        """用系统 HidP 解析报告，彻底不用猜字节位。

        返回 (buttons, values)：
          buttons = {usage: usage_page}  当前按下的键
          values  = {(usage_page, usage): 数值}
        """
        buf = bytes(report[:self.in_len]).ljust(self.in_len, b"\x00")
        buttons, values = {}, {}
        if not self.preparsed:
            return buttons, values
        n = c_ulong(32)
        arr = (USAGE_AND_PAGE * 32)()
        st = hid_dll.HidP_GetUsagesEx(0, 0, arr, byref(n), self.preparsed,
                                      buf, len(buf))
        if nt_success(st):
            for i in range(min(n.value, 32)):
                buttons[arr[i].Usage] = arr[i].UsagePage
        return buttons, values

    def usage_value(self, report, usage_page, usage):
        """取指定 usage 的数值；失败返回 None"""
        if not self.preparsed:
            return None
        buf = bytes(report[:self.in_len]).ljust(self.in_len, b"\x00")
        v = c_ulong()
        if nt_success(hid_dll.HidP_GetUsageValue(0, usage_page, 0, usage, byref(v),
                                                 self.preparsed, buf, len(buf))):
            return v.value
        return None

    def read(self, size=64, timeout_ms=120):
        n = max(size, self.in_len)
        buf = create_string_buffer(n)
        ov = OVERLAPPED()
        ov.hEvent = k32.CreateEventW(None, True, False, None)
        if not ov.hEvent:
            return None
        nread = wintypes.DWORD()
        ok = k32.ReadFile(self.h, buf, n, byref(nread), byref(ov))
        if not ok:
            if k32.GetLastError() != ERROR_IO_PENDING:
                k32.CloseHandle(ov.hEvent)
                return None
            if k32.WaitForSingleObject(ov.hEvent, timeout_ms) != WAIT_OBJECT_0:
                k32.CancelIo(self.h)
                k32.CloseHandle(ov.hEvent)
                return None
            if not k32.GetOverlappedResult(self.h, byref(ov), byref(nread), False):
                k32.CloseHandle(ov.hEvent)
                return None
        k32.CloseHandle(ov.hEvent)
        cnt = nread.value or n
        return list(buf[:cnt])

    def close(self):
        if self.preparsed:
            hid_dll.HidD_FreePreparsedData(self.preparsed)
            self.preparsed = None
        if self.h not in (INVALID_HANDLE_VALUE, None):
            k32.CloseHandle(self.h)
            self.h = INVALID_HANDLE_VALUE


def find_output_iface(vid, pid=None, page=0xFF00):
    """找厂商私有接口（震动命令走这个通道）。没有返回 None。

    游戏手柄那个接口（0x01/0x05）实测 out_len=0，发不了东西，
    震动只能走 0xFF00 这个 64 字节双向通道。
    """
    rows = list_devices(vid, pid)
    for v, p, up, us, inlen, path in rows:
        if up == page:
            return path
    return None


def find_gamepad(vid, pid):
    """挑 gamepad(0x01/0x05) -> joystick(0x01/0x04) -> 第一个"""
    rows = list_devices(vid, pid)
    if not rows:
        return None, None
    for want in ((0x01, 0x05), (0x01, 0x04)):
        for v, p, up, us, inlen, path in rows:
            if (up, us) == want:
                return path, inlen
    return rows[0][5], rows[0][4]
