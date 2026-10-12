package com.tvshare.dance

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.tvshare.dance.ui.AppBackHandler
import com.tvshare.dance.ui.BackKeyRoot
import com.tvshare.dance.ui.HomeScreen
import com.tvshare.dance.ui.PairingScreen
import com.tvshare.dance.ui.ServerScreen
import com.tvshare.dance.ui.SettingsScreen
import com.tvshare.dance.ui.TVShareTheme

private enum class Screen { Server, Pairing, Home, Settings }

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = Prefs(this)
        setContent {
            TVShareTheme {
                BackKeyRoot(onBackPressedDispatcher) { App(prefs) }
            }
        }
    }
}

@Composable
private fun App(prefs: Prefs) {
    var screen by remember {
        mutableStateOf(
            when {
                prefs.serverUrl.isBlank() -> Screen.Server
                prefs.token == null -> Screen.Pairing
                else -> Screen.Home
            }
        )
    }

    when (screen) {
        Screen.Server -> ServerScreen(
            initialUrl = prefs.serverUrl,
            onDone = { url ->
                if (url != prefs.serverUrl) prefs.token = null
                prefs.serverUrl = url
                screen = if (prefs.token == null) Screen.Pairing else Screen.Home
            },
        )

        Screen.Pairing -> PairingScreen(
            serverUrl = prefs.serverUrl,
            onPaired = { token ->
                prefs.token = token
                screen = Screen.Home
            },
            onChangeServer = { screen = Screen.Server },
        )

        Screen.Home -> HomeScreen(
            api = Api(prefs.serverUrl, prefs.token),
            onUnauthorized = {
                prefs.token = null
                screen = Screen.Pairing
            },
            onSettings = { screen = Screen.Settings },
        )

        Screen.Settings -> {
            AppBackHandler { screen = Screen.Home }
            SettingsScreen(
                serverUrl = prefs.serverUrl,
                onChangeServer = { screen = Screen.Server },
                onRepair = {
                    prefs.token = null
                    screen = Screen.Pairing
                },
                onBack = { screen = Screen.Home },
            )
        }
    }
}
