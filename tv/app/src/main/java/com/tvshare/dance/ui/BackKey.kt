package com.tvshare.dance.ui

import androidx.activity.OnBackPressedDispatcher
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type

/**
 * Makes the remote's Back key behave the same on every Android version.
 *
 * Up to Android 15 the key goes through Compose key handling, which would spend the first
 * press on clearing focus instead of navigating back. On Android 16 (predictive back) the
 * system also invokes the back callback directly, *between* the key's down and up events.
 * So: swallow the key, and on release dispatch Back only if the system didn't already.
 */
class BackKeyState {
    internal var pressing = false
    internal var handledDuringPress = false
}

val LocalBackKeyState = staticCompositionLocalOf { BackKeyState() }

fun Modifier.routeBackKey(state: BackKeyState, dispatcher: OnBackPressedDispatcher): Modifier =
    onPreviewKeyEvent { ev ->
        if (ev.key != Key.Back) return@onPreviewKeyEvent false
        when (ev.type) {
            KeyEventType.KeyDown -> {
                if (!state.pressing) state.handledDuringPress = false
                state.pressing = true
            }
            KeyEventType.KeyUp -> {
                state.pressing = false
                if (!state.handledDuringPress) dispatcher.onBackPressed()
            }
        }
        true
    }

/** Wrap each activity's content in this so Back from the remote goes through [routeBackKey]. */
@Composable
fun BackKeyRoot(dispatcher: OnBackPressedDispatcher, content: @Composable () -> Unit) {
    val state = remember { BackKeyState() }
    CompositionLocalProvider(LocalBackKeyState provides state) {
        Box(Modifier.routeBackKey(state, dispatcher)) { content() }
    }
}

/** BackHandler that cooperates with [routeBackKey]; use it instead of BackHandler. */
@Composable
fun AppBackHandler(enabled: Boolean = true, onBack: () -> Unit) {
    val state = LocalBackKeyState.current
    BackHandler(enabled) {
        if (state.pressing) state.handledDuringPress = true
        onBack()
    }
}
