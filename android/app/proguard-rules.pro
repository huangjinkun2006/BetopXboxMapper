# 我们自己的类全部保留（主要是自定义 View 和序列化用的配置数据类）
-keep class com.jinkun.betoppad.** { *; }

# Kotlin 协程 + AppCompat/Material 的通用保留规则
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keepclassmembers class **$WhenMappings {
    <fields>;
}
-keepclassmembers class kotlin.Metadata {
    public <methods>;
}
-keepclasseswithmembernames,includedescriptorclasses class * {
    native <methods>;
}
-keepclassmembers,allowoptimization class !kotlin.**,!com.jinkun.betoppad.** {
    @kotlinx.coroutines.e <methods>;
}
-dontwarn org.jetbrains.annotations.**
-dontwarn kotlinx.coroutines.internal.**
