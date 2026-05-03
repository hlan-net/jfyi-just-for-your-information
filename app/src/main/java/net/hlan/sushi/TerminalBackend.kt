package net.hlan.sushi

sealed class ConnectResult {
    object Success : ConnectResult()
    data class Failure(val message: String) : ConnectResult()
}

sealed class CommandResult {
    object Success : CommandResult()
    data class Failure(val message: String) : CommandResult()
}

interface TerminalBackend {
    fun connect(
        onLine: (String) -> Unit,
        streamMode: Boolean,
        onConnectionClosed: () -> Unit
    ): ConnectResult

    fun isConnected(): Boolean
    fun sendText(text: String): CommandResult
    fun sendCommand(command: String): CommandResult
    fun sendCtrlC()
    fun sendCtrlD()
    fun resizePty(col: Int, row: Int, widthPx: Int, heightPx: Int)
    fun disconnect()
}
