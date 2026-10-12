package com.tvshare.dance

import android.content.Context
import java.security.KeyStore
import java.security.cert.CertificateException
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/**
 * Lets older TVs talk to a Let's Encrypt server.
 *
 * Many TVs (e.g. Xiaomi Mi TV 4) ship a CA list without ISRG Root X1, so HTTPS fails
 * with CertPathValidatorException. We trust the system CAs as usual and, only if they
 * reject a chain, try again against the ISRG Root X1 bundled in res/raw.
 *
 * Android 7+ also gets this via network_security_config; this object covers Android 6
 * and OkHttp (Coil), which need an explicit trust manager.
 */
object Tls {
    lateinit var trustManager: X509TrustManager
        private set
    lateinit var socketFactory: SSLSocketFactory
        private set

    fun install(context: Context) {
        val system = trustManagerFor(null)
        val bundled = trustManagerFor(
            KeyStore.getInstance(KeyStore.getDefaultType()).apply {
                load(null, null)
                context.resources.openRawResource(R.raw.isrg_root_x1).use {
                    setCertificateEntry("isrg_root_x1", CertificateFactory.getInstance("X.509").generateCertificate(it))
                }
            }
        )
        trustManager = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) =
                system.checkClientTrusted(chain, authType)

            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                try {
                    system.checkServerTrusted(chain, authType)
                } catch (e: CertificateException) {
                    bundled.checkServerTrusted(chain, authType)
                }
            }

            override fun getAcceptedIssuers(): Array<X509Certificate> =
                system.acceptedIssuers + bundled.acceptedIssuers
        }
        socketFactory = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trustManager), null) }.socketFactory
        // Used by our Api (HttpURLConnection) and by ExoPlayer's DefaultHttpDataSource.
        HttpsURLConnection.setDefaultSSLSocketFactory(socketFactory)
    }

    private fun trustManagerFor(keyStore: KeyStore?): X509TrustManager =
        TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
            .apply { init(keyStore) }
            .trustManagers
            .filterIsInstance<X509TrustManager>()
            .first()
}
