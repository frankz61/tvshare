package com.tvshare.dance

import android.app.Application
import coil.ImageLoader
import coil.ImageLoaderFactory
import okhttp3.OkHttpClient

class TVShareApp : Application(), ImageLoaderFactory {

    override fun onCreate() {
        super.onCreate()
        Tls.install(this)
    }

    // Thumbnails are loaded by Coil through OkHttp, which needs the same trust manager.
    override fun newImageLoader(): ImageLoader =
        ImageLoader.Builder(this)
            .okHttpClient {
                OkHttpClient.Builder()
                    .sslSocketFactory(Tls.socketFactory, Tls.trustManager)
                    .build()
            }
            .crossfade(true)
            .build()
}
