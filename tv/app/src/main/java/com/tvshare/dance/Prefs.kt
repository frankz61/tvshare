package com.tvshare.dance

import android.content.Context
import androidx.core.content.edit

class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("tvshare", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = sp.getString("server_url", null) ?: BuildConfig.DEFAULT_SERVER_URL
        set(value) = sp.edit { putString("server_url", normalizeServerUrl(value)) }

    var token: String?
        get() = sp.getString("token", null)
        set(value) = sp.edit { putString("token", value) }

    /** Remembered across videos: once a parent turns mirroring on, it stays on. */
    var mirror: Boolean
        get() = sp.getBoolean("mirror", false)
        set(value) = sp.edit { putBoolean("mirror", value) }

    var loop: Boolean
        get() = sp.getBoolean("loop", false)
        set(value) = sp.edit { putBoolean("loop", value) }

    companion object {
        fun normalizeServerUrl(raw: String): String {
            var url = raw.trim().trimEnd('/')
            if (url.isNotEmpty() && !url.startsWith("http://") && !url.startsWith("https://")) {
                url = "http://$url"
            }
            return url
        }
    }
}
