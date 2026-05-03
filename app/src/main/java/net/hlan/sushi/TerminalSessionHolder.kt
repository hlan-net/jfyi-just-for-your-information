package net.hlan.sushi

// Renamed from SshConnectionHolder; held type widened from SshClient to TerminalBackend.
object TerminalSessionHolder {
    var backend: TerminalBackend? = null
}
