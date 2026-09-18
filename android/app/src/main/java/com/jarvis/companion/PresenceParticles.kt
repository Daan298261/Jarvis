package com.jarvis.companion

/** Seeded particle cloud for the companion HUD (orb + humanoid bust). JVM-testable. */
data class HudParticle(
    val x: Float,
    val y: Float,
    val z: Float,
    val gold: Float,
    val light: Float,
    val size: Float,
)

object PresenceParticles {
    fun orb(count: Int = 220, seed: Int = 9041): List<HudParticle> {
        val random = Lcg(seed)
        val out = ArrayList<HudParticle>(count)
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
            )
        }
        return out
    }

    fun humanoid(density: Float = 0.55f, seed: Int = 5103): List<HudParticle> {
        val random = Lcg(seed)
        val out = ArrayList<HudParticle>(1400)
        fun emit(x: Float, y: Float, z: Float, gold: Float, light: Float, size: Float) {
            out += HudParticle(x, y, z, gold, light, size)
        }
        val rows = (36 * density).toInt().coerceAtLeast(18)
        val columns = (72 * density).toInt().coerceAtLeast(36)
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
                if (random.next() < 0.04f && rim < 0.55f) continue
                emit(x, ring[1], z, mask * 0.85f, light * (0.7f + random.next() * 0.4f), 1.4f + random.next() * 0.7f)
            }
        }
        val body = (420 * density).toInt().coerceAtLeast(180)
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
            )
        }
        val core = (90 * density).toInt().coerceAtLeast(40)
        repeat(core) {
            val a = random.next() * Math.PI.toFloat() * 2f
            val r = Math.pow(random.next().toDouble(), 1.4).toFloat() * 0.2f
            emit(
                kotlin.math.cos(a) * r,
                0.9f + kotlin.math.sin(a) * r * 1.2f,
                0.42f,
                0.92f,
                0.85f + (1f - r / 0.2f) * 0.9f,
                1.4f + random.next() * 0.8f,
            )
        }
        return out
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
