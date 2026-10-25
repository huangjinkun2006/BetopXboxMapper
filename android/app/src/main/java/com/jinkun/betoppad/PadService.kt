package com.jinkun.betoppad

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * 前台常驻服务：相当于 PC 版那个托盘，负责把守护进程一直挂着，
 * 也负责闹钟到点后的震铃。
 */
class PadService : Service() {

    companion object {
        const val CH = "betopd"
        const val A_START = "start"
        const val A_STOP = "stop"
        const val A_ALARM = "alarm"
        const val NOTI = 1001

        fun ctxStart(c: Context, action: String) {
            val i = Intent(c, PadService::class.java).setAction(action)
            if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i) else c.startService(i)
        }
    }

    private val scope = MainScope()

    override fun onBind(i: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        /* 服务可能被闹钟Receiver 在没有 Activity 的情况下拉起来，配置得自己读一遍 */
        Conf.load(getSharedPreferences(PREF, Context.MODE_PRIVATE))
        CompanionNotify.make(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTI, CompanionNotify.build(this, "映射守护中"))
        when (intent?.action) {
            A_STOP -> stopMyself()
            A_ALARM -> ringBell()
            else -> ensureDaemon()
        }
        return START_STICKY
    }

    private fun ensureDaemon() {
        if (Bridge.running) return
        scope.launch {
            val ok = Bridge.start(this@PadService, Conf.dev, Conf.hidraw, Conf.grab)
            CompanionNotify.update(this@PadService, if (ok) "映射运行中" else "启动失败")
        }
    }

    private fun ringBell() {
        scope.launch {
            val st = Conf.alarmStrength.coerceIn(0.1, 1.0)
            val big = (255 * st).toInt().coerceAtMost(255)
            repeat(40) {                       // 大约 8 秒，固件会衰减所以一直补发
                Bridge.rumble(big, big)
                delay(200)
            }
            Bridge.rumbleOff()
            CompanionNotify.update(this@PadService, "映射运行中")
        }
    }

    private fun stopMyself() {
        Bridge.stop()
        if (Build.VERSION.SDK_INT >= 26) stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }
}

object CompanionNotify {
    fun make(c: Context) {
        if (Build.VERSION.SDK_INT < 26) return
        val m = c.getSystemService(NotificationManager::class.java)
        if (m.getNotificationChannel(PadService.CH) == null) {
            m.createNotificationChannel(
                NotificationChannel(PadService.CH, "手柄映射", NotificationManager.IMPORTANCE_LOW)
            )
        }
    }

    fun build(c: Context, text: String): Notification {
        val pi = PendingIntent.getActivity(
            c, 1, Intent(c, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return android.app.Notification.Builder(c, PadService.CH)
            .setContentTitle("北通手柄映射器")
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_pad)
            .setContentIntent(pi)
            .setOngoing(true)
            .build()
    }

    /** 重建 + 真正推上去（光 build 不 notify 的话通知栏文字是不会变的） */
    fun update(c: Context, text: String) {
        val m = c.getSystemService(NotificationManager::class.java)
        m.notify(PadService.NOTI, build(c, text))
    }
}
