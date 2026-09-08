using System;
using System.IO;

class InstallerHarness
{
    static int Main(string[] args)
    {
        try
        {
            if (args[0] == "extract") TimeTipInstaller.ExtractArchive(args[1], args[2]);
            else if (args[0] == "rollback")
            {
                // Inject an I/O failure while committing runtime files, after the EXE was swapped.
                TimeTipInstaller.Install(args[1], args[2], false, false, args[3], (source, destination) =>
                {
                    if (Path.GetFileName(source) == "_internal" && Path.GetFileName(Path.GetDirectoryName(source)) == "app")
                        throw new IOException("Simulated runtime-file replacement failure.");
                    if (Directory.Exists(source)) Directory.Move(source, destination);
                    else File.Move(source, destination);
                });
            }
            else TimeTipInstaller.Install(args[0], args[1], false, false, args[2]);
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
            return 2;
        }
    }
}
