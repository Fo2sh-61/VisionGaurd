// VisionGuard Control - the icon by the clock.
//
// It only watches and steers the two Windows services; closing the icon never
// stops VisionGuard. Built by the .NET Framework csc.exe that ships with
// Windows, so this file is C# 5: no $"", no ?., no nameof, no expression bodies.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.ServiceProcess;
using System.Threading;
using System.Windows.Forms;

namespace VisionGuardControl
{
    enum Kind { NotInstalled, Running, Starting, Stopping, NotAnswering, Stopped, Failed }

    // What one check found. Plain data, so the background thread can hand it over.
    class Snapshot
    {
        public Kind Kind;
        public string Text;
        public string Reason;      // set only when the engine left a failure note
        public bool EngineExists;
        public bool FrontExists;
        public bool AnyActive;     // some service is running or on its way up
        public bool AllRunning;
    }

    static class Program
    {
        [STAThread]
        static int Main(string[] args)
        {
            // `--check` prints what the icon would show, once, and exits 0 only
            // when VisionGuard is running. For support and for testing the
            // logic on a real machine without clicking anything.
            if (args.Length == 1 && args[0] == "--check")
            {
                Snapshot s = TrayApp.CheckOnce();
                Console.WriteLine(s.Text);
                return s.Kind == Kind.Running ? 0 : 1;
            }

            // `--qr <text> <png>` writes a QR code picture and exits 0. For tests.
            if (args.Length == 3 && args[0] == "--qr")
            {
                try
                {
                    using (Bitmap bmp = QrCode.Render(QrCode.Encode(args[1]), 8))
                    {
                        bmp.Save(args[2], System.Drawing.Imaging.ImageFormat.Png);
                    }
                    return 0;
                }
                catch (Exception ex)
                {
                    Console.Error.WriteLine("QR code could not be written: " + ex.Message);
                    return 1;
                }
            }

            // `--phone-address <engine.yaml>` prints the address the window would
            // show for phones, or "none". For tests.
            if (args.Length == 2 && args[0] == "--phone-address")
            {
                string address = ControlWindow.PhoneAddressFrom(File.ReadAllLines(args[1]));
                Console.WriteLine(address ?? "none");
                return address != null ? 0 : 1;
            }

            // `--task-state` prints what the window would say about the startup
            // task: set-up, missing, or unknown (Windows would not say).
            if (args.Length == 1 && args[0] == "--task-state")
            {
                int state = ControlWindow.TaskExists();
                Console.WriteLine(state == 1 ? "set-up" : state == 0 ? "missing" : "unknown");
                return state == 1 ? 0 : 1;
            }

            bool trayOnly = false;
            foreach (string a in args)
            {
                if (a == "--tray") trayOnly = true;
            }

            // One icon per Windows session. The event is made before the mutex, so
            // whoever finds the mutex taken can rely on the event existing.
            EventWaitHandle show = new EventWaitHandle(false, EventResetMode.AutoReset, "Local\\VisionGuardControlShow");
            bool created;
            using (Mutex single = new Mutex(true, "Local\\VisionGuardControl", out created))
            {
                if (!created)
                {
                    // Already running: bring its window forward (unless this is
                    // the sign-in start, which wants no window), then leave.
                    if (!trayOnly) show.Set();
                    return 0;
                }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                using (TrayApp app = new TrayApp())
                {
                    Thread waiter = new Thread(delegate()
                    {
                        while (show.WaitOne()) app.ShowWindowSoon();
                    });
                    waiter.IsBackground = true;
                    waiter.Start();
                    if (!trayOnly) app.ShowWindowSoon();
                    Application.Run();
                }
                GC.KeepAlive(single);
            }
            return 0;
        }
    }

    class TrayApp : IDisposable
    {
        const string EngineService = "visionguard-engine";
        const string FrontService = "visionguard-front";
        const string HealthUrl = "https://localhost/healthz";
        const string ConsoleUrl = "https://localhost/";
        const string LogsDir = @"C:\VisionGuard\logs";
        const string ConsoleShortcut = @"C:\Users\Public\Desktop\VisionGuard.lnk";
        const string FailureFile = @"C:\VisionGuard\logs\start-failure.txt";
        static readonly TimeSpan StartingGrace = TimeSpan.FromMinutes(3);

        [DllImport("user32.dll", SetLastError = true)]
        static extern bool DestroyIcon(IntPtr handle);

        // Results from the background checks come back to the UI thread through
        // this. Not the menu: a ContextMenuStrip has no window until it is first
        // shown, so its BeginInvoke threw and the icon sat on "checking..." until
        // someone opened the menu.
        readonly Control ui = new Control();
        readonly NotifyIcon tray = new NotifyIcon();
        readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
        readonly ContextMenuStrip menu = new ContextMenuStrip();
        readonly ToolStripMenuItem statusItem = new ToolStripMenuItem();
        readonly ToolStripMenuItem controlItem = new ToolStripMenuItem("Open VisionGuard Control");
        readonly ToolStripMenuItem openItem = new ToolStripMenuItem("Open VisionGuard");
        readonly ToolStripMenuItem startItem = new ToolStripMenuItem("Start");
        readonly ToolStripMenuItem stopItem = new ToolStripMenuItem("Stop");
        readonly ToolStripMenuItem restartItem = new ToolStripMenuItem("Restart");
        readonly ToolStripMenuItem logsItem = new ToolStripMenuItem("Open logs folder");
        readonly ToolStripMenuItem hideItem = new ToolStripMenuItem("Hide this icon (VisionGuard keeps running)");

        readonly Icon baseIcon;
        ControlWindow window;
        Icon currentIcon;
        Color currentDot = Color.Empty;

        volatile bool checking;
        volatile bool acting;                     // Start / Stop / Restart in progress
        DateTime quietUntil = DateTime.MinValue;  // stops we caused ourselves are not news
        DateTime? startingSince;                  // both running, healthz silent since then
        bool wasRunning;                          // seen running since the last stop

        public TrayApp()
        {
            IntPtr made = ui.Handle;                  // create the window now, before any check
            GC.KeepAlive(made);
            Icon own = null;
            try { own = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch (Exception) { }
            baseIcon = own != null ? own : SystemIcons.Application;

            statusItem.Enabled = false;
            window = new ControlWindow(this, baseIcon);
            controlItem.Font = new Font(controlItem.Font, FontStyle.Bold);
            controlItem.Click += delegate { ShowWindow(); };
            openItem.Click += delegate { OpenConsole(); };
            startItem.Click += delegate { RunAction("start"); };
            stopItem.Click += delegate { RunAction("stop"); };
            restartItem.Click += delegate { RunAction("restart"); };
            logsItem.Click += delegate { OpenLogs(); };
            hideItem.Click += delegate { Application.Exit(); };

            menu.Items.Add(statusItem);
            menu.Items.Add(controlItem);
            menu.Items.Add(openItem);
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(startItem);
            menu.Items.Add(stopItem);
            menu.Items.Add(restartItem);
            menu.Items.Add(logsItem);
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(hideItem);
            startItem.Enabled = stopItem.Enabled = restartItem.Enabled = false;

            tray.ContextMenuStrip = menu;
            tray.DoubleClick += delegate { ShowWindow(); };
            SetStatus(new Snapshot { Kind = Kind.Starting, Text = "VisionGuard: checking..." });
            tray.Visible = true;

            timer.Interval = 3000;
            timer.Tick += delegate { Poll(); };
            timer.Start();
            Poll();
        }

        public void Dispose()
        {
            timer.Stop();
            timer.Dispose();
            tray.Visible = false;
            tray.Dispose();
            menu.Dispose();
            if (window != null) window.Dispose();
            ui.Dispose();
            ReplaceIcon(null);
        }

        // Safe from any thread: the second start signals, a background thread calls this.
        public void ShowWindowSoon()
        {
            try { ui.BeginInvoke(new MethodInvoker(ShowWindow)); }
            catch (Exception) { /* the app is closing */ }
        }

        void ShowWindow()
        {
            if (window == null) return;
            if (!window.Visible) window.Show();
            if (window.WindowState == FormWindowState.Minimized) window.WindowState = FormWindowState.Normal;
            window.Activate();
            window.BringToFront();
        }

        public static Snapshot CheckOnce()
        {
            try { return new TrayApp(false).Check(); }
            catch (Exception ex)
            {
                return new Snapshot { Kind = Kind.Failed, Text = "VisionGuard status could not be read: " + ex.Message };
            }
        }

        // For CheckOnce: no icon, no timer, no window.
        TrayApp(bool showIcon)
        {
            baseIcon = SystemIcons.Application;
        }

        // ---- checking -------------------------------------------------------

        void Poll()
        {
            if (checking) return;       // the last check is still waiting on the network
            checking = true;
            ThreadPool.QueueUserWorkItem(delegate
            {
                Snapshot snap;
                try { snap = Check(); }
                catch (Exception ex)
                {
                    snap = new Snapshot { Kind = Kind.Failed, Text = "VisionGuard status could not be read: " + ex.Message };
                }
                try { ui.BeginInvoke(new MethodInvoker(delegate { checking = false; Apply(snap); })); }
                catch (Exception) { checking = false; /* the icon is closing */ }
            });
        }

        static ServiceControllerStatus? Read(string name)
        {
            try
            {
                using (ServiceController sc = new ServiceController(name))
                {
                    return sc.Status;   // throws when the service does not exist
                }
            }
            catch (InvalidOperationException) { return null; }
        }

        Snapshot Check()
        {
            ServiceControllerStatus? engine = Read(EngineService);
            ServiceControllerStatus? front = Read(FrontService);
            Snapshot s = new Snapshot();
            s.EngineExists = engine.HasValue;
            s.FrontExists = front.HasValue;

            if (!engine.HasValue || !front.HasValue)
            {
                s.Kind = Kind.NotInstalled;
                s.Text = "VisionGuard is not installed";
                return s;
            }

            bool engineUp = engine.Value == ServiceControllerStatus.Running;
            bool frontUp = front.Value == ServiceControllerStatus.Running;
            s.AllRunning = engineUp && frontUp;
            s.AnyActive = engine.Value != ServiceControllerStatus.Stopped || front.Value != ServiceControllerStatus.Stopped;

            if (engineUp && frontUp)
            {
                if (HealthAnswers())
                {
                    startingSince = null;
                    s.Kind = Kind.Running;
                    s.Text = "VisionGuard is running";
                }
                else
                {
                    if (!startingSince.HasValue) startingSince = DateTime.UtcNow;
                    if (DateTime.UtcNow - startingSince.Value > StartingGrace)
                    {
                        s.Kind = Kind.NotAnswering;
                        s.Text = "VisionGuard is running but not answering";
                    }
                    else
                    {
                        s.Kind = Kind.Starting;
                        s.Text = "VisionGuard is starting...";
                    }
                }
                return s;
            }

            startingSince = null;
            if (engine.Value == ServiceControllerStatus.StartPending || front.Value == ServiceControllerStatus.StartPending
                || engine.Value == ServiceControllerStatus.ContinuePending || front.Value == ServiceControllerStatus.ContinuePending)
            {
                s.Kind = Kind.Starting;
                s.Text = "VisionGuard is starting...";
            }
            else if (engine.Value == ServiceControllerStatus.StopPending || front.Value == ServiceControllerStatus.StopPending
                || engine.Value == ServiceControllerStatus.PausePending || front.Value == ServiceControllerStatus.PausePending)
            {
                s.Kind = Kind.Stopping;
                s.Text = "VisionGuard is stopping...";
            }
            else
            {
                bool engineStopped = engine.Value == ServiceControllerStatus.Stopped;
                bool frontStopped = front.Value == ServiceControllerStatus.Stopped;
                string why = engineStopped ? FailureReason() : null;
                if (why != null)
                {
                    s.Kind = Kind.Failed;
                    s.Reason = why;
                    s.Text = "VisionGuard stopped: " + why;
                }
                else if (engineStopped && frontStopped)
                {
                    s.Kind = Kind.Stopped;
                    s.Text = "VisionGuard is stopped";
                }
                // Half up is not "stopped" and not "running": say which half.
                else if (engineStopped)
                {
                    s.Kind = Kind.Failed;
                    s.Text = "VisionGuard's engine is stopped, so the console cannot work";
                }
                else if (frontStopped)
                {
                    s.Kind = Kind.Failed;
                    s.Text = "VisionGuard's web front is stopped, so the console cannot be reached";
                }
                else
                {
                    s.Kind = Kind.Failed;
                    s.Text = "VisionGuard is only partly running";
                }
            }
            return s;
        }

        // Rule 8: a start that failed must say so here, not only in the log.
        static string FailureReason()
        {
            try
            {
                if (!File.Exists(FailureFile)) return null;
                using (StreamReader r = new StreamReader(FailureFile))
                {
                    string line;
                    while ((line = r.ReadLine()) != null)
                    {
                        line = line.Trim();
                        if (line.Length == 0) continue;
                        return line.Length > 120 ? line.Substring(0, 117) + "..." : line;
                    }
                }
            }
            catch (Exception) { }
            return null;
        }

        // The site certificate is trusted by the machine, so no check is switched off.
        static bool HealthAnswers()
        {
            try
            {
                ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
                HttpWebRequest req = (HttpWebRequest)WebRequest.Create(HealthUrl);
                req.Timeout = 3000;
                req.ReadWriteTimeout = 3000;
                req.Proxy = null;
                using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                {
                    return resp.StatusCode == HttpStatusCode.OK;
                }
            }
            catch (Exception) { return false; }
        }

        // ---- showing --------------------------------------------------------

        void Apply(Snapshot s)
        {
            // Remembered until it is down, so a crash that passes through
            // "stopping" between two checks is still news.
            bool dropped = false;
            if (s.Kind == Kind.Running) wasRunning = true;
            else if (s.Kind == Kind.Stopped || s.Kind == Kind.Failed || s.Kind == Kind.NotInstalled)
            {
                dropped = wasRunning && s.Kind != Kind.NotInstalled
                    && !acting && DateTime.UtcNow > quietUntil;
                wasRunning = false;
            }

            SetStatus(s);

            bool busy = acting;
            bool installed = s.EngineExists && s.FrontExists;
            bool pending = s.Kind == Kind.Stopping || (s.Kind == Kind.Starting && !s.AllRunning);
            startItem.Enabled = installed && !busy && !s.AllRunning && !pending;
            stopItem.Enabled = installed && !busy && s.AnyActive;
            restartItem.Enabled = installed && !busy && s.AnyActive && !pending;
            openItem.Enabled = installed;
            window.ShowStatus(s, startItem.Enabled, stopItem.Enabled, restartItem.Enabled);
            if (busy) window.SetBusy();

            if (dropped)
            {
                string body = s.Reason != null ? s.Reason : "It stopped and nobody pressed Stop.";
                Balloon("VisionGuard stopped", body, ToolTipIcon.Error);
            }
        }

        void SetStatus(Snapshot s)
        {
            statusItem.Text = s.Text.Length > 200 ? s.Text.Substring(0, 197) + "..." : s.Text;
            string tip = s.Text;
            if (tip.Length > 63) tip = tip.Substring(0, 60) + "...";   // NotifyIcon.Text throws past 63
            tray.Text = tip;

            Color dot = DotColor(s.Kind);
            if (dot != currentDot)
            {
                currentDot = dot;
                ReplaceIcon(MakeIcon(dot));
            }
        }

        public static Color DotColor(Kind kind)
        {
            switch (kind)
            {
                case Kind.Running: return Color.FromArgb(34, 160, 60);
                case Kind.Starting:
                case Kind.Stopping: return Color.FromArgb(240, 170, 0);
                case Kind.NotInstalled: return Color.FromArgb(140, 140, 140);
                default: return Color.FromArgb(215, 40, 40);
            }
        }

        Icon MakeIcon(Color dot)
        {
            using (Bitmap bmp = new Bitmap(32, 32))
            {
                using (Graphics g = Graphics.FromImage(bmp))
                {
                    g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                    using (Icon big = new Icon(baseIcon, 32, 32))
                    {
                        g.DrawIcon(big, new Rectangle(0, 0, 32, 32));
                    }
                    // white rim so the dot reads on light and dark taskbars
                    g.FillEllipse(Brushes.White, 15, 15, 17, 17);
                    using (SolidBrush b = new SolidBrush(dot))
                    {
                        g.FillEllipse(b, 17, 17, 13, 13);
                    }
                }
                IntPtr h = bmp.GetHicon();
                try
                {
                    using (Icon tmp = Icon.FromHandle(h))
                    {
                        return (Icon)tmp.Clone();
                    }
                }
                finally { DestroyIcon(h); }
            }
        }

        void ReplaceIcon(Icon next)
        {
            Icon old = currentIcon;
            currentIcon = next;
            if (next != null) tray.Icon = next;
            if (old != null) old.Dispose();
        }

        void Balloon(string title, string body, ToolTipIcon icon)
        {
            tray.BalloonTipTitle = title;
            tray.BalloonTipText = body;
            tray.BalloonTipIcon = icon;
            tray.ShowBalloonTip(8000);
        }

        // ---- doing ----------------------------------------------------------

        public void RunAction(string what)
        {
            if (acting) return;
            acting = true;
            startItem.Enabled = stopItem.Enabled = restartItem.Enabled = false;
            window.SetBusy();
            ThreadPool.QueueUserWorkItem(delegate
            {
                string problem = null;
                try
                {
                    if (what == "stop" || what == "restart") StopAll();
                    if (what == "start" || what == "restart") StartAll();
                }
                catch (Exception ex)
                {
                    problem = Explain(ex, what);
                }
                finally
                {
                    quietUntil = DateTime.UtcNow.AddSeconds(15);
                    acting = false;
                }
                try
                {
                    ui.BeginInvoke(new MethodInvoker(delegate
                    {
                        Poll();   // the next check shows the truth, whatever happened
                        if (problem == null) return;
                        // Someone looking at the window gets the words there; otherwise a notice.
                        if (window.Visible) MessageBox.Show(window, problem, "VisionGuard Control");
                        else Balloon("VisionGuard", problem, ToolTipIcon.Warning);
                    }));
                }
                catch (Exception) { }
            });
        }

        static void StartAll()
        {
            Wait(EngineService, true);
            Wait(FrontService, true);
        }

        // front first: nobody should reach a half-stopped engine
        static void StopAll()
        {
            Wait(FrontService, false);
            Wait(EngineService, false);
        }

        static void Wait(string name, bool start)
        {
            using (ServiceController sc = new ServiceController(name))
            {
                sc.Refresh();
                if (start)
                {
                    if (sc.Status == ServiceControllerStatus.Running) return;
                    if (sc.Status != ServiceControllerStatus.StartPending) sc.Start();
                    sc.WaitForStatus(ServiceControllerStatus.Running, TimeSpan.FromSeconds(60));
                }
                else
                {
                    if (sc.Status == ServiceControllerStatus.Stopped) return;
                    if (sc.Status != ServiceControllerStatus.StopPending) sc.Stop();
                    sc.WaitForStatus(ServiceControllerStatus.Stopped, TimeSpan.FromSeconds(60));
                }
            }
        }

        static string Explain(Exception ex, string what)
        {
            Exception cur = ex;
            while (cur != null)
            {
                System.ComponentModel.Win32Exception w = cur as System.ComponentModel.Win32Exception;
                if (w != null && w.NativeErrorCode == 5)
                    return "Windows did not allow this account to " + what + " VisionGuard.";
                cur = cur.InnerException;
            }
            if (ex is System.ServiceProcess.TimeoutException)
                return "VisionGuard did not finish trying to " + what + " within a minute. The icon shows where it stands.";
            return "VisionGuard could not be asked to " + what + ": " + ex.Message;
        }

        // ---- opening --------------------------------------------------------

        public void OpenConsole()
        {
            // The desktop shortcut is what a person double-clicks, so use it when it is there.
            if (File.Exists(ConsoleShortcut))
            {
                try
                {
                    Process.Start(new ProcessStartInfo(ConsoleShortcut) { UseShellExecute = true });
                    return;
                }
                catch (Exception) { /* fall through to the Edge window */ }
            }
            string edge = null;
            string[] roots = new string[]
            {
                Environment.GetEnvironmentVariable("ProgramFiles(x86)"),
                Environment.GetEnvironmentVariable("ProgramFiles")
            };
            foreach (string root in roots)
            {
                if (string.IsNullOrEmpty(root)) continue;
                string p = Path.Combine(root, @"Microsoft\Edge\Application\msedge.exe");
                if (File.Exists(p)) { edge = p; break; }
            }
            try
            {
                if (edge != null) Process.Start(edge, "--app=" + ConsoleUrl);
                else Process.Start(new ProcessStartInfo(ConsoleUrl) { UseShellExecute = true });
            }
            catch (Exception ex)
            {
                Balloon("VisionGuard", "The console could not be opened: " + ex.Message, ToolTipIcon.Warning);
            }
        }

        public void OpenLogs()
        {
            try
            {
                if (!Directory.Exists(LogsDir)) Directory.CreateDirectory(LogsDir);
                Process.Start("explorer.exe", "\"" + LogsDir + "\"");
            }
            catch (Exception ex)
            {
                Balloon("VisionGuard", "The logs folder could not be opened: " + ex.Message, ToolTipIcon.Warning);
            }
        }
    }
}
