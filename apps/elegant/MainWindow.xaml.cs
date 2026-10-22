using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Diagnostics;
using System.Threading;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;

namespace AutoClickerPro
{
    public partial class MainWindow : Window
    {
        const int WM_HOTKEY = 0x0312;
        const int HOTKEY_ID = 9001;

        [DllImport("user32.dll")] static extern bool RegisterHotKey(IntPtr h, int id, uint mods, uint vk);
        [DllImport("user32.dll")] static extern bool UnregisterHotKey(IntPtr h, int id);
        [DllImport("user32.dll")] static extern bool GetCursorPos(out EnginePoint p);

        [StructLayout(LayoutKind.Sequential)]
        struct EnginePoint { public int X, Y; }

        readonly ClickEngine _engine = new ClickEngine();
        HwndSource _source;
        System.Windows.Forms.NotifyIcon _tray;
        DispatcherTimer _countdown;
        DispatcherTimer _pickTimer;
        int _pickTicks;
        int _hotkeyVk = 0x75; // F6
        bool _capturing;
        bool _trayHintShown;
        bool _closing;
        long _lastTickUi;
        readonly Stopwatch _uiClock = Stopwatch.StartNew();

        public MainWindow()
        {
            InitializeComponent();
            Loaded += (s, e) =>
            {
                var fade = new DoubleAnimation(0, 1, new Duration(TimeSpan.FromMilliseconds(220)));
                BeginAnimation(OpacityProperty, fade);
                InitHotkey();
                InitTray();
                LoadConfig();
                ApplyHotkeyChip();
            };
            _engine.Tick += Engine_Tick;
            _engine.Stopped += Engine_Stopped;
            Closed += (s, e) => Cleanup();
            StateChanged += (s, e) => { if (WindowState == WindowState.Minimized) HideToTray(); };
        }

        // ---------- 生命周期 / 托盘 ----------

        void InitTray()
        {
            _tray = new System.Windows.Forms.NotifyIcon
            {
                Text = "连点器 Pro",
                Visible = true
            };
            try
            {
                _tray.Icon = System.Drawing.Icon.ExtractAssociatedIcon(
                    System.Reflection.Assembly.GetExecutingAssembly().Location);
            }
            catch { /* 图标提取失败不影响运行 */ }

            var menu = new System.Windows.Forms.ContextMenuStrip();
            menu.Items.Add("显示主窗口", null, (s, e) => ShowUp());
            menu.Items.Add("开始 / 停止", null, (s, e) => Dispatcher.BeginInvoke(new Action(ToggleStart)));
            menu.Items.Add(new System.Windows.Forms.ToolStripSeparator());
            menu.Items.Add("退出", null, (s, e) => Dispatcher.BeginInvoke(new Action(ExitApp)));
            _tray.ContextMenuStrip = menu;
            _tray.DoubleClick += (s, e) => ShowUp();
        }

        void ShowUp()
        {
            Dispatcher.BeginInvoke(new Action(() =>
            {
                Show();
                WindowState = WindowState.Normal;
                Activate();
            }));
        }

        void HideToTray()
        {
            Hide();
            if (!_trayHintShown && _tray != null)
            {
                _tray.ShowBalloonTip(1500, "连点器 Pro", "已最小化到托盘，双击图标可再次打开。", System.Windows.Forms.ToolTipIcon.Info);
                _trayHintShown = true;
            }
        }

        void ExitApp()
        {
            _closing = true;
            Close();
        }

        void Cleanup()
        {
            _engine.Stop();
            _engine.WaitForExit();
            if (_source != null) UnregisterHotKey(_source.Handle, HOTKEY_ID);
            if (_tray != null) { _tray.Visible = false; _tray.Dispose(); }
            if (!_closing) Application.Current.Shutdown();
            else Application.Current.Shutdown();
        }

        // ---------- 标题栏 ----------

        void TitleBar_MouseLeftButtonDown(object sender, System.Windows.Input.MouseButtonEventArgs e)
        {
            if (e.ClickCount == 1) DragMove();
        }

        void MinBtn_Click(object sender, RoutedEventArgs e) => HideToTray();

        void CloseBtn_Click(object sender, RoutedEventArgs e) => HideToTray();

        void PinBtn_Click(object sender, RoutedEventArgs e) => Topmost = PinBtn.IsChecked == true;

        // ---------- 分段控件 ----------

        void BtnSide_Click(object sender, RoutedEventArgs e)
        {
            var b = (System.Windows.Controls.Primitives.ToggleButton)sender;
            BtnLeft.IsChecked = b == BtnLeft;
            BtnRight.IsChecked = b == BtnRight;
            BtnMiddle.IsChecked = b == BtnMiddle;
            SaveConfig();
        }

        void ModeBtn_Click(object sender, RoutedEventArgs e)
        {
            var b = (System.Windows.Controls.Primitives.ToggleButton)sender;
            ModeSingle.IsChecked = b == ModeSingle;
            ModeDouble.IsChecked = b == ModeDouble;
            ModeHold.IsChecked = b == ModeHold;
            RefreshPosUi();
            SaveConfig();
        }

        void PosBtn_Click(object sender, RoutedEventArgs e)
        {
            var b = (System.Windows.Controls.Primitives.ToggleButton)sender;
            PosFollow.IsChecked = b == PosFollow;
            PosFixed.IsChecked = b == PosFixed;
            PosMulti.IsChecked = b == PosMulti;
            RefreshPosUi();
            SaveConfig();
        }

        // ---------- 热键 ----------

        void InitHotkey()
        {
            _source = HwndSource.FromHwnd(new WindowInteropHelper(this).Handle);
            _source.AddHook(WndProc);
        }

        IntPtr WndProc(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
        {
            if (msg == WM_HOTKEY && wParam.ToInt32() == HOTKEY_ID)
            {
                Dispatcher.BeginInvoke(new Action(ToggleStart));
                handled = true;
            }
            return IntPtr.Zero;
        }

        bool RegisterCurrentHotkey()
        {
            if (_source == null) return false;
            UnregisterHotKey(_source.Handle, HOTKEY_ID);
            return RegisterHotKey(_source.Handle, HOTKEY_ID, 0, (uint)_hotkeyVk);
        }

        void ApplyHotkeyChip()
        {
            HotkeyText.Text = VkName(_hotkeyVk);
        }

        static string VkName(int vk)
        {
            if (vk >= 0x70 && vk <= 0x87) return "F" + (vk - 0x70 + 1);
            if (vk >= '0' && vk <= '9') return ((char)vk).ToString();
            if (vk >= 'A' && vk <= 'Z') return ((char)vk).ToString();
            switch (vk)
            {
                case 0x2D: return "Insert";
                case 0x2E: return "Delete";
                case 0x21: return "PgUp";
                case 0x22: return "PgDn";
                case 0x14: return "CapsLock";
                case 0x60: return "Num0"; case 0x61: return "Num1"; case 0x62: return "Num2";
                case 0x63: return "Num3"; case 0x64: return "Num4"; case 0x65: return "Num5";
                case 0x66: return "Num6"; case 0x67: return "Num7"; case 0x68: return "Num8";
                case 0x69: return "Num9";
            }
            return "0x" + vk.ToString("X2");
        }

        void HotkeyBtn_Click(object sender, RoutedEventArgs e)
        {
            if (_capturing) return;
            _capturing = true;
            HotkeyText.Text = "按键…";
            HotkeyText.Foreground = (Brush)FindResource("AccentBrush");
            StatusText.Text = "按下任意键作为热键，Esc 取消";
        }

        void Window_PreviewKeyDown(object sender, System.Windows.Input.KeyEventArgs e)
        {
            if (!_capturing) return;
            e.Handled = true;
            var k = e.Key == System.Windows.Input.Key.System ? e.SystemKey : e.Key;

            if (k == System.Windows.Input.Key.Escape)
            {
                EndCapture();
                return;
            }
            if (k == System.Windows.Input.Key.LeftCtrl || k == System.Windows.Input.Key.RightCtrl ||
                k == System.Windows.Input.Key.LeftShift || k == System.Windows.Input.Key.RightShift ||
                k == System.Windows.Input.Key.LeftAlt || k == System.Windows.Input.Key.RightAlt ||
                k == System.Windows.Input.Key.LWin || k == System.Windows.Input.Key.RWin)
                return;

            int vk = System.Windows.Input.KeyInterop.VirtualKeyFromKey(k);
            if (vk <= 0) return;

            _hotkeyVk = vk;
            if (RegisterCurrentHotkey())
            {
                EndCapture();
                SaveConfig();
                StatusText.Text = "热键已更新";
            }
            else
            {
                HotkeyText.Text = "注册失败";
                StatusText.Text = "该按键被其他程序占用";
            }
        }

        void EndCapture()
        {
            _capturing = false;
            HotkeyText.Foreground = (Brush)FindResource("TextBrush");
            ApplyHotkeyChip();
        }

        // ---------- 启停 ----------

        void ToggleStart()
        {
            if (_engine.Running) { StopEngine("已停止"); return; }

            CollectConfig();
            SaveConfig();

            if (_engine.Config.CountdownSec > 0)
            {
                int left = _engine.Config.CountdownSec;
                StartBtn.IsEnabled = false;
                SetDot((Brush)FindResource("AccentBrush"), true);
                StatusText.Text = left + " 秒后开始…";
                _countdown = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
                _countdown.Tick += (s, e) =>
                {
                    left--;
                    if (left > 0) { StatusText.Text = left + " 秒后开始…"; return; }
                    _countdown.Stop();
                    StartBtn.IsEnabled = true;
                    BeginEngine();
                };
                _countdown.Start();
            }
            else
            {
                BeginEngine();
            }
        }

        void BeginEngine()
        {
            _engine.Start();
            StartBtn.Content = "停止点击";
            StartBtn.Background = (Brush)FindResource("DangerBrush");
            SetDot((Brush)FindResource("OkBrush"), true);
            StatusText.Text = "运行中 · " + HotkeyText.Text + " 停止";
        }

        void StopEngine(string statusText)
        {
            _engine.Stop();
            _engine.WaitForExit();
            if (_countdown != null) { _countdown.Stop(); StartBtn.IsEnabled = true; }
            StartBtn.Content = "开始点击";
            StartBtn.Background = (Brush)FindResource("AccentGradient");
            SetDot((Brush)FindResource("#5A5D66".ToBrush()), false);
            StatusText.Text = statusText;
            _lastTickUi = 0;
        }

        void StartBtn_Click(object sender, RoutedEventArgs e) => ToggleStart();

        void Engine_Tick(long count)
        {
            if (_uiClock.ElapsedMilliseconds - _lastTickUi < 100) return;
            _lastTickUi = _uiClock.ElapsedMilliseconds;
            Dispatcher.BeginInvoke(new Action(() =>
            {
                CountText.Text = count + " 次";
            }));
        }

        void Engine_Stopped()
        {
            Dispatcher.BeginInvoke(new Action(() =>
            {
                long final = _engine.Count;
                StopEngine("已停止");
                CountText.Text = final + " 次";
            }));
        }

        void SetDot(Brush brush, bool pulse)
        {
            StatusDot.Fill = brush;
            if (pulse)
            {
                var anim = new DoubleAnimation(1, 0.3, new Duration(TimeSpan.FromMilliseconds(650)))
                { AutoReverse = true, RepeatBehavior = RepeatBehavior.Forever };
                StatusDot.BeginAnimation(OpacityProperty, anim);
            }
            else
            {
                StatusDot.BeginAnimation(OpacityProperty, null);
                StatusDot.Opacity = 1;
            }
        }

        // ---------- UI <-> 配置 ----------

        void CollectConfig()
        {
            var c = _engine.Config;
            c.IntervalMs = Clamp(ParseInt(IntervalBox.Text, 100), 1, 60000);
            IntervalBox.Text = c.IntervalMs.ToString();
            c.JitterPercent = Clamp(ParseInt(JitterBox.Text, 0), 0, 90);
            c.Button = BtnRight.IsChecked == true ? MouseBtn.Right
                     : BtnMiddle.IsChecked == true ? MouseBtn.Middle : MouseBtn.Left;
            c.Mode = ModeDouble.IsChecked == true ? ClickMode.Double
                   : ModeHold.IsChecked == true ? ClickMode.Hold : ClickMode.Single;
            c.HoldMs = Clamp(ParseInt(HoldBox.Text, 200), 1, 10000);
            c.Position = PosFixed.IsChecked == true ? PosMode.Fixed
                       : PosMulti.IsChecked == true ? PosMode.Multi : PosMode.Follow;
            c.MaxCount = ParseLong(MaxCountBox.Text, 0);
            c.CountdownSec = Clamp((int)ParseLong(CountdownBox.Text, 0), 0, 3600);
        }

        void RefreshPosUi()
        {
            PosInfo.Text = _engine.Config.Position == PosMode.Fixed
                ? string.Format("固定坐标 ({0}, {1})", _engine.Config.FixedX, _engine.Config.FixedY)
                : _engine.Config.Position == PosMode.Multi
                    ? "多点循环 · " + _engine.Config.Points.Count + " 个坐标"
                    : "跟随当前鼠标位置";
            PickBtn.Visibility = PosFixed.IsChecked == true ? Visibility.Visible : Visibility.Collapsed;
            PointsBtn.Visibility = PosMulti.IsChecked == true ? Visibility.Visible : Visibility.Collapsed;
            HoldPanel.Visibility = ModeHold.IsChecked == true ? Visibility.Visible : Visibility.Collapsed;
        }

        // ---------- 位置拾取 ----------

        void PickBtn_Click(object sender, RoutedEventArgs e)
        {
            Hide();
            _pickTicks = 3;
            StatusText.Text = "3 秒后拾取鼠标位置…";
            _pickTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
            _pickTimer.Tick += (s, ev) =>
            {
                _pickTicks--;
                if (_pickTicks > 0)
                {
                    StatusText.Text = _pickTicks + " 秒后拾取鼠标位置…";
                    return;
                }
                _pickTimer.Stop();
                EnginePoint p;
                GetCursorPos(out p);
                _engine.Config.FixedX = p.X;
                _engine.Config.FixedY = p.Y;
                ShowUp();
                RefreshPosUi();
                SaveConfig();
                StatusText.Text = "已拾取坐标";
            };
            _pickTimer.Start();
        }

        void PointsBtn_Click(object sender, RoutedEventArgs e)
        {
            var win = new PointsWindow(_engine.Config.Points) { Owner = null, Topmost = true };
            win.ShowDialog();
            _engine.Config.Points = win.Result;
            RefreshPosUi();
            SaveConfig();
        }

        // ---------- 配置持久化 ----------

        string ConfigPath()
        {
            string dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "AutoClickerPro");
            Directory.CreateDirectory(dir);
            return Path.Combine(dir, "config.ini");
        }

        void SaveConfig()
        {
            CollectConfig();
            var c = _engine.Config;
            var sb = new StringBuilder();
            sb.AppendLine("interval=" + c.IntervalMs);
            sb.AppendLine("jitter=" + c.JitterPercent);
            sb.AppendLine("button=" + (int)c.Button);
            sb.AppendLine("mode=" + (int)c.Mode);
            sb.AppendLine("hold=" + c.HoldMs);
            sb.AppendLine("pos=" + (int)c.Position);
            sb.AppendLine("fx=" + c.FixedX);
            sb.AppendLine("fy=" + c.FixedY);
            var pts = new List<string>();
            foreach (var p in c.Points) pts.Add(p[0] + "," + p[1]);
            sb.AppendLine("points=" + string.Join(";", pts.ToArray()));
            sb.AppendLine("maxcount=" + c.MaxCount);
            sb.AppendLine("countdown=" + c.CountdownSec);
            sb.AppendLine("topmost=" + (Topmost ? 1 : 0));
            sb.AppendLine("hotkey=" + _hotkeyVk);
            File.WriteAllText(ConfigPath(), sb.ToString());
        }

        void LoadConfig()
        {
            string path = ConfigPath();
            if (!File.Exists(path)) return;
            var map = new Dictionary<string, string>();
            foreach (var line in File.ReadAllLines(path))
            {
                int i = line.IndexOf('=');
                if (i <= 0) continue;
                map[line.Substring(0, i).Trim()] = line.Substring(i + 1).Trim();
            }
            var c = _engine.Config;
            string v;
            if (map.TryGetValue("interval", out v)) c.IntervalMs = Clamp(ParseInt(v, 100), 1, 60000);
            if (map.TryGetValue("jitter", out v)) c.JitterPercent = Clamp(ParseInt(v, 0), 0, 90);
            if (map.TryGetValue("button", out v)) c.Button = (MouseBtn)ParseInt(v, 0);
            if (map.TryGetValue("mode", out v)) c.Mode = (ClickMode)ParseInt(v, 0);
            if (map.TryGetValue("hold", out v)) c.HoldMs = Clamp(ParseInt(v, 200), 1, 10000);
            if (map.TryGetValue("pos", out v)) c.Position = (PosMode)ParseInt(v, 0);
            if (map.TryGetValue("fx", out v)) c.FixedX = ParseInt(v, 0);
            if (map.TryGetValue("fy", out v)) c.FixedY = ParseInt(v, 0);
            if (map.TryGetValue("maxcount", out v)) c.MaxCount = ParseLong(v, 0);
            if (map.TryGetValue("countdown", out v)) c.CountdownSec = Clamp(ParseInt(v, 0), 0, 3600);
            if (map.TryGetValue("hotkey", out v)) _hotkeyVk = ParseInt(v, 0x75);

            c.Points.Clear();
            if (map.TryGetValue("points", out v) && v.Length > 0)
            {
                foreach (var seg in v.Split(';'))
                {
                    var xy = seg.Split(',');
                    if (xy.Length == 2)
                        c.Points.Add(new[] { ParseInt(xy[0], 0), ParseInt(xy[1], 0) });
                }
            }

            IntervalBox.Text = c.IntervalMs.ToString();
            JitterBox.Text = c.JitterPercent.ToString();
            HoldBox.Text = c.HoldMs.ToString();
            MaxCountBox.Text = c.MaxCount.ToString();
            CountdownBox.Text = c.CountdownSec.ToString();

            BtnLeft.IsChecked = c.Button == MouseBtn.Left;
            BtnRight.IsChecked = c.Button == MouseBtn.Right;
            BtnMiddle.IsChecked = c.Button == MouseBtn.Middle;
            ModeSingle.IsChecked = c.Mode == ClickMode.Single;
            ModeDouble.IsChecked = c.Mode == ClickMode.Double;
            ModeHold.IsChecked = c.Mode == ClickMode.Hold;
            PosFollow.IsChecked = c.Position == PosMode.Follow;
            PosFixed.IsChecked = c.Position == PosMode.Fixed;
            PosMulti.IsChecked = c.Position == PosMode.Multi;

            if (map.TryGetValue("topmost", out v) && v == "1") PinBtn.IsChecked = true;
            Topmost = PinBtn.IsChecked == true;
            RefreshPosUi();
        }

        // ---------- 工具 ----------

        static int ParseInt(string s, int def)
        {
            int r; return int.TryParse(s, out r) ? r : def;
        }

        static long ParseLong(string s, long def)
        {
            long r; return long.TryParse(s, out r) ? r : def;
        }

        static int Clamp(int v, int lo, int hi)
        {
            return v < lo ? lo : (v > hi ? hi : v);
        }
    }

    static class BrushExt
    {
        public static System.Windows.Media.Brush ToBrush(this string hex)
        {
            return (System.Windows.Media.Brush)new System.Windows.Media.BrushConverter().ConvertFromString(hex);
        }
    }
}
