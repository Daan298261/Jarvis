# RFC-0238: Desktop loopback command permissions

**Status:** accepted
**Date:** 2026-10-25
**Author:** Codex, requested by Daan

## Problem
The installed desktop portal reports `obsidian_embed_start not allowed by ACL`. Remote-origin native commands require explicit permissions after Tauri runtime updates. Related desktop controls can fail for the same reason.

## Decision
Declare the existing native commands in the application manifest and grant their generated permissions only to the existing main-window capability, restricted to the two existing loopback origins on port 4780. Preserve the command implementations and external-origin denial. Test permission coverage, compile the shell, and verify Obsidian embedding in the installed shell.

## Acceptance criteria
All registered desktop commands have explicit generated permissions. Only the main window and existing local API origins receive access. Obsidian start/resize/stop and native shell tests pass. No broader network origin or unrestricted permission is added.
