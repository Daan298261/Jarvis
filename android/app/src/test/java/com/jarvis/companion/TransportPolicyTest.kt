package com.jarvis.companion

import org.junit.Assert.*
import org.junit.Test

class TransportPolicyTest {
    @Test fun acceptsHttpsOriginsOnly() {
        assertEquals("https://192.168.1.3:4781", TransportPolicy.origin("https://192.168.1.3:4781/"))
        for (url in listOf("http://jarvis", "https://key@jarvis", "https://jarvis/api", "https://jarvis?token=x", "https://jarvis#secret", "https://jarvis:0", "https://jarvis:65536", "https://jarvis/%2f")) {
            assertThrows(IllegalArgumentException::class.java) { TransportPolicy.origin(url) }
        }
    }
    @Test fun retriesOnlyReadsAndJournaledMessages() {
        assertTrue(TransportPolicy.replayable("GET", "/tasks", null))
        assertTrue(TransportPolicy.replayable("POST", "/messages", "stable-id"))
        assertFalse(TransportPolicy.replayable("POST", "/messages", null))
        for (path in listOf("/calls", "/schedules", "/session", "/attachments", "/tasks/one/approve")) {
            assertFalse(TransportPolicy.replayable("POST", path, "not-a-message"))
        }
    }

    @Test fun pairingFailoverIncludesEnrollAndChallenge() {
        assertTrue(TransportPolicy.pairingFailover("/enroll"))
        assertTrue(TransportPolicy.pairingFailover("/challenge/device-1"))
        assertFalse(TransportPolicy.pairingFailover("/messages"))
    }

    @Test fun ordersPublicAndRelayBeforePrivateLan() {
        val ordered = TransportPolicy.orderedForReachability(
            listOf(
                "https://10.2.0.2:4781",
                "https://relay.example.test:4781",
                "https://203.0.113.4:4781",
            ),
        )
        assertEquals("https://relay.example.test:4781", ordered[0])
        assertEquals("https://203.0.113.4:4781", ordered[1])
        assertEquals("https://10.2.0.2:4781", ordered.last())
    }

    @Test fun dialOrderKeepsRecentPublicWanWhenLocalsUnknown() {
        val lan = "https://10.2.0.2:4781"
        val wan = "https://203.0.113.4:4781"
        val relay = "https://relay.example.test:4781"
        val sticky = TransportPolicy.dialOrder(wan, listOf(lan, wan, relay), emptyList())
        assertEquals(wan, sticky[0])
        assertEquals(lan, sticky.last())
        val cold = TransportPolicy.dialOrder(null, listOf(lan, wan, relay), emptyList())
        assertEquals(relay, cold[0])
        assertEquals(wan, cold[1])
        assertEquals(lan, cold.last())
    }

    @Test fun emptyLocalsDoesNotStickyPrivateLan() {
        val lan = "https://10.2.0.2:4781"
        val wan = "https://203.0.113.4:4781"
        val relay = "https://relay.example.test:4781"
        val order = TransportPolicy.dialOrder(lan, listOf(lan, wan, relay), emptyList())
        assertEquals(relay, order[0])
        assertEquals(wan, order[1])
        assertEquals(lan, order.last())
    }

    @Test fun homeWifiDialsLanBeforePublicWan() {
        val lan = "https://10.2.0.2:4781"
        val wan = "https://203.0.113.4:4781"
        val relay = "https://relay.example.test:4781"
        val order = TransportPolicy.dialOrder(wan, listOf(lan, wan, relay), listOf("10.2.0.5"))
        assertEquals(lan, order[0])
        assertEquals(relay, order[1])
        assertEquals(wan, order.last())
    }

    @Test fun leavingHomeDoesNotStickyPrivateLan() {
        val lan = "https://10.2.0.2:4781"
        val wan = "https://203.0.113.4:4781"
        val relay = "https://relay.example.test:4781"
        val order = TransportPolicy.dialOrder(lan, listOf(lan, wan, relay), listOf("100.64.1.8"))
        assertEquals(relay, order[0])
        assertEquals(wan, order[1])
        assertEquals(lan, order.last())
    }

    @Test fun guestWifiOnOtherSubnetUsesWanFirst() {
        val lan = "https://192.168.1.12:4781"
        val wan = "https://203.0.113.4:4781"
        val order = TransportPolicy.dialOrder(null, listOf(lan, wan), listOf("192.168.2.40"))
        assertEquals(wan, order[0])
        assertEquals(lan, order.last())
    }

    @Test fun failedLanOnSameSubnetIsTriedLast() {
        val lan = "https://10.2.0.2:4781"
        val wan = "https://203.0.113.4:4781"
        val relay = "https://relay.example.test:4781"
        val order = TransportPolicy.dialOrder(null, listOf(lan, wan, relay), listOf("10.2.0.5"), listOf(lan))
        assertEquals(relay, order[0])
        assertEquals(wan, order[1])
        assertEquals(lan, order.last())
    }

    @Test fun hostnameTlsErrorsAreOrdinaryDialFailures() {
        val error: Throwable = javax.net.ssl.SSLException("Hostname 8.8.8.8 not verified")
        assertTrue(error is java.io.IOException)
    }

    @Test fun racesOrdinaryGetsButNotPairing() {
        assertTrue(TransportPolicy.mayRaceOrigins("GET", "/connection"))
        assertTrue(TransportPolicy.mayRaceOrigins("GET", "/models"))
        assertFalse(TransportPolicy.mayRaceOrigins("GET", "/challenge/device-1"))
        assertFalse(TransportPolicy.mayRaceOrigins("GET", "/enroll"))
        assertFalse(TransportPolicy.mayRaceOrigins("POST", "/session"))
        assertFalse(TransportPolicy.mayRaceOrigins("POST", "/messages"))
        assertEquals(1500L, TransportPolicy.connectTimeoutMs(2))
        assertEquals(4000L, TransportPolicy.connectTimeoutMs(1))
    }

    @Test fun doesNotRaceGetsWhenHomeLanIsFirst() {
        val lan = "https://10.2.0.2:4781"
        val wan = "https://203.0.113.4:4781"
        val locals = listOf("10.2.0.5")
        val order = TransportPolicy.dialOrder(wan, listOf(lan, wan), locals)
        assertEquals(lan, order[0])
        assertFalse(TransportPolicy.mayRaceOrigins("GET", "/connection", order, locals))
        assertTrue(TransportPolicy.mayRaceOrigins("GET", "/connection", listOf(wan, lan), listOf("100.64.1.8")))
    }

    @Test fun mDnsNameIsLanWhenWifiRfc1918IsPresent() {
        val mdns = "https://jarvis.local:4781"
        val wan = "https://home.example.test:4781"
        val home = TransportPolicy.dialOrder(wan, listOf(mdns, wan), listOf("10.2.0.5"))
        assertEquals(mdns, home[0])
        val away = TransportPolicy.dialOrder(mdns, listOf(mdns, wan), listOf("100.64.1.8"))
        assertEquals(wan, away[0])
        assertEquals(mdns, away.last())
    }

    @Test fun lanMatchUsesInterfacePrefixNotHardcodedSlash24() {
        val lan = "https://10.2.9.12:4781"
        val wan = "https://203.0.113.4:4781"
        val wide = TransportPolicy.dialOrder(null, listOf(lan, wan), listOf("10.2.0.5/16"))
        assertEquals(lan, wide[0])
        val narrow = TransportPolicy.dialOrder(null, listOf(lan, wan), listOf("10.2.0.5"))
        assertEquals(wan, narrow[0])
        assertEquals(lan, narrow.last())
    }

    @Test fun pointToPointNicsAreNotLanDialSources() {
        assertTrue(TransportPolicy.nicIsLanDialSource(true, false, false, false))
        assertFalse(TransportPolicy.nicIsLanDialSource(true, false, false, true))
        assertFalse(TransportPolicy.nicIsLanDialSource(true, false, true, false))
        assertFalse(TransportPolicy.nicIsLanDialSource(true, true, false, false))
    }

    @Test fun lanHostnamesRankWithPrivateAddresses() {
        assertEquals(2, TransportPolicy.reachabilityRank("https://jarvis.local:4781"))
        assertEquals(2, TransportPolicy.reachabilityRank("https://nas.lan:4781"))
        assertEquals(0, TransportPolicy.reachabilityRank("https://home.example.test:4781"))
    }
}
