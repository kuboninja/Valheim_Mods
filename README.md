# Valheim Mods

Valheim modding work — mostly compatibility patches keeping mods alive across game updates.

## [quickstackstore-valheim1-compat](quickstackstore-valheim1-compat/)

A BepInEx preloader patch that lets **Quick Stack - Store - Sort - Trash - Restock 1.4.13**
(Goldenrevolver, MIT) run on **Valheim 1.0**. Nine IL fixes applied to the installed DLL at
startup; none of the original mod is redistributed, and Thunderstore pulls it in as a
dependency.

Verified live on a dedicated server and a client. See that folder's
[README](quickstackstore-valheim1-compat/README.md) for the full fix list, the rebuild
procedure for the next game update, and the two traps worth knowing:

- Harmony hides patch failures — `PatchClassProcessor.Patch()` swallows per-class exceptions
  and its *constructor* can throw right out of `PatchAll()`, silently leaving everything after
  the offending type unpatched.
- The Valheim dedicated server runs the BepInEx preloader **twice, concurrently**, and its
  bind mount doesn't honour file locks — so any patcher that writes to disk must be safe under
  genuine concurrency.
