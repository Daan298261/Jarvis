import assert from "node:assert/strict"
import { test } from "node:test"
import { AVATAR_MOTION_PROFILES, avatarMotionProfile, sampleAvatarMotion } from "./src/presence/avatarMotion.ts"

test("every persona and both humanoids have distinct authored animations in A and B", () => {
  const profiles = Object.entries(AVATAR_MOTION_PROFILES)
  assert.equal(profiles.length, 16)
  assert.equal(new Set(profiles.map(([,p]) => p.name)).size, 16)
  for (const [id, profile] of profiles) {
    assert.equal(avatarMotionProfile(`portrait_${id}`), profile)
    assert.equal(avatarMotionProfile(`portrait_${id}_b`), profile)
    const initial = sampleAvatarMotion(profile, 0, 1, false)
    const later = sampleAvatarMotion(profile, 2, 1, false)
    assert.notDeepEqual(initial, later)
    for (let t = 0; t < 60; t += 0.5) {
      const pose = sampleAvatarMotion(profile, t, 1, false)
      assert.ok(Object.values(pose).every(Number.isFinite))
      assert.ok(Math.abs(pose.x) <= 0.025 && Math.abs(pose.y) <= 0.04)
      assert.ok(Math.abs(pose.yaw) <= 0.04 && Math.abs(pose.roll) <= 0.035)
      assert.ok(Math.abs(pose.flutter) <= 0.025 && Math.abs(pose.ripple) <= 0.025)
    }
  }
  assert.equal(avatarMotionProfile("stormbird_b"), AVATAR_MOTION_PROFILES.anzu)
  assert.equal(avatarMotionProfile("humanoid_bust"), AVATAR_MOTION_PROFILES.humanoid)
})

test("reduced motion and zero animation return the neutral pose for all avatars", () => {
  const neutral = { x: 0, y: 0, yaw: 0, pitch: 0, roll: 0, scale: 1, flutter: 0, ripple: 0 }
  for (const profile of Object.values(AVATAR_MOTION_PROFILES)) {
    for (const pose of [sampleAvatarMotion(profile, 2, 0, false), sampleAvatarMotion(profile, 2, 1, true)]) {
      for (const key of Object.keys(neutral)) assert.equal(Math.abs(pose[key]), neutral[key])
    }
  }
})
