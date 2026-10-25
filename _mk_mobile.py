# -*- coding: utf-8 -*-
"""生成手机版单文件页面 betop-mobile.html（图标直接内嵌，方便丢群里/传手机）"""
import io
import base64
import os

HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>北通 BTP-V1T · 手机版</title>
<meta name="theme-color" content="#f2f3f7">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="北通手柄">
<link rel="apple-touch-icon" href="__ICON__">
<link rel="icon" href="__ICON__">
<style>
:root{
  --bg:#f2f3f7; --card:#fff; --acc:#107c10; --acc-dk:#0c5f0c; --acc-lt:#eaf5ea;
  --txt:#26282e; --sub:#8a8f99; --line:#ececf0; --press:#5dc21e; --warn:#c0392b;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--txt);
  font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
  padding:calc(10px + env(safe-area-inset-top)) 10px calc(24px + env(safe-area-inset-bottom));}
.card{background:var(--card);border-radius:14px;padding:12px 14px;margin-bottom:10px;
  box-shadow:0 1px 3px rgba(0,0,0,.06)}
h1{font-size:17px;margin:2px 0 10px;display:flex;align-items:center;gap:8px}
h2{font-size:13px;margin:0 0 8px;color:var(--sub);font-weight:600}
.badge{font-size:11px;font-weight:600;padding:3px 9px;border-radius:20px;
  background:#f0f0f4;color:var(--sub)}
.badge.on{background:var(--acc-lt);color:var(--acc-dk)}
.badge.err{background:#fdeaea;color:var(--warn)}
.padbox{padding:6px 4px 2px}
svg{width:100%;height:auto;display:block}
.row{display:flex;align-items:center;gap:10px;margin:6px 0}
.row label{width:52px;flex:none;color:var(--sub);font-size:12px}
input[type=range]{flex:1;accent-color:var(--acc);height:26px}
.val{width:38px;text-align:right;font-family:ui-monospace,Menlo,Consolas,monospace;
  font-size:12px;color:var(--sub)}
button{font:inherit;font-size:13px;border:0;border-radius:10px;padding:10px 14px;
  background:var(--acc);color:#fff;font-weight:600;cursor:pointer}
button.ghost{background:#f0f0f4;color:var(--txt)}
button.stop{background:#5a5e66}
button:active{opacity:.75}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.chips{display:flex;flex-wrap:wrap;gap:6px;min-height:30px}
.chip{font:600 12px/1 ui-monospace,Menlo,Consolas,monospace;padding:7px 10px;
  border-radius:8px;background:#f0f0f4;color:var(--sub)}
.chip.on{background:var(--press);color:#16380a}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(48px,1fr));gap:6px}
.cell{background:#f7f8fa;border:1px solid var(--line);border-radius:8px;padding:7px 2px;
  text-align:center;font:600 12px/1.2 ui-monospace,Menlo,Consolas,monospace;color:var(--sub)}
.cell b{display:block;font-size:14px;color:var(--txt)}
.cell.on{background:var(--press);border-color:var(--press);color:#16380a}
.cell.on b{color:#16380a}
.bar{height:8px;border-radius:5px;background:#ececf0;overflow:hidden;margin:3px 0 7px}
.bar i{display:block;height:100%;width:0;background:var(--acc);border-radius:5px;
  transition:width .05s linear}
.hint{font-size:12px;color:var(--sub);line-height:1.7}
.kbd{font:600 11px ui-monospace,Menlo,Consolas,monospace;background:#f0f0f4;
  padding:1px 5px;border-radius:4px}
small{color:var(--sub)}
</style>
</head>
<body>

<div class="card">
  <h1>北通 BTP-V1T <span class="badge" id="badge">未连接</span></h1>
  <div class="hint" id="dev">手机 OTG 接上手柄后，按手柄任意键唤醒就会被这里读到。</div>
</div>

<div class="card padbox">
  <svg id="pad" viewBox="96 36 376 336" xmlns="http://www.w3.org/2000/svg">
    <!-- 机身 -->
    <polygon points="120,162 152,132 212,124 262,116 284,108 306,116 356,124 416,132 448,162 468,210 466,258 438,326 400,356 356,349 330,308 284,294 238,308 212,349 168,356 130,326 102,258 100,210"
             fill="#20222a" stroke="#20222a" stroke-width="9" stroke-linejoin="round"/>
    <rect x="268" y="100" width="32" height="16" rx="6" fill="#20222a"/>
    <!-- 扳机 -->
    <rect x="160" y="52" width="78" height="22" rx="11" fill="#14151a"/>
    <rect id="LTf" x="162" y="54" width="0" height="18" rx="9" fill="#5dc21e"/>
    <rect x="322" y="52" width="78" height="22" rx="11" fill="#14151a"/>
    <rect id="RTf" x="324" y="54" width="0" height="18" rx="9" fill="#5dc21e"/>
    <text x="199" y="42" text-anchor="middle" font-size="11" fill="#8a8f99" font-family="Consolas,monospace">LT</text>
    <text x="361" y="42" text-anchor="middle" font-size="11" fill="#8a8f99" font-family="Consolas,monospace">RT</text>
    <!-- 肩键 -->
    <rect id="kLB" x="154" y="82" width="96" height="20" rx="9" fill="#2e3038"/>
    <text x="202" y="96" text-anchor="middle" font-size="12" fill="#fff" font-family="Consolas,monospace">LB</text>
    <rect id="kRB" x="310" y="82" width="96" height="20" rx="9" fill="#2e3038"/>
    <text x="358" y="96" text-anchor="middle" font-size="12" fill="#fff" font-family="Consolas,monospace">RB</text>
    <!-- 中央亮面斜面板 -->
    <polygon points="234,118 334,118 360,198 208,198" stroke="#2b2e39" stroke-width="8"
             stroke-linejoin="round" fill="#2b2e39"/>
    <!-- 左摇杆 -->
    <circle cx="206" cy="182" r="40" fill="#14151a"/>
    <circle id="kLS" cx="206" cy="182" r="25" fill="#2e3038"/>
    <text x="206" y="186" text-anchor="middle" font-size="12" fill="#c9c9cf" font-family="Consolas,monospace">LS</text>
    <!-- 右摇杆（带 LED 光环） -->
    <circle cx="352" cy="268" r="44" fill="none" stroke="#3f7dff" stroke-width="2"/>
    <circle cx="352" cy="268" r="40" fill="#14151a"/>
    <circle id="kRS" cx="352" cy="268" r="25" fill="#2e3038"/>
    <text x="352" y="272" text-anchor="middle" font-size="12" fill="#c9c9cf" font-family="Consolas,monospace">RS</text>
    <!-- 十字键 -->
    <rect id="kUP"    x="209" y="223" width="23" height="39" rx="7" fill="#191b22"/>
    <rect id="kDOWN"  x="209" y="262" width="23" height="39" rx="7" fill="#191b22"/>
    <rect id="kLEFT"  x="181" y="251" width="39" height="23" rx="7" fill="#191b22"/>
    <rect id="kRIGHT" x="220" y="251" width="39" height="23" rx="7" fill="#191b22"/>
    <!-- ABXY -->
    <circle id="kY" cx="378" cy="134" r="17" fill="#f08a1d"/>
    <text x="378" y="139" text-anchor="middle" font-size="14" fill="#fff" font-family="Consolas,monospace">Y</text>
    <circle id="kX" cx="340" cy="172" r="17" fill="#2e7bff"/>
    <text x="340" y="177" text-anchor="middle" font-size="14" fill="#fff" font-family="Consolas,monospace">X</text>
    <circle id="kB" cx="416" cy="172" r="17" fill="#e0333a"/>
    <text x="416" y="177" text-anchor="middle" font-size="14" fill="#fff" font-family="Consolas,monospace">B</text>
    <circle id="kA" cx="378" cy="210" r="17" fill="#3fb54a"/>
    <text x="378" y="215" text-anchor="middle" font-size="14" fill="#fff" font-family="Consolas,monospace">A</text>
    <!-- 中央三键 + FN -->
    <ellipse id="kBACK" cx="259" cy="145" rx="11" ry="11" fill="#17181f"/>
    <text x="259" y="150" text-anchor="middle" font-size="13" fill="#9aa0ae">&#8617;</text>
    <ellipse id="kSTART" cx="309" cy="145" rx="11" ry="11" fill="#17181f"/>
    <text x="309" y="150" text-anchor="middle" font-size="12" fill="#9aa0ae">&#9776;</text>
    <rect id="kFN" x="246" y="170" width="26" height="20" rx="5" fill="#17181f"/>
    <text x="259" y="184" text-anchor="middle" font-size="11" fill="#8a8f9c" font-family="Consolas,monospace">FN</text>
    <circle cx="308" cy="181" r="15" fill="none" stroke="#3f7dff"/>
    <ellipse id="kGUIDE" cx="308" cy="181" rx="12" ry="11" fill="#17181f"/>
    <text x="308" y="186" text-anchor="middle" font-size="12" fill="#3f7dff">&#10148;</text>
    <!-- LED 灯阵 -->
    <g fill="#3f7dff">
      <circle cx="270" cy="224" r="2.5"/><circle cx="284" cy="224" r="2.5"/>
      <circle cx="298" cy="224" r="2.5"/><circle cx="312" cy="224" r="2.5"/>
      <circle cx="270" cy="238" r="2.5"/><circle cx="284" cy="238" r="2.5"/>
      <circle cx="298" cy="238" r="2.5"/><circle cx="312" cy="238" r="2.5"/>
      <circle cx="270" cy="252" r="2.5"/><circle cx="284" cy="252" r="2.5"/>
      <circle cx="298" cy="252" r="2.5"/><circle cx="312" cy="252" r="2.5"/>
    </g>
  </svg>
</div>

<div class="card">
  <h2>正在按下</h2>
  <div class="chips" id="chips"><span class="chip">—</span></div>
  <div style="margin-top:10px">
    <div class="row"><label>LT</label><div class="bar" style="flex:1"><i id="bLT"></i></div></div>
    <div class="row"><label>RT</label><div class="bar" style="flex:1"><i id="bRT"></i></div></div>
    <div class="row"><label>摇杆</label><small id="axes" style="flex:1">L(0.00, 0.00)　R(0.00, 0.00)</small></div>
  </div>
</div>

<div class="card">
  <h2>震动测试</h2>
  <div class="row"><label>大马达</label>
    <input type="range" id="rBig" min="0" max="100" value="100"><span class="val" id="vBig">100</span></div>
  <div class="row"><label>小马达</label>
    <input type="range" id="rSmall" min="0" max="100" value="0"><span class="val" id="vSmall">0</span></div>
  <div class="row"><label>时长</label>
    <input type="range" id="rMs" min="100" max="3000" step="100" value="600"><span class="val" id="vMs">600</span></div>
  <div class="btns">
    <button id="btnRumble">试震一下</button>
    <button id="btnHold" class="ghost">连续猛震</button>
    <button id="btnStop" class="stop">停</button>
  </div>
  <div class="hint" id="msg" style="margin-top:8px">手机上能不能震，取决于系统给不给 <span class="kbd">vibrationActuator</span> 权限，不行的话会在这里报错。</div>
</div>

<div class="card">
  <h2>按键对照（原始索引）</h2>
  <div class="grid" id="grid"><span class="cell">未连接</span></div>
  <div class="hint" style="margin-top:8px">按手柄上的键，看哪一格亮起来 —— 这就是它在这台手机上汇报的索引。FN 键如果亮了，说明它在安卓上也能用。</div>
</div>

<div class="card">
  <h2>怎么用</h2>
  <div class="hint">
    1. OTG 转接头插手机，手柄接上（或蓝牙配对）。<br>
    2. 按手柄任意键唤醒 —— 安卓为了省电，不按键浏览器是看不到手柄的。<br>
    3. 菜单里选「添加到主屏幕」，之后点图标就能全屏打开，跟 App 一样。<br>
    <span style="color:var(--warn)">注意：</span>这个页面只做显示和震动测试。它没法把按键改成别的键 —— 安卓不像 Windows 有 ViGEm，要改输入流得 root + 注入虚拟设备。
  </div>
  <div class="btns">
    <button id="btnFull" class="ghost">全屏</button>
    <button id="btnScan" class="ghost">重新扫描</button>
  </div>
</div>

<script>
var NAMES = ["A","B","X","Y","LB","RB","LT","RT","BACK","START","LS","RS",
             "上","下","左","右","LOGO"];
var LIT = {A:"#93e59b", B:"#ff8a8e", X:"#8ab4ff", Y:"#ffb75e"};
var BASE = {A:"#3fb54a", B:"#e0333a", X:"#2e7bff", Y:"#f08a1d"};
var PRESS = "#5dc21e";
var KEYS = ["A","B","X","Y","LB","RB","BACK","START","LS","RS",
            "UP","DOWN","LEFT","RIGHT","GUIDE","FN"];
var DEFA = {A:"#3fb54a", B:"#e0333a", X:"#2e7bff", Y:"#f08a1d",
            LB:"#2e3038", RB:"#2e3038", BACK:"#17181f", START:"#17181f",
            LS:"#2e3038", RS:"#2e3038", UP:"#191b22", DOWN:"#191b22",
            LEFT:"#191b22", RIGHT:"#191b22", GUIDE:"#17181f", FN:"#17181f"};
// Gamepad API 标准索引
var IDX = {A:0,B:1,X:2,Y:3,LB:4,RB:5,BACK:8,START:9,LS:10,RS:11,
           UP:12,DOWN:13,LEFT:14,RIGHT:15,GUIDE:16,FN:-1};

var el = {}, cur = null, cells = [], holdTimer = null, lastCnt = -1;
["LTf","RTf","badge","dev","chips","grid","msg","axes","bLT","bRT"].forEach(function(k){
  el[k] = document.getElementById(k);
});
KEYS.forEach(function(k){ el["k"+k] = document.getElementById("k"+k); });

function setFill(node, val){ if(node) node.setAttribute("fill", val); }
function msg(txt, bad){
  el.msg.innerHTML = txt;
  el.msg.style.color = bad ? "var(--warn)" : "var(--sub)";
}

function pick(){
  if(!navigator.getGamepads) return null;
  var gps = navigator.getGamepads();
  for(var i=0;i<gps.length;i++){
    var g = gps[i];
    if(g && g.connected) return g;
  }
  return null;
}

function buildGrid(n){
  el.grid.innerHTML = "";
  cells = [];
  for(var i=0;i<n;i++){
    var d = document.createElement("span");
    d.className = "cell";
    d.innerHTML = "<b>" + i + "</b>" + (NAMES[i] || "");
    el.grid.appendChild(d);
    cells.push(d);
  }
}

function num(b){ return (b && typeof b.value === "number") ? b.value : (b && b.pressed ? 1 : 0); }

function frame(){
  var gp = pick();
  if(gp !== cur){
    cur = gp;
    if(!cur){
      el.badge.textContent = "未连接"; el.badge.className = "badge";
      el.dev.textContent = "没读到手柄。检查一下 OTG 线，然后按手柄任意键唤醒。";
      lastCnt = -1;
    }else{
      el.badge.textContent = "已连接"; el.badge.className = "badge on";
      el.dev.innerHTML = "<b>" + (cur.id || "未知设备").slice(0,60) + "</b><br>按钮 " +
        cur.buttons.length + " 个 / 摇杆轴 " + cur.axes.length + " 个" +
        (cur.vibrationActuator ? " · 支持震动" : " · <span style='color:var(--warn)'>系统不给震动权限</span>");
      buildGrid(cur.buttons.length);
    }
  }
  if(!cur){ requestAnimationFrame(frame); return; }

  var on = [], i, v;
  for(i=0;i<cells.length;i++){
    v = cur.buttons[i];
    if(!v) continue;
    var down = v.pressed || (typeof v.value === "number" && v.value > 0.5);
    if(down){ cells[i].className = "cell on"; on.push(NAMES[i] || ("#"+i)); }
    else cells[i].className = "cell";
  }

  for(i=0;i<KEYS.length;i++){
    var k = KEYS[i], n = IDX[k], node = el["k"+k];
    if(!node) continue;
    if(n < 0 || n >= cur.buttons.length){ setFill(node, DEFA[k]); continue; }
    var b = cur.buttons[n];
    var down = b && (b.pressed || (typeof b.value === "number" && b.value > 0.5));
    setFill(node, down ? (LIT[k] || PRESS) : DEFA[k]);
  }

  // 扳机 / 摇杆
  var lt = (cur.buttons[6] && typeof cur.buttons[6].value === "number") ? cur.buttons[6].value : 0;
  var rt = (cur.buttons[7] && typeof cur.buttons[7].value === "number") ? cur.buttons[7].value : 0;
  el.bLT.style.width = (lt*100) + "%";
  el.bRT.style.width = (rt*100) + "%";
  el.LTf.setAttribute("width", 74*lt);
  el.RTf.setAttribute("width", 74*rt);

  var lx = cur.axes[0]||0, ly = cur.axes[1]||0, rx = cur.axes[2]||0, ry = cur.axes[3]||0;
  var knob = el.kLS, kc = [206,182], rc = [352,268];
  knob.setAttribute("cx", kc[0] + lx*15);
  knob.setAttribute("cy", kc[1] + ly*15);
  el.kRS.setAttribute("cx", rc[0] + rx*15);
  el.kRS.setAttribute("cy", rc[1] + ry*15);
  el.axes.textContent = "L(" + lx.toFixed(2) + ", " + ly.toFixed(2) + ")　R(" +
                        rx.toFixed(2) + ", " + ry.toFixed(2) + ")";

  el.chips.innerHTML = on.length
    ? on.map(function(n){ return '<span class="chip on">'+n+'</span>'; }).join("")
    : '<span class="chip">—</span>';

  requestAnimationFrame(frame);
}

function play(ms){
  if(!cur){
    msg("还没连上手柄，先按手柄任意键唤醒", true);
    return false;
  }
  if(!(cur.vibrationActuator && cur.vibrationActuator.playEffect)){
    msg("这台手机 / 这个浏览器不给 Gamepad 震动的权限，换 Chrome 或 Kiwi 浏览器再试", true);
    return false;
  }
  var big = document.getElementById("rBig").value/100;
  var small = document.getElementById("rSmall").value/100;
  try{
    cur.vibrationActuator.playEffect("dual-rumble", {
      duration: ms, strongMagnitude: big, weakMagnitude: small, startDelay: 0
    });
    return true;
  }catch(e){
    msg("震动失败：" + e.message, true);
    return false;
  }
}
function stop(){
  if(holdTimer){ clearInterval(holdTimer); holdTimer = null; }
  if(cur && cur.vibrationActuator && cur.vibrationActuator.reset){
    try{ cur.vibrationActuator.reset(); }catch(e){}
  }
}

document.getElementById("btnRumble").onclick = function(){
  if(play(parseInt(document.getElementById("rMs").value,10)))
    msg("发了命令。没感觉的话就是系统在录屏/省电，或者把小马达也拉起来试试。");
};
document.getElementById("btnHold").onclick = function(){
  if(holdTimer){ stop(); msg("已停"); return; }
  if(!play(300)) return;
  holdTimer = setInterval(function(){ play(300); }, 200);
  msg("连续震动中，再点一次停（这把固件震一下会衰减，所以每 0.2 秒补发一次）。");
};
document.getElementById("btnStop").onclick = function(){ stop(); msg("已停"); };

["rBig","rSmall","rMs"].forEach(function(id){
  var r = document.getElementById(id), out = document.getElementById("v"+id.slice(1));
  function sync(){ out.textContent = r.value; }
  r.addEventListener("input", sync); sync();
});

document.getElementById("btnFull").onclick = function(){
  var d = document.documentElement;
  if(!document.fullscreenElement && d.requestFullscreen) d.requestFullscreen();
  else if(document.exitFullscreen) document.exitFullscreen();
};
document.getElementById("btnScan").onclick = function(){
  cur = null; msg("重新扫描中，按一下手柄上的键。");
};

window.addEventListener("gamepadconnected", function(e){
  msg("识别到手柄：" + (e.gamepad.id || ""));
});
window.addEventListener("gamepaddisconnected", function(){ cur = null; });
document.addEventListener("visibilitychange", function(){
  if(document.hidden) stop();
});

if(!navigator.getGamepads){
  el.badge.textContent = "浏览器不支持"; el.badge.className = "badge err";
  el.dev.textContent = "这个浏览器没有 Gamepad API，换 Chrome / Edge / Kiwi 打开。";
}else{
  frame();
}
</script>
</body>
</html>
"""


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ico = Image = None
    from PIL import Image as _I
    im = _I.open(os.path.join(here, "icon.ico")).resize((192, 192), _I.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGBA").save(buf, "PNG", optimize=True)
    b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    out = HTML.replace("__ICON__", b64)
    dst = os.path.join(here, "mobile", "betop-mobile.html")
    os.makedirs(os.path.join(here, "mobile"), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(out)
    # 顺手留一张 png，方便单独传 / 当 PWA 图标
    im.convert("RGBA").save(os.path.join(here, "mobile", "icon192.png"))
    print("wrote", dst, len(out), "chars")


if __name__ == "__main__":
    main()
