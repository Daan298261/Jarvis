package com.jarvis.companion

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.SecureRandom
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/** Full archive is separate from the bounded recent-history UI. All content and search keys are encrypted. */
class PhoneMemoryStore(
    context: Context,
    private val crypto: OutboxQueueCrypto = AndroidKeystoreOutboxQueueCrypto("anzu-local-conversations-v1"),
    private val clock: () -> Long = System::currentTimeMillis,
    filename: String = DB_NAME,
) : SQLiteOpenHelper(context, File(context.noBackupFilesDir, filename).absolutePath, null, 1) {
    init { setWriteAheadLoggingEnabled(true) }
    override fun onConfigure(db: SQLiteDatabase) { db.setForeignKeyConstraintsEnabled(true) }
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE meta (id TEXT PRIMARY KEY, value BLOB NOT NULL)")
        db.execSQL("CREATE TABLE projects (id TEXT PRIMARY KEY, name BLOB NOT NULL, notes BLOB NOT NULL, instructions BLOB NOT NULL)")
        db.execSQL("CREATE TABLE notes (id TEXT PRIMARY KEY, project_id TEXT NOT NULL DEFAULT '', payload BLOB NOT NULL, updated_at INTEGER NOT NULL)")
        db.execSQL("CREATE INDEX note_project ON notes(project_id,updated_at)")
        db.execSQL("CREATE TABLE chats (id TEXT PRIMARY KEY, project_id TEXT NOT NULL DEFAULT '', payload BLOB NOT NULL, updated_at INTEGER NOT NULL)")
        db.execSQL("CREATE TABLE messages (chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE, id TEXT NOT NULL, sender TEXT NOT NULL, payload BLOB NOT NULL, created_at INTEGER NOT NULL, PRIMARY KEY(chat_id,id))")
        db.execSQL("CREATE TABLE summaries (chat_id TEXT PRIMARY KEY REFERENCES chats(id) ON DELETE CASCADE, payload BLOB NOT NULL, message_count INTEGER NOT NULL, updated_at INTEGER NOT NULL)")
        db.execSQL("CREATE TABLE message_terms (chat_id TEXT NOT NULL, message_id TEXT NOT NULL, token TEXT NOT NULL, PRIMARY KEY(chat_id,message_id,token), FOREIGN KEY(chat_id,message_id) REFERENCES messages(chat_id,id) ON DELETE CASCADE)")
        db.execSQL("CREATE INDEX term_lookup ON message_terms(token)")
        db.execSQL("CREATE INDEX chat_updated ON chats(updated_at)")
        db.execSQL("CREATE INDEX chat_project ON chats(project_id,updated_at)")
        db.execSQL("CREATE INDEX chat_messages ON messages(chat_id,created_at)")
        db.insertOrThrow("meta", null, ContentValues().apply { put("id", "index_key"); put("value", crypto.encrypt(ByteArray(32).also { SecureRandom().nextBytes(it) })) })
    }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) { error("Unsupported phone memory schema $oldVersion → $newVersion; archive preserved") }
    private fun seal(value: String) = crypto.encrypt(value.toByteArray(Charsets.UTF_8))
    private fun open(value: ByteArray) = crypto.decrypt(value).toString(Charsets.UTF_8)
    private val indexKey: ByteArray by lazy {
        readableDatabase.rawQuery("SELECT value FROM meta WHERE id='index_key'", null).use { c -> check(c.moveToFirst()); crypto.decrypt(c.getBlob(0)) }
    }
    private fun token(word: String): String = Mac.getInstance("HmacSHA256").run {
        init(SecretKeySpec(indexKey, "HmacSHA256")); doFinal(word.toByteArray()).joinToString("") { "%02x".format(it) }
    }
    private fun words(text: String) = Regex("[\\p{L}\\p{N}]{3,}").findAll(text.lowercase(java.util.Locale.ROOT))
        .map { it.value.take(64) }.filterNot { it in STOP_WORDS }.distinct().take(64).toList()
    private inline fun <T> transaction(block: (SQLiteDatabase) -> T): T {
        val db = writableDatabase; db.beginTransaction()
        return try { block(db).also { db.setTransactionSuccessful() } } finally { db.endTransaction() }
    }
    @Synchronized fun upsertChat(id: String, title: String, project: String = "", desktopId: String = "") {
        val existing = chat(id)
        val payload = existing ?: JSONObject().put("id", id).put("title", title).put("desktop_conversation_id", desktopId)
        writableDatabase.insertWithOnConflict("chats", null, ContentValues().apply {
            put("id", id); put("project_id", existing?.optString("project_id") ?: project)
            put("payload", seal(payload.toString())); put("updated_at", clock())
        }, SQLiteDatabase.CONFLICT_IGNORE)
    }
    @Synchronized fun chat(id: String): JSONObject? = readableDatabase.rawQuery("SELECT payload,project_id FROM chats WHERE id=?", arrayOf(id)).use { c ->
        if (c.moveToFirst()) JSONObject(open(c.getBlob(0))).put("project_id", c.getString(1)) else null
    }
    @Synchronized fun append(chatId: String, message: JSONObject) = transaction { db ->
        check(chat(chatId) != null) { "Memory chat does not exist" }
        val id = message.optString("id").ifBlank { error("Memory message needs an ID") }
        val sender = message.optString("role", "unknown")
        val time = message.optLong("at", clock())
        val existing = db.rawQuery("SELECT payload FROM messages WHERE chat_id=? AND id=?", arrayOf(chatId, id)).use { c -> if (c.moveToFirst()) open(c.getBlob(0)) else null }
        if (existing == message.toString()) return@transaction
        val values = ContentValues().apply {
            put("chat_id", chatId); put("id", id); put("sender", sender); put("payload", seal(message.toString())); put("created_at", time)
        }
        if (existing == null) db.insertOrThrow("messages", null, values)
        else {
            values.remove("created_at")
            db.update("messages", values, "chat_id=? AND id=?", arrayOf(chatId, id))
            db.delete("message_terms", "chat_id=? AND message_id=?", arrayOf(chatId, id))
        }
        words(message.optString("text")).forEach { word ->
            db.insertOrThrow("message_terms", null, ContentValues().apply { put("chat_id", chatId); put("message_id", id); put("token", token(word)) })
        }
        val old = summary(chatId)
        val excerpts = old?.optJSONArray("excerpts")?.objects().orEmpty().filter { it.optString("message_id") != id } + JSONObject()
            .put("message_id", id).put("sender", sender).put("at", time).put("text", message.optString("text").replace(Regex("\\s+"), " ").take(220))
        val summary = JSONObject().put("kind", "extractive_quotes").put("excerpts", JSONArray(excerpts.sortedWith(compareByDescending<JSONObject> {
            val text = it.optString("text").lowercase(java.util.Locale.ROOT)
            (if (it.optString("sender") == "user") 2 else 0) +
                (if (Regex("\\b(prefer|remember|project|must|always|name|onthoud|voorkeur|altijd|naam)\\b").containsMatchIn(text)) 8 else 0)
        }.thenByDescending { it.optLong("at") }).take(12)))
        db.insertWithOnConflict("summaries", null, ContentValues().apply {
            put("chat_id", chatId); put("payload", seal(summary.toString())); put("message_count", (old?.optInt("message_count") ?: 0) + if (existing == null) 1 else 0); put("updated_at", time)
        }, SQLiteDatabase.CONFLICT_REPLACE)
        db.execSQL("UPDATE chats SET updated_at=? WHERE id=?", arrayOf(time, chatId))
    }
    @Synchronized fun summary(chatId: String): JSONObject? = readableDatabase.rawQuery("SELECT payload,message_count FROM summaries WHERE chat_id=?", arrayOf(chatId)).use { c ->
        if (c.moveToFirst()) JSONObject(open(c.getBlob(0))).put("message_count", c.getInt(1)) else null
    }
    @Synchronized fun legacyImported(): Boolean = readableDatabase.rawQuery("SELECT id FROM meta WHERE id='legacy_imported'", null).use { it.moveToFirst() }
    @Synchronized fun localChats(limit: Int): List<JSONObject> = readableDatabase.rawQuery(
        "SELECT c.id,c.payload,c.updated_at,COALESCE(s.message_count,0) FROM chats c LEFT JOIN summaries s ON s.chat_id=c.id WHERE c.id LIKE 'local-%' ORDER BY c.updated_at DESC,c.rowid DESC LIMIT ?", arrayOf(limit.coerceIn(1,200).toString())
    ).use { c -> buildList { while (c.moveToNext()) add(JSONObject(open(c.getBlob(1))).put("id", c.getString(0)).put("updated_at", c.getLong(2)).put("message_count", c.getInt(3)).put("local", true)) } }
    @Synchronized fun recentMessages(chatId: String, limit: Int): List<JSONObject> = readableDatabase.rawQuery(
        "SELECT payload FROM messages WHERE chat_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?", arrayOf(chatId, limit.coerceIn(1,500).toString())
    ).use { c -> buildList { while (c.moveToNext()) add(JSONObject(open(c.getBlob(0)))) }.asReversed() }
    @Synchronized fun messages(chatId: String, limit: Int = 100, offset: Int = 0): List<JSONObject> = readableDatabase.rawQuery(
        "SELECT payload FROM messages WHERE chat_id=? ORDER BY created_at,rowid LIMIT ? OFFSET ?", arrayOf(chatId, limit.coerceIn(1, 500).toString(), offset.coerceAtLeast(0).toString())
    ).use { c -> buildList { while (c.moveToNext()) add(JSONObject(open(c.getBlob(0)))) } }
    @Synchronized fun chats(project: String): List<JSONObject> = readableDatabase.rawQuery(
        "SELECT c.id,c.payload,(SELECT count(*) FROM messages m WHERE m.chat_id=c.id) FROM chats c WHERE project_id=? ORDER BY updated_at DESC LIMIT 100", arrayOf(project)
    ).use { c -> buildList { while (c.moveToNext()) add(JSONObject(open(c.getBlob(1))).put("id", c.getString(0)).put("message_count", c.getInt(2))) } }
    @Synchronized fun upsertNote(note: JSONObject, projectId: String = "") {
        writableDatabase.insertWithOnConflict("notes", null, ContentValues().apply {
            put("id", note.getString("id")); put("project_id", projectId); put("payload", seal(note.toString())); put("updated_at", note.optLong("created_at", clock()))
        }, SQLiteDatabase.CONFLICT_REPLACE)
    }
    @Synchronized fun hasNote(id: String): Boolean = readableDatabase.rawQuery("SELECT id FROM notes WHERE id=?", arrayOf(id)).use { it.moveToFirst() }
    @Synchronized fun deleteNote(id: String) { writableDatabase.delete("notes", "id=?", arrayOf(id)) }
    @Synchronized fun notes(projectId: String): List<JSONObject> = readableDatabase.rawQuery("SELECT payload FROM notes WHERE project_id IN ('',?) ORDER BY updated_at DESC LIMIT 8", arrayOf(projectId)).use { c -> buildList { while (c.moveToNext()) add(JSONObject(open(c.getBlob(0)))) } }
    @Synchronized fun saveProject(id: String, name: String, notes: String, instructions: String) {
        require(name.length <= 100 && notes.length <= 8000 && instructions.length <= 4000)
        writableDatabase.insertWithOnConflict("projects", null, ContentValues().apply {
            put("id", id); put("name", seal(name)); put("notes", seal(notes)); put("instructions", seal(instructions))
        }, SQLiteDatabase.CONFLICT_REPLACE)
    }
    @Synchronized fun project(id: String): JSONObject = readableDatabase.rawQuery("SELECT name,notes,instructions FROM projects WHERE id=?", arrayOf(id)).use { c ->
        if (c.moveToFirst()) JSONObject().put("id", id).put("name", open(c.getBlob(0))).put("notes", open(c.getBlob(1))).put("instructions", open(c.getBlob(2)))
        else JSONObject().put("id", id).put("name", if (id.isEmpty()) "All chats" else "Project").put("notes", "").put("instructions", "")
    }
    @Synchronized fun projects(): List<JSONObject> = readableDatabase.rawQuery("SELECT id FROM projects WHERE id<>'' ORDER BY rowid", null).use { c -> buildList { while (c.moveToNext()) add(project(c.getString(0))) } }
    @Synchronized fun linkDesktop(chatId: String, desktopId: String) {
        val payload = chat(chatId) ?: return
        payload.put("desktop_conversation_id", desktopId)
        writableDatabase.update("chats", ContentValues().apply { put("payload", seal(payload.toString())) }, "id=?", arrayOf(chatId))
    }
    @Synchronized fun assignProject(chatId: String, project: String) { writableDatabase.execSQL("UPDATE chats SET project_id=? WHERE id=?", arrayOf(project, chatId)) }
    @Synchronized fun deleteChat(id: String) { writableDatabase.delete("chats", "id=?", arrayOf(id)) }
    @Synchronized fun deleteProject(id: String) = transaction { db ->
        require(id.isNotEmpty()); db.delete("chats", "project_id=?", arrayOf(id)); db.delete("projects", "id=?", arrayOf(id)); db.delete("notes", "project_id=?", arrayOf(id))
    }
    @Synchronized fun clearRecall() = transaction { db ->
        db.delete("chats", null, null); db.delete("projects", null, null); db.delete("notes", null, null)
    }
    /** Only the active project's messages can be recalled; global owner notes/instructions are separate. */
    @Synchronized fun recall(query: String, projectId: String, excludingChat: String?, limit: Int = 4, recentChat: String = ""): List<JSONObject> {
        val tokens = words(query).take(8).map(::token)
        if (tokens.isEmpty()) return emptyList()
        val placeholders = tokens.joinToString(",") { "?" }
        val sql = "SELECT m.chat_id,m.id,m.sender,m.payload FROM message_terms t JOIN messages m ON m.chat_id=t.chat_id AND m.id=t.message_id JOIN chats c ON c.id=m.chat_id WHERE t.token IN ($placeholders) AND c.project_id=? AND c.id<>? AND NOT (m.chat_id=? AND m.id IN (SELECT id FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 12)) GROUP BY m.chat_id,m.id ORDER BY count(DISTINCT t.token) DESC,m.created_at DESC LIMIT ?"
        return readableDatabase.rawQuery(sql, (tokens + listOf(projectId, excludingChat.orEmpty(), recentChat, recentChat, limit.coerceIn(1, 8).toString())).toTypedArray()).use { c ->
            buildList { while (c.moveToNext()) add(JSONObject().put("chat_id", c.getString(0)).put("message_id", c.getString(1)).put("sender", c.getString(2)).put("text", JSONObject(open(c.getBlob(3))).optString("text").take(700))) }
        }
    }
    @Synchronized fun context(query: String, projectId: String, chatId: String?): String {
        val scopes = if (projectId.isEmpty()) listOf(project("")) else listOf(project(""), project(projectId))
        val instructions = scopes.asReversed().mapNotNull {
            val text = it.optString("instructions").take(if (it.optString("id").isBlank()) 800 else 1600)
            text.takeIf { value -> value.isNotBlank() }?.let { value -> (if (it.optString("id").isBlank()) "Global (unless overridden): " else "Project (overrides global): ") + value }
        }.joinToString("\n").take(2400)
        val savedNotes = notes(projectId).map { it.optString("text") }.joinToString("\n")
        val notes = (scopes.map { it.optString("notes") }.filter { it.isNotBlank() }.joinToString("\n") + "\n" + savedNotes).take(1600)
        val quotes = recall(query, projectId, null, recentChat = chatId.orEmpty())
        val recentIds = if (chatId == null) emptySet() else readableDatabase.rawQuery("SELECT id FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 12", arrayOf(chatId)).use { c -> buildSet { while (c.moveToNext()) add(c.getString(0)) } }
        val recentSummary = chatId?.let { summary(it)?.optJSONArray("excerpts")?.objects()?.filter { row -> row.optString("message_id") !in recentIds }?.take(4) }.orEmpty()
        if (instructions.isBlank() && notes.isBlank() && quotes.isEmpty() && recentSummary.isEmpty()) return ""
        return JSONObject().put("owner_instructions", instructions).put("owner_notes", notes)
            .put("historical_quotes", JSONArray(quotes)).put("current_chat_summary", JSONArray(recentSummary)).toString()
    }
    @Synchronized fun migrateLegacy(root: JSONObject) = transaction { db ->
        val done = db.rawQuery("SELECT id FROM meta WHERE id='legacy_imported'", null).use { it.moveToFirst() }
        if (done) return@transaction
        root.optJSONArray("conversations")?.objects()?.forEach { chat ->
            val id = chat.optString("id"); if (id.isBlank()) return@forEach
            upsertChat(id, chat.optString("title"), desktopId = chat.optString("desktop_conversation_id"))
            chat.optJSONArray("messages")?.objects()?.forEachIndexed { i, message ->
                if (message.optString("id").isBlank()) message.put("id", "legacy-$i")
                append(id, message)
            }
        }
        db.insertOrThrow("meta", null, ContentValues().apply { put("id", "legacy_imported"); put("value", seal("1")) })
    }
    companion object {
        const val DB_NAME = "phone-memory.sqlite"
        /** Rotation never renames/deletes an archive or its WAL, so unreadable content remains recoverable. */
        @Synchronized fun recovering(context: Context, crypto: OutboxQueueCrypto, clock: () -> Long = System::currentTimeMillis,
            onRecovered: (StoreRecovery) -> Unit = {}): PhoneMemoryStore {
            val prefs = context.getSharedPreferences("phone_memory_storage", Context.MODE_PRIVATE)
            val filename = prefs.getString("active_file", DB_NAME) ?: DB_NAME
            require(filename == DB_NAME || Regex("phone-memory-[a-f0-9-]+[.]sqlite").matches(filename)) { "Invalid memory archive path" }
            val current = PhoneMemoryStore(context, crypto, clock, filename)
            try {
                current.indexKey
                return current
            } catch (error: Exception) {
                current.close()
                if (error !is java.security.GeneralSecurityException && error !is android.database.sqlite.SQLiteDatabaseCorruptException) throw error
                val replacementName = "phone-memory-${java.util.UUID.randomUUID()}.sqlite"
                val replacement = PhoneMemoryStore(context, crypto, clock, replacementName)
                try {
                    replacement.indexKey
                    check(prefs.edit().putString("active_file", replacementName).commit()) { "Cannot save memory recovery location" }
                } catch (failure: Exception) { replacement.close(); throw failure }
                val oldFile = File(context.noBackupFilesDir, filename)
                onRecovered(StoreRecovery(oldFile, oldFile.isFile))
                return replacement
            }
        }
        private val STOP_WORDS = setOf("the", "and", "for", "with", "that", "this", "what", "how", "was", "are", "you", "can", "het", "een", "van", "voor", "met", "dat", "wat")
    }
}
