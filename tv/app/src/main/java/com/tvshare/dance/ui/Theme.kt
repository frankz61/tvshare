package com.tvshare.dance.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.Color
import androidx.tv.material3.LocalContentColor
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.darkColorScheme
import kotlin.math.roundToLong

object Palette {
    val background = Color(0xFF1B1613)
    val surface = Color(0xFF2A221D)
    val surfaceFocused = Color(0xFF3A2F28)
    val accent = Color(0xFFFF7A59)
    val accentSoft = Color(0xFF5A3426)
    val text = Color(0xFFF6ECE4)
    val muted = Color(0xFFB3A196)
    val danger = Color(0xFFFF6B60)
}

@Composable
fun TVShareTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Palette.accent,
            onPrimary = Color.White,
            background = Palette.background,
            onBackground = Palette.text,
            surface = Palette.surface,
            onSurface = Palette.text,
            surfaceVariant = Palette.surfaceFocused,
            onSurfaceVariant = Palette.muted,
            border = Palette.accent,
        ),
    ) {
        // tv-material Text defaults to black outside a Surface; make light text the default.
        CompositionLocalProvider(LocalContentColor provides Palette.text, content = content)
    }
}

fun formatDuration(seconds: Double): String {
    val total = seconds.roundToLong().coerceAtLeast(0)
    val h = total / 3600
    val m = (total % 3600) / 60
    val s = total % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
}
