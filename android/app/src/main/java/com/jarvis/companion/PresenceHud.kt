package com.jarvis.companion

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

private val HudGold = Color(0xFFF5A623)
private val HudCyan = Color(0xFF3AD4FF)
private val HudCore = Color(0xFFFFD080)

@Composable
fun PresenceHud(mode: String, connected: Boolean, phase: String) {
    val particles = remember(mode) {
        if (mode == "humanoid") PresenceParticles.humanoid() else PresenceParticles.orb()
    }
    val motion = rememberInfiniteTransition(label = "presence")
    val tick by motion.animateFloat(
        initialValue = 0f,
        targetValue = Math.PI.toFloat() * 2f,
        animationSpec = infiniteRepeatable(tween(if (phase == "idle") 9000 else 4200, easing = LinearEasing), RepeatMode.Restart),
        label = "tick",
    )
    val activity = when {
        !connected && phase == "idle" -> 0.12f
        phase == "listening" -> 0.55f
        phase == "thinking" -> 0.78f
        phase == "speaking" -> 0.92f
        else -> 0.22f
    }
    Canvas(Modifier.fillMaxWidth().height(340.dp)) {
        drawHud(particles, mode == "humanoid", connected, activity, tick)
    }
}

private fun DrawScope.drawHud(
    particles: List<HudParticle>,
    humanoid: Boolean,
    connected: Boolean,
    activity: Float,
    tick: Float,
) {
    val cx = size.width / 2f
    val cy = size.height * if (humanoid) 0.56f else 0.50f
    val palette = if (!connected && activity < 0.2f) Color(0xFFFF6A54) else if (humanoid) HudCyan else HudGold
    val scale = min(size.width, size.height) * if (humanoid) 0.38f else 0.34f
    drawCircle(
        brush = Brush.radialGradient(
            colors = listOf(palette.copy(alpha = 0.22f + activity * 0.18f), Color.Transparent),
            center = Offset(cx, cy),
            radius = scale * 1.85f,
        ),
        radius = scale * 1.85f,
        center = Offset(cx, cy),
    )
    if (!humanoid) {
        for (i in 0..4) {
            val pulse = 1f + sin(tick + i * 0.7f) * 0.04f * (0.4f + activity)
            drawCircle(
                color = palette.copy(alpha = (0.18f - i * 0.03f) * (0.55f + activity)),
                radius = scale * (0.72f + i * 0.12f) * pulse,
                center = Offset(cx, cy),
                style = Stroke(width = if (i == 0) 2.4f else 1.1f),
            )
        }
        drawCircle(color = HudCore.copy(alpha = 0.95f), radius = 7f + activity * 6f, center = Offset(cx, cy))
    }
    val yaw = if (humanoid) 0.08f + sin(tick) * 0.05f else tick
    for (particle in particles) {
        val swirl = if (humanoid) 0f else tick * 0.35f
        val x = particle.x * cos(swirl) - particle.z * sin(swirl)
        val z = particle.x * sin(swirl) + particle.z * cos(swirl)
        val y = particle.y + sin(tick * 1.1f + particle.x * 4f) * 0.018f * (0.4f + activity)
        val px = cx + x * scale * if (humanoid) 1.05f else 1.15f
        val py = cy - (if (humanoid) (y - 0.35f) else y) * scale - yaw * 8f
        val depth = (0.55f + z * 0.7f).coerceIn(0.15f, 1.2f)
        val goldMix = particle.gold.coerceIn(0f, 1f)
        val color = lerpColor(palette, HudGold, goldMix).copy(
            alpha = (0.22f + particle.light * 0.18f + activity * 0.25f) * depth,
        )
        drawCircle(color = color, radius = particle.size * depth * (1.1f + activity * 0.55f), center = Offset(px, py))
    }
}

private fun lerpColor(a: Color, b: Color, t: Float): Color {
    val u = t.coerceIn(0f, 1f)
    return Color(
        red = a.red + (b.red - a.red) * u,
        green = a.green + (b.green - a.green) * u,
        blue = a.blue + (b.blue - a.blue) * u,
        alpha = a.alpha + (b.alpha - a.alpha) * u,
    )
}
