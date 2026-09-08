using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.IO.Pipes;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("TimeTip Setup")]
[assembly: AssemblyVersion("1.1.0.0")]
[assembly: AssemblyFileVersion("1.1.0.0")]

class TimeTipInstaller
{
    [STAThread]
    static int Main()
    {
        using (var guard = new Mutex(false, "Local\\TimeTip.Installer"))
        {
        bool owns;
        try { owns = guard.WaitOne(0); }
        catch (AbandonedMutexException) { owns = true; }
        if (!owns)
        {
            MessageBox.Show("已有一个 TimeTip 安装程序在运行。", "TimeTip");
            return 2;
        }
        try
        {
            Install(Process.GetCurrentProcess().MainModule.FileName,
                    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TimeTip"),
                    true, true);
            return 0;
        }
        catch (Exception error)
        {
            MessageBox.Show("安装未完成。原有设置不会被删除。\n\n" + error.Message,
                            "TimeTip", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        finally { guard.ReleaseMutex(); }
        }
    }

    internal static void Install(string self, string appDir, bool shortcuts, bool launch, string channel = "TimeTip.SingleInstance",
                                 Action<string, string> move = null)
    {
        move = move ?? Move;
        appDir = Path.GetFullPath(appDir);
        Directory.CreateDirectory(appDir);
        string work = Path.Combine(appDir, ".update-" + Guid.NewGuid().ToString("N"));
        string staged = Path.Combine(work, "app");
        string backup = Path.Combine(work, "previous");
        string archive = Path.Combine(work, "payload.zip");
        Directory.CreateDirectory(staged);
        Directory.CreateDirectory(backup);
        bool preserveRecovery = false;
        try
        {
            ExtractPayload(self, archive);
            ExtractArchive(archive, staged);
            if (!File.Exists(Path.Combine(staged, "TimeTip.exe")) || !Directory.Exists(Path.Combine(staged, "_internal")))
                throw new Exception("安装包缺少程序或运行库，请重新打包。");
            string installed = Path.Combine(appDir, "TimeTip.exe");
            StopInstalled(installed, channel);
            var saved = new List<string>();
            var replaced = new List<string>();
            try
            {
                foreach (string name in new string[] { "TimeTip.exe", "_internal" })
                {
                    string oldPath = Path.Combine(appDir, name);
                    if (File.Exists(oldPath) || Directory.Exists(oldPath))
                    {
                        move(oldPath, Path.Combine(backup, name));
                        saved.Add(name);
                    }
                    move(Path.Combine(staged, name), oldPath);
                    replaced.Add(name);
                }
            }
            catch
            {
                preserveRecovery = true;
                foreach (string name in replaced) DeleteKnownPath(appDir, Path.Combine(appDir, name));
                foreach (string name in saved) Move(Path.Combine(backup, name), Path.Combine(appDir, name));
                preserveRecovery = false;
                throw;
            }
            if (shortcuts) CreateShortcut(installed, appDir);
            if (launch) Process.Start(new ProcessStartInfo(installed) { WorkingDirectory = appDir, UseShellExecute = true });
        }
        finally
        {
            if (!preserveRecovery) DeleteKnownPath(appDir, work);
        }
    }

    internal static void ExtractPayload(string package, string destination)
    {
        using (FileStream fs = File.OpenRead(package))
        {
            if (fs.Length < 112) throw new Exception("安装包不完整。");
            fs.Seek(-48, SeekOrigin.End);
            byte[] trailer = new byte[48];
            if (fs.Read(trailer, 0, 48) != 48 || Encoding.ASCII.GetString(trailer, 0, 8) != "TTIPZIP2")
                throw new Exception("安装包格式不正确。");
            long length = BitConverter.ToInt64(trailer, 8);
            if (length <= 0 || length > fs.Length - 112) throw new Exception("安装包长度不正确。");
            fs.Seek(fs.Length - 48 - length, SeekOrigin.Begin);
            using (var hash = SHA256.Create())
            using (var output = File.Create(destination))
            {
                byte[] buffer = new byte[1024 * 1024];
                long remaining = length;
                while (remaining > 0)
                {
                    int read = fs.Read(buffer, 0, (int)Math.Min(buffer.Length, remaining));
                    if (read <= 0) throw new Exception("安装包读取失败。");
                    output.Write(buffer, 0, read);
                    hash.TransformBlock(buffer, 0, read, buffer, 0);
                    remaining -= read;
                }
                hash.TransformFinalBlock(new byte[0], 0, 0);
                for (int i = 0; i < 32; i++)
                    if (hash.Hash[i] != trailer[16 + i]) throw new Exception("安装包校验失败，请重新获取安装包。");
            }
        }
    }

    internal static void ExtractArchive(string archive, string destination)
    {
        using (var zip = ZipFile.OpenRead(archive))
        {
            long size = 0;
            foreach (var entry in zip.Entries)
            {
                size += entry.Length;
                if (size > 1024L * 1024 * 1024) throw new Exception("安装包解压后过大。");
                string target = Path.GetFullPath(Path.Combine(destination, entry.FullName.Replace('/', Path.DirectorySeparatorChar)));
                EnsureInside(destination, target);
                if (String.IsNullOrEmpty(entry.Name)) Directory.CreateDirectory(target);
                else
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    using (var input = entry.Open())
                    using (var output = File.Create(target)) input.CopyTo(output);
                }
            }
        }
    }

    static void StopInstalled(string installed, string channel)
    {
        var matches = new List<Process>();
        foreach (var process in Process.GetProcessesByName("TimeTip"))
        {
            bool match = false;
            try { match = String.Equals(Path.GetFullPath(process.MainModule.FileName), installed, StringComparison.OrdinalIgnoreCase); }
            catch (Exception) { }
            if (match) matches.Add(process); else process.Dispose();
        }
        if (matches.Count == 0) return;
        try
        {
            // Current releases save pending edits and exit through the IPC command.
            try
            {
                using (var pipe = new NamedPipeClientStream(".", channel, PipeDirection.InOut, PipeOptions.Asynchronous))
                {
                    pipe.Connect(500);
                    var greeting = new StringBuilder();
                    // The server is local and writes its PID immediately.
                    var buffer = new byte[64];
                    var read = pipe.BeginRead(buffer, 0, buffer.Length, null, null);
                    if (read.AsyncWaitHandle.WaitOne(1000))
                    {
                        int count = pipe.EndRead(read);
                        greeting.Append(Encoding.ASCII.GetString(buffer, 0, count));
                        int pid;
                        if (greeting.ToString().StartsWith("PID ") && Int32.TryParse(greeting.ToString().Substring(4).Trim(), out pid)
                            && matches.Exists(p => p.Id == pid))
                        {
                            byte[] command = Encoding.ASCII.GetBytes("QUIT\n");
                            pipe.Write(command, 0, command.Length);
                            pipe.Flush();
                        }
                    }
                }
            }
            catch (Exception) { }
            // Older versions close to the tray: closing first saves their current edits.
            foreach (var process in matches)
            {
                try { if (!process.HasExited) process.CloseMainWindow(); }
                catch (InvalidOperationException) { }
            }
            foreach (var process in matches)
            {
                if (process.HasExited) continue;
                if (process.WaitForExit(2400)) continue;
                process.Kill();
                process.WaitForExit(5000);
                if (!process.HasExited) throw new Exception("旧版 TimeTip 未退出，请从托盘退出后重试。");
            }
        }
        finally { foreach (var process in matches) process.Dispose(); }
    }

    static void Move(string source, string destination)
    {
        if (Directory.Exists(source)) Directory.Move(source, destination);
        else File.Move(source, destination);
    }

    static void EnsureInside(string root, string path)
    {
        string prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!Path.GetFullPath(path).StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            throw new Exception("无效的安装文件路径。");
    }

    static void DeleteKnownPath(string root, string path)
    {
        EnsureInside(root, path);
        if (Directory.Exists(path)) Directory.Delete(path, true);
        else if (File.Exists(path)) File.Delete(path);
    }

    static void CreateShortcut(string installed, string appDir)
    {
        Type shellType = Type.GetTypeFromProgID("WScript.Shell");
        object shell = Activator.CreateInstance(shellType);
        object shortcut = null;
        try
        {
            string path = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "TimeTip.lnk");
            shortcut = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
            Type type = shortcut.GetType();
            type.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { installed });
            type.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { appDir });
            type.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
        }
        finally
        {
            if (shortcut != null) System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shortcut);
            System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
        }
    }
}

