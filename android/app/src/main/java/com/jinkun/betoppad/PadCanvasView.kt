package com.jinkun.betoppad

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.CornerPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.util.AttributeSet
import android.view.View

/**
 * 手柄图。坐标直接照搬 PC 版 padui.py 那张图（画布 376x336），
 * 这里按 View 宽度整体缩放，所以两个版本的样子是一模一样的。
 */
class PadCanvasView : View {
    constructor(c: Context) : super(c)
    constructor(c: Context, a: AttributeSet?) : super(c, a)
    constructor(c: Context, a: AttributeSet?, s: Int) : super(c, a, s)

    companion object {
        private const val VB_X = 96f
        private const val VB_Y = 36f
        private const val VB_W = 376f
        private const val VB_H = 336f

        private val P_BODY = Color.parseColor("#20222a")
        private val P_KNOB = Color.parseColor("#2e3038")
        private val P_RING = Color.parseColor("#14151a")
        private val P_DPAD = Color.parseColor("#191b22")
        private val P_PANEL = Color.parseColor("#2b2e39")
        private val P_LED = Color.parseColor("#3f7dff")
        private val P_ABXY = Color.parseColor("#17181f")
        private val PRESS = Color.parseColor("#5dc21e")
        private val SUB = Color.parseColor("#8a8f99")

        private val ABXY = mapOf(
            "Y" to (Color.parseColor("#f08a1d") to Color.parseColor("#ffb75e")),
            "X" to (Color.parseColor("#2e7bff") to Color.parseColor("#8ab4ff")),
            "B" to (Color.parseColor("#e0333a") to Color.parseColor("#ff8a8e")),
            "A" to (Color.parseColor("#3fb54a") to Color.parseColor("#93e59b")),
        )
    }

    /** 按键是否按下（输入的是虚拟键码） */
    var pressed: Set<Int> = emptySet()
        set(v) { field = v; postInvalidate() }
    /** 摇杆位置 -1..1 */
    var lx = 0f; var ly = 0f; var rx = 0f; var ry = 0f
    var lt = 0f; var rt = 0f

    private var s = 1f
    private val pf = Paint(Paint.ANTI_ALIAS_FLAG)
    private val pt = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE; textAlign = Paint.Align.CENTER
        textSize = 12f
    }

    override fun onMeasure(w: Int, h: Int) {
        val ww = MeasureSpec.getSize(w)
        setMeasuredDimension(ww, (ww * VB_H / VB_W).toInt())
    }

    private fun X(v: Float) = (v - VB_X) * s
    private fun Y(v: Float) = (v - VB_Y) * s
    private fun L(v: Float) = v * s

    private fun fill(c: Int) = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = c; style = Paint.Style.FILL }

    private fun rr(x1: Float, y1: Float, x2: Float, y2: Float, r: Float, c: Int) {
        pf.color = c
        pf.style = Paint.Style.FILL
        pf.pathEffect = CornerPathEffect(L(r))
        val p = Path()
        p.moveTo(X(x1), Y(y1)); p.lineTo(X(x2), Y(y1))
        p.lineTo(X(x2), Y(y2)); p.lineTo(X(x1), Y(y2)); p.close()
        canvasRef?.drawPath(p, pf)
        pf.pathEffect = null
    }

    private fun circle(cx: Float, cy: Float, r: Float, c: Int, stroke: Int? = null, sw: Float = 0f) {
        pf.color = c; pf.style = Paint.Style.FILL
        canvasRef?.drawCircle(X(cx), Y(cy), L(r), pf)
        if (stroke != null) {
            val st = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = stroke; style = Paint.Style.STROKE; strokeWidth = sw
            }
            canvasRef?.drawCircle(X(cx), Y(cy), L(r), st)
        }
    }

    private fun label(t: String, x: Float, y: Float, c: Int = Color.WHITE, size: Float = 12f) {
        pt.color = c; pt.textSize = L(size)
        canvasRef?.drawText(t, X(x), Y(y), pt)
    }

    private var canvasRef: Canvas? = null

    private fun isOn(cg: String): Boolean {
        val t = VIEW_MAP[cg] ?: return false
        return pressed.contains(t.code)
    }

    private fun col(cg: String, base: Int): Int {
        val pair = ABXY[cg]
        if (pair != null) return if (isOn(cg)) pair.second else pair.first
        return if (isOn(cg)) PRESS else base
    }

    override fun onDraw(cv: Canvas) {
        super.onDraw(cv)
        canvasRef = cv
        s = width / VB_W
        if (s <= 0f) return

        // 机身轮廓
        val body = Path()
        val pts = listOf(120f,162f, 152f,132f, 212f,124f, 262f,116f, 284f,108f, 306f,116f,
            356f,124f, 416f,132f, 448f,162f, 468f,210f, 466f,258f, 438f,326f, 400f,356f,
            356f,349f, 330f,308f, 284f,294f, 238f,308f, 212f,349f, 168f,356f, 130f,326f,
            102f,258f, 100f,210f)
        body.moveTo(X(pts[0]), Y(pts[1]))
        for (i in 2 until pts.size step 2) body.lineTo(X(pts[i]), Y(pts[i + 1]))
        body.close()
        pf.color = P_BODY; pf.style = Paint.Style.FILL
        pf.pathEffect = CornerPathEffect(L(9f))
        cv.drawPath(body, pf)
        pf.pathEffect = null
        rr(268f, 100f, 300f, 116f, 6f, P_BODY)

        // 扳机
        rr(160f, 52f, 238f, 74f, 11f, P_RING)
        if (lt > 0f) rr(162f, 54f, 162f + 74f * lt, 72f, 9f, PRESS)
        label("LT", 199f, 42f, SUB, 11f)
        rr(322f, 52f, 400f, 74f, 11f, P_RING)
        if (rt > 0f) rr(324f, 54f, 324f + 74f * rt, 72f, 9f, PRESS)
        label("RT", 361f, 42f, SUB, 11f)

        // 肩键
        rr(154f, 82f, 250f, 102f, 9f, col("LB", P_KNOB))
        label("LB", 202f, 96f)
        rr(310f, 82f, 406f, 102f, 9f, col("RB", P_KNOB))
        label("RB", 358f, 96f)

        // 中央亮面斜面板
        val panel = Path()
        panel.moveTo(X(234f), Y(118f)); panel.lineTo(X(334f), Y(118f))
        panel.lineTo(X(360f), Y(198f)); panel.lineTo(X(208f), Y(198f)); panel.close()
        pf.color = P_PANEL; pf.pathEffect = CornerPathEffect(L(8f))
        cv.drawPath(panel, pf); pf.pathEffect = null

        // 左摇杆
        circle(206f, 182f, 40f, P_RING)
        circle(206f + lx * 15, 182f + ly * 15, 25f, col("L3", P_KNOB))
        label("LS", 206f + lx * 15, 186f + ly * 15, Color.parseColor("#c9c9cf"), 12f)

        // 右摇杆（带 LED 光环）
        circle(352f, 268f, 44f, Color.TRANSPARENT, P_LED, L(2f))
        circle(352f, 268f, 40f, P_RING)
        circle(352f + rx * 15, 268f + ry * 15, 25f, col("R3", P_KNOB))
        label("RS", 352f + rx * 15, 272f + ry * 15, Color.parseColor("#c9c9cf"), 12f)

        // 十字键
        rr(208.6f, 223f, 231.4f, 262f, 7f, col("UP", P_DPAD))
        rr(208.6f, 262f, 231.4f, 301f, 7f, col("DOWN", P_DPAD))
        rr(181f, 250.6f, 220f, 273.4f, 7f, col("LEFT", P_DPAD))
        rr(220f, 250.6f, 259f, 273.4f, 7f, col("RIGHT", P_DPAD))
        rr(208.6f, 250.6f, 231.4f, 273.4f, 4f, if (isOn("UP") || isOn("DOWN") ||
            isOn("LEFT") || isOn("RIGHT")) PRESS else P_DPAD)

        // ABXY
        drawFaceBt(cv, "Y", 378f, 134f)
        drawFaceBt(cv, "X", 340f, 172f)
        drawFaceBt(cv, "B", 416f, 172f)
        drawFaceBt(cv, "A", 378f, 210f)

        // 返回 / 菜单 / FN / LOGO
        circle(259f, 145f, 11f, col("BACK", P_ABXY))
        label("↩", 259f, 150f, Color.parseColor("#9aa0ae"), 13f)
        circle(309f, 145f, 11f, col("START", P_ABXY))
        label("☰", 309f, 150f, Color.parseColor("#9aa0ae"), 12f)
        rr(246f, 170f, 272f, 190f, 5f, if (fnHeld) PRESS else P_ABXY)
        label("FN", 259f, 184f, SUB, 11f)
        circle(308f, 181f, 15f, Color.TRANSPARENT, P_LED, L(1f))
        circle(308f, 181f, 12f, col("LOGO", P_ABXY))
        label("➤", 308f, 186f, P_LED, 12f)

        // LED 灯阵
        for (r in 0..2) for (c in 0..3)
            circle(270f + c * 14, 224f + r * 14, 2.5f, P_LED)
    }

    /** FN 没有目标虚拟键，单独标记 —— 按下时告诉 App 它就是 FN */
    var fnHeld = false
        set(v) { field = v; postInvalidate() }

    private fun drawFaceBt(cv: Canvas, name: String, cx: Float, cy: Float) {
        val pair = ABXY[name]!!
        circle(cx, cy, 17f, if (isOn(name)) pair.second else pair.first)
        label(name, cx, cy + 5f, Color.WHITE, 13f)
    }
}
