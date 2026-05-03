package net.hlan.sushi

import android.app.Activity
import android.os.Bundle
import android.widget.EditText
import android.widget.ScrollView
import android.widget.TextView

class TerminalActivity : Activity() {

    // Field widened from SshClient to TerminalBackend; all call sites already go through the interface.
    private var sshClient: TerminalBackend? = null

    private lateinit var terminalOutput: TextView
    private lateinit var commandInput: EditText
    private lateinit var scrollView: ScrollView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_terminal)

        terminalOutput = findViewById(R.id.terminal_output)
        commandInput = findViewById(R.id.command_input)
        scrollView = findViewById(R.id.scroll_view)

        sshClient = TerminalSessionHolder.backend

        commandInput.setOnEditorActionListener { _, _, _ ->
            val text = commandInput.text.toString()
            commandInput.text.clear()
            sshClient?.sendCommand(text)
            true
        }
    }

    fun appendLine(line: String) {
        runOnUiThread {
            terminalOutput.append(line)
            scrollView.post { scrollView.fullScroll(ScrollView.FOCUS_DOWN) }
        }
    }

    fun resizeTerminal(col: Int, row: Int, widthPx: Int, heightPx: Int) {
        sshClient?.resizePty(col, row, widthPx, heightPx)
    }

    fun sendCtrlC() = sshClient?.sendCtrlC() ?: Unit

    fun sendCtrlD() = sshClient?.sendCtrlD() ?: Unit

    override fun onDestroy() {
        sshClient?.disconnect()
        super.onDestroy()
    }
}
