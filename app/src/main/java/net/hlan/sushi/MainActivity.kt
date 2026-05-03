package net.hlan.sushi

import android.app.Activity
import android.content.Intent
import android.os.Bundle

class MainActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
    }

    // Stores a TerminalBackend in the holder; TerminalActivity reads it from there.
    private fun launchTerminal(backend: TerminalBackend) {
        TerminalSessionHolder.backend = backend
        startActivity(Intent(this, TerminalActivity::class.java))
    }

    override fun onDestroy() {
        // Access the backend through the holder as TerminalBackend, not SshClient.
        TerminalSessionHolder.backend?.disconnect()
        TerminalSessionHolder.backend = null
        super.onDestroy()
    }
}
