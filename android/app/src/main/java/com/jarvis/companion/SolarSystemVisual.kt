package com.jarvis.companion

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin
import kotlin.random.Random

/** Schematic distances and periods keep all eight planets readable on a phone. */
object SolarSystemVisual {
    data class Planet(val name: String, val orbit: Float, val radius: Float, val color: Long, val periodSeconds: Float)
    val planets = listOf(
        Planet("Mercury", .22f, .012f, 0xFFB8AAA0, 14f),
        Planet("Venus", .32f, .020f, 0xFFE8C58B, 22f),
        Planet("Earth", .43f, .022f, 0xFF4CA9F0, 32f),
        Planet("Mars", .54f, .017f, 0xFFE47751, 44f),
        Planet("Jupiter", .67f, .044f, 0xFFD9B391, 65f),
        Planet("Saturn", .80f, .037f, 0xFFE9D196, 88f),
        Planet("Uranus", .94f, .028f, 0xFF90E0DF, 115f),
        Planet("Neptune", 1.08f, .027f, 0xFF527DE0, 150f),
    )
    data class Star(val x: Float, val y: Float, val radius: Float, val phase: Float, val rank: Float)
    val stars = Random(223).let { random ->
        List(220) { i -> Star(random.nextFloat(), random.nextFloat(), .5f + random.nextFloat(), random.nextFloat() * 6.28f, i / 220f) }
    }

    fun position(planet: Planet, index: Int, seconds: Float): Pair<Float, Float> {
        val angle = seconds / planet.periodSeconds * (2 * PI).toFloat() + index * 2.39996f
        return cos(angle) * planet.orbit to sin(angle) * planet.orbit
    }

    /** Stable ranked fade avoids random stars popping back as context increases. */
    fun starAlpha(rank: Float, contextUsed: Float?): Float =
        if (contextUsed == null) 1f else ((1f - contextUsed.coerceIn(0f, 1f) - rank) * 30f).coerceIn(0f, 1f)
}
