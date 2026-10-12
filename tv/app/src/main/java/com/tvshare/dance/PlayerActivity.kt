package com.tvshare.dance

import android.os.Bundle
import android.view.LayoutInflater
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import androidx.tv.material3.Button
import androidx.tv.material3.ButtonDefaults
import androidx.tv.material3.Text
import com.tvshare.dance.ui.AppBackHandler
import com.tvshare.dance.ui.BackKeyRoot
import com.tvshare.dance.ui.Palette
import com.tvshare.dance.ui.TVShareTheme
import com.tvshare.dance.ui.formatDuration
import kotlinx.coroutines.delay

private const val SEEK_MS = 5_000L
private val SPEEDS = listOf(1.0f, 0.75f, 0.5f)

class PlayerActivity : ComponentActivity() {

    companion object {
        const val EXTRA_TITLE = "title"
        const val EXTRA_URL = "url"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val url = intent.getStringExtra(EXTRA_URL)
        if (url == null) {
            finish()
            return
        }
        val title = intent.getStringExtra(EXTRA_TITLE).orEmpty()
        val prefs = Prefs(this)
        val headers = Api(prefs.serverUrl, prefs.token).authHeaders()
        setContent {
            TVShareTheme {
                BackKeyRoot(onBackPressedDispatcher) {
                    PlayerScreen(title, url, headers, prefs, onExit = ::finish)
                }
            }
        }
    }
}

@androidx.annotation.OptIn(UnstableApi::class)
@Composable
private fun PlayerScreen(
    title: String,
    url: String,
    headers: Map<String, String>,
    prefs: Prefs,
    onExit: () -> Unit,
) {
    val context = LocalContext.current
    val player = remember {
        val http = DefaultHttpDataSource.Factory()
            .setDefaultRequestProperties(headers)
            .setConnectTimeoutMs(10_000)
            .setReadTimeoutMs(20_000)
            .setAllowCrossProtocolRedirects(true)
        ExoPlayer.Builder(context)
            .setMediaSourceFactory(DefaultMediaSourceFactory(http))
            .setSeekBackIncrementMs(SEEK_MS)
            .setSeekForwardIncrementMs(SEEK_MS)
            .build()
            .apply {
                setMediaItem(MediaItem.fromUri(url))
                repeatMode = if (prefs.loop) Player.REPEAT_MODE_ONE else Player.REPEAT_MODE_OFF
                playWhenReady = true
                prepare()
            }
    }

    var isPlaying by remember { mutableStateOf(false) }
    var playbackState by remember { mutableIntStateOf(Player.STATE_IDLE) }
    var error by remember { mutableStateOf<String?>(null) }
    var position by remember { mutableLongStateOf(0L) }
    var duration by remember { mutableLongStateOf(0L) }

    var mirror by remember { mutableStateOf(prefs.mirror) }
    var loop by remember { mutableStateOf(prefs.loop) }
    var speed by remember { mutableFloatStateOf(1.0f) }

    var controlsVisible by remember { mutableStateOf(false) }
    var interaction by remember { mutableIntStateOf(0) } // bumps the auto-hide timer
    var osdVisible by remember { mutableStateOf(false) }  // slim progress bar after a quick seek
    var osdTick by remember { mutableIntStateOf(0) }

    val rootFocus = remember { FocusRequester() }
    val playFocus = remember { FocusRequester() }

    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onIsPlayingChanged(playing: Boolean) {
                isPlaying = playing
            }

            override fun onPlaybackStateChanged(state: Int) {
                playbackState = state
                if (state == Player.STATE_ENDED) controlsVisible = true
            }

            override fun onPlayerError(e: PlaybackException) {
                error = when (e.errorCode) {
                    PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS -> "服务器拒绝访问，可能需要重新配对"
                    PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED,
                    PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT -> "网络连接失败，请检查网络"
                    else -> "播放失败（${e.errorCodeName}）"
                }
            }
        }
        player.addListener(listener)
        onDispose {
            player.removeListener(listener)
            player.release()
        }
    }

    LifecycleEventEffect(Lifecycle.Event.ON_STOP) { player.pause() }

    LaunchedEffect(player) {
        while (true) {
            position = player.currentPosition
            duration = player.duration.coerceAtLeast(0L)
            delay(250)
        }
    }

    LaunchedEffect(controlsVisible, interaction, isPlaying) {
        if (controlsVisible && isPlaying) {
            delay(5_000)
            controlsVisible = false
        }
    }

    LaunchedEffect(osdTick) {
        if (osdTick > 0) {
            delay(1_500)
            osdVisible = false
        }
    }

    LaunchedEffect(controlsVisible) {
        if (controlsVisible) runCatching { playFocus.requestFocus() } else rootFocus.requestFocus()
    }

    fun togglePlay() {
        when {
            playbackState == Player.STATE_ENDED -> {
                player.seekTo(0)
                player.play()
            }
            player.isPlaying -> player.pause()
            else -> {
                if (playbackState == Player.STATE_IDLE) {
                    error = null
                    player.prepare()
                }
                player.play()
            }
        }
    }

    fun quickSeek(forward: Boolean) {
        if (forward) player.seekForward() else player.seekBack()
        osdVisible = true
        osdTick++
    }

    fun handleKeyDown(key: Key): Boolean = when (key) {
        Key.MediaPlayPause -> { togglePlay(); true }
        Key.MediaPlay -> { player.play(); true }
        Key.MediaPause -> { player.pause(); true }
        Key.MediaFastForward -> { quickSeek(true); true }
        Key.MediaRewind -> { quickSeek(false); true }
        else -> if (controlsVisible) {
            false // let D-pad move between the control buttons
        } else when (key) {
            Key.DirectionCenter, Key.Enter, Key.NumPadEnter -> {
                togglePlay()
                controlsVisible = true
                true
            }
            Key.DirectionLeft -> { quickSeek(false); true }
            Key.DirectionRight -> { quickSeek(true); true }
            Key.DirectionUp, Key.DirectionDown, Key.Menu -> { controlsVisible = true; true }
            else -> false
        }
    }

    // Back closes the menu first, then leaves the player. The remote's Back key is routed
    // here by BackKeyRoot on every Android version.
    AppBackHandler { if (controlsVisible) controlsVisible = false else onExit() }

    // Keys whose KeyDown we consumed; their KeyUp is swallowed too, so the button that
    // gains focus in between doesn't see a stray release and click.
    val consumedKeys = remember { mutableSetOf<Key>() }

    Box(
        Modifier
            .fillMaxSize()
            .background(Color.Black)
            .focusRequester(rootFocus)
            .focusable()
            .onPreviewKeyEvent { ev ->
                when (ev.type) {
                    KeyEventType.KeyDown -> {
                        interaction++
                        handleKeyDown(ev.key).also { if (it) consumedKeys += ev.key }
                    }
                    KeyEventType.KeyUp -> {
                        consumedKeys.remove(ev.key)
                    }
                    else -> false
                }
            },
    ) {
        AndroidView(
            factory = { ctx ->
                (LayoutInflater.from(ctx).inflate(R.layout.player_view, null) as PlayerView).apply {
                    this.player = player
                    keepScreenOn = true
                }
            },
            // Mirror only the picture (the TextureView), never the controls drawn on top.
            update = { view -> view.videoSurfaceView?.scaleX = if (mirror) -1f else 1f },
            modifier = Modifier.fillMaxSize(),
        )

        if (playbackState == Player.STATE_BUFFERING && error == null) {
            CenterMessage("加载中…")
        }
        error?.let { CenterMessage("$it\n按 OK 键重试，返回键退出") }

        AnimatedVisibility(
            visible = osdVisible && !controlsVisible,
            enter = fadeIn(),
            exit = fadeOut(),
            modifier = Modifier.align(Alignment.BottomCenter),
        ) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .background(Brush.verticalGradient(listOf(Color.Transparent, Color(0xCC000000))))
                    .padding(horizontal = 48.dp, vertical = 28.dp),
            ) {
                TimeRow(position, duration)
                ProgressBar(position, duration)
            }
        }

        AnimatedVisibility(
            visible = controlsVisible,
            enter = fadeIn(),
            exit = fadeOut(),
            modifier = Modifier.fillMaxSize(),
        ) {
            Box(Modifier.fillMaxSize()) {
                Text(
                    title,
                    fontSize = 28.sp,
                    fontWeight = FontWeight.Bold,
                    color = Color.White,
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(Brush.verticalGradient(listOf(Color(0xCC000000), Color.Transparent)))
                        .padding(horizontal = 48.dp, vertical = 28.dp),
                )

                Column(
                    Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .background(Brush.verticalGradient(listOf(Color.Transparent, Color(0xE6000000))))
                        .padding(start = 48.dp, end = 48.dp, top = 48.dp, bottom = 28.dp),
                ) {
                    TimeRow(position, duration)
                    ProgressBar(position, duration)
                    Spacer(Modifier.height(20.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                        ControlButton("◀◀ 5秒") { quickSeek(false) }
                        ControlButton(
                            when {
                                playbackState == Player.STATE_ENDED -> "重播"
                                isPlaying -> "暂停"
                                else -> "播放"
                            },
                            modifier = Modifier.focusRequester(playFocus),
                        ) { togglePlay() }
                        ControlButton("5秒 ▶▶") { quickSeek(true) }
                        ControlButton("速度 ${speedLabel(speed)}", active = speed != 1.0f) {
                            speed = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.size]
                            player.setPlaybackSpeed(speed)
                        }
                        ControlButton(if (mirror) "镜像 开" else "镜像 关", active = mirror) {
                            mirror = !mirror
                            prefs.mirror = mirror
                        }
                        ControlButton(if (loop) "循环 开" else "循环 关", active = loop) {
                            loop = !loop
                            prefs.loop = loop
                            player.repeatMode = if (loop) Player.REPEAT_MODE_ONE else Player.REPEAT_MODE_OFF
                        }
                    }
                    Spacer(Modifier.height(14.dp))
                    Text(
                        "提示：菜单隐藏时，遥控器 ← → 快退/快进 5 秒，OK 键暂停/播放",
                        fontSize = 15.sp,
                        color = Color(0xB3FFFFFF),
                    )
                }
            }
        }
    }
}

private fun speedLabel(speed: Float): String = when (speed) {
    1.0f -> "1.0x"
    0.75f -> "0.75x"
    else -> "0.5x"
}

@Composable
private fun TimeRow(position: Long, duration: Long) {
    Row(Modifier.fillMaxWidth()) {
        Text(formatDuration(position / 1000.0), color = Color.White, fontSize = 18.sp)
        Spacer(Modifier.weight(1f))
        Text(formatDuration(duration / 1000.0), color = Color(0xB3FFFFFF), fontSize = 18.sp)
    }
}

@Composable
private fun ProgressBar(position: Long, duration: Long) {
    val fraction = if (duration > 0) (position.toFloat() / duration).coerceIn(0f, 1f) else 0f
    Box(
        Modifier
            .padding(top = 8.dp)
            .fillMaxWidth()
            .height(6.dp)
            .background(Color(0x40FFFFFF), RoundedCornerShape(3.dp)),
    ) {
        Box(
            Modifier
                .fillMaxWidth(fraction)
                .height(6.dp)
                .background(Palette.accent, RoundedCornerShape(3.dp)),
        )
    }
}

@Composable
private fun ControlButton(
    label: String,
    modifier: Modifier = Modifier,
    active: Boolean = false,
    onClick: () -> Unit,
) {
    Button(
        onClick = onClick,
        modifier = modifier,
        colors = ButtonDefaults.colors(
            containerColor = if (active) Palette.accentSoft else Color(0x33FFFFFF),
            contentColor = Color.White,
            focusedContainerColor = Palette.accent,
            focusedContentColor = Color.White,
        ),
    ) {
        Text(label, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun CenterMessage(text: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            text,
            color = Color.White,
            fontSize = 24.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier
                .background(Color(0x99000000), RoundedCornerShape(12.dp))
                .padding(horizontal = 24.dp, vertical = 16.dp),
        )
    }
}
