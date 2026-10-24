
package com.ps06.camera

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.os.Bundle
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import java.io.BufferedReader
import java.io.ByteArrayOutputStream
import java.io.InputStreamReader
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicReference

class MainActivity : AppCompatActivity() {
    private lateinit var previewView: PreviewView
    private lateinit var status: TextView
    private val executor = Executors.newSingleThreadExecutor()
    private val latestJpeg = AtomicReference<ByteArray?>(null)

    @Volatile private var running = true
    @Volatile private var frameCount = 0
    private var server: ServerSocket? = null

    private fun imageProxyToJpeg(image: ImageProxy): ByteArray? {
        val width = image.width
        val height = image.height
        val planes = image.planes
        if (planes.size < 3) return null

        val nv21 = ByteArray(width * height + width * height / 2)
        var index = 0

        val y = planes[0]
        val yBuffer = y.buffer.duplicate()
        for (row in 0 until height) {
            for (col in 0 until width) {
                nv21[index++] = yBuffer.get(
                    row * y.rowStride + col * y.pixelStride
                )
            }
        }

        val u = planes[1]
        val v = planes[2]
        val ub = u.buffer.duplicate()
        val vb = v.buffer.duplicate()

        for (row in 0 until height / 2) {
            for (col in 0 until width / 2) {
                nv21[index++] = vb.get(
                    row * v.rowStride + col * v.pixelStride
                )
                nv21[index++] = ub.get(
                    row * u.rowStride + col * u.pixelStride
                )
            }
        }

        val output = ByteArrayOutputStream()
        val yuv = YuvImage(nv21, ImageFormat.NV21, width, height, null)
        val success = yuv.compressToJpeg(
            Rect(0, 0, width, height), 75, output
        )
        return if (success) output.toByteArray() else null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(20, 24, 20, 20)
        }

        status = TextView(this).apply {
            text = "PS06 Android Camera\nStarting USB stream..."
        }

        previewView = PreviewView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
            )
        }

        val restart = Button(this).apply {
            text = "Restart camera"
            setOnClickListener { startCameraIfPermitted() }
        }

        layout.addView(status)
        layout.addView(previewView)
        layout.addView(restart)
        setContentView(layout)

        Thread({ startMjpegServer() }, "PS06-MJPEG-Server").start()
        startCameraIfPermitted()
    }

    private fun startCameraIfPermitted() {
        if (ContextCompat.checkSelfPermission(
                this, Manifest.permission.CAMERA
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(
                this, arrayOf(Manifest.permission.CAMERA), 10
            )
            return
        }

        val providerFuture = ProcessCameraProvider.getInstance(this)
        providerFuture.addListener({
            try {
                val provider = providerFuture.get()

                val preview = Preview.Builder().build().also {
                    it.surfaceProvider = previewView.surfaceProvider
                }

                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(
                        ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST
                    )
                    .setTargetResolution(android.util.Size(640, 480))
                    .build()

                analysis.setAnalyzer(executor) { image ->
                    try {
                        val jpeg = imageProxyToJpeg(image)
                        if (jpeg != null) {
                            latestJpeg.set(jpeg)
                            frameCount++

                            if (frameCount % 20 == 0) {
                                runOnUiThread {
                                    status.text =
                                        "PS06 Android Camera - LIVE\n" +
                                        "USB stream: port 8081\n" +
                                        "Frames: $frameCount"
                                }
                            }
                        } else {
                            android.util.Log.w(
                                "PS06Camera", "JPEG conversion returned null"
                            )
                        }
                    } catch (e: Exception) {
                        android.util.Log.e(
                            "PS06Camera", "Frame conversion failed", e
                        )
                    } finally {
                        image.close()
                    }
                }

                provider.unbindAll()
                provider.bindToLifecycle(
                    this,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    analysis
                )

                status.text =
                    "Camera started - waiting for frames\nUSB stream: port 8081"
            } catch (e: Exception) {
                android.util.Log.e("PS06Camera", "Camera setup failed", e)
                status.text = "Camera error: ${e.message}"
            }
        }, ContextCompat.getMainExecutor(this))
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)

        if (requestCode == 10 &&
            grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED
        ) {
            startCameraIfPermitted()
        } else if (requestCode == 10) {
            status.text = "Camera permission required"
        }
    }

    private fun startMjpegServer() {
        try {
            server = ServerSocket(8081)

            while (running) {
                val client = server!!.accept()
                Thread({ serveClient(client) }, "PS06-MJPEG-Client").start()
            }
        } catch (e: Exception) {
            if (running) {
                android.util.Log.e("PS06Camera", "Stream server failed", e)
                runOnUiThread {
                    status.text = "Stream server error: ${e.message}"
                }
            }
        }
    }

    private fun serveClient(socket: Socket) {
        socket.use { client ->
            try {
                client.soTimeout = 5000
                val reader = BufferedReader(
                    InputStreamReader(client.getInputStream())
                )
                val request = reader.readLine() ?: return

                while (reader.readLine()?.isNotEmpty() == true) {
                    // Consume HTTP headers.
                }

                val output = client.getOutputStream()

                if (request.startsWith("GET /health")) {
                    val body =
                        "PS06 camera stream ready; frames=$frameCount"
                    val response =
                        "HTTP/1.1 200 OK\r\n" +
                        "Content-Type: text/plain\r\n" +
                        "Content-Length: ${body.toByteArray().size}\r\n" +
                        "Connection: close\r\n\r\n" + body

                    output.write(response.toByteArray())
                    output.flush()
                    return
                }

                output.write(
                    ("HTTP/1.1 200 OK\r\n" +
                        "Cache-Control: no-cache\r\n" +
                        "Connection: close\r\n" +
                        "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n")
                        .toByteArray()
                )
                output.flush()

                var last: ByteArray? = null

                while (running && !client.isClosed) {
                    val jpeg = latestJpeg.get()

                    if (jpeg != null && jpeg !== last) {
                        output.write(
                            ("--frame\r\nContent-Type: image/jpeg\r\n" +
                                "Content-Length: ${jpeg.size}\r\n\r\n")
                                .toByteArray()
                        )
                        output.write(jpeg)
                        output.write("\r\n".toByteArray())
                        output.flush()
                        last = jpeg
                    }

                    Thread.sleep(50)
                }
            } catch (e: Exception) {
                android.util.Log.d(
                    "PS06Camera", "HTTP client disconnected", e
                )
            }
        }
    }

    override fun onDestroy() {
        running = false

        try {
            server?.close()
        } catch (e: Exception) {
            android.util.Log.e("PS06Camera", "Server close failed", e)
        }

        executor.shutdown()
        super.onDestroy()
    }
}
