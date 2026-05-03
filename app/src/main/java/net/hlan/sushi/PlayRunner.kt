package net.hlan.sushi

// Accepts TerminalBackend instead of constructing SshClient directly.
// Existing SSH call sites are unchanged — they go through the interface.
class PlayRunner(private val backend: TerminalBackend) {

    fun run(commands: List<String>) {
        if (!backend.isConnected()) return
        for (command in commands) {
            val result = backend.sendCommand(command)
            if (result is CommandResult.Failure) break
        }
    }

    fun interrupt() {
        backend.sendCtrlC()
    }

    fun sendRaw(text: String): CommandResult = backend.sendText(text)
}
