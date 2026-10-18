// The VisionGuard Control window: a status light, Start / Stop, the
// start-with-the-PC switch, the phone address with its QR code, and the last
// problem. It does no work of its own: the buttons call the same code the icon's
// menu calls, and the icon's check feeds it. C# 5 only.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace VisionGuardControl
{
    // What the settings part of the window needs; read off the UI thread.
    class Settings
    {
        public bool AutoStartOn;
        public string AutoStartProblem;  // set when autostart.txt exists but could not be read
        public int TaskState;        // 1 = set up, 0 = missing, -1 = could not be asked
        public string PhoneAddress;  // null when engine.yaml names none
    }

    class ControlWindow : Form
    {
        public const string AutoStartFile = @"C:\VisionGuard\data\autostart.txt";
        public const string EngineYaml = @"C:\VisionGuard\data\engine.yaml";
        public const string TaskName = "VisionGuard start at boot";

        readonly TrayApp app;
        readonly Panel light = new Panel();
        readonly Label statusText = new Label();
        readonly Button mainButton = new Button();
        readonly Button restartButton = new Button();
        readonly CheckBox autoBox = new CheckBox();
        readonly Label autoNote = new Label();
        readonly Button openButton = new Button();
        readonly Label phoneText = new Label();
        readonly Button copyButton = new Button();
        readonly PictureBox qr = new PictureBox();
        readonly Label problemText = new Label();
        readonly Button logsButton = new Button();

        Color dot = Color.FromArgb(140, 140, 140);
        string mainMode = "start";        // what the big button does when pressed
        bool settingBox;                  // true while we move the checkbox ourselves
        string phoneAddress;
        volatile bool reading;

        public ControlWindow(TrayApp owner, Icon icon)
        {
            app = owner;
            Text = "VisionGuard Control";
            Icon = icon;
            Font = new Font("Segoe UI", 9F);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(480, 560);
            AutoScaleMode = AutoScaleMode.None;

            light.SetBounds(24, 20, 56, 56);
            light.Paint += delegate(object s, PaintEventArgs e)
            {
                e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                using (SolidBrush b = new SolidBrush(dot)) e.Graphics.FillEllipse(b, 2, 2, 52, 52);
            };
            statusText.SetBounds(96, 20, 360, 56);
            statusText.Font = new Font("Segoe UI", 12F, FontStyle.Bold);
            statusText.TextAlign = ContentAlignment.MiddleLeft;
            statusText.Text = "VisionGuard: checking...";

            mainButton.SetBounds(24, 92, 316, 48);
            mainButton.Font = new Font("Segoe UI", 12F, FontStyle.Bold);
            mainButton.Text = "Start VisionGuard";
            mainButton.Enabled = false;
            mainButton.Click += delegate { app.RunAction(mainMode); };
            restartButton.SetBounds(352, 92, 104, 48);
            restartButton.Text = "Restart";
            restartButton.Enabled = false;
            restartButton.Click += delegate { app.RunAction("restart"); };

            autoBox.SetBounds(24, 160, 432, 24);
            autoBox.Text = "Start automatically when the PC starts";
            autoBox.Enabled = false;
            autoBox.CheckedChanged += delegate { AutoBoxChanged(); };
            autoNote.SetBounds(44, 186, 412, 32);
            autoNote.ForeColor = Color.Gray;
            autoNote.Text = "Checking...";

            openButton.SetBounds(24, 228, 432, 40);
            openButton.Text = "Open VisionGuard";
            openButton.Click += delegate { app.OpenConsole(); };

            Controls.Add(Header("Phones", 284));
            phoneText.SetBounds(24, 308, 280, 76);
            phoneText.Text = "Checking...";
            copyButton.SetBounds(24, 390, 96, 30);
            copyButton.Text = "Copy";
            copyButton.Visible = false;
            copyButton.Click += delegate { CopyAddress(); };
            qr.SetBounds(316, 304, 140, 140);
            qr.SizeMode = PictureBoxSizeMode.Zoom;

            Controls.Add(Header("Problems", 458));
            problemText.SetBounds(24, 480, 432, 34);
            problemText.Text = "No problems reported.";
            logsButton.SetBounds(24, 518, 140, 30);
            logsButton.Text = "Open logs folder";
            logsButton.Click += delegate { app.OpenLogs(); };

            Controls.AddRange(new Control[]
            {
                light, statusText, mainButton, restartButton, autoBox, autoNote, openButton,
                phoneText, copyButton, qr, problemText, logsButton
            });

            // The X hides the window; the icon by the clock keeps VisionGuard in reach.
            FormClosing += delegate(object s, FormClosingEventArgs e)
            {
                if (e.CloseReason == CloseReason.UserClosing) { e.Cancel = true; Hide(); }
            };
            VisibleChanged += delegate { if (Visible) ReadSettings(); };
        }

        Label Header(string text, int y)
        {
            Label l = new Label();
            l.SetBounds(24, y, 432, 20);
            l.Text = text;
            l.Font = new Font("Segoe UI", 10F, FontStyle.Bold);
            return l;
        }

        // ---- fed by the icon's check ----------------------------------------

        public void ShowStatus(Snapshot s, bool canStart, bool canStop, bool canRestart)
        {
            dot = TrayApp.DotColor(s.Kind);
            light.Invalidate();
            statusText.Text = s.Text;

            bool stopMode = s.AnyActive;
            mainMode = stopMode ? "stop" : "start";
            mainButton.Text = stopMode ? "Stop VisionGuard" : "Start VisionGuard";
            mainButton.Enabled = stopMode ? canStop : canStart;
            restartButton.Enabled = canRestart;

            if (s.Reason != null) problemText.Text = s.Reason;
            else if (s.Kind == Kind.Failed || s.Kind == Kind.NotAnswering)
                problemText.Text = "No reason was written down. The logs folder may say more.";
            else if (s.Kind == Kind.NotInstalled) problemText.Text = "VisionGuard is not installed on this PC.";
            else problemText.Text = "No problems reported.";
        }

        public void SetBusy()
        {
            mainButton.Enabled = false;
            restartButton.Enabled = false;
        }

        // ---- settings -------------------------------------------------------

        // The first line, trimmed, "off" in any case means off. Anything else, or
        // no file, means on - the startup task reads it the same way. A file that
        // is there but cannot be read is reported, never shown as a quiet "on".
        public static bool ReadAutoStart(out string problem)
        {
            problem = null;
            try
            {
                if (!File.Exists(AutoStartFile)) return true;
                using (StreamReader r = new StreamReader(AutoStartFile))
                {
                    string line = r.ReadLine();
                    if (line != null && line.Trim().Equals("off", StringComparison.OrdinalIgnoreCase)) return false;
                }
            }
            catch (Exception ex) { problem = ex.Message; }
            return true;
        }

        void ReadSettings()
        {
            if (reading) return;
            reading = true;
            ThreadPool.QueueUserWorkItem(delegate
            {
                Settings st = new Settings();
                try
                {
                    st.AutoStartOn = ReadAutoStart(out st.AutoStartProblem);
                    st.TaskState = TaskExists();
                    st.PhoneAddress = ReadPhoneAddress();
                }
                catch (Exception) { }
                try
                {
                    BeginInvoke(new MethodInvoker(delegate { reading = false; ApplySettings(st); }));
                }
                catch (Exception) { reading = false; }
            });
        }

        void ApplySettings(Settings st)
        {
            settingBox = true;
            autoBox.Checked = st.AutoStartOn;
            settingBox = false;
            if (st.AutoStartProblem != null)
            {
                autoBox.Enabled = false;
                autoNote.ForeColor = Color.FromArgb(190, 30, 30);
                autoNote.Text = "The setting could not be read: " + st.AutoStartProblem;
            }
            else if (st.TaskState == 1)
            {
                autoBox.Enabled = true;
                autoNote.ForeColor = Color.Gray;
                autoNote.Text = "Takes effect the next time the PC starts.";
            }
            else
            {
                autoBox.Enabled = false;
                autoNote.ForeColor = Color.Gray;
                autoNote.Text = st.TaskState == 0
                    ? "Automatic start is not set up on this PC; run Setup again."
                    : "Windows would not say whether automatic start is set up on this PC.";
            }

            phoneAddress = st.PhoneAddress;
            Image old = qr.Image;
            qr.Image = null;
            if (old != null) old.Dispose();
            if (phoneAddress == null)
            {
                phoneText.Text = "No phone address is set (tls.names in C:\\VisionGuard\\data\\engine.yaml).";
                copyButton.Visible = false;
            }
            else
            {
                phoneText.Text = phoneAddress;
                copyButton.Visible = true;
                try
                {
                    bool[,] modules = QrCode.Encode(phoneAddress);
                    int px = Math.Max(2, 140 / QrCode.SideInModules(modules));
                    qr.Image = QrCode.Render(modules, px);
                }
                catch (Exception ex)
                {
                    phoneText.Text = phoneAddress + "\r\n(No QR code: " + ex.Message + ")";
                }
            }
        }

        void AutoBoxChanged()
        {
            if (settingBox) return;
            bool want = autoBox.Checked;
            try
            {
                File.WriteAllText(AutoStartFile, (want ? "on" : "off") + "\n");
                autoNote.ForeColor = Color.Gray;
                autoNote.Text = "Takes effect the next time the PC starts.";
            }
            catch (Exception ex)
            {
                settingBox = true;
                autoBox.Checked = !want;
                settingBox = false;
                autoNote.ForeColor = Color.FromArgb(190, 30, 30);
                autoNote.Text = "The setting could not be saved, so it is unchanged: " + ex.Message;
            }
        }

        // 1 = the startup task exists, 0 = it does not, -1 = could not ask.
        // Asked through the Task Scheduler itself, not schtasks.exe: schtasks
        // gives the same exit code for "no such task" and "not allowed to look",
        // and its words change with the Windows language. The error codes do not.
        public static int TaskExists()
        {
            object scheduler = null;
            try
            {
                Type kind = Type.GetTypeFromProgID("Schedule.Service");
                if (kind == null) return -1;
                scheduler = Activator.CreateInstance(kind);
                kind.InvokeMember("Connect", BindingFlags.InvokeMethod, null, scheduler, new object[0]);
                object folder = kind.InvokeMember("GetFolder", BindingFlags.InvokeMethod, null, scheduler, new object[] { "\\" });
                folder.GetType().InvokeMember("GetTask", BindingFlags.InvokeMethod, null, folder, new object[] { TaskName });
                return 1;
            }
            catch (TargetInvocationException ex)
            {
                // .NET hands 0x80070002 over as a FileNotFoundException, not a
                // COMException, so the code is read off whatever came back.
                const int NotFound = unchecked((int)0x80070002);
                return ex.InnerException != null
                    && Marshal.GetHRForException(ex.InnerException) == NotFound ? 0 : -1;
            }
            catch (Exception) { return -1; }
            finally
            {
                if (scheduler != null) { try { Marshal.ReleaseComObject(scheduler); } catch (Exception) { } }
            }
        }

        static string ReadPhoneAddress()
        {
            try
            {
                if (!File.Exists(EngineYaml)) return null;
                return PhoneAddressFrom(File.ReadAllLines(EngineYaml));
            }
            catch (Exception) { return null; }
        }

        // The first tls.names entry that is not 127.0.0.1 or localhost.
        public static string PhoneAddressFrom(string[] lines)
        {
            bool inTls = false;
            bool inNames = false;
            List<string> names = new List<string>();
            foreach (string raw in lines)
            {
                string line = raw;
                int hash = line.IndexOf('#');
                if (hash >= 0) line = line.Substring(0, hash);
                if (line.Trim().Length == 0) continue;
                bool indented = line.Length > 0 && (line[0] == ' ' || line[0] == '\t');
                string t = line.Trim();
                if (!indented)
                {
                    inTls = t == "tls:";
                    inNames = false;
                    continue;
                }
                if (!inTls) continue;
                if (t.StartsWith("names:"))
                {
                    inNames = true;
                    string rest = t.Substring(6).Trim();
                    if (rest.StartsWith("[")) rest = rest.Substring(1);
                    int close = rest.IndexOf(']');
                    if (close >= 0) rest = rest.Substring(0, close);
                    foreach (string part in rest.Split(','))
                    {
                        string n = part.Trim().Trim('"', '\'');
                        if (n.Length > 0) names.Add(n);
                    }
                }
                else if (inNames && t.StartsWith("-"))
                {
                    string n = t.Substring(1).Trim().Trim('"', '\'');
                    if (n.Length > 0) names.Add(n);
                }
                else inNames = false;
            }
            foreach (string n in names)
            {
                if (n == "127.0.0.1" || n.Equals("localhost", StringComparison.OrdinalIgnoreCase)) continue;
                return "https://" + n + ":8443/";
            }
            return null;
        }

        void CopyAddress()
        {
            try
            {
                Clipboard.SetText(phoneAddress);
                copyButton.Text = "Copied";
                System.Windows.Forms.Timer back = new System.Windows.Forms.Timer();
                back.Interval = 2000;
                back.Tick += delegate { back.Stop(); back.Dispose(); copyButton.Text = "Copy"; };
                back.Start();
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, "The address could not be copied: " + ex.Message, "VisionGuard Control");
            }
        }
    }
}
