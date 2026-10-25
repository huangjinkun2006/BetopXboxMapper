package com.jinkun.betoppad

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(c: Context, i: Intent?) {
        PadService.ctxStart(c, PadService.A_ALARM)
    }
}
