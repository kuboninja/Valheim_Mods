# QuickStackStore compatibility patch — build source

Keeps **QuickStackStore 1.4.13** (Goldenrevolver, MIT) working on **Valheim 1.0**, whose
update changed enough method signatures and type names to break most of the mod. Upstream
issue #35 is still open.

Nothing here is loaded at runtime; these are the sources used to *produce* the runtime files.

Two of Goldenrevolver's binaries (stock and patched) sit in `v1-two-dll/` as local recovery
copies and are gitignored — they are someone else's compiled work, and the patcher rebuilds
the patched one from the stock DLL on demand. `LICENSE.QuickStackStore` is kept alongside
them because MIT requires the notice to travel with any copy that is distributed.

Paths in this document point at the live install (`E:\Games\Valheim Server\mods\`); adjust
if you work from this copy.

## Paths used by the scripts

The Python scripts resolve two locations from the environment rather than hardcoding them:

- `%TEMP%` — working directory for extracted reference assemblies (`%TEMP%\qss_refs\`) and the
  patcher's output DLL.
- `%APPDATA%` — used to reach the Thunderstore/r2modman profile when reading the client log.

`CECIL_DIR` at the top of each script points at your BepInEx `core` folder; edit it if yours is
not at `E:\Games\Valheim Server\mods\BepInEx\core`.

## Building

No compiled binaries are committed. To produce the patcher and the Thunderstore zip:

```
dotnet build patcher/QssValheim1CompatPatcher.csproj -c Release
```

Copy the resulting `QssValheim1Compat.Patcher.dll` into `package/patchers/`, then zip the
contents of `package/` — with `manifest.json`, `icon.png` and `README.md` at the zip root, and
forward slashes in entry paths (`Compress-Archive` writes backslashes, which Thunderstore may
mishandle; build the zip with `System.IO.Compression.ZipArchive` instead).

The csproj references `BepInEx.dll` and `Mono.Cecil.dll` from the BepInEx install; retarget the
`HintPath`s if yours lives elsewhere.

Before shipping a rebuild, run `patcher-test` against a stock 1.4.13 DLL and confirm the output
hash still matches the build recorded in the fix table below — that is a far stronger check
than launching the game.

## What actually runs

| Runtime file | What it is |
|---|---|
| `BepInEx/plugins/Goldenrevolver-.../QuickStackStore.dll` | Our Cecil-patched build of the mod. **Replaces** the stock DLL in place. |
| `BepInEx/plugins/local-QSSRandyCompatFix/QSSRandyCompatFix.dll` | Companion plugin — patches Harmony and the game, which cannot be done from inside the mod's own DLL. |

`QuickStackStore.dll.original-1.4.13.bak` beside the mod is the untouched stock DLL. It is
**not loaded**; it is the clean input the patch script reads. Never point the script at an
already-patched DLL — the edits would be applied twice.

Both files must be byte-identical on server and client.

## Rebuilding after a Valheim update

1. Re-extract reference assemblies from the running container into `%TEMP%\qss_refs\`
   (`assembly_valheim`, `Assembly-CSharp`, `assembly_utils`, `assembly_guiutils`,
   `gui_framework`, plus the UnityEngine ones the csproj needs):

       docker cp valheim-server:/home/steam/valheim/valheim_server_Data/Managed/<name>.dll <dest>

   Prefix with `MSYS_NO_PATHCONV=1` when calling from Git Bash.

2. `python scripts/audit_stale_apis.py` — every IL member reference checked against the
   current game assemblies. Two `ZRoutedRpc::Register` / `ZRpc::Register` hits are known
   false positives (generic-signature string comparison); anything else is real.

3. `python scripts/audit_harmony_targets.py` — `[HarmonyPatch]` attribute targets leave no
   IL reference, so they need their own pass. Should report 0 problems.

4. Add any newly-broken API to `scripts/patch_message_calls.py`, re-run it, and copy the
   output over `QuickStackStore.dll` on **both** server and client.

5. Rebuild the plugin: `dotnet build -c Release` in `QSSRandyCompatFix/`, deploy to both.

6. `python scripts/verify_all_applied.py` cross-checks every patch-declaring class in the
   DLL against what the client log says actually applied. Note it only reports on
   `QuickStackStore.*` types — bundled `ServerSync.*` classes are filtered out of the log
   and will show as "NEVER PROCESSED" even when they are fine.

## The trap that cost the most time

Harmony hides these failures. `PatchClassProcessor.Patch()` catches per-class exceptions and
returns a possibly-empty list without rethrowing, logging only when `Harmony.DEBUG` is on —
so "no exception" proves nothing; check the *returned count*.

Worse, `PatchClassProcessor`'s **constructor** can throw (Mono `BadImageFormatException`
reading attributes of a method whose signature names a deleted type). That escapes Harmony's
try/catch entirely and aborts the whole `PatchAll()` loop, silently leaving every type after
it unpatched. A startup `BadImageFormatException` is not cosmetic. The companion plugin now
replaces `Harmony.PatchAll(Assembly)` with a per-type try/catch version that names the
offending type instead of dying.

## Layout

| Folder | What it is |
|---|---|
| `scripts/` | The Python/Cecil patcher and audit scripts. Still the fastest way to iterate. |
| `v1-two-dll-working/` | Archived, in-game-verified two-DLL solution (patched mod + companion plugin) with `HASHES.txt`. |
| `v2-patcher/` | Single BepInEx preloader patcher. Same nine fixes, ports `patch_message_calls.py` to C#. **Not yet verified on a live server** — see below. |
| `v2-patcher-test/` | Offline harness. Applies `QssPatches.Apply` to a stock DLL so the output can be hash-compared to a known-good build. |

The C# port is proven equivalent: `v2-patcher-test` output is **byte-identical** to the
Python-built DLL that was verified in-game (`38E0F049…`). Re-run that comparison after any
change to `QssPatches.cs` — it is a far better regression test than relaunching the game.

## The Valheim dedicated server runs the BepInEx preloader TWICE

Confirmed in the server log — two `Preloader started` banners, each loading every patcher,
running concurrently, before a single `Chainloader started`. Any patcher that writes to disk
therefore runs twice in parallel against the same file.

That is what destroyed `QuickStackStore.dll` on the first attempt: both instances saw the stock
hash, both began writing, and the file ended up 0 bytes. It is almost certainly also the cause
of the root-owned 0-byte `Backpacks.dll` that broke this server earlier — the ADARC patcher has
exactly the same exposure.

**File locking does not help.** A `FileMode.CreateNew` lock file was tried first and both
instances acquired it — this bind mount does not honour `FileShare.None` across processes.
Verified in the log: both runs patched, and both reported creating the backup, meaning neither
saw the other. The lock is still taken (it costs nothing where locking does work) but nothing
may depend on it.

So a disk-writing patcher here must be **safe under genuine concurrency**:

1. write the backup from the bytes already hash-verified as stock, never by copying the live
   file — a concurrent instance may have replaced it with the patched build by then, and
   copying that over the backup poisons the rollback;
2. stage to a temp path unique per process (`.<guid>.tmp`), cleaned up in a `finally` — a
   shared temp path lets instances clobber each other mid-rename;
3. stage first and prove it loads with Cecil before touching the original;
4. delete-then-rename rather than overwrite-copy — on this bind mount creating a file succeeds
   where overwriting one fails partway, truncating the target;
5. re-hash after writing and restore the backup if it does not match — and treat "the target
   already holds the expected hash" as success, since a lost rename race just means the other
   instance wrote the same bytes first.

Verified live: both preloader instances patch concurrently, the target ends at the expected
hash, the backup stays stock, and no temp files are left behind.

Writing to disk is unavoidable for patching a *plugin*: a preloader's in-memory
`AssemblyDefinition` only covers the game's managed assemblies, and plugin DLLs are loaded from
disk by path by the Chainloader afterwards.

## Fixes currently applied to QuickStackStore.dll

| # | Problem | Fix |
|---|---|---|
| 1 | `Character.Message` gained a trailing `bool log` | 9 call sites retargeted to the 5-arg overload |
| 2 | `ZRoutedRpc.Everybody` became a compile-time const with no storage | 3 `ldsfld` replaced with `ldc.i8 0` |
| 3 | `Inventory.Changed()` gained `(bool, bool)` | 8 call sites retargeted |
| 4 | `InventoryGui.m_splitPanel` → `m_splitDialog` | field reference retargeted |
| 5 | `OnRightClick` → `OnRightDown`, `OnLeftClick` → `OnLeftDown` | patch targets retargeted (see note) |
| 6 | `InventoryGrid.Element` → top-level `InventoryElement` | shared `TypeReference` repointed |
| 7 | `ItemData.GetTooltip` gained `bool appending` | declared arg-type array extended |
| 8 | `HasRandyPlugin`'s unguarded `.First()` for a field EquipmentAndQuickSlots 3.x removed | reflection block wrapped in `catch(Exception)` |
| 9 | Trash confirm dialog showed wrong amounts | cloned `SplitDialog` component disabled before `SetActive` |

Note on #5: favoriting must hook `OnLeftDown`, not `OnLeftClick`. `OnLeftDown` is what sets
`m_pressedItem` and fires `m_onSelected` — the pickup. Patching `OnLeftClick` meant the drag
had already started, and QSS's own `ShouldIgnoreFavoritingClick` bails whenever
`InventoryGui.m_dragGo` is set, so the first click was always swallowed and only a second one
favorited.

Fixes 8 and 9 started life as Harmony patches in the companion plugin and were later moved
into IL, which is what allows the v2 single-DLL design. Fix 8 is safe to do this way because
`HasRandyPlugin` sets its result local to `EnabledWithQuickSlots` *before* the risky block and
degrades correctly when `RandyQuickSlotsEnabled` stays null — so catching and falling through
returns exactly what the finalizer used to force. Fix 9 uses `enabled = false` rather than
`Destroy` because `Destroy` is deferred to end-of-frame and `OnEnable` would still fire first.

## The companion plugin (v1 only)

`v1-two-dll-working/QSSRandyCompatFix.dll` additionally carried a **resilient
`Harmony.PatchAll`** — a prefix on Harmony itself that try/catches per type so one unreadable
type cannot abort a whole assembly's scan. It is deliberately **not** in v2: it patches Harmony
globally and affects every installed mod, which is out of scope for a narrow compatibility
patch. It only ever mattered because `BorderRenderer` and `TooltipRenderer` threw, and fixes 6
and 7 removed that. Worth reinstating locally if a future update reintroduces a type Mono
cannot read, since it names the offending type instead of failing silently.
