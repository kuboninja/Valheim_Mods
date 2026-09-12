using System;
using System.IO;
using Mono.Cecil;
using QssValheim1Compat;

// Offline harness: applies the patcher's IL fixes to a copy of the stock DLL so the output can
// be diffed against the build that was verified in-game, without needing to launch the game.
internal static class Program
{
    private static int Main(string[] args)
    {
        if (args.Length < 2)
        {
            Console.Error.WriteLine("usage: <stock QuickStackStore.dll> <output dll>");
            return 2;
        }

        using var input = new MemoryStream(File.ReadAllBytes(args[0]));
        using var module = ModuleDefinition.ReadModule(input);

        QssPatches.Apply(module, m => Console.WriteLine("  " + m));

        using var output = new MemoryStream();
        module.Write(output);
        File.WriteAllBytes(args[1], output.ToArray());

        Console.WriteLine($"wrote {args[1]} ({new FileInfo(args[1]).Length} bytes)");
        return 0;
    }
}
