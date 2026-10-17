package com.jarvis.companion

import org.junit.Assert.*
import org.junit.Test

class SolarSystemVisualTest {
    @Test fun eightPlanetsRemainOnDistinctOrbitsAndMoveAtIndependentRates() {
        val planets = SolarSystemVisual.planets
        assertEquals(listOf("Mercury", "Venus", "Earth", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune"), planets.map { it.name })
        planets.forEachIndexed { index, planet ->
            val (x, y) = SolarSystemVisual.position(planet, index, 0f)
            assertEquals(planet.orbit * planet.orbit, x * x + y * y, .00001f)
            assertNotEquals(SolarSystemVisual.position(planet, index, 0f), SolarSystemVisual.position(planet, index, 1f))
            val (endX, endY) = SolarSystemVisual.position(planet, index, planet.periodSeconds)
            assertEquals(x, endX, .00001f)
            assertEquals(y, endY, .00001f)
        }
        assertTrue(planets.zipWithNext().all { (a, b) -> a.orbit < b.orbit && a.periodSeconds < b.periodSeconds })
    }

    @Test fun fillingContextOnlyExtinguishesStarsAndEmptyContextRestoresThem() {
        val totals = (0..100).map { percent ->
            SolarSystemVisual.stars.sumOf { SolarSystemVisual.starAlpha(it.rank, percent / 100f).toDouble() }
        }
        assertTrue(totals.zipWithNext().all { (a, b) -> a >= b })
        assertEquals(0.0, totals.last(), .0001)
        assertTrue(totals[50] in 100.0..115.0)
        assertEquals(1f, SolarSystemVisual.starAlpha(.9f, null))
        assertEquals(1f, SolarSystemVisual.starAlpha(.9f, 0f))
    }
}
