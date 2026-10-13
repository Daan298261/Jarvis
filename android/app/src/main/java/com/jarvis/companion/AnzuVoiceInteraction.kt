package com.jarvis.companion

import android.app.assist.AssistStructure
import android.content.Intent
import android.os.Bundle
import android.service.voice.VoiceInteractionService
import android.service.voice.VoiceInteractionSession
import android.service.voice.VoiceInteractionSessionService

class AnzuVoiceInteractionService : VoiceInteractionService() {
    override fun onReady() { super.onReady(); current = this }
    override fun onShutdown() { current = null; super.onShutdown() }
    companion object { @Volatile var current: AnzuVoiceInteractionService? = null }
}

class AnzuVoiceSessionService : VoiceInteractionSessionService() {
    override fun onNewSession(args: Bundle?): VoiceInteractionSession = AnzuVoiceSession(this)
}

class AnzuVoiceSession(context: android.content.Context) : VoiceInteractionSession(context) {
    override fun onShow(args: Bundle?, flags: Int) {
        super.onShow(args, flags)
        PhoneTools.assistantContext = ""
        // Launch the normal protected UI. Never bypass ANZU's biometric/PIN gate.
        context.startActivity(Intent(context, MainActivity::class.java).setAction(Intent.ACTION_ASSIST)
            .putExtra("anzu_assist", true).putExtra("anzu_voice", args?.getBoolean("anzu_voice", true) ?: true)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP))
        hide()
    }
    override fun onHandleAssist(state: AssistState) {
        super.onHandleAssist(state)
        val structure = state.assistStructure ?: return
        val collected = StringBuilder()
        fun visit(node: AssistStructure.ViewNode, depth: Int) {
            if (depth > 16 || collected.length > 4000 || node.isAssistBlocked) return
            if (node.inputType and android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD == android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD) return
            node.text?.let { collected.append(it.take(300)).append('\n') }
            for (i in 0 until node.childCount) visit(node.getChildAt(i), depth + 1)
        }
        for (i in 0 until structure.windowNodeCount) visit(structure.getWindowNodeAt(i).rootViewNode, 0)
        PhoneTools.assistantContext = collected.toString().take(4000)
    }
}
