package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PresenceVisualTest {
    @Test
    fun offline_activity_meets_daylight_floor_and_rejects_tip_dim() {
        val offline = PresenceVisual.effectiveActivity(PresencePhase.OFFLINE)
        assertTrue(
            "Offline activity $offline must be ≥ ${PresenceVisual.OFFLINE_ACTIVITY_FLOOR}",
            offline >= PresenceVisual.OFFLINE_ACTIVITY_FLOOR,
        )
        assertTrue(
            "Offline must not use tip dead-dim ${PresenceVisual.REJECTED_TIP_OFFLINE_ACTIVITY}",
            offline > PresenceVisual.REJECTED_TIP_OFFLINE_ACTIVITY,
        )
        assertEquals(0.45f, PresenceVisual.OFFLINE_ACTIVITY_FLOOR, 0.0001f)
        assertTrue(PresenceVisual.isOfflineReadable(PresencePhase.OFFLINE))
    }

    @Test
    fun every_phase_stays_above_rejected_tip_dim() {
        for (phase in PresencePhase.entries) {
            val activity = PresenceVisual.effectiveActivity(phase)
            assertTrue("$phase activity $activity", activity >= PresenceVisual.OFFLINE_ACTIVITY_FLOOR)
            assertTrue("$phase vs tip dim", activity > PresenceVisual.REJECTED_TIP_OFFLINE_ACTIVITY)
        }
    }

    @Test
    fun resolve_phase_first_match_covers_desktop_aligned_states() {
        assertEquals(
            PresencePhase.OFFLINE,
            PresenceVisual.resolvePhase(PresenceInputs(connected = false)),
        )
        assertEquals(
            PresencePhase.SPEAKING,
            PresenceVisual.resolvePhase(PresenceInputs(connected = false, speaking = true)),
        )
        assertEquals(
            PresencePhase.LISTENING,
            PresenceVisual.resolvePhase(PresenceInputs(connected = false, recording = true)),
        )
        assertEquals(
            PresencePhase.THINKING,
            PresenceVisual.resolvePhase(PresenceInputs(connected = false, offlineAnswering = true)),
        )
        assertEquals(
            PresencePhase.ERROR,
            PresenceVisual.resolvePhase(
                PresenceInputs(connected = true, tasks = listOf(PresenceTaskSignal(status = "failed"))),
            ),
        )
        assertEquals(
            PresencePhase.APPROVAL,
            PresenceVisual.resolvePhase(
                PresenceInputs(
                    connected = true,
                    tasks = listOf(
                        PresenceTaskSignal(
                            status = "waiting",
                            waitingForConfirmation = true,
                            hasApproval = true,
                        ),
                    ),
                ),
            ),
        )
        assertEquals(
            PresencePhase.ALERT,
            PresenceVisual.resolvePhase(PresenceInputs(connected = true, systemDegraded = true)),
        )
        assertEquals(
            PresencePhase.WORKING,
            PresenceVisual.resolvePhase(
                PresenceInputs(connected = true, tasks = listOf(PresenceTaskSignal(status = "running"))),
            ),
        )
        assertEquals(
            PresencePhase.THINKING,
            PresenceVisual.resolvePhase(
                PresenceInputs(connected = true, tasks = listOf(PresenceTaskSignal(status = "queued"))),
            ),
        )
        assertEquals(
            PresencePhase.WAITING,
            PresenceVisual.resolvePhase(
                PresenceInputs(connected = true, tasks = listOf(PresenceTaskSignal(status = "waiting"))),
            ),
        )
        assertEquals(
            PresencePhase.IDLE,
            PresenceVisual.resolvePhase(PresenceInputs(connected = true)),
        )
    }

    @Test
    fun default_presence_mode_is_humanoid() {
        assertEquals("humanoid", PresenceVisual.DEFAULT_PRESENCE_MODE)
        assertEquals("humanoid", PresenceVisual.normalizePresenceMode(null))
        assertEquals("humanoid", PresenceVisual.normalizePresenceMode(""))
        assertEquals("humanoid", PresenceVisual.normalizePresenceMode("unknown"))
        assertEquals("orb", PresenceVisual.normalizePresenceMode("orb"))
        assertEquals("humanoid", PresenceVisual.normalizePresenceMode("humanoid"))
    }
}

class PresenceParticlesRfc0139Test {
    @Test
    fun humanoid_composition_meets_rich_multi_orb_bar() {
        val humanoid = PresenceParticles.humanoid()
        val smoke = PresenceParticles.compositionSmoke(humanoid)
        assertTrue(
            "humanoid total ${smoke.total} core=${smoke.coreOrbs} halo=${smoke.halo} sparks=${smoke.sparks}",
            smoke.meetsHumanoidBar(),
        )
        assertTrue(smoke.total >= PresenceVisual.HUMANOID_MIN_PARTICLES)
        assertTrue(smoke.hasHead)
        assertTrue(smoke.hasBody)
        assertEquals(humanoid.size, PresenceParticles.humanoid().size)
    }

    @Test
    fun offline_does_not_drop_humanoid_density() {
        // Offline uses the same particle cloud; density must stay rich (no sparse stub path).
        val cloud = PresenceParticles.humanoid()
        val smoke = PresenceParticles.compositionSmoke(cloud)
        assertFalse("sparse stub", smoke.total < 200)
        assertTrue(smoke.coreOrbs >= 40)
        assertTrue(smoke.halo >= 40)
        assertTrue(smoke.sparks >= 40)
    }

    @Test
    fun orb_also_has_multi_layer_detail() {
        val orb = PresenceParticles.orb()
        val smoke = PresenceParticles.compositionSmoke(orb)
        assertTrue(orb.size > 100)
        assertTrue(smoke.coreOrbs > 0)
        assertTrue(smoke.halo > 0)
    }
}
