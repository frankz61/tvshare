package com.tvshare.dance

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

data class Category(val id: Int, val name: String)

data class Video(
    val id: String,
    val title: String,
    val categoryId: Int?,
    val duration: Double,
    val videoUrl: String,
    val thumbUrl: String,
)

data class PairStart(val pairId: String, val code: String, val expiresIn: Int)

class AuthException : IOException("未授权")

class Api(private val baseUrl: String, private val token: String?) {

    fun absolute(path: String): String = baseUrl + path

    fun authHeaders(): Map<String, String> =
        if (token != null) mapOf("Authorization" to "Bearer $token") else emptyMap()

    private suspend fun request(method: String, path: String): String = withContext(Dispatchers.IO) {
        val conn = URL(absolute(path)).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = method
            conn.connectTimeout = 8000
            conn.readTimeout = 15000
            authHeaders().forEach { (k, v) -> conn.setRequestProperty(k, v) }
            if (method == "POST") {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write("{}".toByteArray()) }
            }
            val code = conn.responseCode
            if (code == 401) throw AuthException()
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val body = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) throw IOException("服务器返回 $code")
            body
        } finally {
            conn.disconnect()
        }
    }

    suspend fun categories(): List<Category> {
        val arr = JSONArray(request("GET", "/api/categories"))
        return (0 until arr.length()).map { i ->
            val o = arr.getJSONObject(i)
            Category(o.getInt("id"), o.getString("name"))
        }
    }

    /** Only videos that finished processing; the TV has nothing to show for the rest. */
    suspend fun videos(): List<Video> {
        val arr = JSONArray(request("GET", "/api/videos"))
        return (0 until arr.length()).mapNotNull { i ->
            val o = arr.getJSONObject(i)
            if (o.getString("status") != "ready") return@mapNotNull null
            Video(
                id = o.getString("id"),
                title = o.getString("title"),
                categoryId = if (o.isNull("category_id")) null else o.getInt("category_id"),
                duration = o.optDouble("duration", 0.0),
                videoUrl = o.getString("video_url"),
                thumbUrl = o.getString("thumb_url"),
            )
        }
    }

    suspend fun startPairing(): PairStart {
        val o = JSONObject(request("POST", "/api/pair"))
        return PairStart(o.getString("pair_id"), o.getString("code"), o.getInt("expires_in"))
    }

    /** Returns the token once a parent confirmed the code, "" while pending, null if expired. */
    suspend fun pollPairing(pairId: String): String? {
        val o = JSONObject(request("GET", "/api/pair/$pairId"))
        return when (o.getString("status")) {
            "confirmed" -> o.getString("token")
            "pending" -> ""
            else -> null
        }
    }
}
