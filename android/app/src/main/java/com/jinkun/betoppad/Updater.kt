package com.jinkun.betoppad

import android.app.DownloadManager
import android.content.Context
import android.net.Uri
import android.os.Environment
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** 更新检查：读 GitHub 上最新 release，比对版本号，有就丢给系统下载器装 */
object Updater {

    const val VERSION = "1.0.0"
    /* 跟 PC 版共用同一个仓库，所以：
       ① 不能读 /releases/latest —— 谁后发谁就是 latest，会读到 PC 的 v1.0.9
       ② 只认 tag 以 "android-v" 开头的 release */
    private const val API_RELEASES =
        "https://api.github.com/repos/huangjinkun2006/BetopXboxMapper/releases?per_page=20"

    data class Info(val newest: Boolean, val tag: String, val notes: String, val apk: String?)

    suspend fun check(): Info = withContext(Dispatchers.IO) {
        /** "android-v1.2.3" -> [1,2,3]；tag 前缀得先剥掉 */
        fun parts(a: String): List<Int> =
            a.trim().lowercase().removePrefix("android-v").removePrefix("v")
                .split(".").map { it.toIntOrNull() ?: 0 }

        fun newer(a: String, b: String): Boolean {
            val x = parts(a); val y = parts(b)
            for (i in 0..2) {
                val p = x.getOrElse(i) { 0 }
                val q = y.getOrElse(i) { 0 }
                if (p != q) return p > q
            }
            return false
        }

        /** 只挑 tag 以 "android-v" 开头的；PC 版的 v1.0.9 之类直接无视 */
        fun isOurs(tag: String) = tag.trim().lowercase().startsWith("android-v")

        try {
            val conn = URL(API_RELEASES).openConnection() as HttpURLConnection
            conn.setRequestProperty("Accept", "application/vnd.github+json")
            conn.connectTimeout = 8000
            conn.readTimeout = 8000
            val body = conn.inputStream.bufferedReader().readText()
            conn.disconnect()
            val arr = org.json.JSONArray(body)
            var tag = ""
            var notes = ""
            var apk: String? = null
            /* GitHub 列表按创建时间倒序，取第一个属于我们的就行 */
            for (i in 0 until arr.length()) {
                val j = arr.getJSONObject(i)
                val t = j.optString("tag_name", "")
                if (!isOurs(t)) continue
                val assets = j.optJSONArray("assets")
                var found: String? = null
                if (assets != null) {
                    for (k in 0 until assets.length()) {
                        val a = assets.getJSONObject(k)
                        if (a.optString("name").endsWith(".apk")) {
                            found = a.optString("browser_download_url")
                        }
                    }
                }
                if (found == null) continue
                tag = t; notes = j.optString("body", ""); apk = found
                break
            }
            if (tag.isEmpty()) {
                Info(true, "", "还没发布安卓版更新", null)
            } else {
                Info(!newer(tag, VERSION), tag, notes, apk)
            }
        } catch (e: Exception) {
            Info(true, "", "检查失败：${e.message}", null)
        }
    }

    fun download(ctx: Context, url: String, tag: String): Long {
        val req = DownloadManager.Request(Uri.parse(url))
            .setTitle("北通手柄映射器 $tag")
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "BetopPad-$tag.apk")
            .setMimeType("application/vnd.android.package-archive")
        val dm = ctx.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        return dm.enqueue(req)
    }
}
