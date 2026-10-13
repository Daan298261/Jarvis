package org.anzu.fixture;

import java.security.MessageDigest;
import javax.crypto.Cipher;
import javax.crypto.spec.SecretKeySpec;

public final class Main {
    static final String API = "https://api.fixture.anzu-test.example.com/v1/login";
    static final String PUSH = "wss://push.fixture.anzu-test.example.com/socket";
    static final String GOOGLE_KEY = "AIzaSyFixtureKeyForAnzuTesting012345678";
    static final String AWS_KEY = "AKIAFIXTUREANZU12345";
    static final String BUCKET = "https://anzu-fixture.s3.amazonaws.com/upload";

    public static byte[] seal(byte[] data) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/ECB/PKCS5Padding");
        cipher.init(Cipher.ENCRYPT_MODE, new SecretKeySpec("0123456789ABCDEF".getBytes(), "AES"));
        return cipher.doFinal(data);
    }

    public static byte[] digest(String password) throws Exception {
        return MessageDigest.getInstance("MD5").digest(password.getBytes());
    }

    public static String endpoints() {
        return API + " " + PUSH + " " + GOOGLE_KEY + " " + AWS_KEY + " " + BUCKET;
    }
}
