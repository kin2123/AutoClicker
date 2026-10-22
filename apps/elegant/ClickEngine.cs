using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;

namespace AutoClickerPro
{
    public enum MouseBtn { Left, Right, Middle }
    public enum ClickMode { Single, Double, Hold }
    public enum PosMode { Follow, Fixed, Multi }

    public class ClickConfig
    {
        public int IntervalMs = 100;
        public int JitterPercent = 0;
        public MouseBtn Button = MouseBtn.Left;
        public ClickMode Mode = ClickMode.Single;
        public int HoldMs = 200;
        public PosMode Position = PosMode.Follow;
        public int FixedX;
        public int FixedY;
        public List<int[]> Points = new List<int[]>();
        public long MaxCount;
        public int CountdownSec;
    }

    public class ClickEngine
    {
        const uint MOVE = 0x0001, LEFTDOWN = 0x0002, LEFTUP = 0x0004,
                   RIGHTDOWN = 0x0008, RIGHTUP = 0x0010,
                   MIDDLEDOWN = 0x0020, MIDDLEUP = 0x0040,
                   ABSOLUTE = 0x8000, VIRTUALDESK = 0x4000;

        [StructLayout(LayoutKind.Sequential)]
        struct POINT { public int X, Y; }

        [StructLayout(LayoutKind.Sequential)]
        struct MOUSEINPUT { public int dx, dy; public uint mouseData, dwFlags, time; public IntPtr extraInfo; }

        [StructLayout(LayoutKind.Sequential)]
        struct INPUT { public uint type; public MOUSEINPUT mi; }

        [DllImport("user32.dll")]
        static extern uint SendInput(uint n, INPUT[] inputs, int size);

        [DllImport("user32.dll")]
        static extern bool GetCursorPos(out POINT p);

        [DllImport("user32.dll")]
        static extern int GetSystemMetrics(int index);

        public ClickConfig Config = new ClickConfig();
        public volatile bool Running;
        public long Count;
        public event Action<long> Tick;
        public event Action Stopped;

        Thread _thread;
        volatile bool _stop;

        public void Start()
        {
            if (Running) return;
            Count = 0;
            _stop = false;
            Running = true;
            _thread = new Thread(Run) { IsBackground = true };
            _thread.Start();
        }

        public void Stop()
        {
            _stop = true;
        }

        public void WaitForExit()
        {
            var t = _thread;
            if (t != null && t.IsAlive) t.Join(3000);
        }

        void Run()
        {
            var rnd = new Random();
            var sw = Stopwatch.StartNew();
            long limit = Config.MaxCount;
            int idx = 0;

            while (!_stop)
            {
                double jitter = 1.0;
                if (Config.JitterPercent > 0)
                    jitter = 1.0 + (rnd.NextDouble() * 2 - 1) * Config.JitterPercent / 100.0;
                double intervalMs = Math.Max(1.0, Config.IntervalMs * jitter);

                DoClick(ref idx);

                Count++;
                var ev = Tick; if (ev != null) ev(Count);
                if (limit > 0 && Count >= limit) break;

                long target = sw.ElapsedMilliseconds + (long)intervalMs;
                while (!_stop)
                {
                    long remain = target - sw.ElapsedMilliseconds;
                    if (remain <= 0) break;
                    if (remain > 15) Thread.Sleep(15);
                    else if (remain > 2) Thread.Sleep((int)(remain - 1));
                    else Thread.SpinWait(60);
                }
            }

            Running = false;
            var st = Stopped; if (st != null) st();
        }

        void DoClick(ref int idx)
        {
            if (Config.Position == PosMode.Fixed)
                MoveTo(Config.FixedX, Config.FixedY);
            else if (Config.Position == PosMode.Multi && Config.Points.Count > 0)
            {
                int[] p = Config.Points[idx % Config.Points.Count];
                idx++;
                MoveTo(p[0], p[1]);
            }

            uint down, up;
            switch (Config.Button)
            {
                case MouseBtn.Right: down = RIGHTDOWN; up = RIGHTUP; break;
                case MouseBtn.Middle: down = MIDDLEDOWN; up = MIDDLEUP; break;
                default: down = LEFTDOWN; up = LEFTUP; break;
            }

            if (Config.Mode == ClickMode.Hold)
            {
                Send(down);
                Thread.Sleep(Math.Max(1, Config.HoldMs));
                Send(up);
            }
            else if (Config.Mode == ClickMode.Double)
            {
                Send(down); Send(up);
                Thread.Sleep(40);
                Send(down); Send(up);
            }
            else
            {
                Send(down); Send(up);
            }
        }

        void Send(uint flags)
        {
            var i = new INPUT[1];
            i[0].type = 0;
            i[0].mi.dwFlags = flags;
            SendInput(1, i, Marshal.SizeOf(typeof(INPUT)));
        }

        void MoveTo(int x, int y)
        {
            int vx = GetSystemMetrics(76), vy = GetSystemMetrics(77);
            int vw = GetSystemMetrics(78), vh = GetSystemMetrics(79);
            if (vw <= 0 || vh <= 0) return;
            var i = new INPUT[1];
            i[0].type = 0;
            i[0].mi.dwFlags = MOVE | ABSOLUTE | VIRTUALDESK;
            i[0].mi.dx = (int)((x - vx) * 65536.0 / vw);
            i[0].mi.dy = (int)((y - vy) * 65536.0 / vh);
            SendInput(1, i, Marshal.SizeOf(typeof(INPUT)));
        }
    }
}
