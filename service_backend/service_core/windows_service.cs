using System;
using System.IO;
using System.Diagnostics;
using System.ServiceProcess;
using System.Runtime.InteropServices;
using System.Threading;

public class TimeTipService : ServiceBase {
    private Process child;
    private volatile bool stopping;
    private readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    public TimeTipService(string name) { ServiceName = name; CanStop = true; AutoLog = true; }
    protected override void OnStart(string[] args) {
        stopping = false;
        child = new Process();
        child.StartInfo = new ProcessStartInfo(Path.Combine(root, "TimeTipCore.exe")) {
            WorkingDirectory = Directory.GetParent(root.TrimEnd(Path.DirectorySeparatorChar)).FullName,
            UseShellExecute = false, CreateNoWindow = true
        };
        child.EnableRaisingEvents = true;
        child.Exited += delegate { if (!stopping) { Environment.Exit(1); } };
        if (!child.Start()) throw new Exception("Failed to start TimeTipCore");
        Thread.Sleep(1200);
        if (child.HasExited) throw new Exception("Core exited during startup. Check ProgramData/logs/service.log.");
    }
    protected override void OnStop() {
        stopping = true;
        if (child != null) {
            if (!child.HasExited) { child.Kill(); child.WaitForExit(20000); }
            child.Dispose();
            child = null;
        }
    }

    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr OpenSCManager(string machine, string database, uint access);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr OpenService(IntPtr manager, string name, uint access);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr CreateService(IntPtr manager, string name, string display, uint access, uint type, uint start, uint error, string binary, string group, IntPtr tag, string deps, string account, string password);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool ChangeServiceConfig(IntPtr service, uint type, uint start, uint error, string binary, string group, IntPtr tag, string deps, string account, string password, string display);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool DeleteService(IntPtr service);
    [DllImport("advapi32.dll")] static extern bool CloseServiceHandle(IntPtr handle);
    static void Fail() { throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); }
    static void Install(string name) {
        IntPtr manager = OpenSCManager(null, null, 0xF003F);
        if (manager == IntPtr.Zero) Fail();
        IntPtr service = IntPtr.Zero;
        string binary = "\"" + Process.GetCurrentProcess().MainModule.FileName + "\" --name " + name;
        try {
            service = OpenService(manager, name, 0xF01FF);
            if (service == IntPtr.Zero) {
                service = CreateService(manager, name, name == "TimeTipService" ? "Time-Tip Service" : name, 0xF01FF, 0x10, 2, 1, binary, null, IntPtr.Zero, null, null, null);
                if (service == IntPtr.Zero) Fail();
            } else if (!ChangeServiceConfig(service, 0xFFFFFFFF, 2, 1, binary, null, IntPtr.Zero, null, null, null, "Time-Tip Service")) Fail();
        } finally { if (service != IntPtr.Zero) CloseServiceHandle(service); CloseServiceHandle(manager); }
    }
    static bool Exists(string name) {
        foreach (ServiceController item in ServiceController.GetServices()) {
            using (item) { if (item.ServiceName == name) return true; }
        }
        return false;
    }
    static void Control(string name, bool start) {
        if (!Exists(name)) { if (!start) return; throw new Exception("Service is not installed"); }
        using (ServiceController controller = new ServiceController(name)) {
            controller.Refresh();
            if (start) {
                if (controller.Status == ServiceControllerStatus.StopPending) controller.WaitForStatus(ServiceControllerStatus.Stopped, TimeSpan.FromSeconds(30));
                if (controller.Status != ServiceControllerStatus.Running) { controller.Start(); controller.WaitForStatus(ServiceControllerStatus.Running, TimeSpan.FromSeconds(30)); }
            } else if (controller.Status != ServiceControllerStatus.Stopped) {
                if (controller.Status != ServiceControllerStatus.StopPending) controller.Stop();
                controller.WaitForStatus(ServiceControllerStatus.Stopped, TimeSpan.FromSeconds(30));
            }
        }
    }
    static void Remove(string name) {
        Control(name, false);
        IntPtr manager = OpenSCManager(null, null, 0xF003F);
        if (manager == IntPtr.Zero) Fail();
        IntPtr service = OpenService(manager, name, 0xF01FF);
        try { if (service != IntPtr.Zero && !DeleteService(service)) Fail(); }
        finally { if (service != IntPtr.Zero) CloseServiceHandle(service); CloseServiceHandle(manager); }
    }
    public static int Main(string[] args) {
        string name = "TimeTipService";
        string command = "";
        for (int i = 0; i < args.Length; i++) {
            if (args[i] == "--name" && i + 1 < args.Length) name = args[++i];
            else command = args[i];
        }
        try {
            if (command == "install") Install(name);
            else if (command == "uninstall") Remove(name);
            else if (command == "start") Control(name, true);
            else if (command == "stop") Control(name, false);
            else if (command == "restart") { Control(name, false); Control(name, true); }
            else if (command == "--console") {
                var service = new TimeTipService(name);
                service.OnStart(new string[0]);
                Console.CancelKeyPress += delegate(object sender, ConsoleCancelEventArgs e) { service.OnStop(); };
                Console.ReadLine();
                service.OnStop();
            } else ServiceBase.Run(new TimeTipService(name));
            return 0;
        } catch (Exception ex) { Console.Error.WriteLine(ex.ToString()); return 1; }
    }
}
