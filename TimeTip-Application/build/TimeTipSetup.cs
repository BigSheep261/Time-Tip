using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.IO.Pipes;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

internal static class TimeTipSetup
{
    private static readonly string[] ApplicationEntries = { "TimeTip.exe", "_internal" };

    [STAThread]
    private static int Main()
    {
        using (var mutex = new Mutex(false, @"Local\TimeTip.Installer"))
        {
            bool ownsMutex;
            try { ownsMutex = mutex.WaitOne(0); }
            catch (AbandonedMutexException) { ownsMutex = true; }
            if (!ownsMutex)
            {
                MessageBox.Show("已有一个 TimeTip 安装程序在运行。", "TimeTip");
                return 2;
            }

            try
            {
                var localData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                var installRoot = Path.Combine(localData, "TimeTip");
                try { Install(installRoot); }
                catch (Exception error)
                {
                    MessageBox.Show("TimeTip 安装失败。\n\n" + error.Message, "TimeTip",
                                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return 1;
                }

                var executable = Path.Combine(installRoot, "TimeTip.exe");
                try { CreateDesktopShortcut(executable); }
                catch (Exception error)
                {
                    MessageBox.Show("TimeTip 已安装，创建桌面快捷方式失败。\n\n" + error.Message, "TimeTip");
                }
                try { Process.Start(new ProcessStartInfo(executable) { WorkingDirectory = installRoot }); }
                catch (Exception error)
                {
                    MessageBox.Show("TimeTip 已安装，可手动打开以下程序。\n" + executable + "\n\n" + error.Message, "TimeTip");
                }
                return 0;
            }
            finally { mutex.ReleaseMutex(); }
        }
    }

    private static void Install(string installRoot)
    {
        string parent = Path.GetDirectoryName(installRoot);
        string staging = Path.Combine(parent, "TimeTip.setup." + Guid.NewGuid().ToString("N"));
        string incoming = Path.Combine(staging, "incoming");
        string previous = Path.Combine(staging, "previous");
        bool keepStaging = false;
        try
        {
            Directory.CreateDirectory(incoming);
            Directory.CreateDirectory(previous);
            using (var payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("TimeTip.Payload.zip"))
            {
                if (payload == null)
                    throw new InvalidDataException("安装程序中缺少 TimeTip 文件。");
                using (var archive = new ZipArchive(payload, ZipArchiveMode.Read))
                    archive.ExtractToDirectory(incoming);
            }
            if (!File.Exists(Path.Combine(incoming, "TimeTip.exe")) ||
                !Directory.Exists(Path.Combine(incoming, "_internal")))
                throw new InvalidDataException("安装程序中的 TimeTip 文件不完整。");

            CloseInstalledApplication(Path.Combine(installRoot, "TimeTip.exe"));
            Directory.CreateDirectory(installRoot);
            var backedUp = new List<string>();
            var installed = new List<string>();
            try
            {
                foreach (string name in ApplicationEntries)
                {
                    string current = Path.Combine(installRoot, name);
                    if (File.Exists(current) || Directory.Exists(current))
                    {
                        MoveEntry(current, Path.Combine(previous, name));
                        backedUp.Add(name);
                    }
                    MoveEntry(Path.Combine(incoming, name), current);
                    installed.Add(name);
                }
            }
            catch (Exception installError)
            {
                try
                {
                    foreach (string name in installed)
                        MoveEntry(Path.Combine(installRoot, name), Path.Combine(incoming, name));
                    foreach (string name in backedUp)
                        MoveEntry(Path.Combine(previous, name), Path.Combine(installRoot, name));
                }
                catch (Exception restoreError)
                {
                    keepStaging = true;
                    throw new IOException("恢复原版本失败。备份位于 " + previous + "\n" +
                                          installError.Message + "\n" + restoreError.Message);
                }
                throw;
            }
        }
        finally
        {
            if (!keepStaging && Directory.Exists(staging))
            {
                try { Directory.Delete(staging, true); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }
    }

    private static void MoveEntry(string source, string destination)
    {
        if (Directory.Exists(source))
            Directory.Move(source, destination);
        else
            File.Move(source, destination);
    }

    private static void CloseInstalledApplication(string executable)
    {
        var running = new List<Process>();
        var processes = Process.GetProcessesByName("TimeTip");
        try
        {
            foreach (var process in processes)
            {
                try
                {
                    if (String.Equals(process.MainModule.FileName, executable, StringComparison.OrdinalIgnoreCase))
                        running.Add(process);
                }
                catch (InvalidOperationException) { }
                catch (System.ComponentModel.Win32Exception) { }
            }
            if (running.Count == 0)
                return;

            try
            {
                using (var pipe = new NamedPipeClientStream(".", "TimeTip.SingleInstance",
                                                            PipeDirection.InOut, PipeOptions.Asynchronous))
                {
                    pipe.Connect(1500);
                    string greeting = ReadMessage(pipe);
                    if (running.Exists(process => greeting == "PID " + process.Id))
                    {
                        byte[] command = Encoding.ASCII.GetBytes("QUIT\n");
                        pipe.Write(command, 0, command.Length);
                        ReadMessage(pipe);
                    }
                }
            }
            catch (IOException) { }
            catch (TimeoutException) { }

            foreach (var process in running)
                if (!process.WaitForExit(15000))
                    throw new IOException("请在系统托盘退出 TimeTip，然后重新运行安装程序。");
        }
        finally
        {
            foreach (var process in processes)
                process.Dispose();
        }
    }

    private static string ReadMessage(NamedPipeClientStream pipe)
    {
        byte[] buffer = new byte[64];
        var pending = pipe.BeginRead(buffer, 0, buffer.Length, null, null);
        using (var ready = pending.AsyncWaitHandle)
        {
            if (!ready.WaitOne(1500))
                throw new TimeoutException();
            return Encoding.ASCII.GetString(buffer, 0, pipe.EndRead(pending)).Trim();
        }
    }

    private static void CreateDesktopShortcut(string executable)
    {
        string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        dynamic shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
        try
        {
            dynamic shortcut = shell.CreateShortcut(Path.Combine(desktop, "TimeTip.lnk"));
            try
            {
                shortcut.TargetPath = executable;
                shortcut.WorkingDirectory = Path.GetDirectoryName(executable);
                shortcut.Save();
            }
            finally { Marshal.FinalReleaseComObject(shortcut); }
        }
        finally { Marshal.FinalReleaseComObject(shell); }
    }
}
