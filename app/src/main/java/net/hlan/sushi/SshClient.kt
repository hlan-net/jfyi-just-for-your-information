package net.hlan.sushi

import com.jcraft.jsch.ChannelShell
import com.jcraft.jsch.JSch
import com.jcraft.jsch.Session
import java.io.InputStream
import java.io.OutputStream

class SshClient(
    private val host: String,
    private val port: Int,
    private val username: String,
    private val password: String
) : TerminalBackend {

    private var session: Session? = null
    private var channel: ChannelShell? = null
    private var outputStream: OutputStream? = null

    override fun connect(
        onLine: (String) -> Unit,
        streamMode: Boolean,
        onConnectionClosed: () -> Unit
    ): ConnectResult {
        return try {
            val jsch = JSch()
            val s = jsch.getSession(username, host, port)
            s.setPassword(password)
            s.setConfig("StrictHostKeyChecking", "no")
            s.connect()
            session = s

            val ch = s.openChannel("shell") as ChannelShell
            ch.setPtySize(80, 24, 0, 0)
            channel = ch
            outputStream = ch.outputStream
            ch.connect()

            Thread {
                try {
                    val inputStream: InputStream = ch.inputStream
                    val buffer = ByteArray(4096)
                    val lineBuffer = StringBuilder()
                    var len: Int
                    while (inputStream.read(buffer).also { len = it } != -1) {
                        val chunk = String(buffer, 0, len, Charsets.UTF_8)
                        if (streamMode) {
                            onLine(chunk)
                        } else {
                            lineBuffer.append(chunk)
                            var nl: Int
                            while (lineBuffer.indexOf("\n").also { nl = it } != -1) {
                                onLine(lineBuffer.substring(0, nl + 1))
                                lineBuffer.delete(0, nl + 1)
                            }
                        }
                    }
                } catch (_: Exception) {
                } finally {
                    onConnectionClosed()
                }
            }.start()

            ConnectResult.Success
        } catch (e: Exception) {
            ConnectResult.Failure(e.message ?: "Connection failed")
        }
    }

    override fun isConnected(): Boolean =
        session?.isConnected == true && channel?.isConnected == true

    override fun sendText(text: String): CommandResult {
        return try {
            outputStream?.write(text.toByteArray(Charsets.UTF_8))
            outputStream?.flush()
            CommandResult.Success
        } catch (e: Exception) {
            CommandResult.Failure(e.message ?: "Send failed")
        }
    }

    override fun sendCommand(command: String): CommandResult =
        sendText("$command\n")

    override fun sendCtrlC() {
        outputStream?.write(byteArrayOf(0x03))
        outputStream?.flush()
    }

    override fun sendCtrlD() {
        outputStream?.write(byteArrayOf(0x04))
        outputStream?.flush()
    }

    override fun resizePty(col: Int, row: Int, widthPx: Int, heightPx: Int) {
        channel?.setPtySize(col, row, widthPx, heightPx)
    }

    override fun disconnect() {
        channel?.disconnect()
        session?.disconnect()
        channel = null
        session = null
        outputStream = null
    }
}
