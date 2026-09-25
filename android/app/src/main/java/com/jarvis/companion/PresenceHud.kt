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
import android.provider.Settings
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

private val HudGold = Color(0xFFF5A623)
private val HudCyan = Color(0xFF3AD4FF)
private val HudCore = Color(0xFFFFD080)
private val HudOfflineWarm = Color(0xFFFF8A6A)
private val HudAlert = Color(0xFFFF7957)
private val HudError = Color(0xFFFFB020)
private val HudApproval = Color(0xFFF5D76E)
private val HudWaiting = Color(0xFF7996B3)

/**
 * Companion Home HUD presence (RFC-0139).
 * Compose particle / multi-orb path — fail-closed readable chrome (no WebView soft-fail stub).
 */
@Composable
fun PresenceHud(
    mode: String,
    phase: PresencePhase,
    audioLevel: Float = 0f,
) {
    val humanoid = PresenceVisual.normalizePresenceMode(mode) == "humanoid"
    val particles = remember(humanoid) {
        if (humanoid) PresenceParticles.humanoid() else PresenceParticles.orb()
    }
    val context = LocalContext.current
    val reducedMotion = remember(context) {
        // RFC-0051 / RFC-0139: hold a quieter pose when system animator scale is off.
        Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    }
    val period = PresenceVisual.animationPeriodMs(phase, reducedMotion)
    val motion = rememberInfiniteTransition(label = "presence")
    val tick by motion.animateFloat(
        initialValue = 0f,
        targetValue = Math.PI.toFloat() * 2f,
        animationSpec = infiniteRepeatable(tween(period, easing = LinearEasing), RepeatMode.Restart),
        label = "tick",
    )
    val activity = PresenceVisual.effectiveActivity(phase, audioLevel)
    val amplitude = PresenceVisual.motionAmplitude(phase, reducedMotion)
    Canvas(Modifier.fillMaxWidth().height(340.dp)) {
        drawHud(
            particles = particles,
            humanoid = humanoid,
            phase = phase,
            activity = activity,
            amplitude = amplitude,
            tick = if (reducedMotion) 0.35f else tick,
            reducedMotion = reducedMotion,
        )
    }
}

/** Back-compat overload used by older call sites; maps connected+phase string → [PresencePhase]. */
@Composable
fun PresenceHud(mode: String, connected: Boolean, phase: String) {
    val mapped = when {
        !connected -> PresencePhase.OFFLINE
        phase == "listening" -> PresencePhase.LISTENING
        phase == "thinking" -> PresencePhase.THINKING
        phase == "speaking" -> PresencePhase.SPEAKING
        phase == "working" || phase == "executing" -> PresencePhase.WORKING
        phase == "alert" -> PresencePhase.ALERT
        phase == "error" -> PresencePhase.ERROR
        phase == "approval" -> PresencePhase.APPROVAL
        phase == "waiting" -> PresencePhase.WAITING
        else -> PresencePhase.IDLE
    }
    PresenceHud(mode = mode, phase = mapped)
}

private fun DrawScope.drawHud(
    particles: List<HudParticle>,
    humanoid: Boolean,
    phase: PresencePhase,
    activity: Float,
    amplitude: Float,
    tick: Float,
    reducedMotion: Boolean,
) {
    val cx = size.width / 2f
    val cy = size.height * if (humanoid) 0.56f else 0.50f
    val palette = paletteFor(phase, humanoid)
    val scale = min(size.width, size.height) * if (humanoid) 0.40f else 0.34f
    val breath = if (reducedMotion) 1f else 1f + sin(tick * 0.85f) * 0.035f * amplitude
    val glowAlpha = (0.28f + activity * 0.32f).coerceIn(0.42f, 0.72f)

    // Atmospheric glow — Offline keeps a strong floor so daylight still reads the silhouette.
    drawCircle(
        brush = Brush.radialGradient(
            colors = listOf(palette.copy(alpha = glowAlpha), palette.copy(alpha = glowAlpha * 0.35f), Color.Transparent),
            center = Offset(cx, cy - if (humanoid) scale * 0.08f else 0f),
            radius = scale * 1.95f * breath,
        ),
        radius = scale * 1.95f * breath,
        center = Offset(cx, cy - if (humanoid) scale * 0.08f else 0f),
    )

    drawStateChrome(
        cx = cx,
        cy = cy,
        scale = scale * breath,
        phase = phase,
        palette = palette,
        activity = activity,
        tick = tick,
        humanoid = humanoid,
        reducedMotion = reducedMotion,
    )

    if (!humanoid) {
        for (i in 0..4) {
            val pulse = 1f + sin(tick + i * 0.7f) * 0.04f * (0.55f + activity)
            drawCircle(
                color = palette.copy(alpha = (0.22f - i * 0.03f) * (0.65f + activity)),
                radius = scale * (0.72f + i * 0.12f) * pulse,
                center = Offset(cx, cy),
                style = Stroke(width = if (i == 0) 2.6f else 1.2f),
            )
        }
        drawCircle(color = HudCore.copy(alpha = 0.95f), radius = 8f + activity * 7f, center = Offset(cx, cy))
    }

    val yaw = if (humanoid) 0.08f + sin(tick) * 0.05f * amplitude else tick
    val swirlBase = if (humanoid) {
        when (phase) {
            PresencePhase.THINKING -> tick * 0.12f
            PresencePhase.WORKING -> tick * 0.18f
            PresencePhase.SPEAKING -> tick * 0.08f
            else -> 0f
        }
    } else {
        tick * 0.35f
    }

    for (particle in particles) {
        val layerBoost = when (particle.layer) {
            0 -> 1.25f
            2 -> 1.1f
            3 -> 0.95f + sin(tick * 2.2f + particle.x * 6f) * 0.12f * amplitude
            else -> 1f
        }
        val swirl = swirlBase * if (particle.layer >= 2) 1.4f else 1f
        val x = particle.x * cos(swirl) - particle.z * sin(swirl)
        val z = particle.x * sin(swirl) + particle.z * cos(swirl)
        val speechWave = if (phase == PresencePhase.SPEAKING) {
            sin(tick * 3.2f + particle.y * 5f) * 0.028f * activity
        } else {
            0f
        }
        val listenBias = if (phase == PresencePhase.LISTENING) particle.y * 0.012f else 0f
        val y = particle.y +
            sin(tick * 1.1f + particle.x * 4f) * 0.022f * (0.55f + activity) * amplitude +
            speechWave +
            listenBias
        val px = cx + x * scale * if (humanoid) 1.05f else 1.15f
        val py = cy - (if (humanoid) (y - 0.35f) else y) * scale - yaw * 8f
        val depth = (0.55f + z * 0.7f).coerceIn(0.2f, 1.25f)
        val goldMix = particle.gold.coerceIn(0f, 1f)
        // Alpha floor tied to activity so Offline particles stay visible outdoors.
        val alpha = ((0.32f + particle.light * 0.22f + activity * 0.38f) * depth * layerBoost)
            .coerceIn(0.28f, 1f)
        val color = lerpColor(palette, HudGold, goldMix).copy(alpha = alpha)
        val radius = particle.size * depth * (1.15f + activity * 0.65f) * layerBoost
        drawCircle(color = color, radius = radius, center = Offset(px, py))
    }

    // Secondary multi-orb accents (core + shoulder sparks) — always drawn for humanoid detail.
    if (humanoid) {
        drawSecondaryOrbs(cx, cy, scale, palette, activity, tick, amplitude, phase)
    }
}

private fun DrawScope.drawStateChrome(
    cx: Float,
    cy: Float,
    scale: Float,
    phase: PresencePhase,
    palette: Color,
    activity: Float,
    tick: Float,
    humanoid: Boolean,
    reducedMotion: Boolean,
) {
    val ringCy = cy - if (humanoid) scale * 0.12f else 0f
    when (phase) {
        PresencePhase.OFFLINE -> {
            // Broken ring offline cue without collapsing brightness.
            val path = Path()
            val r = scale * 0.92f
            for (seg in 0 until 5) {
                val start = tick * 0.15f + seg * (Math.PI.toFloat() * 2f / 5f) + 0.12f
                val sweep = Math.PI.toFloat() * 2f / 5f * 0.55f
                path.reset()
                path.addArc(
                    oval = Rect(cx - r, ringCy - r, cx + r, ringCy + r),
                    startAngleDegrees = Math.toDegrees(start.toDouble()).toFloat(),
                    sweepAngleDegrees = Math.toDegrees(sweep.toDouble()).toFloat(),
                )
                drawPath(
                    path = path,
                    color = HudOfflineWarm.copy(alpha = 0.55f + activity * 0.25f),
                    style = Stroke(width = 2.8f, cap = StrokeCap.Round),
                )
            }
        }
        PresencePhase.APPROVAL, PresencePhase.WAITING -> {
            val lock = scale * 0.88f
            drawCircle(
                color = (if (phase == PresencePhase.APPROVAL) HudApproval else HudWaiting)
                    .copy(alpha = 0.55f + activity * 0.2f),
                radius = lock,
                center = Offset(cx, ringCy),
                style = Stroke(width = 3.2f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(14f, 10f), tick * 8f)),
            )
            // Lock indicator nub.
            drawCircle(
                color = HudApproval.copy(alpha = 0.9f),
                radius = 5.5f + activity * 2f,
                center = Offset(cx, ringCy - lock),
            )
        }
        PresencePhase.THINKING -> {
            for (i in 0..2) {
                val spin = tick + i * 2.1f
                val expand = 1f + sin(tick * 1.4f + i) * 0.06f
                drawCircle(
                    color = palette.copy(alpha = 0.28f + activity * 0.18f - i * 0.04f),
                    radius = scale * (0.62f + i * 0.14f) * expand,
                    center = Offset(cx + cos(spin) * 4f, ringCy + sin(spin) * 3f),
                    style = Stroke(width = 1.6f),
                )
            }
        }
        PresencePhase.LISTENING -> {
            val pulse = 1f + sin(tick * 2.4f) * 0.08f * activity
            drawCircle(
                color = palette.copy(alpha = 0.4f + activity * 0.25f),
                radius = scale * 0.78f * pulse,
                center = Offset(cx, cy + scale * 0.22f),
                style = Stroke(width = 2.4f),
            )
        }
        PresencePhase.ALERT, PresencePhase.ERROR -> {
            val flicker = if (reducedMotion) 0.85f else 0.65f + 0.35f * absSin(tick * (if (phase == PresencePhase.ERROR) 5.5f else 3.8f))
            drawCircle(
                color = (if (phase == PresencePhase.ERROR) HudError else HudAlert).copy(alpha = flicker * (0.45f + activity * 0.3f)),
                radius = scale * 0.95f,
                center = Offset(cx, ringCy),
                style = Stroke(width = 3.4f),
            )
        }
        PresencePhase.WORKING -> {
            for (i in 0..3) {
                val a = tick * 1.6f + i * (Math.PI.toFloat() / 2f)
                drawCircle(
                    color = palette.copy(alpha = 0.5f),
                    radius = 3.2f + activity * 2f,
                    center = Offset(cx + cos(a) * scale * 0.7f, ringCy + sin(a) * scale * 0.55f),
                )
            }
        }
        PresencePhase.SPEAKING, PresencePhase.IDLE -> Unit
    }
}

private fun DrawScope.drawSecondaryOrbs(
    cx: Float,
    cy: Float,
    scale: Float,
    palette: Color,
    activity: Float,
    tick: Float,
    amplitude: Float,
    phase: PresencePhase,
) {
    val chest = Offset(cx, cy - scale * 0.05f)
    val head = Offset(cx, cy - scale * 0.42f)
    val pulse = 1f + sin(tick * 1.3f) * 0.08f * amplitude
    drawCircle(
        brush = Brush.radialGradient(
            colors = listOf(HudCore.copy(alpha = 0.55f + activity * 0.35f), Color.Transparent),
            center = chest,
            radius = 18f * pulse * (0.9f + activity * 0.25f),
        ),
        radius = 18f * pulse * (0.9f + activity * 0.25f),
        center = chest,
    )
    drawCircle(
        color = palette.copy(alpha = 0.55f + activity * 0.3f),
        radius = 6.5f + activity * 4f,
        center = chest,
    )
    drawCircle(
        brush = Brush.radialGradient(
            colors = listOf(palette.copy(alpha = 0.5f + activity * 0.28f), Color.Transparent),
            center = head,
            radius = 14f * pulse,
        ),
        radius = 14f * pulse,
        center = head,
    )
    // Shoulder secondary orbs.
    val shoulderY = cy + scale * 0.18f
    val shoulderSpread = scale * 0.38f
    for (side in listOf(-1f, 1f)) {
        val o = Offset(cx + side * shoulderSpread, shoulderY)
        drawCircle(
            color = palette.copy(alpha = 0.35f + activity * 0.25f),
            radius = 4.5f + activity * 2.5f + sin(tick + side) * 1.2f * amplitude,
            center = o,
        )
    }
    if (phase == PresencePhase.OFFLINE) {
        // Warm offline accent orb — colour shift in addition to brightness floor.
        drawCircle(
            color = HudOfflineWarm.copy(alpha = 0.42f + activity * 0.28f),
            radius = 9f + activity * 3f,
            center = Offset(cx + scale * 0.22f, cy - scale * 0.28f),
        )
    }
}

private fun paletteFor(phase: PresencePhase, humanoid: Boolean): Color = when (phase) {
    PresencePhase.OFFLINE -> HudOfflineWarm
    PresencePhase.ERROR -> HudError
    PresencePhase.ALERT -> HudAlert
    PresencePhase.APPROVAL -> HudApproval
    PresencePhase.WAITING -> HudWaiting
    PresencePhase.SPEAKING -> HudCyan
    PresencePhase.LISTENING -> Color(0xFF2AD8FF)
    PresencePhase.WORKING -> Color(0xFF00BDFF)
    PresencePhase.THINKING -> Color(0xFF1AA0FF)
    PresencePhase.IDLE -> if (humanoid) HudCyan else HudGold
}

private fun absSin(v: Float): Float = kotlin.math.abs(sin(v))

private fun lerpColor(a: Color, b: Color, t: Float): Color {
    val u = t.coerceIn(0f, 1f)
    return Color(
        red = a.red + (b.red - a.red) * u,
        green = a.green + (b.green - a.green) * u,
        blue = a.blue + (b.blue - a.blue) * u,
        alpha = a.alpha + (b.alpha - a.alpha) * u,
    )
}
