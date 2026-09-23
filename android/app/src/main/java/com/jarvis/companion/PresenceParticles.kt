package com.jarvis.companion

/** Seeded particle cloud for the companion HUD (orb + humanoid bust). JVM-testable. */
data class HudParticle(
    val x: Float,
    val y: Float,
    val z: Float,
    val gold: Float,
    val light: Float,
    val size: Float,
    /** Layer hint: 0 core, 1 body/head, 2 halo, 3 spark — richer Offline/Idle multi-orb detail (RFC-0139). */
    val layer: Int = 1,
)

object PresenceParticles {
    fun orb(count: Int = 280, seed: Int = 9041): List<HudParticle> {
        val random = Lcg(seed)
        val out = ArrayList<HudParticle>(count + 120)
        repeat(count) {
            val angle = random.next() * Math.PI.toFloat() * 2f
            val radius = Math.sqrt(random.next().toDouble()).toFloat()
            val ring = 0.18f + radius * 0.82f
            out += HudParticle(
                x = kotlin.math.cos(angle) * ring,
                y = kotlin.math.sin(angle) * ring * 0.72f,
                z = (random.next() - 0.5f) * 0.35f,
                gold = 0.55f + random.next() * 0.45f,
                light = 0.35f + (1f - radius) * 1.1f,
                size = 1.1f + random.next() * 1.6f,
                layer = 1,
            )
        }
        // Secondary halo + core orbs so orb mode is not a single faint blob.
        repeat(48) {
            val a = random.next() * Math.PI.toFloat() * 2f
            val r = 0.72f + random.next() * 0.28f
            out += HudParticle(
                x = kotlin.math.cos(a) * r,
                y = kotlin.math.sin(a) * r * 0.78f,
                z = (random.next() - 0.5f) * 0.2f,
                gold = 0.4f + random.next() * 0.3f,
                light = 0.55f + random.next() * 0.35f,
                size = 1.6f + random.next() * 1.2f,
                layer = 2,
            )
        }
        repeat(36) {
            val a = random.next() * Math.PI.toFloat() * 2f
            val r = Math.pow(random.next().toDouble(), 1.5).toFloat() * 0.22f
            out += HudParticle(
                x = kotlin.math.cos(a) * r,
                y = kotlin.math.sin(a) * r * 0.9f,
                z = 0.25f,
                gold = 0.95f,
                light = 1.1f + (1f - r / 0.22f) * 0.6f,
                size = 2.0f + random.next() * 1.4f,
                layer = 0,
            )
        }
        return out
    }

    /**
     * Particle / multi-orb humanoid bust. Density default raised for RFC-0139 Offline readability;
     * adds halo + spark layers so Offline never drops to a sparse stub.
     */
    fun humanoid(density: Float = 0.72f, seed: Int = 5103): List<HudParticle> {
        val random = Lcg(seed)
        val out = ArrayList<HudParticle>(2200)
        fun emit(x: Float, y: Float, z: Float, gold: Float, light: Float, size: Float, layer: Int = 1) {
            out += HudParticle(x, y, z, gold, light, size, layer)
        }
        val rows = (42 * density).toInt().coerceAtLeast(24)
        val columns = (84 * density).toInt().coerceAtLeast(48)
        for (row in 0 until rows) {
            val t = row / rows.toFloat()
            val ring = headRing(t)
            for (col in 0 until columns) {
                val angle = (col + random.next() * 0.4f) / columns * Math.PI.toFloat() * 2f
                val front = kotlin.math.cos(angle)
                val x = kotlin.math.sin(angle) * ring[0]
                val nose = gauss(x, 0.14f) * gauss(ring[1] - 0.82f, 0.29f) * 0.07f
                val z = front * ring[2] + maxOf(0f, front) * nose
                val mask = gauss(x, 0.43f) * gauss(ring[1] - 0.88f, 0.46f) * smooth(front, 0.28f, 0.86f)
                val rim = kotlin.math.abs(kotlin.math.sin(angle)).toDouble().pow(8.5).toFloat()
                val light = if (front < 0f) 0.1f + rim * 0.35f else 0.32f + rim * 3.4f + mask * 1.4f
                if (random.next() < 0.03f && rim < 0.55f) continue
                emit(x, ring[1], z, mask * 0.85f, light * (0.7f + random.next() * 0.4f), 1.4f + random.next() * 0.7f, 1)
            }
        }
        val body = (520 * density).toInt().coerceAtLeast(260)
        repeat(body) {
            val y = -1.15f + random.next() * 1.28f
            val shoulder = kotlin.math.exp(-((y + 0.42f) / 0.48f).let { it * it })
            val width = 0.28f + shoulder * 1.05f
            val nx = (random.next() * 2f - 1f) * Math.pow(random.next().toDouble(), 0.34).toFloat()
            val x = nx * width
            val edge = kotlin.math.abs(nx)
            emit(
                x,
                y,
                0.04f + (random.next() * 2f - 1f) * (0.14f + shoulder * 0.12f),
                if (random.next() < 0.04f) 0.72f else 0f,
                0.2f + (1f - edge) * 0.45f,
                1f + random.next() * 0.7f,
                1,
            )
        }
        // Core multi-orb cluster (chest / heart) — always present, including Offline.
        val core = (120 * density).toInt().coerceAtLeast(64)
        repeat(core) {
            val a = random.next() * Math.PI.toFloat() * 2f
            val r = Math.pow(random.next().toDouble(), 1.4).toFloat() * 0.22f
            emit(
                kotlin.math.cos(a) * r,
                0.9f + kotlin.math.sin(a) * r * 1.2f,
                0.42f,
                0.92f,
                0.85f + (1f - r / 0.22f) * 0.9f,
                1.5f + random.next() * 0.9f,
                0,
            )
        }
        // Secondary head core orb.
        repeat((48 * density).toInt().coerceAtLeast(28)) {
            val a = random.next() * Math.PI.toFloat() * 2f
            val r = Math.pow(random.next().toDouble(), 1.2).toFloat() * 0.14f
            emit(
                kotlin.math.cos(a) * r * 0.6f,
                1.05f + kotlin.math.sin(a) * r,
                0.55f + random.next() * 0.08f,
                0.88f,
                1.0f + random.next() * 0.4f,
                1.8f + random.next() * 1.1f,
                0,
            )
        }
        // Halo ring around head / shoulders — Offline must keep this density.
        val halo = (160 * density).toInt().coerceAtLeast(90)
        repeat(halo) {
            val a = random.next() * Math.PI.toFloat() * 2f
            val r = 0.55f + random.next() * 0.35f
            val y = 0.55f + kotlin.math.sin(a * 0.5f) * 0.12f + random.next() * 0.35f
            emit(
                kotlin.math.cos(a) * r,
                y,
                kotlin.math.sin(a) * r * 0.35f,
                0.25f + random.next() * 0.35f,
                0.45f + random.next() * 0.4f,
                1.2f + random.next() * 1.0f,
                2,
            )
        }
        // Sparks / secondary orbs — richer than a sparse stub.
        val sparks = (140 * density).toInt().coerceAtLeast(80)
        repeat(sparks) {
            val a = random.next() * Math.PI.toFloat() * 2f
            val r = 0.2f + random.next() * 0.95f
            emit(
                kotlin.math.cos(a) * r * (0.4f + random.next() * 0.7f),
                -0.4f + random.next() * 2.0f,
                (random.next() - 0.5f) * 0.55f,
                if (random.next() < 0.35f) 0.8f else 0.15f,
                0.55f + random.next() * 0.7f,
                0.7f + random.next() * 1.4f,
                3,
            )
        }
        return out
    }

    fun compositionSmoke(particles: List<HudParticle>): CompositionSmoke {
        val layers = particles.groupingBy { it.layer }.eachCount()
        return CompositionSmoke(
            total = particles.size,
            coreOrbs = layers[0] ?: 0,
            bodyHead = layers[1] ?: 0,
            halo = layers[2] ?: 0,
            sparks = layers[3] ?: 0,
            hasHead = particles.any { it.y > 1.0f },
            hasBody = particles.any { it.y < 0f },
        )
    }

    data class CompositionSmoke(
        val total: Int,
        val coreOrbs: Int,
        val bodyHead: Int,
        val halo: Int,
        val sparks: Int,
        val hasHead: Boolean,
        val hasBody: Boolean,
    ) {
        fun meetsHumanoidBar(): Boolean =
            total >= PresenceVisual.HUMANOID_MIN_PARTICLES &&
                coreOrbs >= 40 &&
                halo >= 40 &&
                sparks >= 40 &&
                hasHead &&
                hasBody
    }

    private fun headRing(t: Float): FloatArray {
        val clamped = t.coerceIn(0f, 1f)
        val profile = arrayOf(
            floatArrayOf(0.05f, 0.18f, 0.16f),
            floatArrayOf(0.34f, 0.35f, 0.29f),
            floatArrayOf(0.51f, 0.63f, 0.38f),
            floatArrayOf(0.59f, 1.02f, 0.42f),
            floatArrayOf(0.55f, 1.34f, 0.39f),
            floatArrayOf(0.37f, 1.56f, 0.29f),
            floatArrayOf(0.08f, 1.65f, 0.10f),
        )
        val scaled = clamped * (profile.size - 1)
        val i = scaled.toInt().coerceAtMost(profile.size - 2)
        val f = scaled - i
        val a = profile[i]
        val b = profile[i + 1]
        return floatArrayOf(
            a[0] + (b[0] - a[0]) * f,
            a[1] + (b[1] - a[1]) * f,
            a[2] + (b[2] - a[2]) * f,
        )
    }

    private fun gauss(v: Float, s: Float): Float = kotlin.math.exp(-(v * v) / (s * s))
    private fun smooth(v: Float, edge0: Float, edge1: Float): Float {
        val t = ((v - edge0) / (edge1 - edge0)).coerceIn(0f, 1f)
        return t * t * (3f - 2f * t)
    }

    private class Lcg(seed: Int) {
        private var state = seed.toLong() and 0xffffffffL
        fun next(): Float {
            state = (state * 1664525L + 1013904223L) and 0xffffffffL
            return state / 4294967296f
        }
    }
}

private fun Double.pow(exp: Double): Double = Math.pow(this, exp)
