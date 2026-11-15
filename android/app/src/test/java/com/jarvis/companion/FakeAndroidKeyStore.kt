package com.jarvis.companion

import org.robolectric.RobolectricTestRunner
import java.io.InputStream
import java.io.OutputStream
import java.security.Key
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.KeyPairGeneratorSpi
import java.security.KeyStoreSpi
import java.security.PrivateKey
import java.security.Provider
import java.security.SecureRandom
import java.security.Security
import java.security.cert.Certificate
import java.security.spec.AlgorithmParameterSpec
import java.util.Collections
import java.util.Date
import java.util.concurrent.ConcurrentHashMap
import javax.crypto.KeyGeneratorSpi
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

/**
 * The JVM has no AndroidKeyStore, but [JarvisApp] and the phone stores need one. This installs an
 * in-memory stand-in (real AES keys; the EC request is answered with a throwaway RSA pair because the JVM sandbox has no EC curves; no hardware) so a real [CompanionModel] can be built
 * in a Robolectric test. Test-only; production code is untouched.
 */
object FakeAndroidKeyStore {
    private val entries = ConcurrentHashMap<String, Key>()

    @Synchronized fun install() {
        if (Security.getProvider("AndroidKeyStore") != null) return
        Security.addProvider(object : Provider("AndroidKeyStore", 1.0, "In-memory test keystore") {
            init {
                put("KeyStore.AndroidKeyStore", FakeStore::class.java.name)
                put("KeyGenerator.AES", FakeAesGenerator::class.java.name)
                put("KeyPairGenerator.EC", FakeEcGenerator::class.java.name)
            }
        })
    }

    /**
     * The provider lives outside Robolectric's sandbox classloader, so the spec it receives is a different
     * `KeyGenParameterSpec` class than the one this file compiles against: read its alias reflectively.
     */
    private fun aliasOf(params: AlgorithmParameterSpec?): String? =
        params?.let { runCatching { it.javaClass.getMethod("getKeystoreAlias").invoke(it) as? String }.getOrNull() }

    class FakeStore : KeyStoreSpi() {
        override fun engineGetKey(alias: String, password: CharArray?): Key? = entries[alias]
        override fun engineGetCertificateChain(alias: String): Array<Certificate>? = null
        override fun engineGetCertificate(alias: String): Certificate? = null
        override fun engineGetCreationDate(alias: String): Date? = Date()
        override fun engineSetKeyEntry(alias: String, key: Key, password: CharArray?, chain: Array<out Certificate>?) { entries[alias] = key }
        override fun engineSetKeyEntry(alias: String, key: ByteArray?, chain: Array<out Certificate>?) = Unit
        override fun engineSetCertificateEntry(alias: String, cert: Certificate?) = Unit
        override fun engineDeleteEntry(alias: String) { entries.remove(alias) }
        override fun engineAliases() = Collections.enumeration(entries.keys.toList())
        override fun engineContainsAlias(alias: String) = entries.containsKey(alias)
        override fun engineSize() = entries.size
        override fun engineIsKeyEntry(alias: String) = entries.containsKey(alias)
        override fun engineIsCertificateEntry(alias: String) = false
        override fun engineGetCertificateAlias(cert: Certificate?): String? = null
        override fun engineStore(stream: OutputStream?, password: CharArray?) = Unit
        override fun engineLoad(stream: InputStream?, password: CharArray?) = Unit
    }

    class FakeAesGenerator : KeyGeneratorSpi() {
        private var alias: String? = null
        override fun engineInit(random: SecureRandom?) = Unit
        override fun engineInit(params: AlgorithmParameterSpec?, random: SecureRandom?) {
            alias = aliasOf(params)
        }
        override fun engineInit(keysize: Int, random: SecureRandom?) = Unit
        override fun engineGenerateKey(): SecretKey {
            val key = SecretKeySpec(ByteArray(32).also { SecureRandom().nextBytes(it) }, "AES")
            alias?.let { entries[it] = key }
            return key
        }
    }

    class FakeEcGenerator : KeyPairGeneratorSpi() {
        private var alias: String? = null
        override fun initialize(keysize: Int, random: SecureRandom?) = Unit
        override fun initialize(params: AlgorithmParameterSpec?, random: SecureRandom?) {
            alias = aliasOf(params)
        }
        override fun generateKeyPair(): KeyPair {
            val pair = KeyPairGenerator.getInstance("RSA").apply { initialize(1024) }.generateKeyPair()
            alias?.let { entries[it] = pair.private as PrivateKey }
            return pair
        }
    }
}

/** Robolectric runner that has the fake AndroidKeyStore in place before the application is created. */
class KeystoreRobolectricRunner(testClass: Class<*>) : RobolectricTestRunner(testClass) {
    init { FakeAndroidKeyStore.install() }
}
