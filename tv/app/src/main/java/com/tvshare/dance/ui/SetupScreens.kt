package com.tvshare.dance.ui

import android.os.SystemClock
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Button
import androidx.tv.material3.OutlinedButtonDefaults
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.OutlinedButton
import androidx.tv.material3.Text
import com.tvshare.dance.Api
import com.tvshare.dance.BuildConfig
import com.tvshare.dance.Prefs
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import java.io.IOException

@Composable
private fun SetupFrame(content: @Composable () -> Unit) {
    Box(
        Modifier
            .fillMaxSize()
            .background(Palette.background)
            .padding(horizontal = 96.dp, vertical = 48.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) { content() }
    }
}

@Composable
fun ServerScreen(initialUrl: String, onDone: (String) -> Unit) {
    var url by remember { mutableStateOf(initialUrl.ifBlank { "http://" }) }
    var focused by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val focus = remember { FocusRequester() }
    val submit = {
        val normalized = Prefs.normalizeServerUrl(url)
        if (normalized.length <= "http://".length) error = "请填写服务器地址" else onDone(normalized)
    }

    SetupFrame {
        Text("设置服务器地址", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(12.dp))
        Text(
            "填写家长部署的服务器地址，例如 http://123.45.67.89:8000",
            color = Palette.muted,
        )
        Spacer(Modifier.height(32.dp))
        BasicTextField(
            value = url,
            onValueChange = { url = it; error = null },
            singleLine = true,
            textStyle = TextStyle(color = Palette.text, fontSize = 24.sp),
            cursorBrush = SolidColor(Palette.accent),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { submit() }),
            modifier = Modifier
                .width(640.dp)
                .focusRequester(focus)
                .onFocusChanged { focused = it.isFocused }
                .background(Palette.surface, RoundedCornerShape(12.dp))
                .border(2.dp, if (focused) Palette.accent else Palette.surfaceFocused, RoundedCornerShape(12.dp))
                .padding(horizontal = 20.dp, vertical = 16.dp),
        )
        error?.let {
            Spacer(Modifier.height(8.dp))
            Text(it, color = Palette.danger)
        }
        Spacer(Modifier.height(24.dp))
        Button(onClick = submit) { Text("下一步") }
    }
    LaunchedEffect(Unit) { focus.requestFocus() }
}

@Composable
fun PairingScreen(serverUrl: String, onPaired: (String) -> Unit, onChangeServer: () -> Unit) {
    var code by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    val paired by rememberUpdatedState(onPaired)
    val buttonFocus = remember { FocusRequester() }

    LaunchedEffect(serverUrl) {
        val api = Api(serverUrl, null)
        while (true) {
            try {
                val start = api.startPairing()
                code = start.code
                error = null
                // Ask for a fresh code a little before the old one expires.
                val deadline = SystemClock.elapsedRealtime() + start.expiresIn * 1000L - 10_000
                while (SystemClock.elapsedRealtime() < deadline) {
                    delay(2000)
                    val result = try {
                        api.pollPairing(start.pairId)
                    } catch (e: IOException) {
                        "" // brief network blip: keep the same code on screen
                    }
                    if (result == null) break
                    if (result.isNotEmpty()) {
                        paired(result)
                        return@LaunchedEffect
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                code = null
                error = "连不上服务器 $serverUrl\n请确认地址正确、服务器已启动（${e.message ?: e.javaClass.simpleName}）"
                delay(5000)
            }
        }
    }

    SetupFrame {
        Text("绑定这台电视", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(16.dp))
        Text(
            "家长用手机打开 $serverUrl ，登录后点「绑定电视」，输入下面的配对码",
            color = Palette.muted,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(40.dp))
        val shown = code
        if (shown != null) {
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                shown.forEach { digit ->
                    Box(
                        Modifier
                            .width(88.dp)
                            .height(112.dp)
                            .background(Palette.surface, RoundedCornerShape(16.dp)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(digit.toString(), fontSize = 64.sp, fontWeight = FontWeight.Bold, color = Palette.accent)
                    }
                }
            }
            Spacer(Modifier.height(24.dp))
            Text("等待手机确认…", color = Palette.muted)
        } else if (error != null) {
            Text(error!!, color = Palette.danger, textAlign = TextAlign.Center)
        } else {
            Text("正在获取配对码…", color = Palette.muted)
        }
        Spacer(Modifier.height(40.dp))
        OutlinedButton(onClick = onChangeServer, modifier = Modifier.focusRequester(buttonFocus)) {
            Text("修改服务器地址")
        }
    }
    LaunchedEffect(Unit) { buttonFocus.requestFocus() }
}

@Composable
fun SettingsScreen(serverUrl: String, onChangeServer: () -> Unit, onRepair: () -> Unit, onBack: () -> Unit) {
    val focus = remember { FocusRequester() }
    SetupFrame {
        Text("设置", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(16.dp))
        Text("服务器：$serverUrl", color = Palette.muted)
        Text("版本：${BuildConfig.VERSION_NAME}", color = Palette.muted)
        Spacer(Modifier.height(32.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Button(onClick = onBack, modifier = Modifier.focusRequester(focus)) { Text("返回") }
            OutlinedButton(onClick = onChangeServer) { Text("修改服务器地址") }
            OutlinedButton(
                onClick = onRepair,
                colors = OutlinedButtonDefaults.colors(contentColor = Palette.danger),
            ) { Text("重新配对") }
        }
    }
    LaunchedEffect(Unit) { focus.requestFocus() }
}
