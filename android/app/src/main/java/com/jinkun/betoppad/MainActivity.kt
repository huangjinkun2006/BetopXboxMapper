package com.jinkun.betoppad

import android.app.AlarmManager
import android.app.AlertDialog
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.text.method.ScrollingMovementMethod
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.TextView
import android.widget.TimePicker
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Calendar

class MainActivity : AppCompatActivity() {

    private lateinit var pad: PadCanvasView
    private lateinit var badge: TextView
    private lateinit var devTv: TextView
    private lateinit var chips: TextView
    private lateinit var logTv: TextView
    private lateinit var btnRun: Button

    private val scope = MainScope()
    private val pressed = HashSet<Int>()
    private var waitingBind: Target? = null
    private var unbound = false
    private var rootOk = false

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        val prefs = getSharedPreferences(PREF, Context.MODE_PRIVATE)
        Conf.load(prefs)
        setContentView(buildUi())
        askNotify()
        scope.launch {
            boot()
        }
    }

    /** Android 13 起通知要运行时授权，不给的话前台服务那条常驻通知是隐形的 */
    private fun askNotify() {
        if (Build.VERSION.SDK_INT < 33) return
        if (checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED) return
        requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 11)
    }

    private fun save() = Conf.save(getSharedPreferences(PREF, Context.MODE_PRIVATE))

    // ------------------------------------------------------------ 界面
    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun card(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        val g = GradientDrawable()
        g.setColor(Color.WHITE); g.cornerRadius = dp(14).toFloat()
        background = g
        val lp = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT)
        lp.setMargins(dp(10), dp(5), dp(10), dp(5))
        layoutParams = lp
        setPadding(dp(14), dp(12), dp(14), dp(12))
    }

    private fun tv(t: String, size: Int = 13, color: Int = Color.parseColor("#26282e"),
                   bold: Boolean = false): TextView = TextView(this).apply {
        text = t; textSize = size.toFloat(); setTextColor(color)
        if (bold) paint.isFakeBoldText = true
    }

    private fun sub(t: String) = tv(t, 11, Color.parseColor("#8a8f99"))

    private fun btn(t: String, primary: Boolean = true, fn: (Button) -> Unit): Button =
        Button(this).apply {
            text = t
            setTextColor(if (primary) Color.WHITE else Color.parseColor("#26282e"))
            val g = GradientDrawable()
            g.setColor(if (primary) Color.parseColor("#107c10") else Color.parseColor("#f0f0f4"))
            g.cornerRadius = dp(10).toFloat()
            background = g
            val lp = LinearLayout.LayoutParams(0, dp(44), 1f)
            lp.setMargins(dp(4), dp(4), dp(4), dp(4))
            layoutParams = lp
            setOnClickListener { fn(this) }
        }

    private fun buildUi(): ScrollView {
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.setBackgroundColor(Color.parseColor("#f2f3f7"))

        val head = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(14), dp(14), dp(14), dp(6))
        }
        head.addView(tv("北通 BTP-V1T 映射器", 18, bold = true))
        badge = tv("未启动", 11, Color.parseColor("#8a8f99")).apply {
            val g = GradientDrawable()
            g.setColor(Color.parseColor("#f0f0f4")); g.cornerRadius = dp(10).toFloat()
            setPadding(dp(10), dp(4), dp(10), dp(4))
            background = g
        }
        head.addView(badge)
        root.addView(head)

        // 手柄图
        val c1 = card()
        pad = PadCanvasView(this)
        c1.addView(pad, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT))
        chips = tv("—", 12, Color.parseColor("#8a8f99"))
        c1.addView(chips)
        root.addView(c1)

        // 状态 + 主控
        val c2 = card()
        devTv = tv("设备：未知", 12, Color.parseColor("#8a8f99"))
        c2.addView(devTv)
        btnRun = btn("启动映射") { toggle() }
        val row1 = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        row1.addView(btnRun)
        c2.addView(row1)
        val row2 = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        row2.addView(btn("选手柄", false) { pickDevice() })
        row2.addView(btn("探测按键", false) { probeNow() })
        c2.addView(row2)
        root.addView(c2)

        // 工具
        val c3 = card()
        c3.addView(sub("功能"))
        val g1 = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        g1.addView(btn("改键", false) { openRebind() })
        g1.addView(btn("震动实验室", false) { openLab() })
        c3.addView(g1)
        val g2 = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        g2.addView(btn("震动闹钟", false) { openAlarm() })
        g2.addView(btn("检查更新", false) { openUpdate() })
        c3.addView(g2)
        val g3 = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        g3.addView(btn("摇杆反向", false) { openAxes() })
        g3.addView(btn("使用说明", false) { openHelp() })
        c3.addView(g3)
        val g4 = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        g4.addView(btn("独占接管", false) { b ->
            Conf.grab = !Conf.grab
            save()
            b.text = "独占接管: " + if (Conf.grab) "开" else "关"
            toast(if (Conf.grab) "独占接管已开（下次启动生效）" else "独占接管已关")
        }.apply { text = "独占接管: " + if (Conf.grab) "开" else "关" })
        c3.addView(g4)
        root.addView(c3)

        // 日志
        val c4 = card()
        c4.addView(sub("日志"))
        logTv = TextView(this).apply {
            textSize = 11f
            setTextColor(Color.parseColor("#8a8f99"))
            movementMethod = ScrollingMovementMethod()
            height = dp(120)
        }
        c4.addView(logTv)
        root.addView(c4)

        val sv = ScrollView(this)
        sv.addView(root)
        sv.setBackgroundColor(Color.parseColor("#f2f3f7"))
        return sv
    }

    private fun log(s: String) {
        runOnUiThread {
            logTv.append("$s\n")
            val lines = logTv.text.split("\n")
            if (lines.size > 60) logTv.text = lines.takeLast(50).joinToString("\n")
        }
    }

    private fun setBadge(t: String, ok: Boolean) {
        badge.text = t
        val g = GradientDrawable()
        g.setColor(if (ok) Color.parseColor("#eaf5ea") else Color.parseColor("#f0f0f4"))
        g.cornerRadius = dp(10).toFloat()
        badge.background = g
        badge.setTextColor(if (ok) Color.parseColor("#0c5f0c") else Color.parseColor("#8a8f99"))
    }

    // ------------------------------------------------------------ 启动流程
    private suspend fun boot() = withContext(Dispatchers.Main) {
        log("本机 ABI：${Bridge.abiAsset()}")
        val ok = withContext(Dispatchers.IO) { Bridge.hasRoot() }
        rootOk = ok
        if (!ok) {
            setBadge("没 root", false)
            log("su 不通。这软件必须 root —— 它要直接读写 /dev/input 和 /dev/uinput。")
            return@withContext
        }
        log("root 正常，释放守护进程…")
        val out = Bridge.install(this@MainActivity)
        log(out.trim().ifEmpty { "betopd 已就位" })
        setBadge("待命", true)
        if (Conf.dev.isBlank()) pickDevice(auto = true)
        else devTv.text = "设备：${Conf.dev}"
    }

    private fun pickDevice(auto: Boolean = false) {
        if (!rootOk) { toast("先解决 root"); return }
        scope.launch {
            val devs = Bridge.listDevices()
            if (devs.isEmpty()) {
                log("一个 /dev/input/event* 都没读到"); return@launch
            }
            val guess = devs.indexOfFirst {
                it.second.contains("betop", true) || it.second.contains("gamepad", true) ||
                it.second.contains("BFM", true)
            }
            if (auto && guess >= 0) {
                Conf.dev = devs[guess].first; save()
                devTv.text = "设备：${Conf.dev}（${devs[guess].second}）"
                log("自动选中 ${devs[guess].first} · ${devs[guess].second}")
                return@launch
            }
            withContext(Dispatchers.Main) {
                val names = devs.map { "${it.first}\n${it.second}" }.toTypedArray()
                AlertDialog.Builder(this@MainActivity)
                    .setTitle("哪个是手柄？")
                    .setItems(names) { _, i ->
                        Conf.dev = devs[i].first; save()
                        devTv.text = "设备：${Conf.dev}"
                        log("选中 ${devs[i].first}")
                    }.show()
            }
        }
    }

    private fun probeNow() {
        if (Conf.dev.isBlank()) { toast("先选设备"); return }
        scope.launch {
            val p = Bridge.probe(Conf.dev)
            withContext(Dispatchers.Main) {
                AlertDialog.Builder(this@MainActivity)
                    .setTitle("设备信息")
                    .setMessage(
                        "名字：${p.name}\n物理口：${p.id}\n\n" +
                        "按键码（${p.keys.size} 个）：\n${p.keys.joinToString(" ")}\n\n" +
                        "轴（码 最小 最大）：\n" +
                        p.axes.joinToString("\n") { (a, lo, hi) -> "  $a  $lo .. $hi" }
                    ).show()
                log("probe：${p.keys.size} 键 / ${p.axes.size} 轴")
            }
        }
    }

    // ------------------------------------------------------------ 运行
    private fun toggle() {
        if (Bridge.running) {
            Bridge.stop()
            PadService.ctxStart(this, PadService.A_STOP)
            btnRun.text = "启动映射"
            setBadge("待命", true)
            pressed.clear(); unbound = false; refreshPad()
            log("已停止")
            return
        }
        if (!rootOk || Conf.dev.isBlank()) { toast("先 root + 选手柄"); return }
        scope.launch {
            log("写映射表并启动守护进程…")
            Bridge.writeMap(Conf.toConfText())
            val ok = Bridge.start(this@MainActivity, Conf.dev, Conf.hidraw, Conf.grab)
            if (!ok) { log("启动失败"); return@launch }
            PadService.ctxStart(this@MainActivity, PadService.A_START)
            btnRun.text = "停止映射"
            setBadge("运行中", true)
            log("已启动（虚拟手柄已创建）")
            // 顺手挑一个 hidraw 节点，留着震动用
            if (Conf.hidraw.isBlank()) {
                val h = Bridge.listHidraw()
                if (h.isNotEmpty()) { Conf.hidraw = h.first(); save(); log("震动通道候选：${h.joinToString(" ")}") }
            }
            startReader()
        }
    }

    private fun startReader() {
        scope.launch(Dispatchers.IO) {
            while (Bridge.running) {
                val line = Bridge.readLine() ?: break
                if (line.isBlank() || line.startsWith("READY")) continue
                withContext(Dispatchers.Main) { apply(line) }
            }
            withContext(Dispatchers.Main) {
                btnRun.text = "启动映射"
                setBadge("守护进程掉了", false)
                log("守护进程退出")
            }
        }
    }

    /** daemon 报的是【原始】键码，这里按映射表折算成虚拟按键来画界面 */
    private fun apply(line: String) {
        val p = line.split(" ")
        if (p.size < 3) return
        val code = p[1].toIntOrNull() ?: return
        val v = p[2].toIntOrNull() ?: return
        if (p[0] == "K") {
            val dst = Conf.keyMap()[code]
            if (dst == null) {
                unbound = v > 0
                if (v > 0) chips.text = "未绑定的键：$code（可能就是 FN）"
            } else if (v > 0) pressed.add(dst) else pressed.remove(dst)
        } else if (p[0] == "A") {
            val dst = Conf.absMap()[code] ?: return
            val f = when (dst) {
                0x00 -> { pad.lx = v / 32768f; return }
                0x01 -> { pad.ly = v / 32768f; return }
                0x03 -> { pad.rx = v / 32768f; return }
                0x04 -> { pad.ry = v / 32768f; return }
                0x02 -> { pad.lt = v / 255f; return }
                0x05 -> { pad.rt = v / 255f; return }
                else -> return
            }
            Unit
        }
        refreshPad()
    }

    private fun refreshPad() {
        pad.pressed = pressed.toSet()
        pad.fnHeld = unbound
        val names = pressed.mapNotNull { c -> TARGETS.firstOrNull { it.code == c }?.cg }
        chips.text = if (names.isEmpty()) "—" else names.joinToString(" ")
        pad.invalidate()
    }

    // ------------------------------------------------------------ 改键
    private fun openRebind() {
        if (!Bridge.running) { toast("先启动映射再改键，不然听不到按键"); return }
        val names = TARGETS.map { "${it.cg}　${it.cn}" }.toTypedArray()
        AlertDialog.Builder(this)
            .setTitle("要改哪个键？")
            .setItems(names) { _, i ->
                val t = TARGETS[i]
                waitingBind = t
                AlertDialog.Builder(this)
                    .setTitle("按下手柄上的键")
                    .setMessage("现在按一下你想让 ${t.cg}（${t.cn}） 用的那个实体键。\n\n" +
                        "选了「不用」就是丢弃这个键。")
                    .setNegativeButton("取消") { _, _ -> waitingBind = null }
                    .setOnDismissListener { waitingBind = null }
                    .show()
                // 捕获下一个原始按键
                scope.launch(Dispatchers.IO) {
                    for (n in 0 until 300) {
                        if (waitingBind == null) break
                        val line = Bridge.readLine() ?: break
                        if (!line.startsWith("K ")) continue
                        val pp = line.split(" ")
                        val src = pp[1].toIntOrNull() ?: continue
                        if (pp[2].toIntOrNull() != 1) continue
                        withContext(Dispatchers.Main) {
                            Conf.setKey(src, t.code)
                            save()
                            log("已绑定：原始 $src -> ${t.cg}(${t.code})")
                            toast("绑好了，重启映射生效")
                            waitingBind = null
                        }
                        break
                    }
                }
            }.show()
    }

    // ------------------------------------------------------------ 摇杆反向
    /** 注意这里是手柄上报的原始轴码，不是映射后的那套虚拟码 */
    private fun openAxes() {
        val srcs = intArrayOf(0x00, 0x01, 0x02, 0x05)
        val labels = arrayOf("左摇杆 横", "左摇杆 纵", "右摇杆 横", "右摇杆 纵")
        val inv = Conf.invert()
        val checked = BooleanArray(srcs.size) { inv.contains(srcs[it]) }
        AlertDialog.Builder(this)
            .setTitle("哪个方向反了就勾哪个")
            .setMultiChoiceItems(labels, checked) { _, i, v ->
                if (v != Conf.invert().contains(srcs[i])) Conf.toggleInvert(srcs[i])
            }
            .setPositiveButton("生效（会重启映射）") { _, _ ->
                save()
                if (!Bridge.running) { toast("已保存，下次启动生效"); return@setPositiveButton }
                scope.launch {
                    Bridge.stop()
                    Bridge.writeMap(Conf.toConfText())
                    Bridge.start(this@MainActivity, Conf.dev, Conf.hidraw, Conf.grab)
                    log("轴反向已改，映射重启")
                    toast("改好了")
                }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    // ------------------------------------------------------------ 震动实验室
    private fun openLab() {
        val ll = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(16), dp(8), dp(16), 0) }
        val tBig = tv("大马达 255"); ll.addView(tBig)
        val sBig = SeekBar(this).apply { max = 255; progress = 255 }
        ll.addView(sBig)
        val tSmall = tv("小马达 0"); ll.addView(tSmall)
        val sSmall = SeekBar(this).apply { max = 255 }
        ll.addView(sSmall)
        sBig.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(s: SeekBar?, p: Int, f: Boolean) { tBig.text = "大马达 $p" }
            override fun onStartTrackingTouch(s: SeekBar?) {}
            override fun onStopTrackingTouch(s: SeekBar?) {}
        })
        sSmall.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(s: SeekBar?, p: Int, f: Boolean) { tSmall.text = "小马达 $p" }
            override fun onStartTrackingTouch(s: SeekBar?) {}
            override fun onStopTrackingTouch(s: SeekBar?) {}
        })
        var holding = false
        val d = AlertDialog.Builder(this)
            .setTitle("震动实验室")
            .setView(ll)
            .setPositiveButton("试震一下", null)
            .setNeutralButton("连续", null)
            .setNegativeButton("停") { _, _ -> holding = false; scope.launch { Bridge.rumbleOff(); toast("停了") } }
            .create()
        d.setOnShowListener {
            d.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                scope.launch {
                    if (!Bridge.running) { toast("先启动映射"); return@launch }
                    Bridge.rumble(sBig.progress, sSmall.progress)
                    delay(500)
                    Bridge.rumbleOff()
                }
            }
            d.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener {
                holding = !holding
                scope.launch {
                    while (holding) { Bridge.rumble(sBig.progress, sSmall.progress); delay(200) }
                    Bridge.rumbleOff()
                }
            }
        }
        d.setOnDismissListener { holding = false }
        d.show()
        if (Conf.hidraw.isBlank()) log("还没选震动通道（hidraw），先看能不能震")
    }

    // ------------------------------------------------------------ 闹钟
    private fun openAlarm() {
        val ll = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER }
        val tp = TimePicker(this).apply { setIs24HourView(true) }
        ll.addView(tp)
        val st = tv("强度 100%")
        ll.addView(st)
        val sb = SeekBar(this).apply { max = 100; progress = (Conf.alarmStrength * 100).toInt() }
        ll.addView(sb)
        sb.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(s: SeekBar?, p: Int, f: Boolean) { st.text = "强度 $p%" }
            override fun onStartTrackingTouch(s: SeekBar?) {}
            override fun onStopTrackingTouch(s: SeekBar?) {}
        })
        AlertDialog.Builder(this)
            .setTitle("震动闹钟")
            .setView(ll)
            .setPositiveButton("开启") { _, _ ->
                Conf.alarmOn = true
                Conf.alarmTime = "%02d:%02d".format(tp.hour, tp.minute)
                Conf.alarmStrength = sb.progress / 100.0
                save()
                setAlarm(true)
                toast("闹钟 ${Conf.alarmTime}")
            }
            .setNeutralButton("试震") { _, _ ->
                Conf.alarmStrength = sb.progress / 100.0; save()
                PadService.ctxStart(this, PadService.A_ALARM)
            }
            .setNegativeButton("关掉") { _, _ ->
                Conf.alarmOn = false; save(); setAlarm(false); toast("闹钟关了")
            }
            .show()
    }

    private fun setAlarm(on: Boolean) {
        val am = getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val pi = PendingIntent.getBroadcast(
            this, 7, Intent(this, AlarmReceiver::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        if (!on) { am.cancel(pi); return }
        val (h, m) = Conf.alarmTime.split(":").map { it.toInt() }
        val cal = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, h); set(Calendar.MINUTE, m)
            set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
            if (timeInMillis <= System.currentTimeMillis()) add(Calendar.DAY_OF_YEAR, 1)
        }
        am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, cal.timeInMillis, pi)
        log("闹钟 ${Conf.alarmTime} 已挂上")
    }

    // ------------------------------------------------------------ 更新 / 帮助
    private fun openUpdate() {
        toast("正在查…")
        scope.launch {
            val info = Updater.check()
            withContext(Dispatchers.Main) {
                if (info.newest) {
                    AlertDialog.Builder(this@MainActivity)
                        .setTitle("已是最新")
                        .setMessage("当前版本 ${Updater.VERSION}\n\n${info.notes.take(300)}")
                        .show()
                } else {
                    AlertDialog.Builder(this@MainActivity)
                        .setTitle("有新版本 ${info.tag}")
                        .setMessage(info.notes.take(400))
                        .setPositiveButton("下载") { _, _ ->
                            if (info.apk != null) {
                                Updater.download(this@MainActivity, info.apk!!, info.tag)
                                toast("已丢给下载器，下完点开安装")
                            } else toast("这个版本没带 apk")
                        }.show()
                }
            }
        }
    }

    private fun openHelp() {
        AlertDialog.Builder(this)
            .setTitle("怎么用")
            .setMessage("""
1. 手机必须 root。这软件是绕过 framework 直接读写 /dev/input 和 /dev/uinput 的，
   等于给安卓做了个 ViGEm —— 没有别的办法能在安卓上伪造手柄。

2. OTG 接上手柄 → 点「选手柄」，认不出就手动挑那个名字带 betop/gamepad 的节点。

3. 点「启动映射」。这时候系统里会多出一个标准安卓手柄，
   游戏里看到的就不是原来那把了 —— 所有只认标准手柄的游戏都能用。

4. 按键不对就点「改键」：挑虚拟目标键，然后按实体键。
   FN 这种非标准键也能绑。

5. 「探测按键」能看到这台手机实际给每个物理键分配的键码，
   kernel 排列不一样时对照它改就行。

6. 震动：实验室里能试，闹钟到点也会震。命令走 /dev/hidraw，
   格式是 PC 上穷举出来的那条。

注意：开了「独占接管」后物理手柄的信号会被吃掉，
万一守护进程崩了手柄会短暂失灵 —— 点「停止映射」就恢复。
            """.trimIndent())
            .show()
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
}
