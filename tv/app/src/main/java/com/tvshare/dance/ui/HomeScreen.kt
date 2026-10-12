package com.tvshare.dance.ui

import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.itemsIndexed
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.focusRestorer
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.tv.material3.Border
import androidx.tv.material3.Card
import androidx.tv.material3.CardDefaults
import androidx.tv.material3.ClickableSurfaceDefaults
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.OutlinedButton
import androidx.tv.material3.Surface
import androidx.tv.material3.Text
import androidx.compose.foundation.BorderStroke
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.tvshare.dance.Api
import com.tvshare.dance.AuthException
import com.tvshare.dance.Category
import com.tvshare.dance.PlayerActivity
import com.tvshare.dance.Video
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/** Selected tab: null = all videos, -1 = uncategorized, otherwise a category id. */
private const val UNCATEGORIZED = -1

@Composable
fun HomeScreen(api: Api, onUnauthorized: () -> Unit, onSettings: () -> Unit) {
    var categories by remember { mutableStateOf<List<Category>>(emptyList()) }
    var videos by remember { mutableStateOf<List<Video>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var selected by remember { mutableStateOf<Int?>(null) }
    val scope = rememberCoroutineScope()
    val unauthorized by rememberUpdatedState(onUnauthorized)
    val firstCard = remember { FocusRequester() }
    val selectedTab = remember { FocusRequester() }
    var focusedOnce by remember { mutableStateOf(false) }

    suspend fun load() {
        try {
            val cats = api.categories()
            val vids = api.videos()
            categories = cats
            videos = vids
            error = null
            if (selected != null && selected != UNCATEGORIZED && cats.none { it.id == selected }) selected = null
        } catch (e: CancellationException) {
            throw e
        } catch (e: AuthException) {
            unauthorized()
        } catch (e: Exception) {
            error = "加载失败，请检查网络（${e.message ?: e.javaClass.simpleName}）"
        }
    }

    // Reload whenever the app comes back to the foreground, so newly uploaded videos show up.
    LifecycleResumeEffect(api) {
        val job = scope.launch { load() }
        onPauseOrDispose { job.cancel() }
    }

    val all = videos.orEmpty()
    val hasUncategorized = all.any { it.categoryId == null }
    val shown = when (selected) {
        null -> all
        UNCATEGORIZED -> all.filter { it.categoryId == null }
        else -> all.filter { it.categoryId == selected }
    }

    LaunchedEffect(videos) {
        if (!focusedOnce && !videos.isNullOrEmpty()) {
            focusedOnce = true
            runCatching { firstCard.requestFocus() }
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .background(Palette.background)
            .padding(start = 48.dp, end = 48.dp, top = 28.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("💃 舞蹈练习", fontSize = 30.sp, fontWeight = FontWeight.Bold, color = Palette.text)
            Spacer(Modifier.weight(1f))
            OutlinedButton(onClick = { scope.launch { load() } }) { Text("刷新") }
            Spacer(Modifier.padding(start = 12.dp))
            OutlinedButton(onClick = onSettings) { Text("设置") }
        }
        Spacer(Modifier.height(16.dp))

        LazyRow(
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            // Room for the focused tab to scale up without being clipped.
            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp),
            // Pressing Up from the grid lands on the current tab, not the geometrically nearest
            // one — including the first time, before any tab has had focus to restore.
            modifier = Modifier.focusRestorer(selectedTab),
        ) {
            item { CategoryTab("全部", selected == null, selectedTab) { selected = null } }
            items(categories, key = { it.id }) { c ->
                CategoryTab(c.name, selected == c.id, selectedTab) { selected = c.id }
            }
            if (hasUncategorized) {
                item { CategoryTab("未分类", selected == UNCATEGORIZED, selectedTab) { selected = UNCATEGORIZED } }
            }
        }
        Spacer(Modifier.height(8.dp))

        when {
            videos == null && error == null -> Message("正在加载…")
            error != null && videos == null -> Message(error!!)
            shown.isEmpty() -> Message(
                if (all.isEmpty()) "还没有视频\n请家长用手机打开 ${api.absolute("")} 上传舞蹈视频"
                else "这个分类里还没有视频"
            )
            else -> LazyVerticalGrid(
                columns = GridCells.Fixed(4),
                horizontalArrangement = Arrangement.spacedBy(24.dp),
                verticalArrangement = Arrangement.spacedBy(24.dp),
                contentPadding = PaddingValues(top = 12.dp, bottom = 48.dp, start = 4.dp, end = 4.dp),
                modifier = Modifier.fillMaxSize(),
            ) {
                itemsIndexed(shown, key = { _, v -> v.id }) { index, v ->
                    VideoCard(
                        video = v,
                        api = api,
                        modifier = if (index == 0) Modifier.focusRequester(firstCard) else Modifier,
                    )
                }
            }
        }
    }
}

@Composable
private fun CategoryTab(label: String, selected: Boolean, selectedRequester: FocusRequester, onSelect: () -> Unit) {
    Surface(
        onClick = onSelect,
        // TV convention: moving focus onto a tab switches to it, no click needed.
        modifier = Modifier
            .then(if (selected) Modifier.focusRequester(selectedRequester) else Modifier)
            .onFocusChanged { if (it.isFocused) onSelect() },
        shape = ClickableSurfaceDefaults.shape(CircleShape),
        colors = ClickableSurfaceDefaults.colors(
            containerColor = if (selected) Palette.accentSoft else Palette.surface,
            contentColor = Palette.text,
            focusedContainerColor = Palette.accent,
            focusedContentColor = androidx.compose.ui.graphics.Color.White,
        ),
        scale = ClickableSurfaceDefaults.scale(focusedScale = 1.08f),
    ) {
        Text(
            label,
            fontSize = 20.sp,
            fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
            modifier = Modifier.padding(horizontal = 24.dp, vertical = 10.dp),
        )
    }
}

@Composable
private fun VideoCard(video: Video, api: Api, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    Card(
        onClick = {
            context.startActivity(
                Intent(context, PlayerActivity::class.java)
                    .putExtra(PlayerActivity.EXTRA_TITLE, video.title)
                    .putExtra(PlayerActivity.EXTRA_URL, api.absolute(video.videoUrl))
            )
        },
        modifier = modifier.fillMaxWidth(),
        shape = CardDefaults.shape(RoundedCornerShape(16.dp)),
        colors = CardDefaults.colors(
            containerColor = Palette.surface,
            contentColor = Palette.text,
            focusedContainerColor = Palette.surfaceFocused,
            focusedContentColor = Palette.text,
        ),
        scale = CardDefaults.scale(focusedScale = 1.06f),
        border = CardDefaults.border(
            focusedBorder = Border(BorderStroke(3.dp, Palette.accent), shape = RoundedCornerShape(16.dp)),
        ),
    ) {
        Box(Modifier.fillMaxWidth().aspectRatio(16f / 10f).background(Palette.surfaceFocused)) {
            val request = remember(video.thumbUrl) {
                ImageRequest.Builder(context)
                    .data(api.absolute(video.thumbUrl))
                    .apply { api.authHeaders().forEach { (k, v) -> addHeader(k, v) } }
                    .crossfade(true)
                    .build()
            }
            AsyncImage(
                model = request,
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
            Text(
                formatDuration(video.duration),
                fontSize = 14.sp,
                color = androidx.compose.ui.graphics.Color.White,
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .padding(8.dp)
                    .background(androidx.compose.ui.graphics.Color(0x99000000), RoundedCornerShape(6.dp))
                    .padding(horizontal = 6.dp, vertical = 2.dp),
            )
        }
        Text(
            video.title,
            fontSize = 18.sp,
            fontWeight = FontWeight.SemiBold,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
        )
    }
}

@Composable
private fun Message(text: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            text,
            style = MaterialTheme.typography.titleLarge,
            color = Palette.muted,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
        )
    }
}
