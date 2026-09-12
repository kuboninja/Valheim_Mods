using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Threading;
using BepInEx;
using BepInEx.Logging;
using Mono.Cecil;

namespace QssValheim1Compat
{
    // BepInEx preloader patch that repairs the installed QuickStackStore 1.4.13 for Valheim 1.0.
    //
    // It redistributes none of Goldenrevolver's code: Thunderstore installs the official package
    // as a dependency and this rewrites that installed copy before the Chainloader loads it.
    //
    // The rewrite has to go to disk. A preloader's in-memory AssemblyDefinition only covers the
    // game's managed assemblies; plugin DLLs are loaded from disk by path afterwards, so an
    // in-memory edit would never be seen.
    public static class Patcher
    {
        // The exact stock build this was written and tested against. Anything else is left alone
        // rather than risk mangling a future upstream release.
        private const string StockSha256 = "0635F5871342E416A1BD2247A1F5785A280E11FF7A97D4C1FC880C85143785F1";

        private const string TargetFileName = "QuickStackStore.dll";
        private const string BackupSuffix = ".qsscompat-original-1.4.13.bak";
        private const string MarkerSuffix = ".qsscompat.sha256";
        private const string LockSuffix = ".qsscompat.lock";
        private const string TempSuffix = ".qsscompat.tmp";
        private const int LockTimeoutMs = 30000;

        private static readonly ManualLogSource Log = Logger.CreateLogSource("QSSValheim1Compat");

        // Required by BepInEx's patcher contract. Nothing is patched through the normal
        // in-memory pipeline, so this stays empty and Patch is never called.
        public static IEnumerable<string> TargetDLLs => new string[0];

        public static void Patch(AssemblyDefinition assembly) { }

        public static void Initialize()
        {
            try
            {
                Run();
            }
            catch (Exception ex)
            {
                // Never take the game down over a failed compatibility patch.
                Log.LogError($"Patch aborted; QuickStackStore left untouched. {ex}");
            }
        }

        private static void Run()
        {
            var target = Directory
                .GetFiles(Paths.PluginPath, TargetFileName, SearchOption.AllDirectories)
                .FirstOrDefault();

            if (target == null)
            {
                Log.LogInfo($"{TargetFileName} not installed; nothing to do.");
                return;
            }

            // The Valheim dedicated server starts the BepInEx preloader TWICE, concurrently, so
            // every patcher runs twice in parallel. Two instances rewriting the same file is how
            // you end up with a truncated, unloadable DLL. Take an exclusive lock via an atomic
            // create before touching anything, and do the checks inside it -- the loser of the
            // race will see the finished marker and no-op.
            var lockPath = target + LockSuffix;
            FileStream lockFile = null;
            var waitedMs = 0;

            while (lockFile == null)
            {
                try
                {
                    lockFile = new FileStream(lockPath, FileMode.CreateNew, FileAccess.Write, FileShare.None);
                }
                catch (IOException)
                {
                    if (waitedMs >= LockTimeoutMs)
                    {
                        Log.LogWarning($"Another instance held the patch lock for {LockTimeoutMs}ms; skipping. " +
                                       $"If this persists, delete {Path.GetFileName(lockPath)}.");
                        return;
                    }

                    Thread.Sleep(200);
                    waitedMs += 200;
                }
            }

            try
            {
                PatchUnderLock(target);
            }
            finally
            {
                lockFile.Dispose();
                try { File.Delete(lockPath); } catch { /* best effort */ }
            }
        }

        private static void PatchUnderLock(string target)
        {
            var marker = target + MarkerSuffix;
            var currentHash = Sha256(File.ReadAllBytes(target));

            if (File.Exists(marker) && string.Equals(File.ReadAllText(marker).Trim(), currentHash, StringComparison.OrdinalIgnoreCase))
            {
                Log.LogInfo("QuickStackStore already patched; nothing to do.");
                return;
            }

            if (!string.Equals(currentHash, StockSha256, StringComparison.OrdinalIgnoreCase))
            {
                Log.LogWarning(
                    $"{TargetFileName} is not the stock 1.4.13 build this patch was tested against " +
                    $"(found {currentHash}). Refusing to patch it. If QuickStackStore has been updated, " +
                    "this compatibility patch is probably no longer needed and should be removed.");
                return;
            }

            var stockBytes = File.ReadAllBytes(target);

            byte[] patched;
            using (var input = new MemoryStream(stockBytes))   // read fully, hold no file handle
            using (var module = ModuleDefinition.ReadModule(input))
            using (var output = new MemoryStream())
            {
                QssPatches.Apply(module, m => Log.LogInfo(m));
                module.Write(output);
                patched = output.ToArray();
            }

            if (patched.Length == 0)
                throw new InvalidOperationException("patched assembly came back empty");

            var expectedHash = Sha256(patched);

            // Write the backup from the bytes we already hash-verified as stock, rather than
            // copying the live file. A concurrent instance may have replaced the live file with
            // the patched build by now, and copying that over the backup would poison it.
            var backup = target + BackupSuffix;
            if (!File.Exists(backup))
            {
                try
                {
                    File.WriteAllBytes(backup, stockBytes);
                    Log.LogInfo($"Saved a copy of the stock DLL to {Path.GetFileName(backup)}");
                }
                catch (IOException) { /* another instance created it first; fine */ }
            }

            // Stage into a file unique to this process. The lock above cannot be trusted -- this
            // server's bind mount does not honour FileShare.None across processes, so two
            // preloader instances really do get here at once. A shared temp path would let them
            // clobber each other's staging file mid-rename.
            var temp = $"{target}.{Guid.NewGuid():N}{TempSuffix}";
            try
            {
                File.WriteAllBytes(temp, patched);
                if (new FileInfo(temp).Length != patched.Length)
                    throw new IOException("staged file length does not match the patched assembly");
                using (var verify = new MemoryStream(File.ReadAllBytes(temp)))
                    ModuleDefinition.ReadModule(verify).Dispose();   // throws if it is not loadable

                // Delete-then-rename rather than an overwriting copy: on this bind mount creating
                // a file succeeds where overwriting one fails partway, truncating the target.
                try
                {
                    if (File.Exists(target)) File.Delete(target);
                    File.Move(temp, target);
                }
                catch (Exception ex)
                {
                    // A concurrent instance writes byte-identical output, so if the target is
                    // already correct its swap simply won this race and there is nothing to fix.
                    if (!TargetMatches(target, expectedHash))
                    {
                        Restore(backup, target);
                        throw new IOException($"swap failed, restored the stock DLL: {ex.Message}", ex);
                    }
                }

                if (!TargetMatches(target, expectedHash))
                {
                    Restore(backup, target);
                    throw new IOException($"written file does not match the expected patched build; restored the stock DLL");
                }

                File.WriteAllText(marker, expectedHash);
                Log.LogInfo("QuickStackStore patched for Valheim 1.0.");
            }
            finally
            {
                try { if (File.Exists(temp)) File.Delete(temp); } catch { /* best effort */ }
            }
        }

        private static bool TargetMatches(string target, string expectedHash)
        {
            try
            {
                return File.Exists(target) && Sha256(File.ReadAllBytes(target)) == expectedHash;
            }
            catch (IOException)
            {
                return false;   // mid-write by a concurrent instance
            }
        }

        private static void Restore(string backup, string target)
        {
            try
            {
                if (File.Exists(target)) File.Delete(target);
                File.Copy(backup, target);
                Log.LogWarning("Restored the stock QuickStackStore.dll from backup.");
            }
            catch (Exception ex)
            {
                Log.LogError($"COULD NOT RESTORE {Path.GetFileName(target)}. Reinstall QuickStackStore. {ex.Message}");
            }
        }

        private static string Sha256(byte[] bytes)
        {
            using (var sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "");
        }
    }
}
