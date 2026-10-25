package com.jinkun.betoppad

import android.content.Context
import android.os.Build
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.io.DataOutputStream
import java.io.File
import java.io.FileOutputStream

/**
 * 和 root 守护进程的桥。
 *
 * 流程：assets/<abi>/libbetopd.so（其实是 ELF 可执行） -> 释放到 /data/local/tmp/betopd
 *      -> su 拉起 -> 拿 stdout（"K <码> <0|1>" / "A <轴> <值>"）更新界面
 *      -> 往 stdin 写 "R <大> <小>" 让它震动
 */
object Bridge {

    private const val REMOTE = "/data/local/tmp/betopd"
    private const val REMOTE_MAP = "/data/local/tmp/betopd.map"

    data class Probe(
        val name: String, val id: String,
        val keys: List<Int>, val axes: List<Triple<Int, Int, Int>>
    )

    /** 这台机器、这个 App 该用 assets 下哪一套二进制 */
    fun abiAsset(): String {
        val abis = Build.SUPPORTED_ABIS.toList()
        return when {
            abis.contains("arm64-v8a") -> "arm64-v8a"
            abis.contains("armeabi-v7a") -> "armeabi-v7a"
            abis.contains("x86_64") -> "x86_64"
            abis.contains("x86") -> "x86"
            else -> abis.firstOrNull() ?: "arm64-v8a"
        }
    }

    private fun su(vararg cmds: String): Pair<Int, String> = try {
        val p = Runtime.getRuntime().exec(arrayOf("su", "-c", cmds.joinToString(" && ")))
        val out = p.inputStream.bufferedReader().readText()
        val err = p.errorStream.bufferedReader().readText()
        val code = p.waitFor()
        code to (out + err)
    } catch (e: Exception) {
        -1 to (e.message ?: "su 调用失败")
    }

    fun hasRoot(): Boolean {
        val (c, o) = su("id -u")
        return c == 0 && o.trim().startsWith("0")
    }

    /** 释放 binary 并 chmod —— 每次升级都要重来一遍 */
    suspend fun install(ctx: Context): String = withContext(Dispatchers.IO) {
        val local = File(ctx.filesDir, "betopd").absolutePath
        ctx.assets.open("${abiAsset()}/libbetopd.so").use { src ->
            FileOutputStream(local).use { dst -> src.copyTo(dst) }
        }
        su("cp $local $REMOTE", "chmod 755 $REMOTE", "ls -l $REMOTE").second
    }

    suspend fun writeMap(text: String) = withContext(Dispatchers.IO) {
        val tmp = "/data/local/tmp/.betopd.map"
        val pw = Runtime.getRuntime().exec(arrayOf("su", "-c", "cat > $tmp"))
        DataOutputStream(pw.outputStream).use {
            it.writeBytes(text); it.flush()
        }
        pw.waitFor()
        su("mv $tmp $REMOTE_MAP", "chmod 644 $REMOTE_MAP")
    }

    /** 列出所有 /dev/input/event*，顺便把名字读出来 */
    suspend fun listDevices(): List<Pair<String, String>> = withContext(Dispatchers.IO) {
        val (_, out) = su(
            "for f in /dev/input/event*; do echo -n \"\$f|\"; cat /sys/class/input/\${f##*/}/device/name 2>/dev/null || getevent -p \$f 2>/dev/null | head -1; echo; done"
        )
        out.lineSequence().mapNotNull {
            val p = it.split("|", limit = 2)
            if (p.size == 2 && p[0].startsWith("/dev/input")) p[0].trim() to p[1].trim()
            else null
        }.toList()
    }

    suspend fun listHidraw(): List<String> = withContext(Dispatchers.IO) {
        val (_, out) = su("ls /dev/hidraw* 2>/dev/null")
        out.lineSequence().map { it.trim() }.filter { it.startsWith("/dev") }.toList()
    }

    /** 探测某设备实际支持哪些键/轴 —— 改键面板靠它拿到真实按键列表 */
    suspend fun probe(dev: String): Probe = withContext(Dispatchers.IO) {
        val (_, out) = su("$REMOTE --probe $dev")
        var name = ""; var id = ""
        val keys = ArrayList<Int>()
        val axes = ArrayList<Triple<Int, Int, Int>>()
        for (line in out.lineSequence()) {
            val c = line.split("\t")
            when (c[0]) {
                "NAME" -> name = c.getOrNull(1) ?: ""
                "PHYS" -> if (id.isEmpty()) id = c.getOrNull(1) ?: ""
                "KEY" -> c.getOrNull(1)?.toIntOrNull()?.let { keys.add(it) }
                "ABS" -> {
                    val a = c.getOrNull(1)?.toIntOrNull()
                    val lo = c.getOrNull(2)?.toIntOrNull()
                    val hi = c.getOrNull(3)?.toIntOrNull()
                    if (a != null && lo != null && hi != null) axes.add(Triple(a, lo, hi))
                }
            }
        }
        Probe(name, id, keys, axes)
    }

    // ---------------------------------------------------------- 运行
    private var proc: Process? = null
    private var out: java.io.BufferedReader? = null
    private var stdin: java.io.OutputStream? = null

    val running: Boolean get() = proc?.isAlive == true

    fun start(ctx: Context, dev: String, hidraw: String, grab: Boolean): Boolean {
        stop()
        val args = mutableListOf(REMOTE, dev, REMOTE_MAP)
        if (grab) args.add("--grab")
        if (hidraw.isNotBlank()) args.addAll(listOf("--hidraw", hidraw))
        return try {
            val p = Runtime.getRuntime().exec(arrayOf("su", "-c", args.joinToString(" ")))
            proc = p
            out = p.inputStream.bufferedReader()
            stdin = p.outputStream
            Thread { runCatching { p.errorStream.bufferedReader().readText() } }.start()
            true
        } catch (e: Exception) {
            e.printStackTrace()
            false
        }
    }

    fun stop() {
        runCatching { proc?.destroy() }
        runCatching {
            Runtime.getRuntime().exec(arrayOf("su", "-c", "pkill -f $REMOTE")).waitFor()
        }
        proc = null; out = null; stdin = null
    }

    /** 读一行状态；没数据就阻塞等（调用方在协程里） */
    suspend fun readLine(): String? = withContext(Dispatchers.IO) {
        runCatching { out?.readLine() }.getOrNull()
    }

    suspend fun rumble(big: Int, small: Int) = withContext(Dispatchers.IO) {
        if (!running) return@withContext
        runCatching {
            stdin?.write("R $big $small\n".toByteArray())
            stdin?.flush()
        }
    }

    suspend fun rumbleOff() = withContext(Dispatchers.IO) {
        runCatching {
            stdin?.write("R 0 0\n".toByteArray())
            stdin?.flush()
        }
        delay(60)
    }
}
