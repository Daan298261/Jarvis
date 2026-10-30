package com.jarvis.companion

import android.app.assist.AssistStructure
import android.content.Intent
import android.os.Bundle
import android.service.voice.VoiceInteractionService
import android.service.voice.VoiceInteractionSession
import android.service.voice.VoiceInteractionSessionService

const val ANZU_VOICE_ASSIST_ACTION = "android.intent.action.VOICE_ASSIST"

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
        if (!WakeSettings(context).screenContext) return
        val structure = state.assistStructure ?: return
        val collected = StringBuilder()
        fun visit(node: AssistStructure.ViewNode, depth: Int) {
            if (depth > 16 || collected.length > 4000 || node.isAssistBlocked) return
            if (isSensitiveAssistInput(node.inputType)) return
            node.text?.let { collected.append(it.take(300)).append('\n') }
            for (i in 0 until node.childCount) visit(node.getChildAt(i), depth + 1)
        }
        for (i in 0 until structure.windowNodeCount) visit(structure.getWindowNodeAt(i).rootViewNode, 0)
        PhoneTools.assistantContext = collected.toString().take(4000)
    }
}

internal fun isSensitiveAssistInput(inputType: Int): Boolean {
    val kind = inputType and android.text.InputType.TYPE_MASK_CLASS
    val variation = inputType and android.text.InputType.TYPE_MASK_VARIATION
    return (kind == android.text.InputType.TYPE_CLASS_TEXT && variation in setOf(
        android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD,
        android.text.InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD,
        android.text.InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD,
    )) || (kind == android.text.InputType.TYPE_CLASS_NUMBER && variation == android.text.InputType.TYPE_NUMBER_VARIATION_PASSWORD)
}
