package net.hlan.sushi

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

// Consumes TerminalBackend from TerminalSessionHolder rather than SshClient.
class ConversationManager {

    suspend fun executeCommand(command: String): CommandResult {
        val backend = TerminalSessionHolder.backend
            ?: return CommandResult.Failure("No active session")
        return withContext(Dispatchers.IO) {
            backend.sendCommand(command)
        }
    }

    suspend fun sendRaw(text: String): CommandResult {
        val backend = TerminalSessionHolder.backend
            ?: return CommandResult.Failure("No active session")
        return withContext(Dispatchers.IO) {
            backend.sendText(text)
        }
    }

    suspend fun isSessionActive(): Boolean = withContext(Dispatchers.IO) {
        TerminalSessionHolder.backend?.isConnected() == true
    }
}
