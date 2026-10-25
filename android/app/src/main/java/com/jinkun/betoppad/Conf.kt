package com.jinkun.betoppad

import org.json.JSONObject

/** 虚拟手柄对外暴露的标准键（Linux/Android gamepad 布局），改键面板的目标就是这些 */
data class Target(val cg: String, val code: Int, val cn: String)

val TARGETS = listOf(
    Target("A", 0x130, "A"), Target("B", 0x131, "B"),
    Target("X", 0x133, "X"), Target("Y", 0x134, "Y"),
    Target("LB", 0x136, "LB"), Target("RB", 0x137, "RB"),
    Target("LT", 0x138, "LT"), Target("RT", 0x139, "RT"),
    Target("BACK", 0x13a, "返回"), Target("START", 0x13b, "菜单"),
    Target("LOGO", 0x13c, "LOGO"),
    Target("L3", 0x13d, "左摇杆按下"), Target("R3", 0x13e, "右摇杆按下"),
    Target("UP", 0x220, "上"), Target("DOWN", 0x221, "下"),
    Target("LEFT", 0x222, "左"), Target("RIGHT", 0x223, "右"),
    Target("FN", -1, "不用（丢弃）"),
)

/** 界面上手柄图需要的键名 -> 虚拟码，方便直接点亮 */
val VIEW_MAP = TARGETS.associateBy { it.cg }

/**
 * 默认物理->虚拟 映射。
 * 说明：安卓 kernel 的 hid-input 把手柄按钮攒成 BTN_TRIGGER(0x120) 那一串，
 * 按 usage 顺序排：usage n -> 0x120 + (n-1)。
 * 所以 BTP-V1T 上 A=usage1 -> 0x120，B=usage2 -> 0x121，X=usage4 -> 0x123
 * ……FN=usage105 -> 0x188（这个超出上面那串，得 probe 才知道落在哪）。
 * 万一机器之间的排列不一样，用改键面板改一下就行。
 */
val DEFAULT_KEY = linkedMapOf(
    0x120 to 0x130,   // A
    0x121 to 0x131,   // B
    0x123 to 0x133,   // X
    0x124 to 0x134,   // Y
    0x126 to 0x136,   // LB
    0x127 to 0x137,   // RB
    0x12f to 0x13a,   // BACK（返回）
    0x12a to 0x13b,   // START（菜单）
    0x12b to 0x13c,   // GUIDE（蓝色箭头）
    0x12d to 0x13d,   // LS（左摇杆按下）
    0x12e to 0x13e,   // RS（右摇杆按下）
)

/** 默认轴映射：物理 -> 虚拟（左/右摇杆 + 两个扳机 + 十字键 HAT 原样透传） */
val DEFAULT_ABS = linkedMapOf(
    0x00 to 0x00,   // ABS_X  -> ABS_X   左摇杆 X
    0x01 to 0x01,   // ABS_Y  -> ABS_Y   左摇杆 Y
    0x02 to 0x03,   // ABS_Z  -> ABS_RX  右摇杆 X（这把的手柄 Z 才是右摇杆横轴）
    0x05 to 0x04,   // ABS_RZ -> ABS_RY  右摇杆 Y
    0x0a to 0x02,   // ABS_BRAKE -> ABS_Z   LT
    0x09 to 0x05,   // ABS_GAS   -> ABS_RZ  RT
    0x10 to 0x10,   // HAT0X
    0x11 to 0x11,   // HAT0Y
)

const val PREF = "betop"
const val K_MAP_KEY = "map_key"
const val K_MAP_ABS = "map_abs"
const val K_INVERT = "invert"
const val K_DEV = "dev"
const val K_HIDRAW = "hidraw"
const val K_GRAB = "grab"
const val K_ALARM = "alarm_on"
const val K_ALARM_TIME = "alarm_time"
const val K_ALARM_ST = "alarm_strength"

object Conf {
    private var j = JSONObject()
    var raw: String = ""
        private set

    fun load(prefs: android.content.SharedPreferences) {
        raw = prefs.getString(PREF, "") ?: ""
        j = try { JSONObject(raw) } catch (e: Exception) { JSONObject() }
    }

    fun save(prefs: android.content.SharedPreferences) {
        raw = j.toString()
        prefs.edit().putString(PREF, raw).apply()
    }

    fun keyMap(): MutableMap<Int, Int> {
        val m = LinkedHashMap(DEFAULT_KEY)
        val o = j.optJSONObject(K_MAP_KEY) ?: return m
        val it = o.keys()
        while (it.hasNext()) {
            val k = it.next()
            m[k.toInt()] = o.getInt(k)
        }
        return m
    }

    fun absMap(): MutableMap<Int, Int> {
        val m = LinkedHashMap(DEFAULT_ABS)
        val o = j.optJSONObject(K_MAP_ABS) ?: return m
        val it = o.keys()
        while (it.hasNext()) {
            val k = it.next()
            m[k.toInt()] = o.getInt(k)
        }
        return m
    }

    fun invert(): MutableSet<Int> {
        val s = HashSet<Int>()
        val a = j.optJSONArray(K_INVERT) ?: return s
        for (i in 0 until a.length()) s.add(a.getInt(i))
        return s
    }

    fun setKey(src: Int, dst: Int) {
        val o = j.optJSONObject(K_MAP_KEY) ?: JSONObject()
        o.put(src.toString(), dst)
        j.put(K_MAP_KEY, o)
    }

    fun setAbs(src: Int, dst: Int) {
        val o = j.optJSONObject(K_MAP_ABS) ?: JSONObject()
        o.put(src.toString(), dst)
        j.put(K_MAP_ABS, o)
    }

    fun toggleInvert(src: Int) {
        val s = invert()
        if (!s.add(src)) s.remove(src)
        val a = org.json.JSONArray()
        s.forEach { a.put(it) }
        j.put(K_INVERT, a)
    }

    var dev: String
        get() = j.optString(K_DEV, "")
        set(v) { j.put(K_DEV, v) }

    var hidraw: String
        get() = j.optString(K_HIDRAW, "")
        set(v) { j.put(K_HIDRAW, v) }

    var grab: Boolean
        get() = j.optBoolean(K_GRAB, true)
        set(v) { j.put(K_GRAB, v) }

    var alarmOn: Boolean
        get() = j.optBoolean(K_ALARM, false)
        set(v) { j.put(K_ALARM, v) }

    var alarmTime: String
        get() = j.optString(K_ALARM_TIME, "07:00")
        set(v) { j.put(K_ALARM_TIME, v) }

    var alarmStrength: Double
        get() = j.optDouble(K_ALARM_ST, 1.0)
        set(v) { j.put(K_ALARM_ST, v) }

    /** 导出给 daemon 读的映射文件 */
    fun toConfText(): String {
        val sb = StringBuilder("# betop map\n")
        keyMap().forEach { (s, d) -> sb.append("k $s $d\n") }
        absMap().forEach { (s, d) -> sb.append("a $s $d\n") }
        invert().forEach { sb.append("i $it 1\n") }
        return sb.toString()
    }
}
